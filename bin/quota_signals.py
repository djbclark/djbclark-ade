#!/usr/bin/env python3
"""Read-only quota forecasts. No scheduling, routing, model calls or state writes."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / 'config/quota-signals.toml'


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except ValueError:
        return None


def number(value, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        return None
    return float(value)


def fresh(value, now, cfg):
    when = stamp(value)
    return when is not None and 0 <= (now - when).total_seconds() <= cfg['max_age_seconds']


def load_config(path):
    with path.open('rb') as stream:
        cfg = tomllib.load(stream)
    for key in ('max_age_seconds', 'conserve_deficit_percent', 'surplus_min_percent',
                'surplus_horizon_hours', 'command_timeout_seconds'):
        if number(cfg.get(key)) is None or cfg[key] <= 0:
            raise ValueError(f'invalid config threshold: {key}')
    if not isinstance(cfg.get('pools'), list):
        raise ValueError('config pools must be an array')
    return cfg


def collect(path, argv, cfg):
    """Return unknown on CLI failure; never print stderr (may contain account data)."""
    try:
        if path:
            return json.loads(path.read_text())
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=cfg['command_timeout_seconds'], check=False)
        # aiuse exit 3 means no usable pools; its JSON can still describe exclusions.
        if proc.returncode not in ((0, 3) if argv[0] == 'aiuse' else (0,)):
            return None
        return json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def paseo_caps(data, source, now, cfg):
    """Unknown never grants quota; stale zero remains a veto. Fable is a sublimit."""
    caps = []
    if not isinstance(data, list):
        return caps
    for row in data:
        if not isinstance(row, dict) or row.get('sourceId') != source:
            continue
        report = row.get('report')
        if not isinstance(report, dict) or report.get('status') != 'available':
            continue
        windows = report.get('windows')
        if not isinstance(windows, list):
            continue
        for window in windows:
            if not isinstance(window, dict):
                continue
            if 'fable' in str(window.get('label', '')).lower() or 'fable' in str(window.get('id', '')).lower():
                continue
            rem = number(window.get('remainingPct'), 100)
            if rem is None:
                used = number(window.get('usedPct'), 100)
                rem = 100 - used if used is not None else None
            reset = stamp(window.get('resetsAt'))
            if reset is not None and reset <= now:
                continue
            if rem is not None and (fresh(row.get('fetchedAt'), now, cfg) or rem == 0):
                caps.append(rem)
    return caps


def signal(pool, rows, paseo, now, wave_start, cfg):
    provider, family = pool['provider'], pool.get('family') or 'default'
    result = dict(pool=f'{provider}/{family}', routable=False, conserve=False, surplus=False,
                  reason='unknown', windows=[])
    candidates = [r for r in rows if isinstance(r, dict) and r.get('provider') == provider
                  and (r.get('pool_family') or 'default') == family]
    # Multiple accounts cannot safely be collapsed into one pool entitlement.
    if len(candidates) != 1:
        result['reason'] = 'missing_or_ambiguous_pool'
        return result
    row = candidates[0]
    collected = stamp(row.get('collected_at'))
    result['collected_at'] = row.get('collected_at')
    if (not fresh(row.get('collected_at'), now, cfg) or row.get('stale') is True
            or row.get('fresh') is not True or collected <= wave_start):
        result['reason'] = 'stale_or_pre_wave_reading'
        return result
    if row.get('usable_now') is not True or row.get('requires_operator_approval') is True:
        result['reason'] = 'not_usable_or_operator_gated'
        return result
    windows = row.get('windows')
    if not isinstance(windows, list) or not windows:
        return result
    headroom = number(row.get('headroom_percent'), 100)
    if headroom is None:
        return result
    caps = paseo_caps(paseo, pool.get('paseo_source', provider if family == 'default' else ''), now, cfg)
    effective = min([headroom, *caps])
    result['remaining_percent'] = effective
    if effective <= 0:
        result['reason'] = 'exhausted'
        result['conserve'] = True
        return result
    forecasts = []
    complete = True
    own_caps = [w for w in windows if isinstance(w, dict)
                and w.get('pool_family') == family and w.get('quota_scope') == 'model_sublimit']
    model_pool = row.get('quota_scope') == 'model_sublimit' or family == 'fable' or bool(own_caps)
    families = {family}
    if model_pool:
        parents = [row.get('shared_pool_family'), *(w.get('shared_pool_family') for w in own_caps)]
        families.update(parent for parent in parents if isinstance(parent, str) and parent)
    for window in windows:
        if not isinstance(window, dict):
            result['reason'] = 'unknown_window'
            return result
        window_family = window.get('pool_family')
        if window_family and window_family not in families:
            continue
        model_window = (window.get('quota_scope') == 'model_sublimit'
                        or any('fable' in str(window.get(key, '')).lower()
                               for key in ('label', 'id', 'window_id')))
        if model_window and not model_pool:
            continue
        rem = number(window.get('remaining_percent'), 100)
        if rem is None or window.get('state') in ('unknown', 'exhausted') or rem <= 0:
            result['reason'] = 'unknown_or_exhausted_window'
            result['conserve'] = rem == 0 or window.get('state') == 'exhausted'
            return result
        reset = stamp(window.get('resets_at'))
        if reset is None or reset <= now:
            result['reason'] = 'missing_or_elapsed_reset'
            return result
        duration = number(window.get('window_minutes'))
        ratio = number(window.get('pace_ratio'))
        item = dict(label=window.get('label'), resets_at=window.get('resets_at'),
                    conserve=False, surplus=False, projected_remaining_percent=None)
        # Early pace and missing clock/pace are not evidence for a forecast.
        if (not duration or ratio is None or window.get('pace_early') is not False
                or (reset - collected).total_seconds() > duration * 60):
            complete = False
        else:
            # Apply any tighter Paseo cap pessimistically to each aiuse window.
            left = max(0, rem - (headroom - effective))
            minutes = (reset - collected).total_seconds() / 60
            projected = left - ratio * 100 / duration * minutes
            item['projected_remaining_percent'] = round(projected, 3)
            item['conserve'] = projected <= -cfg['conserve_deficit_percent']
            item['surplus'] = (projected >= cfg['surplus_min_percent']
                               and (reset - now).total_seconds() <= cfg['surplus_horizon_hours'] * 3600)
            forecasts.append(item)
        result['windows'].append(item)
    if not result['windows']:
        result['reason'] = 'no_applicable_windows'
        return result
    result['routable'] = True
    result['conserve'] = any(w['conserve'] for w in forecasts)
    # Never recommend spending more while another window is short or unforecastable.
    result['surplus'] = (complete and all(w['projected_remaining_percent'] >= 0 for w in forecasts)
                         and any(w['surplus'] for w in forecasts))
    result['reason'] = 'forecast' if complete else 'pace_unavailable_or_early'
    return result


def evaluate(aiuse, paseo, now, wave_start, cfg):
    rows = aiuse.get('available', []) if isinstance(aiuse, dict) else []
    rows = rows if isinstance(rows, list) else []
    pools = {(p['provider'], p.get('family') or 'default'): p for p in cfg['pools']}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('provider'), str):
            key = row['provider'], row.get('pool_family') or 'default'
            pools.setdefault(key, dict(provider=key[0], family=key[1]))
    return dict(schema_version=1, checked_at=now.isoformat(), wave_start=wave_start.isoformat(),
                pools=[signal(p, rows, paseo, now, wave_start, cfg) for p in pools.values()])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--aiuse-json', type=Path)
    parser.add_argument('--paseo-json', type=Path)
    parser.add_argument('--wave-start', required=True, help='previous dispatch wave start, ISO timestamp')
    parser.add_argument('--now', help='ISO timestamp for reproducible offline evaluation')
    args = parser.parse_args(argv)
    now = stamp(args.now) if args.now else datetime.now(UTC)
    start = stamp(args.wave_start)
    if now is None or start is None or start > now:
        parser.error('timestamps must include timezone; wave start must not be in the future')
    try:
        cfg = load_config(args.config)
        aiuse = collect(args.aiuse_json, ['aiuse', '--available', '--json'], cfg)
        paseo = collect(args.paseo_json, ['paseo', 'usage', 'ls', '--json'], cfg)
        if not args.now:
            now = datetime.now(UTC)
        print(json.dumps(evaluate(aiuse, paseo, now, start, cfg), allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'quota-signals: invalid configuration ({type(exc).__name__})', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
