"""ade_gates: the Claude quota gates' numbers, from code defaults, config/gates.toml, a temporary profile and env JSON.

Imported by bin/claude-fleet-governor, bin/claude-quota-guard and bin/gate-profile (they run under `python3 -I`, so each
puts this directory on sys.path first, the way bin/acp-dispatch does for failover.py). Not a program.

  load_gates(gate, now, defaults) -> (thresholds, info)      gate: "governor" | "quota_guard" | "frontier"

Precedence, lowest to highest: `defaults` (the script's THRESHOLDS: the fail-safe when config/gates.toml is missing or
unparsable) < gates.toml baseline < the active profile < env JSON (CLAUDE_GOVERNOR_THRESHOLDS /
CLAUDE_QUOTA_GUARD_THRESHOLDS; tests and emergencies; bad input raises GateEnvError). The `frontier` gate has NO env override:
its keys are the away frontier allowance (docs/gates.md), and an environment variable an agent can set must not widen it.

A profile (state: ~/.local/state/ade/gate-profile.json, env GATE_PROFILE_STATE) applies only when ALL of these hold; otherwise
the baseline applies and info["ignored"] says why: the file parses as {"schema": 1, "profile", "since", "until", ...}; both
times are timezone-aware UTC; since <= now < until; until - since <= [meta].max_profile_hours; the profile exists in
gates.toml; every key it sets is listed under [floors.<gate>], moves in that key's `loosen` direction (never tighter than the
baseline) and stays within `bound`. One bad value rejects the whole profile, for both gates (the governor and the guard
must agree). An expired file is ignored, left in place as the audit trail, and announced once (`notify_expired`). The profile
file is read as a regular file only (no symlink, FIFO or directory), at most 64 KiB.

The baseline is guarded at run time: a key listed under [floors] whose gates.toml value is looser than the code default in its
floor direction gets the code default instead (logged once to stderr, info["baseline_guarded"]): the file may tighten or equal
the code, a loosening belongs in a profile. Keys with no floor entry (timings, ages, locks) take the file's value.

info keys: source ("gates.toml" | "code"), toml_error, toml_path, baseline (the values before profile and env), profile
({name, since, until, reason, set_by} or None), ignored (why a state file does not apply, or None), expired (the profile
dict when the file expired and no one was told yet, else None), profile_values, env_values, baseline_guarded ({key: the
gates.toml value that was replaced by the code default}).
"""
from __future__ import annotations

import errno
import fcntl
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GATES = ("governor", "quota_guard", "frontier")
ENV_VARS = {"governor": "CLAUDE_GOVERNOR_THRESHOLDS", "quota_guard": "CLAUDE_QUOTA_GUARD_THRESHOLDS"}
SCHEMA = 1
DEFAULT_MAX_HOURS = 240
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# Pairs that must stay in order after a profile is applied, each (hi, lo) with hi at least lo. The guard's weekly triggers fire
# watch, then tight, then critical as the percent left falls; the governor's tight triggers must not fire after its critical one.
# A profile that crosses a pair is rejected whole.
ORDERINGS = {
    "quota_guard": (("watch_weekly", "tight_weekly"), ("tight_weekly", "critical_weekly")),
    "governor": (("tight_left_weekly", "critical_left"), ("tight_left_five_hour", "critical_left")),
}

