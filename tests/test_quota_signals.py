"""Offline contract and safety cases, based on sanitized aiuse 1.5/Paseo shapes."""
import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('quota_signals', ROOT / 'bin/quota_signals.py')
qs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qs)
FIXTURES = ROOT / 'tests/fixtures/quota-signals'
NOW = qs.stamp('2026-11-12T12:05:00Z')
START = qs.stamp('2026-11-12T11:59:00Z')


@pytest.fixture
def inputs():
    return (json.loads((FIXTURES / 'aiuse.json').read_text()),
            json.loads((FIXTURES / 'paseo.json').read_text()),
            qs.load_config(ROOT / 'config/quota-signals.toml'))


def run(inputs):
    aiuse, paseo, cfg = inputs
    return next(p for p in qs.evaluate(aiuse, paseo, NOW, START, cfg)['pools'] if p['pool'] == 'codex/default')


def test_conserve(inputs):
    result = run(inputs)
    assert result['routable'] and result['conserve'] and not result['surplus']
    assert result['windows'][0]['projected_remaining_percent'] == -20


def test_surplus(inputs):
    inputs[0]['available'][0]['windows'][0]['pace_ratio'] = 0.2
    assert run(inputs)['surplus'] and not run(inputs)['conserve']


@pytest.mark.parametrize('field,value', [('collected_at', None), ('collected_at', 'bad'),
    ('collected_at', '2026-11-12T11:00:00Z'), ('collected_at', '2026-11-12T11:59:00Z'),
    ('collected_at', '2026-11-12T13:00:00Z'), ('stale', True), ('fresh', False),
    ('usable_now', False), ('headroom_percent', None), ('requires_operator_approval', True)])
def test_unknown_stale_and_gated_fail_closed(inputs, field, value):
    inputs[0]['available'][0][field] = value
    result = run(inputs)
    assert not result['routable'] and not result['surplus']


@pytest.mark.parametrize('field,value', [('remaining_percent', None), ('remaining_percent', float('nan')),
    ('remaining_percent', True), ('resets_at', None), ('resets_at', '2026-11-12T11:00:00Z'),
    ('state', 'unknown')])
def test_bad_window_fails_closed(inputs, field, value):
    inputs[0]['available'][0]['windows'][0][field] = value
    assert not run(inputs)['routable']


@pytest.mark.parametrize('field,value', [('pace_ratio', None), ('pace_ratio', float('inf')),
    ('pace_early', True), ('pace_early', None), ('window_minutes', 0)])
def test_no_prediction_from_unreliable_pace(inputs, field, value):
    inputs[0]['available'][0]['windows'][0][field] = value
    result = run(inputs)
    assert result['routable'] and not result['surplus'] and not result['conserve']


def test_tighter_paseo_caps_surplus(inputs):
    inputs[0]['available'][0]['windows'][0]['pace_ratio'] = 0.2
    inputs[1][0]['report']['windows'][0]['remainingPct'] = 5
    assert not run(inputs)['surplus']
    assert run(inputs)['conserve']


def test_stale_paseo_only_zero_vetoes(inputs):
    inputs[1][0]['fetchedAt'] = '2026-11-12T10:00:00Z'
    inputs[1][0]['report']['windows'][0]['remainingPct'] = 5
    assert run(inputs)['remaining_percent'] == 40
    inputs[1][0]['report']['windows'][0]['remainingPct'] = 0
    assert not run(inputs)['routable']


def test_paseo_unknown_never_creates_headroom(inputs):
    inputs[0]['available'] = []
    assert not run(inputs)['routable']


def test_paseo_failure_does_not_loosen_primary(inputs):
    inputs[1][0]['report'] = {'status': 'unavailable'}
    assert run(inputs)['conserve']


def test_fable_not_shared_quota(inputs):
    inputs[1][0]['report']['windows'].append({'id': 'weekly_model_fable', 'remainingPct': 0})
    inputs[0]['available'][0]['windows'].append({
        'window_id': 'weekly_model_fable', 'label': 'Weekly Fable',
        'pool_family': 'fable', 'quota_scope': 'model_sublimit',
        'remaining_percent': 0, 'state': 'exhausted'})
    assert run(inputs)['routable']


def test_multiple_windows_veto_surplus_and_preserve_conservation(inputs):
    row = inputs[0]['available'][0]
    other = copy.deepcopy(row['windows'][0])
    other['pace_ratio'] = 0.1
    row['windows'].append(other)
    assert run(inputs)['conserve'] and not run(inputs)['surplus']


def test_missing_pool_is_explicit(inputs):
    pools = qs.evaluate(*inputs[:2], NOW, START, inputs[2])['pools']
    argon = next(p for p in pools if p['pool'] == 'antigravity/gemini_argon')
    assert not argon['routable'] and argon['reason'] == 'missing_or_ambiguous_pool'


def test_ambiguous_accounts_fail_closed(inputs):
    inputs[0]['available'].append(copy.deepcopy(inputs[0]['available'][0]))
    assert not run(inputs)['routable']


def test_surplus_horizon(inputs):
    inputs[0]['available'][0]['windows'][0]['pace_ratio'] = 0.2
    inputs[2]['surplus_horizon_hours'] = 12
    assert not run(inputs)['surplus']


