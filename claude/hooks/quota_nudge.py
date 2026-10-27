#!/usr/bin/env python3
"""quota_nudge.py — tell a Claude session what the quota guard's level means for it.

Registered under UserPromptSubmit next to context_size_nudge.py. Claude Code surfaces
UserPromptSubmit stdout to the model as a system-reminder. Reads ONLY the state file that
bin/claude-quota-guard writes (never runs aiuse; no subprocess, no network) and prints that
level's `advice`, prefixed `[quota-guard <level>]`, once per (session id, level): again
when the level rises, and again after a drop followed by a rise.

Silent when the state file is missing, unreadable, older than MAX_AGE_SECONDS (a stopped
guard must not keep nagging) or at level `ok`.

Separately, once per session it prints "[quota-guard unreadable] aiuse unreadable since <when>:
check `aiuse --available --json`" while the guard reports a real, current unreadable episode:
`last_unreadable_pinged_at` is set (the guard failed at least twice in a row and pinged) AND
`last_unreadable_at` is within MAX_AGE_SECONDS (the guard is still running and still failing).
A single hiccup, or a guard that stopped running, prints nothing. It does not depend on the
age of the level part of the state.

The once-per-session memory (~/.claude/state/quota-nudges.json) is read, updated and written
under an exclusive flock on <file>.lock (non-blocking, LOCK_RETRIES x LOCK_WAIT_S), so two
sessions' prompts never overwrite each other's acknowledgement; if the lock cannot be had the
hook prints nothing and changes nothing.

While the guard state names an unexpired gate profile (`profile`: {name, until}, bin/gate-profile, 2026-10-26) it also prints, once per
session per America/New_York day (any level, `ok` included), "[gates] <name> profile active until <time>; gate-profile clear restores
normal routing". The state already holds it: no extra file is read. When the state's `frontier_allowance.judged` is true (2026-10-27: the
guard found the effective gate, standing baseline or profile, allowing judged frontier use, level ok/watch-for-weekly, cap floor held)
the line says the frontier model is allowed where the agent judges it significantly better, with a one-line `frontier-reason`, and the
per-day Agent-tool cap; with no profile active that is its own once-per-day line, "[gates] frontier allowance: ...".

History: 2026-10-23, after the Claude weekly window ran out 2.6 days early on 2026-10-20
with a `conserve` alert unread for 11 hours. docs/model-routing.md "Quota guard".

MUST always exit 0 and finish in well under 100 ms. Python 3 stdlib only.
"""
# Every failure is swallowed on purpose: a hook error must never block a prompt.
# ruff: noqa: BLE001, S110
import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ("ok", "watch", "tight", "critical")
FRONTIER1, JUDGMENT = "Fable 5.1", "Opus 5.5"   # the literal names S3 replaces with role lookups (docs/model-tiers-design.md)
MAX_AGE_SECONDS = 2 * 3600
MAX_SESSIONS = 200
LOCK_RETRIES = 10
LOCK_WAIT_S = 0.02


def _state_file():
    return Path(os.environ.get("CLAUDE_QUOTA_GUARD_STATE")
                or Path.home() / ".local/state/ade/quota-guard.json")


def _nudge_file():
    return Path(os.environ.get("CLAUDE_QUOTA_NUDGE_STATE")
                or Path.home() / ".claude/state/quota-nudges.json")


def _now():
    raw = os.environ.get("CLAUDE_QUOTA_GUARD_NOW")
    if raw:
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _fresh_guard_state():
    try:
        st = json.loads(_state_file().read_text())
        checked = datetime.fromisoformat(str(st["checked_at"]).replace("Z", "+00:00"))
    except Exception:
        return None
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    if not isinstance(st, dict) or (_now() - checked).total_seconds() > MAX_AGE_SECONDS:
        return None
    return st


def _load_nudges():
    try:
        d = json.loads(_nudge_file().read_text())
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_nudges(state):
    try:
        p = _nudge_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=p.parent)
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp, p)
    except Exception:
        pass


def _parse(text):
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@contextlib.contextmanager
def _nudge_lock():
    """Exclusive flock on <nudge file>.lock around the whole read-modify-write. Yields True when
    held, False when it could not be had (bounded non-blocking retry, 0.2 s at most)."""
    handle = None
    try:
        p = _nudge_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        handle = open(p.with_name(p.name + ".lock"), "a")
        for _ in range(LOCK_RETRIES):
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                time.sleep(LOCK_WAIT_S)
        else:
            held = False
    except Exception:
        held = False
    try:
        yield held
    finally:
        try:
            if handle is not None:
                handle.close()  # closing the descriptor drops the flock
        except Exception:
            pass


