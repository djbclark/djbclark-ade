#!/usr/bin/env python3
"""Which Claude Code session is this process in? ONE shared answer for ade_claims.py and acp-dispatch (in bin/ since 2026-11-06, docs/slim E3; fleet.py and autorename, its other callers, were removed the same day).

`CLAUDE_CODE_SESSION_ID` in a tool shell is not reliable (2026-11-02, PR 259; upstream issue 81304): a session started from another session's
environment (a /baton or /handoff successor, a Paseo agent launched from a shell inside the predecessor, `--fork-session`) keeps the PREDECESSOR's
id there, and a non-Claude agent started from a Claude shell inherits that shell's CLAUDE_PID. Taking the env var at its word resolves a successor to
its predecessor: its relays go out under the predecessor's label, and every reply goes to the wrong session.

The registry is the authority: a running Claude Code writes `<config>/sessions/<pid>.json` with its current `sessionId`. The anchor is
`CLAUDE_PID`, which Claude Code sets in every child shell next to `CLAUDE_CODE_SESSION_ID` to its OWN pid, so a nested Claude (a `claude -p` or ACP
child) names itself. It counts only when it is an ancestor of this process, has a registry file whose `pid` and `procStart` match the live process,
and holds a uuid `sessionId`. Never "the nearest ancestor with a file": that skips an unregistered nested Claude and names its parent's session
(adversary, PR 259). The env var is only the fallback when no registry entry matches.

Moved here from skills/autorename/autorename.py (PR 259) so there is one copy; autorename imports it.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

SID_RE = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def proc_start_matches(pid: int, recorded: Any) -> bool:
    """False only when the registry's `procStart` provably names another process than the live `pid`: a crashed Claude leaves its file behind and
    the pid can be reused. Claude Code writes `procStart` as `ps -o lstart= -p PID` under `LC_ALL=C TZ=UTC`; this runs the same command, so both
    stamps are UTC and no local-time conversion (DST's repeated hour) is involved. A missing or unparsable stamp, or a failing `ps`, proves nothing,
    so the pid alone stands."""
    if not isinstance(recorded, str) or not recorded.strip():
        return True
    fmt = "%a %b %d %H:%M:%S %Y"
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=10, env={**os.environ, "LC_ALL": "C", "TZ": "UTC"}).stdout.strip()
        if not out:
            return True
        live = calendar.timegm(time.strptime(" ".join(out.split()), fmt))
        was = calendar.timegm(time.strptime(" ".join(recorded.split()), fmt))
    except (OSError, ValueError, OverflowError, subprocess.TimeoutExpired):
        return True
    return abs(live - was) <= 5


def ancestor_pids() -> list[int]:
    """Pids above this process, nearest first (one `ps` call). Empty when the process table cannot be read."""
    try:
        text = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    parent: dict[int, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            parent[int(parts[0])] = int(parts[1])
    chain: list[int] = []
    pid = os.getppid()
    for _ in range(64):
        if pid <= 1 or pid not in parent:
            break
        chain.append(pid)
        pid = parent[pid]
    return chain


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True    # EPERM: it exists
    return True


def registered_session_id(ancestors: Callable[[], Iterable[int]] | None = None, require_ancestor: bool = True) -> str | None:
    """The registry's session id for the Claude Code that owns this process, or None (then the env var is the fallback). ANCESTORS returns the pids
    above this process (default: a `ps` walk); a caller that hides its ancestry (a notice sender) passes one that returns nothing."""
    raw = os.environ.get("CLAUDE_PID", "")
    if not raw.isdigit() or int(raw) <= 1:
        return None
    pid = int(raw)
    if require_ancestor:
        if pid not in set((ancestors or ancestor_pids)()):
            return None
    elif not pid_alive(pid):    # no ancestry to prove it, so the Claude process itself must still be alive (and, below, the same one)
        return None
    try:
        data = json.loads((config_dir() / "sessions" / f"{pid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("pid") != pid:
        return None
    sid = data.get("sessionId")
    if not (isinstance(sid, str) and SID_RE.fullmatch(sid)):
        return None
    return sid if proc_start_matches(pid, data.get("procStart")) else None


def own_session_id(ancestors: Callable[[], Iterable[int]] | None = None) -> str | None:
    """This process's Claude Code session id, or None. The registry's id first. Else CLAUDE_CODE_SESSION_ID, unless CLAUDE_PID names a process that is
    provably NOT above this one: Claude Code exports both to every child shell, so a non-Claude agent (omp, codex) started from a Claude shell, or a
    /baton successor, carries a pair that names another session. With CLAUDE_PID unset, or an ancestor table that cannot be read, the env var stands
    alone (an older Claude, a failing `ps`)."""
    anc = set((ancestors or ancestor_pids)())
    raw = os.environ.get("CLAUDE_PID", "")
    if raw.isdigit() and int(raw) > 1 and anc and int(raw) not in anc:
        return None
    return registered_session_id(lambda: anc) or (os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip() or None


def owner_session_id(ancestors: Callable[[], Iterable[int]] | None = None) -> str:
    """The session id to record or compare as an OWNER (claims, job records, handoff listings): the registry's id of the live Claude CLAUDE_PID names (an
    ancestor, or a detached job's still-living Claude), else CLAUDE_CODE_SESSION_ID as is, else "". Unlike own_session_id it never vetoes the env var: an orphaned background job (`nohup`, `setsid`, a tmux server
    started from a Claude shell) is reparented to launchd, so its CLAUDE_PID is no ancestor, yet its env pair is correct and its work belongs to that
    session. Only a /baton successor's inherited stale id is corrected (adversary, PR 248 r1b A1). One writer and one reader of an owner use this, so
    they agree (A2).

    The registry is read WITHOUT the ancestor proof here: Claude Code sets CLAUDE_PID next to CLAUDE_CODE_SESSION_ID, so the Claude process it names (live,
    same procStart, same pid in its file) is the session that exported this environment even after the job was detached. A successor's orphaned `nohup`
    job therefore still resolves to the successor's own id, not the stale env id its detached environment carries (local-review r2). If that process is
    gone, or its file does not match, the env var stands. (This is also why an owner read keeps treating an agent started from a Claude shell as that
    Claude: owners are not identity labels, and dispatched agents carry ADE_CLAIM_ID first.)

    Known limit (local-review r3, A4/A5): once that Claude has exited, a successor's detached job can only read the stale id its environment carries, and a
    registry whose sessionId changes in place (a /clear) moves a living orphan to the new id; a failing `ps` lets a reused pid pass the procStart check. A
    job that must outlive its Claude under the successor's id gets it from `claude_identity.py` at launch (acp-dispatch records it)."""
    return (registered_session_id(ancestors, require_ancestor=False) or (os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip())


if __name__ == "__main__":
    # `python3 claude_identity.py`: the owner id for a shell script (skills/baton, skills/handoff), "" and exit 1 when there is none.
    _sid = owner_session_id()
    print(_sid)
    raise SystemExit(0 if _sid else 1)
