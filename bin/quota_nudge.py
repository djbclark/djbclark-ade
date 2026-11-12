#!/usr/bin/env python3
"""Batch-boundary quota advice. Print-only; never changes routing or gates.

Seed: claude/hooks/quota_nudge.py (level/profile reminders). Unlike the old
hook this is explicit, per-pool, and reads the router's current merged sources.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config/quota-advisory.toml"


def state_path():
    return Path(os.environ.get("ADE_SPENDING_PROFILES") or
                Path.home() / ".local/state/ade/spending-profiles.json")


def parse_until(value):
    if not isinstance(value, str):
        raise ValueError("until must be an ISO-8601 timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("until requires a timezone")
    return stamp


def load_profiles(path=None, now=None):
    """Expiry is evaluated on every read, with no daemon or state rewrite."""
    now = now or datetime.now(timezone.utc)
    try:
        raw = json.loads((path or state_path()).read_text())
        if not isinstance(raw, dict):
            return {}
    except (OSError, ValueError):
        return {}
    active = {}
    for pool, row in raw.items():
        try:
            if (re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", pool)
                    and isinstance(row, dict) and isinstance(row.get("name"), str)
                    and row["name"].isprintable() and 0 < len(row["name"]) <= 160
                    and parse_until(row["until"]) > now):
                active[pool] = {"name": row["name"], "until": row["until"]}
        except (ValueError, TypeError, KeyError):
            continue
    return active


def save_profile(pool, name=None, until=None, path=None):
    """Explicit operator command; atomic replace. Expired rows are pruned."""
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", pool):
        raise ValueError("pool must be a router pool id")
    rows = load_profiles(path)
    if name is None:
        rows.pop(pool, None)
    else:
        if not name.isprintable() or not 0 < len(name) <= 160:
            raise ValueError("profile name must be 1-160 printable characters")
        if parse_until(until) <= datetime.now(timezone.utc):
            raise ValueError("until must be in the future")
        rows[pool] = {"name": name, "until": until}
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(rows, handle)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def report(quota, *, profiles=None, config=CONFIG):
    with config.open("rb") as handle:
        cfg = tomllib.load(handle)
    defaults = cfg["thresholds"]
    if not isinstance(defaults, dict) or not isinstance(cfg.get("pools", {}), dict):
        raise ValueError("advisory thresholds/pools must be tables")
    profiles = load_profiles() if profiles is None else profiles
    result = []
    for pool in sorted(set(quota) | set(profiles)):
        limits = {**defaults, **cfg.get("pools", {}).get(pool, {})}
        critical, conserve, max_age = (limits[k] for k in
                                       ("critical_left", "conserve_left", "max_age_seconds"))
        if not (all(type(x) in (int, float) and math.isfinite(x)
                    for x in (critical, conserve, max_age))
                and 0 <= critical < conserve <= 100 and max_age >= 0):
            raise ValueError("invalid advisory thresholds")
        info = quota.get(pool, {})
        left, age = info.get("remaining"), info.get("age_s")
        known = (type(left) in (int, float) and math.isfinite(left) and 0 <= left <= 100
                 and type(age) in (int, float) and math.isfinite(age) and 0 <= age <= max_age)
        level = ("unknown" if not known else "critical" if left <= critical
                 else "conserve" if left <= conserve else "ok")
        result.append({"pool": pool, "level": level,
                       "remaining_percent": left if known else None,
                       "profile": profiles.get(pool)})
    return result


def print_reminder(quota):
    """Always advisory: even unavailable config/state cannot block a batch."""
    try:
        rows = report(quota)
    except (OSError, ValueError, KeyError, TypeError):
        print("[quota advisory] unavailable; check quota sources/config")
        return
    print("[quota advisory] batch reminder (print-only)")
    if not rows:
        print("  quota unknown; refresh aiuse/Paseo before planning")
    for row in rows:
        left = row["remaining_percent"]
        text = "unmeasured/stale" if left is None else f"{left:g}% left"
        print(f"  {row['pool']}: {row['level']} ({text})")
        if row["profile"]:
            p = row["profile"]
            print(f"    operator profile: {p['name']} until {p['until']} (advisory only)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--set-profile", metavar="POOL")
    group.add_argument("--clear-profile", metavar="POOL")
    parser.add_argument("--name")
    parser.add_argument("--until", help="ISO-8601 timestamp with timezone")
    args = parser.parse_args(argv)
    if args.set_profile or args.clear_profile:
        if args.set_profile and (not args.name or not args.until):
            parser.error("--set-profile requires --name and --until")
        try:
            save_profile(args.set_profile or args.clear_profile,
                         args.name if args.set_profile else None, args.until)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    else:
        if args.name or args.until:
            parser.error("--name/--until require --set-profile")
        import route_agent
        quota, _age = route_agent.load_snapshot()
        print_reminder(quota)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