def test_threshold_config(inputs):
    inputs[2]['conserve_deficit_percent'] = 25
    assert not run(inputs)['conserve']


def test_command_collection_fail_closed(inputs, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)
    monkeypatch.setattr(qs.subprocess, 'run', fail)
    assert qs.collect(None, ['aiuse', '--available', '--json'], inputs[2]) is None


def test_offline_cli(capsys):
    assert qs.main(['--aiuse-json', str(FIXTURES / 'aiuse.json'), '--paseo-json',
                    str(FIXTURES / 'paseo.json'), '--wave-start', START.isoformat(),
                    '--now', NOW.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)['schema_version'] == 1


def test_malformed_window_is_unroutable(inputs):
    inputs[0]['available'][0]['windows'] = [None]
    assert not run(inputs)['routable']


def test_small_deficit_vetoes_other_window_surplus(inputs):
    row = inputs[0]['available'][0]
    row['windows'][0]['pace_ratio'] = 0.84  # -2%, below conservation alert threshold
    other = copy.deepcopy(row['windows'][0])
    other['pace_ratio'] = 0.1
    row['windows'].append(other)
    assert not run(inputs)['conserve'] and not run(inputs)['surplus']


def test_live_clock_is_sampled_after_collection(inputs, monkeypatch, capsys):
    class Clock:
        calls = 0
        @classmethod
        def now(cls, tz):
            cls.calls += 1
            return qs.stamp('2026-11-12T11:59:30Z') if cls.calls == 1 else NOW
    values = iter(inputs[:2])
    monkeypatch.setattr(qs, 'datetime', type('TestClock', (Clock,),
        {'fromisoformat': staticmethod(qs.datetime.fromisoformat)}))
    monkeypatch.setattr(qs, 'collect', lambda *args: next(values))
    assert qs.main(['--wave-start', START.isoformat()]) == 0
    data = json.loads(capsys.readouterr().out)
    codex = next(p for p in data['pools'] if p['pool'] == 'codex/default')
    assert codex['routable']


@pytest.mark.parametrize('metadata', [
    {'pool_family': 'other'}, {'quota_scope': 'model_sublimit'},
    {'label': 'Weekly Fable'}, {'id': 'weekly_model_fable'},
    {'window_id': 'weekly_model_fable'},
])
def test_aiuse_filters_foreign_and_model_windows(inputs, metadata):
    inputs[0]['available'][0]['windows'].append(
        dict(remaining_percent=0, state='exhausted', **metadata))
    assert run(inputs)['routable']
    assert len(run(inputs)['windows']) == 1


def test_only_foreign_windows_is_unknown(inputs):
    inputs[0]['available'][0]['windows'] = [
        {'pool_family': 'other', 'remaining_percent': 50}]
    assert not run(inputs)['routable']
    assert run(inputs)['reason'] == 'no_applicable_windows'


def test_own_fable_sublimit_still_binds(inputs):
    row = inputs[0]['available'][0]
    row.update(pool_family='fable', quota_scope='model_sublimit')
    row['windows'][0].update(pool_family='fable', quota_scope='model_sublimit',
                             label='Weekly Fable', remaining_percent=0)
    pools = qs.evaluate(*inputs[:2], NOW, START, inputs[2])['pools']
    fable = next(p for p in pools if p['pool'] == 'codex/fable')
    assert not fable['routable'] and fable['conserve']


def test_cursor_grok_does_not_hide_empty_included_pools(inputs):
    cursor = json.loads((FIXTURES / 'cursor-split.json').read_text())
    pools = qs.evaluate(cursor, [], NOW, START, inputs[2])['pools']
    cursor_pools = {p['pool']: p for p in pools if p['pool'].startswith('cursor/')}
    assert cursor_pools['cursor/grok_bot']['routable']
    assert cursor_pools['cursor/grok_bot']['remaining_percent'] == 82.072928
    for family in ('total', 'auto', 'third_party'):
        assert not cursor_pools[f'cursor/{family}']['routable']
        assert cursor_pools[f'cursor/{family}']['reason'] == 'missing_or_ambiguous_pool'


@pytest.mark.parametrize('unknown_parent', [False, True])
def test_model_pool_retains_shared_parent_window(inputs, unknown_parent):
    row = inputs[0]['available'][0]
    row.update(provider='claude', pool_family='fable', quota_scope='model_sublimit',
               shared_pool_family='default')
    parent = row['windows'][0]
    parent.update(pool_family='default', quota_scope='shared')
    cap = copy.deepcopy(parent)
    cap.update(pool_family='fable', quota_scope='model_sublimit', label='Weekly Fable',
               remaining_percent=80, pace_ratio=0.1)
    row['windows'].append(cap)
    if unknown_parent:
        parent['remaining_percent'] = None
    pools = qs.evaluate(*inputs[:2], NOW, START, inputs[2])['pools']
    fable = next(p for p in pools if p['pool'] == 'claude/fable')
    assert not fable['surplus']
    if unknown_parent:
        assert not fable['routable']
    else:
        assert fable['conserve'] and len(fable['windows']) == 2