def _unreadable_nudge(raw, session_id, nudges):
    """See the module docstring for the gate. True when `nudges` changed."""
    if not isinstance(raw, dict) or not raw.get("last_unreadable_pinged_at"):
        return False
    since = _parse(raw.get("unreadable_since"))
    last = _parse(raw.get("last_unreadable_at"))
    if since is None or last is None or (_now() - last).total_seconds() > MAX_AGE_SECONDS:
        return False
    stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    key = f"{session_id}#unreadable"
    if nudges.get(key) == stamp:
        return False
    print(f"[quota-guard unreadable] aiuse unreadable since {stamp}: check `aiuse --available --json`",
          flush=True)
    nudges.pop(key, None)
    nudges[key] = stamp
    return True


def _frontier_text(st):
    """The sentence saying the frontier model is allowed, or None unless the guard state says judged use is in force right now
    (`frontier_allowance.judged`: the effective gate, level ok/watch-for-weekly and the cap floor all hold)."""
    allow = st.get("frontier_allowance")
    calls = allow.get("agent_calls_per_day") if isinstance(allow, dict) else None
    if not (isinstance(allow, dict) and allow.get("judged") is True and isinstance(calls, int) and not isinstance(calls, bool)):
        return None
    cap = f"at most {calls} Agent-tool calls today" if calls > 0 else "no Agent-tool call without asking"
    return (f"{FRONTIER1} (frontier) is allowed where you judge it significantly "
            f"better than {JUDGMENT}; give the reason in one line (acp-dispatch --kind frontier --frontier-reason \"...\"; Agent tool: "
            f"a \"frontier-reason: ...\" prompt line), {cap}")


def _profile_nudge(st, session_id, nudges):
    """One line per session per New York day: while the guard state names an unexpired gate profile, that; with no profile, the frontier
    allowance line when the standing baseline allows judged use (2026-10-27). True when `nudges` changed."""
    prof = st.get("profile")
    until = _parse(prof.get("until")) if isinstance(prof, dict) and isinstance(prof.get("name"), str) else None
    try:
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        today = _now().astimezone(ny).date().isoformat()
        local = until.astimezone(ny) if until is not None else None
        when = f"{local:%a %b} {local.day} {local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'} {local:%Z}" if local else None
    except Exception:
        return False
    frontier = _frontier_text(st)
    if until is None or until <= _now():   # no profile, or the guard has not run since it expired: only the standing allowance may speak
        if frontier is None:
            return False
        key, stamp = f"{session_id}#frontier", today
        if nudges.get(key) == stamp:
            return False
        print(f"[gates] frontier allowance: {frontier}.", flush=True)
        nudges.pop(key, None)
        nudges[key] = stamp
        return True
    key = f"{session_id}#profile"
    stamp = f"{prof.get('until')}|{today}"
    if nudges.get(key) == stamp:
        return False
    name = prof["name"] if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", prof["name"]) else "gate"     # ASCII only, as ade_gates.NAME_RE
    if frontier is not None:
        print(f"[gates] {name} profile active until {when}: {frontier}. gate-profile clear restores normal routing.", flush=True)
    else:
        print(f"[gates] {name} profile active until {when}; gate-profile clear restores normal routing", flush=True)
    nudges.pop(key, None)
    nudges[key] = stamp
    return True


def _level_nudge(st, session_id, nudges):
    level = st.get("level")
    if level not in LEVELS:
        return False
    shown = nudges.get(session_id)
    shown = shown if shown in LEVELS else "ok"
    if level != "ok" and LEVELS.index(level) > LEVELS.index(shown):
        advice = st.get("advice")
        if isinstance(advice, str) and advice.strip():
            print(f"[quota-guard {level}] {advice}", flush=True)
    if shown != level:
        nudges.pop(session_id, None)
        nudges[session_id] = level  # a drop is remembered too, so a later rise speaks again
        return True
    return False


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    try:
        state = json.loads(_state_file().read_text())
    except Exception:
        return
    if not isinstance(state, dict):
        return
    session_id = str(data.get("session_id") or "unknown")
    with _nudge_lock() as held:
        if not held:
            return  # print nothing, change nothing: the next prompt tries again
        nudges = _load_nudges()
        dirty = _unreadable_nudge(state, session_id, nudges)
        st = _fresh_guard_state()
        if st is not None:
            dirty = _level_nudge(st, session_id, nudges) or dirty
            dirty = _profile_nudge(st, session_id, nudges) or dirty
        if dirty:
            _save_nudges(dict(list(nudges.items())[-MAX_SESSIONS:]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
