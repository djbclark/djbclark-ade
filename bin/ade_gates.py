"""ade_gates: the Claude quota gates' numbers, from code defaults, config/gates.toml, a temporary profile and env JSON.

Imported by bin/claude-fleet-governor, bin/claude-quota-guard and bin/gate-profile (they run under `python3 -I`, so each
puts this directory on sys.path first, the way bin/acp-dispatch does for failover.py). Not a program.

  load_gates(gate, now, defaults) -> (thresholds, info)      gate: "governor" | "quota_guard"

Precedence, lowest to highest: `defaults` (the script's THRESHOLDS: the fail-safe when config/gates.toml is missing or
unparsable) < gates.toml baseline < the active profile < env JSON (CLAUDE_GOVERNOR_THRESHOLDS /
CLAUDE_QUOTA_GUARD_THRESHOLDS; tests and emergencies; bad input raises GateEnvError).

A profile (state: ~/.local/state/ade/gate-profile.json, env GATE_PROFILE_STATE) applies only when ALL of these hold; otherwise
the baseline applies and info["ignored"] says why: the file parses as {"schema": 1, "profile", "since", "until", ...}; both
times are timezone-aware UTC; since <= now < until; until - since <= [meta].max_profile_hours; the profile exists in
gates.toml; every key it sets is listed under [floors.<gate>], moves in that key's `loosen` direction (never tighter than the
baseline) and stays within `bound`. One bad value rejects the whole profile, for both gates (the governor and the guard
must agree). An expired file is ignored, left in place as the audit trail, and announced once (`notify_expired`).

info keys: source ("gates.toml" | "code"), toml_error, toml_path, baseline (the values before profile and env), profile
({name, since, until, reason, set_by} or None), ignored (why a state file does not apply, or None), expired (the profile
dict when the file expired and no one was told yet, else None), profile_values, env_values.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GATES = ("governor", "quota_guard")
ENV_VARS = {"governor": "CLAUDE_GOVERNOR_THRESHOLDS", "quota_guard": "CLAUDE_QUOTA_GUARD_THRESHOLDS"}
SCHEMA = 1
DEFAULT_MAX_HOURS = 240
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# Keys that must stay in order after a profile is applied, each at least the next (the guard's weekly triggers fire
# watch, then tight, then critical as the percent left falls; a profile that crosses them would skip a level).
ORDERINGS = {"quota_guard": ("watch_weekly", "tight_weekly", "critical_weekly")}
_LOGGED: set[str] = set()


class GateEnvError(ValueError):
    """The env JSON override is not usable."""


# -- paths ---------------------------------------------------------------------------------------------------------

def _home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def toml_path() -> Path:
    return Path(os.environ.get("GATES_TOML") or Path(__file__).resolve().parent.parent / "config" / "gates.toml")


def profile_state_path() -> Path:
    return Path(os.environ.get("GATE_PROFILE_STATE") or _home() / ".local/state/ade/gate-profile.json")


def profile_log_path() -> Path:
    return Path(os.environ.get("GATE_PROFILE_LOG") or _home() / ".local/state/ade/gate-profile.log")


# -- small helpers -------------------------------------------------------------------------------------------------

def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _log_once(msg: str) -> None:
    if msg not in _LOGGED:
        _LOGGED.add(msg)
        print(f"ade_gates: {msg}", file=sys.stderr)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: Any) -> datetime | None:
    """A timezone-aware ISO time whose offset is zero (Z or +00:00); anything else is None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        return None
    return dt.astimezone(UTC)


NY = ZoneInfo("America/New_York")


def ny(dt: datetime) -> str:
    """America/New_York, 12-hour, 3-letter day: `Thu Oct 29 5:00 PM EDT`."""
    d = dt.astimezone(NY)
    return f"{d:%a %b} {d.day} {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'} {d:%Z}"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# -- gates.toml ------------------------------------------------------------------------------------------------------

def read_toml() -> tuple[dict[str, Any] | None, str | None]:
    path = toml_path()
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh), None
    except OSError as e:
        return None, f"{path}: {e.strerror or e}"
    except tomllib.TOMLDecodeError as e:
        return None, f"{path}: not valid TOML ({e})"


def max_hours(cfg: dict[str, Any]) -> float:
    v = (cfg.get("meta") or {}).get("max_profile_hours") if isinstance(cfg.get("meta"), dict) else None
    return float(v) if is_num(v) and v > 0 else float(DEFAULT_MAX_HOURS)