# The `frontier` gate (docs/gates.md "Frontier allowance"): the code default is the fail-safe baseline, exactly today's rule
# (no judged use, one frontier slice per pool per wave, no Agent-tool calls without asking).
FRONTIER_DEFAULTS = {
    "frontier1_judged": 0.0,                 # 1 = an agent may pick the claude frontier model on its own judgment
    "frontier2_judged": 0.0,                 # same for the codex frontier model
    "frontier1_per_wave": 1.0,               # frontier slices in flight per wave on the claude pool
    "frontier2_per_wave": 1.0,               # same on the codex pool
    "frontier1_agent_calls_per_day": 0.0,    # Agent-tool frontier-1 calls allowed without asking per New York day (0: always ask)
    "frontier1_min_left": 10.0,              # percent of the frontier-1 cap that must be left
    "frontier2_min_left": 60.0,              # percent left on the codex binding window
}
FRONTIER_REASON_MIN, FRONTIER_REASON_MAX = 10, 200
GUARD_STATE_MAX_AGE_S = 30 * 60              # quota-guard.json older than this proves nothing about the level
JUDGED_OK_LEVELS = ("ok", "watch")           # tight and critical are the stop signal in every profile
JUDGED_OK_REASONS = ("weekly",)              # the only watch reason a profile may spend through (not stale, fable cap, alert, snapshot-only)
MAX_PROFILE_BYTES = 64 * 1024     # the profile file is a few hundred bytes; anything bigger is not one
NOTIFY_LOCK_WAIT = 10.0           # s the governor/guard wait for the state lock before skipping a notice (retried next run)
CLI_LOCK_WAIT = 120.0             # s `gate-profile set/extend/clear` wait: longer than two 60 s pings (env GATE_PROFILE_LOCK_WAIT)
_LOGGED: set[str] = set()


class GateEnvError(ValueError):
    """The env JSON override is not usable."""


