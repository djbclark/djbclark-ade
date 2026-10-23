#!/usr/bin/env python3
"""quota_nudge.py — tell a Claude session what the quota guard's level means for it.

Registered under UserPromptSubmit next to context_size_nudge.py. Claude Code surfaces
UserPromptSubmit stdout to the model as a system-reminder. Reads ONLY the state file that
bin/claude-quota-guard writes (never runs aiuse; no subprocess, no network) and prints that
level's `advice`, prefixed `[quota-guard <level>]`, once per (session id, level): again
when the level rises, and again after a drop followed by a rise.

Silent when the state file is missing, unreadable, older than MAX_AGE_SECONDS (a stopped
guard must not keep nagging) or at level `ok`.

Separately, once per session while the state's `unreadable_since` is set and over an hour old
(the guard has failed to read aiuse on every run since), it prints "[quota-guard unreadable]
aiuse unreadable since <when>: check `aiuse --available --json`", whatever the level or age of
the rest of the state.

History: 2026-10-23, after the Claude weekly window ran out 2.6 days early on 2026-10-20
with a `conserve` alert unread for 11 hours. docs/model-routing.md "Quota guard".

MUST always exit 0 and finish in well under 100 ms. Python 3 stdlib only.
"""
# Every failure is swallowed on purpose: a hook error must never block a prompt.
# ruff: noqa: BLE001, S110
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ("ok", "watch", "tight", "critical")
MAX_AGE_SECONDS = 2 * 3600
UNREADABLE_AFTER_SECONDS = 3600   # an unreadable episode this old gets its own line
MAX_SESSIONS = 200


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


def _unreadable_nudge(raw, session_id, nudges):
    """Print once per session while `unreadable_since` is set and over UNREADABLE_AFTER old (the
    guard has failed to read aiuse for every run since); True when `nudges` changed."""
    since = _parse(raw.get("unreadable_since")) if isinstance(raw, dict) and raw.get("unreadable_since") else None
    if since is None or (_now() - since).total_seconds() <= UNREADABLE_AFTER_SECONDS:
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
    nudges = _load_nudges()
    dirty = _unreadable_nudge(state, session_id, nudges)
    st = _fresh_guard_state()
    if st is not None:
        dirty = _level_nudge(st, session_id, nudges) or dirty
    if dirty:
        _save_nudges(dict(list(nudges.items())[-MAX_SESSIONS:]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