def toml_baseline(cfg: dict[str, Any], gate: str) -> dict[str, float] | None:
    """The numeric keys of cfg[gate], or None when the table is missing or holds a non-number."""
    tbl = cfg.get(gate)
    if not isinstance(tbl, dict) or not tbl or not all(is_num(v) for v in tbl.values()):
        return None
    return {k: float(v) for k, v in tbl.items()}


def floor_spec(cfg: dict[str, Any], gate: str, key: str) -> dict[str, Any] | None:
    floors = cfg.get("floors")
    tbl = floors.get(gate) if isinstance(floors, dict) else None
    spec = tbl.get(key) if isinstance(tbl, dict) else None
    return spec if isinstance(spec, dict) else None


def spec_problem(spec: dict[str, Any]) -> str | None:
    if spec.get("loosen") not in ("lower", "higher"):
        return "`loosen` must be \"lower\" or \"higher\""
    if not is_num(spec.get("bound")):
        return "`bound` must be a number"
    return None


def value_problem(spec: dict[str, Any], baseline: float, value: Any) -> str | None:
    """Why `value` is not an allowed profile value for a key with this floor spec and baseline, or None."""
    if not is_num(value):
        return f"{value!r} is not a number"
    bad = spec_problem(spec)
    if bad:
        return f"floor spec is malformed: {bad}"
    bound = float(spec["bound"])
    if spec["loosen"] == "lower":
        if value > baseline:
            return f"{value:g} is tighter than the baseline {baseline:g} (lower is looser)"
        if value < bound:
            return f"{value:g} is below the floor {bound:g}"
    else:
        if value < baseline:
            return f"{value:g} is tighter than the baseline {baseline:g} (higher is looser)"
        if value > bound:
            return f"{value:g} is above the ceiling {bound:g}"
    return None


def ordering_problems(gate: str, values: dict[str, Any]) -> list[str]:
    """Where `values` (a gate's keys after a profile is applied) break ORDERINGS; [] when they hold or a key is absent."""
    chain = ORDERINGS.get(gate, ())
    if not all(is_num(values.get(k)) for k in chain):
        return []
    return [f"{a} {values[a]:g} must be at least {b} {values[b]:g} (ordering {' >= '.join(chain)})"
            for a, b in zip(chain, chain[1:]) if values[a] < values[b]]


def profile_problems(cfg: dict[str, Any], name: str, baselines: dict[str, dict[str, float]]) -> list[str]:
    """Every reason profile `name` cannot be used; [] when it can. `baselines` is {gate: {key: baseline value}}."""
    profiles = cfg.get("profiles")
    prof = profiles.get(name) if isinstance(profiles, dict) else None
    if not isinstance(prof, dict):
        return [f"no profile {name!r} in gates.toml"]
    out: list[str] = []
    for gate, tbl in prof.items():
        if gate == "description" and isinstance(tbl, str):
            continue
        if gate not in GATES:
            out.append(f"profile {name}: unknown entry {gate!r}")
            continue
        if not isinstance(tbl, dict):
            out.append(f"profile {name}.{gate}: not a table")
            continue
        before = len(out)
        for key, value in tbl.items():
            spec = floor_spec(cfg, gate, key)
            if spec is None:
                out.append(f"profile {name}.{gate}.{key}: not overridable (no [floors.{gate}] entry)")
            elif key not in baselines.get(gate, {}):
                out.append(f"profile {name}.{gate}.{key}: no baseline value")
            else:
                why = value_problem(spec, baselines[gate][key], value)
                if why:
                    out.append(f"profile {name}.{gate}.{key}: {why}")
        if len(out) == before:  # every value is a valid number: the profile as applied must keep the key order
            out += [f"profile {name}.{gate}: {p}" for p in ordering_problems(gate, {**baselines.get(gate, {}), **tbl})]
    return out


def toml_baselines(cfg: dict[str, Any]) -> dict[str, dict[str, float]]:
    return {g: toml_baseline(cfg, g) or {} for g in GATES}


# -- the profile state file ------------------------------------------------------------------------------------------

def read_profile_file() -> tuple[dict[str, Any] | None, str | None]:
    """(parsed dict, None) | (None, None) when there is no file | (None, why) when it cannot be used at all."""
    path = profile_state_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, f"{path}: unreadable ({e.strerror or e})"
    try:
        data = json.loads(text)
    except ValueError:
        return None, f"{path}: corrupt JSON"
    if not isinstance(data, dict):
        return None, f"{path}: not a JSON object"
    return data, None


