"""ade_gates: the frontier-model allowance, from code defaults and config/gates.toml [frontier] (docs/gates.md).

Imported by bin/route_agent.py (the planner's per-wave cap), bin/acp-dispatch (the dispatch grant) and
claude/hooks/frontier_agent_gate.py (the Agent-tool hook). Not a program. Since 2026-11-07 (slim-down E7) this is the
frontier half only: the Claude quota gates (the fleet governor, the quota guard, the gate profile tool and their
[governor]/[quota_guard]/[profiles] tables) were deleted, and the Claude reading the allowance needs comes from
route_agent's merged quota snapshot (`aiuse --available --json` plus `paseo usage ls --json`) instead of the quota
guard's state file.

  load_frontier(now) -> (thresholds, info)                 the effective [frontier] gate
  read_guard_state() -> dict | None                        the Claude reading for the allowance (route_agent.claude_quota_state)
  judged_guard_block(state, t, now) -> str | None          why claude's judged frontier use is not allowed now, or None
  judged_pool_block(family, t, now, state, remaining)      the same for either family: one copy for acp-dispatch and route_agent
  frontier_reason(text) -> (reason, problem)               a `frontier-reason` line, checked

The code default (FRONTIER_DEFAULTS) is the FAIL-SAFE, all closed: no judged use, one frontier slice per pool per wave,
no Agent-tool calls without asking. It applies when gates.toml is missing, unreadable or its [frontier] table holds a
non-number. The standing allowance is gates.toml's [frontier] baseline: a "higher is looser" key (every key but
`*_min_left`) may rise to its `[floors.frontier]` bound and takes the code default above it; a `*_min_left` key is never
looser (lower) than the code default. There is no env override of the numbers (an agent must not widen the allowance
from its environment); GATES_TOML redirects the file (tests). info keys: source ("gates.toml" | "code"), toml_error,
toml_path, baseline, baseline_guarded ({key: the file's value that was replaced}), profile (always None: gate profiles
were deleted with the quota gates; kept so older readers of `info["profile"]` still work).
"""
from __future__ import annotations

import os
import stat
import sys
import tomllib
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

FRONTIER_DEFAULTS = {
    "frontier1_judged": 0.0,                 # 1 = an agent may pick the claude frontier model on its own judgment
    "frontier2_judged": 0.0,                 # same for the codex frontier model
    "frontier1_per_wave": 1.0,               # frontier slices in flight per wave on the claude pool
    "frontier2_per_wave": 1.0,               # same on the codex pool
    "frontier1_agent_calls_per_day": 0.0,    # Agent-tool frontier-1 calls allowed without asking per New York day (0: always ask)
    "frontier1_min_left": 10.0,              # percent of the frontier-1 (Fable) cap that must be left
    "frontier1_window_min_left": 30.0,       # percent left on the tightest Claude window (was the quota guard's tight level)
    "frontier2_min_left": 60.0,              # percent left on the codex binding window
}
FRONTIER_REASON_MIN, FRONTIER_REASON_MAX = 10, 200
GUARD_STATE_MAX_AGE_S = 30 * 60              # a Claude reading older than this proves nothing about the window
_LOGGED: set[str] = set()


def toml_path() -> Path:
    return Path(os.environ.get("GATES_TOML") or Path(__file__).resolve().parent.parent / "config" / "gates.toml")


def is_num(v: Any) -> bool:
    """A finite number a float can hold: bool, nan, inf and an integer too large for a float are not numbers."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e300


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


def ny_date(dt: datetime) -> str:
    """The America/New_York calendar date (the Agent-tool hook's daily cap)."""
    return dt.astimezone(NY).date().isoformat()


def read_toml() -> tuple[dict[str, Any] | None, str | None]:
    path = toml_path()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)      # a FIFO with no writer would block a plain open forever
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return None, f"{path}: not a regular file"
            return tomllib.load(fh), None
    except OSError as e:
        return None, f"{path}: {e.strerror or e}"
    except (tomllib.TOMLDecodeError, ValueError, RecursionError) as e:     # 4300+ digit integer: ValueError; 5000 nested arrays: RecursionError
        return None, f"{path}: not valid TOML ({e})"


def code_direction(key: str) -> str:
    """"lower" for a `*_min_left` key (lower is looser), "higher" for every other frontier key. From the code, never the file."""
    return "lower" if key.endswith("_min_left") else "higher"


def baseline_limit(cfg: dict[str, Any], key: str, default: float) -> float:
    """The loosest gates.toml value `key` may take: a "higher" key may rise to its `[floors.frontier]` numeric `bound` (the
    standing allowance); a `*_min_left` key, or one whose bound is missing, trusts only the code `default`."""
    if code_direction(key) == "higher":
        floors = cfg.get("floors")
        tbl = floors.get("frontier") if isinstance(floors, dict) else None
        spec = tbl.get(key) if isinstance(tbl, dict) else None
        if isinstance(spec, dict) and is_num(spec.get("bound")):
            return float(spec["bound"])
    return default