class LockBusy(Exception):
    """The state lock stayed held past the wait bound (a ping is in flight)."""


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
    """A finite number a float can hold: bool, nan, inf and an integer too large for a float are not numbers."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e300


def _show(v: Any) -> str:
    """repr(v) for a message; a huge integer (repr raises past 4300 digits) is named, not printed; long text is cut."""
    if isinstance(v, int) and v.bit_length() > 1024:
        return "an out-of-range integer"
    text = repr(v)
    return text if len(text) <= 80 else text[:77] + "..."


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
    except (tomllib.TOMLDecodeError, ValueError, RecursionError) as e:     # 4300+ digit integer: ValueError; 5000 nested arrays: RecursionError
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
        return f"{_show(value)} is not a number"
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


def baseline_loosens(cfg: dict[str, Any], gate: str, key: str, value: float, default: float) -> bool:
    """True when the gates.toml baseline `value` is looser than the code `default` in the key's floor direction. A key with no
    floor entry has no direction (False); a floor entry whose direction is unreadable trusts only the code default."""
    spec = floor_spec(cfg, gate, key)
    if spec is None:
        return False
    if spec.get("loosen") == "lower":
        return value < default
    if spec.get("loosen") == "higher":
        return value > default
    return value != default


def ordering_problems(gate: str, values: dict[str, Any]) -> list[str]:
    """Where `values` (a gate's keys after a profile is applied) break ORDERINGS; [] when they hold or a key is absent."""
    out = []
    for hi, lo in ORDERINGS.get(gate, ()):
        a, b = values.get(hi), values.get(lo)
        if is_num(a) and is_num(b) and a < b:
            out.append(f"{hi} {a:g} must be at least {lo} {b:g}")
    return out


def profile_problems(cfg: dict[str, Any], name: str, baselines: dict[str, dict[str, float]]) -> list[str]:
    """Every reason profile `name` cannot be used; [] when it can. `baselines` is {gate: {key: baseline value}}."""
    if not NAME_RE.fullmatch(str(name)):      # a name the gates would ignore at run time must not be set
        return [f"profile name {_show(name)} is not [a-z0-9_-], 32 chars at most"]
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

def _read_regular(path: Path) -> tuple[bytes | None, str | None]:
    """(bytes, None) | (None, None) when absent | (None, why) for a symlink, FIFO, directory, device, oversized or unreadable file.
    Never blocks (O_NONBLOCK) and never follows a final symlink (O_NOFOLLOW); the type is checked on the open descriptor."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return None, None
    except OSError as e:
        if e.errno == errno.ELOOP:
            return None, f"{path}: is a symlink (not followed)"
        return None, f"{path}: unreadable ({e.strerror or e})"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, f"{path}: not a regular file"
        data = b""
        while len(data) <= MAX_PROFILE_BYTES:
            chunk = os.read(fd, MAX_PROFILE_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > MAX_PROFILE_BYTES:
            return None, f"{path}: larger than {MAX_PROFILE_BYTES // 1024} KiB"
        return data, None
    except OSError as e:
        return None, f"{path}: unreadable ({e.strerror or e})"
    finally:
        os.close(fd)


def read_profile_file() -> tuple[dict[str, Any] | None, str | None]:
    """(parsed dict, None) | (None, None) when there is no file | (None, why) when it cannot be used at all."""
    path = profile_state_path()
    raw, why = _read_regular(path)
    if raw is None:
        return None, why
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):      # bad JSON, bad UTF-8, a 4300+ digit integer, absurd nesting
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
    schema = data.get("schema")
    if type(schema) is not int or schema != SCHEMA:      # not True, not 1.0
        res["ignored"] = f"profile file schema {_show(schema)} is not {SCHEMA}"
        return res
    raw_name = data.get("profile")
    name = raw_name if isinstance(raw_name, str) and NAME_RE.fullmatch(raw_name) else None      # ASCII [a-z0-9_-], 32 at most
    since, until = parse_utc(data.get("since")), parse_utc(data.get("until"))
    if until is None:
        res["ignored"] = "`until` is missing or not a UTC time (timezone-aware, offset zero)"
        return res
    info = {"name": name, "since": data.get("since"), "until": data.get("until"),
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
    elif name is None:
        res["ignored"] = "`profile` is missing or not a valid name ([a-z0-9_-], 32 characters at most)"
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
    var = ENV_VARS.get(gate)
    raw = os.environ.get(var) if var else None
    if not raw:
        return {}
    try:
        over = json.loads(raw)
    except (ValueError, RecursionError) as e:       # JSONDecodeError, and the plain ValueError of a 4300+ digit integer
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
                            "profile": None, "ignored": None, "expired": None, "profile_values": {}, "env_values": {},
                            "baseline_guarded": {}}
    cfg, err = read_toml()
    if cfg is not None:
        file_base = toml_baseline(cfg, gate)
        if file_base is None:
            err = f"{toml_path()}: [{gate}] is missing, empty or holds a non-number"
            cfg = None
        else:
            accepted: dict[str, float] = {}
            for k, v in file_base.items():
                if defaults and k not in base:
                    continue
                if defaults and baseline_loosens(cfg, gate, k, v, base[k]):
                    info["baseline_guarded"][k] = v
                    _log_once(f"{toml_path()} [{gate}].{k} = {v:g} is looser than the code default {base[k]:g}; using the code "
                              "default (a loosening belongs in a profile)")
                    continue
                accepted[k] = v
            base.update(accepted)
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


# -- the frontier allowance ------------------------------------------------------------------------------------------

def load_frontier(now: datetime | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    """The effective `frontier` gate (FRONTIER_DEFAULTS < gates.toml < active profile) and its info dict."""
    return load_gates("frontier", now, FRONTIER_DEFAULTS)


def frontier_reason(text: Any) -> tuple[str | None, str | None]:
    """(reason, problem) for a `frontier-reason`: (None, None) when missing or blank (baseline treatment), (None, why) when
    given but not one line of FRONTIER_REASON_MIN..MAX characters, else (the stripped one-line reason, None)."""
    if text is None:
        return None, None
    if not isinstance(text, str):
        return None, "a frontier-reason must be text"
    s = text.strip()
    if not s:
        return None, None
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        return None, "a frontier-reason is one line (no newline or control character)"
    if not FRONTIER_REASON_MIN <= len(s) <= FRONTIER_REASON_MAX:
        return None, f"a frontier-reason is {FRONTIER_REASON_MIN}-{FRONTIER_REASON_MAX} characters (got {len(s)})"
    return s, None


def judged_guard_block(state: Any, t: dict[str, float], now: datetime) -> str | None:
    """Why the claude frontier model's judged use is NOT allowed by the quota guard's state file, or None when it is. Fails closed:
    a missing, unreadable, stale, future-dated or unexplained state blocks. `t` is the effective `frontier` gate."""
    if not isinstance(state, dict):
        return "the quota guard state is missing or unreadable"
    checked = parse_utc(state.get("checked_at"))
    if checked is None:
        return "the quota guard state has no usable checked_at"
    age = (now - checked).total_seconds()
    if not -60 <= age <= GUARD_STATE_MAX_AGE_S:
        return f"the quota guard state is {age / 60:.0f} min old (limit {GUARD_STATE_MAX_AGE_S // 60})"
    level = state.get("level")
    if level not in JUDGED_OK_LEVELS:
        return f"the quota guard level is {level!r}: the baseline rules apply at tight and critical"
    if state.get("stale") is not False:
        return "the quota guard data is stale"
    reasons = state.get("reasons")
    if level == "watch" and (not isinstance(reasons, list) or not reasons
                             or any(r not in JUDGED_OK_REASONS for r in reasons)):
        return f"the quota guard is at watch for a reason other than the weekly window ({reasons!r})"
    if level == "ok" and reasons not in (None, []):
        return f"the quota guard reports reasons {reasons!r} at level ok"
    left = state.get("fable_left")
    if not is_num(left):
        return "the frontier-1 cap reading (fable_left) is missing"
    if left < t.get("frontier1_min_left", FRONTIER_DEFAULTS["frontier1_min_left"]):
        return f"the frontier-1 cap has {left:g}% left (floor {t['frontier1_min_left']:g}%)"
    return None


# -- expiry notice and daily nudge -----------------------------------------------------------------------------------

def _marked_text(data: dict[str, Any], key: str, value: str) -> str:
    return json.dumps({**data, key: value}, indent=1, sort_keys=True) + "\n"


def _mark_and_ping(data: dict[str, Any], key: str, value: str, text: str, ping: Callable[[str], bool]) -> bool:
    """Write `key: value` into the profile file, then ping; remove the mark again when the ping fails, so a failed ping is
    retried by the next run and a sent one never is. Call with the state lock held. The mark is taken back only while the file
    still holds exactly what was marked: a profile that was cleared, set again or extended meanwhile (a writer that did not wait
    for the lock) is never overwritten or brought back."""
    path = profile_state_path()
    marked = _marked_text(data, key, value)
    try:
        atomic_write(path, marked)
    except OSError as e:
        _log_once(f"could not record {key}: {e}")
        return False
    ok = False
    try:
        ok = bool(ping(text))
    finally:
        if not ok:
            try:
                now_raw, _ = _read_regular(path)
                if now_raw == marked.encode("utf-8"):
                    atomic_write(path, json.dumps(data, indent=1, sort_keys=True) + "\n")
            except OSError:
                pass
    return ok


def state_lock_path() -> Path:
    path = profile_state_path()
    return path.with_name(path.name + ".lock")


def _state_lock(wait: float | None = None, create: bool = False):
    """The flock beside the state file, held for the `with`; None when it cannot be opened (no state dir: nothing to notify;
    `create` makes the directory first). Waits at most `wait` seconds (default NOTIFY_LOCK_WAIT) and raises LockBusy after.
    Serialises every writer of the profile file: the governor's and guard's notices, `gate-profile set/extend/clear`. It is held
    across a ping (up to 60 s), so a reader never takes it: the gates read the file lock-free (writes are atomic replaces)."""
    lock_path = state_lock_path()
    try:
        if create:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        deadline = time.monotonic() + (NOTIFY_LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockBusy(f"{lock_path} is held (a ping is in flight)") from None
                time.sleep(0.05)
        return os.fdopen(fd, "a")
    except BaseException:
        os.close(fd)      # the one path that leaves the descriptor open is the success return, which fdopen owns
        raise


def _safe_name(name: Any) -> str:
    return name if isinstance(name, str) and NAME_RE.fullmatch(name) else "gate"


def notify_expired(info: dict[str, Any], ping: Callable[[str], bool], now: datetime | None = None) -> bool:
    """Send ONE ping for an expired profile file and record `expired_notified` in it. True when a ping was sent."""
    exp = info.get("expired")
    if not isinstance(exp, dict):
        return False
    now = now or datetime.now(UTC)
    try:
        lock = _state_lock()
    except LockBusy as e:
        _log_once(f"expiry notice skipped, retried next run: {e}")
        return False
    if lock is None:
        _log_once(f"expiry notice skipped, cannot lock {state_lock_path()} (not a usable regular file)")
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
    try:
        lock = _state_lock()
    except LockBusy as e:
        _log_once(f"daily nudge skipped, retried next run: {e}")
        return False
    if lock is None:
        _log_once(f"daily nudge skipped, cannot lock {state_lock_path()} (not a usable regular file)")
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