def resolve_profile(cfg: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """{"profile": dict|None (active), "ignored": str|None, "expired": dict|None, "applies": {gate: {key: value}}}."""
    res: dict[str, Any] = {"profile": None, "ignored": None, "expired": None, "applies": {}}
    data, why = read_profile_file()
    if data is None:
        res["ignored"] = why
        return res
    if data.get("schema") != SCHEMA:
        res["ignored"] = f"profile file schema {data.get('schema')!r} is not {SCHEMA}"
        return res
    name = data.get("profile")
    since, until = parse_utc(data.get("since")), parse_utc(data.get("until"))
    if until is None:
        res["ignored"] = "`until` is missing or not a UTC time (timezone-aware, offset zero)"
        return res
    info = {"name": name if isinstance(name, str) else None, "since": data.get("since"), "until": data.get("until"),
            "reason": data.get("reason"), "set_by": data.get("set_by")}
    if until <= now:
        res["ignored"] = f"profile {name!r} expired at {iso(until)}"
        if not data.get("expired_notified"):
            res["expired"] = info
        return res
    if since is None:
        res["ignored"] = "`since` is missing or not a UTC time (timezone-aware, offset zero)"
    elif since > now:
        res["ignored"] = f"profile {name!r} starts in the future ({iso(since)})"
    elif until <= since:
        res["ignored"] = "`until` is not after `since`"
    elif cfg is None:
        res["ignored"] = "gates.toml is unavailable, so no profile can be checked"
    elif (until - since).total_seconds() > max_hours(cfg) * 3600:
        res["ignored"] = f"window is {(until - since).total_seconds() / 3600:g} h, over max_profile_hours {max_hours(cfg):g}"
    elif not isinstance(name, str):
        res["ignored"] = "`profile` is missing or not a string"
    else:
        problems = profile_problems(cfg, name, toml_baselines(cfg))
        if problems:
            res["ignored"] = "; ".join(problems)
        else:
            res["profile"] = info
            res["applies"] = {g: dict(t) for g, t in cfg["profiles"][name].items() if g in GATES}
    return res


# -- the loader ----------------------------------------------------------------------------------------------------

def env_overrides(gate: str, known: dict[str, Any]) -> dict[str, float]:
    var = ENV_VARS[gate]
    raw = os.environ.get(var)
    if not raw:
        return {}
    try:
        over = json.loads(raw)
    except json.JSONDecodeError as e:
        raise GateEnvError(f"{var} is not JSON: {e}")
    if not isinstance(over, dict):
        raise GateEnvError(f"{var} must be a JSON object")
    out: dict[str, float] = {}
    for k, v in over.items():
        if k not in known or not is_num(v):
            raise GateEnvError(f"unknown or non-numeric threshold {k!r}")
        out[k] = float(v)
    return out


def load_gates(gate: str, now: datetime | None = None, defaults: dict[str, Any] | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    """The effective thresholds of `gate` and an info dict (module docstring). `defaults` is the script's THRESHOLDS."""
    if gate not in GATES:
        raise ValueError(f"unknown gate {gate!r}")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    base = {k: float(v) for k, v in (defaults or {}).items()}
    info: dict[str, Any] = {"source": "code", "toml_error": None, "toml_path": str(toml_path()), "baseline": dict(base),
                            "profile": None, "ignored": None, "expired": None, "profile_values": {}, "env_values": {}}
    cfg, err = read_toml()
    if cfg is not None:
        file_base = toml_baseline(cfg, gate)
        if file_base is None:
            err = f"{toml_path()}: [{gate}] is missing, empty or holds a non-number"
            cfg = None
        else:
            base.update({k: v for k, v in file_base.items() if k in base or not defaults})
            info.update(source="gates.toml", baseline=dict(base))
    if err:
        info["toml_error"] = err
        _log_once(f"{err}; using the code defaults for {gate}")
    prof = resolve_profile(cfg, now)
    info.update(profile=prof["profile"], ignored=prof["ignored"], expired=prof["expired"])
    t = dict(base)
    pv = {k: float(v) for k, v in prof["applies"].get(gate, {}).items() if k in t}
    t.update(pv)
    info["profile_values"] = pv
    ev = env_overrides(gate, t)
    t.update(ev)
    info["env_values"] = ev
    return t, info


def profile_brief(info: dict[str, Any]) -> dict[str, Any] | None:
    """The `profile` field of the gates' state files: {"name", "until"} or None."""
    p = info.get("profile")
    return {"name": p.get("name"), "until": p.get("until")} if isinstance(p, dict) else None


# -- expiry notice and daily nudge -----------------------------------------------------------------------------------

def _mark_and_ping(data: dict[str, Any], key: str, value: str, text: str, ping: Callable[[str], bool]) -> bool:
    """Write `key: value` into the profile file, then ping; remove the mark again when the ping fails, so a failed ping is
    retried by the next run and a sent one never is. Call with the state lock held."""
    path = profile_state_path()
    try:
        atomic_write(path, json.dumps({**data, key: value}, indent=1, sort_keys=True) + "\n")
    except OSError as e:
        _log_once(f"could not record {key}: {e}")
        return False
    ok = False
    try:
        ok = bool(ping(text))
    finally:
        if not ok:
            try:
                atomic_write(path, json.dumps(data, indent=1, sort_keys=True) + "\n")
            except OSError:
                pass
    return ok


def _state_lock():
    """The flock beside the state file, held for the `with`; None when it cannot be opened (no state dir: nothing to notify).
    Serialises the governor, the guard and the CLI."""
    path = profile_state_path()
    try:
        lock = open(path.with_name(path.name + ".lock"), "a")
    except OSError:
        return None
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def _safe_name(name: Any) -> str:
    return name if isinstance(name, str) and NAME_RE.fullmatch(name) else "gate"


def notify_expired(info: dict[str, Any], ping: Callable[[str], bool], now: datetime | None = None) -> bool:
    """Send ONE ping for an expired profile file and record `expired_notified` in it. True when a ping was sent."""
    exp = info.get("expired")
    if not isinstance(exp, dict):
        return False
    now = now or datetime.now(UTC)
    lock = _state_lock()
    if lock is None:
        return False
    with lock:
        data, _ = read_profile_file()
        if not isinstance(data, dict) or data.get("expired_notified") or data.get("until") != exp.get("until"):
            return False
        until = parse_utc(exp.get("until"))
        text = (f"djbclark-ade: {_safe_name(exp.get('name'))} profile expired, baseline restored"
                + (f" (gates were loosened until {ny(until)})" if until else ""))
        return _mark_and_ping(data, "expired_notified", iso(now), text, ping)


def ny_date(dt: datetime) -> str:
    return dt.astimezone(NY).date().isoformat()


def days_left(until: datetime, now: datetime) -> str:
    mins = max(0, int((until - now).total_seconds() // 60))
    return f"{mins // 1440} days left" if mins >= 1440 else f"{mins // 60}h {mins % 60}m left"


def next_nudge(data: dict[str, Any], until: datetime, now: datetime) -> datetime | None:
    """When the next daily nudge is due: `now` when one is owed today, the next New York midnight otherwise, None when the
    profile's own last day (the expiry ping's day) is the next one. `data` is the profile state file."""
    today, last = now.astimezone(NY).date(), until.astimezone(NY).date()
    if today >= last:
        return None
    if data.get("last_daily_nudge") != today.isoformat():
        return now
    tomorrow = today + timedelta(days=1)
    if tomorrow >= last:
        return None
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=NY).astimezone(UTC)


def notify_daily(info: dict[str, Any], ping: Callable[[str], bool], now: datetime | None = None) -> bool:
    """While a profile is active, ONE ping per America/New_York calendar day, from the first caller (the governor) that day.

    The day is the New York date, not 24 h since the last one (DST days are 23 or 25 h), recorded as `last_daily_nudge` in the
    profile file (`gate-profile set` records the day it was set: that day already had its ping). The day the profile expires
    gets the expiry ping instead, so none then; nothing at all when no profile is active."""
    prof = info.get("profile")
    if not isinstance(prof, dict):
        return False
    now = now or datetime.now(UTC)
    until = parse_utc(prof.get("until"))
    if until is None:
        return False
    lock = _state_lock()
    if lock is None:
        return False
    with lock:
        data, _ = read_profile_file()
        if not isinstance(data, dict) or data.get("until") != prof.get("until") or data.get("profile") != prof.get("name"):
            return False
        due = next_nudge(data, until, now)
        if due is None or due > now:
            return False
        text = (f"djbclark-ade: {_safe_name(prof.get('name'))} profile active until {ny(until)}, {days_left(until, now)}; "
                "restore normal routing now: gate-profile clear (stay longer: gate-profile extend --for 24h)")
        return _mark_and_ping(data, "last_daily_nudge", ny_date(now), text, ping)