def load_frontier(now: datetime | None = None) -> tuple[dict[str, float], dict[str, Any]]:
    """The effective `frontier` gate (FRONTIER_DEFAULTS < gates.toml [frontier], capped at its floors) and its info dict.
    `now` is accepted for the older signature (a gate profile used to depend on it) and ignored."""
    base = dict(FRONTIER_DEFAULTS)
    info: dict[str, Any] = {"source": "code", "toml_error": None, "toml_path": str(toml_path()), "baseline": dict(base),
                            "profile": None, "baseline_guarded": {}}
    cfg, err = read_toml()
    if cfg is not None:
        tbl = cfg.get("frontier")
        if not isinstance(tbl, dict) or not tbl or not all(is_num(v) for v in tbl.values()):
            err = f"{toml_path()}: [frontier] is missing, empty or holds a non-number"
        else:
            for k, v in tbl.items():
                if k not in base:
                    continue
                v, lim = float(v), baseline_limit(cfg, k, FRONTIER_DEFAULTS[k])
                if (v < lim) if code_direction(k) == "lower" else (v > lim):
                    info["baseline_guarded"][k] = v
                    _log_once(f"{toml_path()} [frontier].{k} = {v:g} is looser than "
                              f"{'the code default' if lim == FRONTIER_DEFAULTS[k] else 'its floor bound'} {lim:g}; "
                              "using the code default")
                    continue
                base[k] = v
            info.update(source="gates.toml", baseline=dict(base))
    if err:
        info["toml_error"] = err
        _log_once(f"{err}; using the closed code defaults for frontier")
    return base, info


def frontier_reason(text: Any) -> tuple[str | None, str | None]:
    """(reason, problem) for a `frontier-reason`: (None, None) when missing or blank (closed treatment), (None, why) when
    given but not one line of FRONTIER_REASON_MIN..MAX characters, else (the stripped one-line reason, None)."""
    if text is None:
        return None, None
    if not isinstance(text, str):
        return None, "a frontier-reason must be text"
    s = text.strip()
    if not s:
        return None, None
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in s):
        return None, "a frontier-reason is one line, no control or format character"
    if not FRONTIER_REASON_MIN <= len(s) <= FRONTIER_REASON_MAX:
        return None, f"a frontier-reason is {FRONTIER_REASON_MIN}-{FRONTIER_REASON_MAX} characters (got {len(s)})"
    return s, None


def read_guard_state() -> Any:
    """The Claude reading the allowance judges: route_agent.claude_quota_state(), built from the merged quota snapshot
    (`aiuse --available --json` and `paseo usage ls --json`). None when route_agent cannot be imported or the read fails;
    `judged_guard_block` fails closed on None. Kept under its old name (it read the quota guard's state file until
    2026-11-07) so acp-dispatch and the hook keep their import surface."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import route_agent
        return route_agent.claude_quota_state()
    except Exception as e:  # noqa: BLE001 - an unreadable reading is the closed treatment, never a crash
        _log_once(f"the Claude quota reading failed ({type(e).__name__}: {str(e)[:120]})")
        return None


def judged_guard_block(state: Any, t: dict[str, float], now: datetime) -> str | None:
    """Why the claude frontier model's judged use is NOT allowed by the Claude reading (`read_guard_state`), or None when it
    is. Fails closed: a missing, unknown (a Paseo report that is not `available` with no other source), stale (older than
    GUARD_STATE_MAX_AGE_S), future-dated or windowless reading blocks, and so do a tightest Claude window under
    `frontier1_window_min_left` (the quota guard's old tight/critical stop signal) and a Fable cap under `frontier1_min_left`.
    `t` is the effective `frontier` gate."""
    if not isinstance(state, dict):
        return "the Claude quota reading is missing or unreadable"
    unknown = state.get("unknown")
    if unknown:
        return f"the Claude quota is unknown ({str(unknown)[:120]})"
    checked = parse_utc(state.get("checked_at"))
    if checked is None:
        return "the Claude quota reading has no usable time"
    age = (now - checked).total_seconds()
    if not -60 <= age <= GUARD_STATE_MAX_AGE_S:
        return f"the Claude quota reading is {age / 60:.0f} min old (limit {GUARD_STATE_MAX_AGE_S // 60})"
    left = state.get("remaining")
    if not is_num(left):
        return "the Claude quota reading has no window percentage"
    floor = t.get("frontier1_window_min_left", FRONTIER_DEFAULTS["frontier1_window_min_left"])
    if left < floor:
        return f"the Claude subscription has {left:g}% left on its tightest window (floor {floor:g}%): the closed rules apply"
    fable = state.get("fable_left")
    if not is_num(fable):
        return "the frontier-1 cap reading (fable_left) is missing"
    if fable < t.get("frontier1_min_left", FRONTIER_DEFAULTS["frontier1_min_left"]):
        return f"the frontier-1 cap has {fable:g}% left (floor {t['frontier1_min_left']:g}%)"
    return None


def judged_pool_block(family: int, t: dict[str, float], now: datetime, guard_state: Any, remaining: Any) -> str | None:
    """Why the allowance's cap checks fail for frontier `family` (1 claude, 2 codex and the other pools), or None when they pass.
    claude: `judged_guard_block` on the Claude reading. Other pools: the pool reading at least `frontier2_min_left`. One copy for
    acp-dispatch's grant and route_agent's per-wave cap."""
    if family == 1:
        return judged_guard_block(guard_state, t, now)
    floor = t["frontier2_min_left"]
    if is_num(remaining) and remaining >= floor:
        return None
    return f"the codex pool has {'no reading' if not is_num(remaining) else f'{remaining:g}% left'} (floor {floor:g}%)"

