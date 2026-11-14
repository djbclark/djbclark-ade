"""Lead succession, read from `ade-self-session`'s own handoff records (2026-11-14).

An acknowledged self-handoff replaces the lead: the predecessor is archived and a new agent id carries on. Tools that pinned
the old id (ade-worker-run's window records and `ade.lead` labels, a scheduled `ade-net-resume --lead ID`, ade-auto-permit,
fable-wait) must follow the replacement without a hand step. The durable ledger already exists: `ade-self-session finish`
leaves `handoff-<predecessor>.json` in its state directory with `status: archived` once the predecessor is confirmed
archived, `successor` and the successor's own acknowledgement (`ack.agent_id`). This module only READS those records.
It never writes one and never calls paseo.

A link `predecessor -> successor` counts only when the record is a completed handoff of that daemon home: kind `handoff`,
`predecessor` equal to the file's own id, `home` equal to this daemon's PASEO_HOME, `status` exactly `archived`, a UUID
`successor` different from the predecessor, and `ack.agent_id` equal to that successor. Anything else (a handoff still
awaiting its acknowledgement, an `archive-unknown` one, a record of another home, a corrupt or oversized file, a symlink)
is no link, so the chain stops there and the callers keep their old refusals. A cycle is a
SuccessionError, never an endless loop (every consumer reports it; none silently falls back to the old id).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RECORD_RE = re.compile(r"handoff-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.json")
MAX_RECORD_BYTES = 262144  # ade_self_session reads its own records with the same limit
# `paseo ls --label ade.lead=<id>` costs one CLI call per id: only this many nearest predecessors are queried that way (a
# worker of a lead eight handoffs back is long gone). Registries and ownership checks use the whole lineage (file reads only).
RECENT_PREDECESSORS = 8


class SuccessionError(Exception):
    """A cycle: the ledger is inconsistent, so nothing is resolved from it."""


def default_state_dir(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("ADE_SELF_SESSION_STATE") or Path.home() / ".local/state/djbclark-ade/self-session")


def default_home(env=None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("PASEO_HOME") or Path.home() / ".paseo")


def _read_record(path: Path) -> dict | None:
    """The JSON object in a regular, small file, else None (missing, a symlink, oversized, unreadable, not an object)."""
    # Same discipline as ade_self_session.read_regular: no symlink, no FIFO wait, a bounded read of a regular file.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            raw = os.read(fd, MAX_RECORD_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_RECORD_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return None
    return data if isinstance(data, dict) else None


def _link(record: dict | None, predecessor: str, home: Path) -> str | None:
    """The successor id when `record` is a completed handoff of `predecessor` on this home, else None."""
    if not record:
        return None
    successor = record.get("successor")
    ack = record.get("ack")
    try:
        same_home = Path(str(record.get("home"))).resolve() == home.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if (record.get("kind") != "handoff" or record.get("predecessor") != predecessor or not same_home
            or record.get("status") != "archived" or not isinstance(successor, str) or not UUID_RE.fullmatch(successor)
            or successor == predecessor or not isinstance(ack, dict) or ack.get("agent_id") != successor):
        return None
    return successor


def successor_of(lead: str, state_dir: Path | None = None, home: Path | None = None) -> str | None:
    """The agent that replaced `lead` through a completed self-handoff, or None."""
    if not UUID_RE.fullmatch(lead):
        return None
    state = state_dir or default_state_dir()
    return _link(_read_record(state / f"handoff-{lead}.json"), lead, home or default_home())


def chain(lead: str, state_dir: Path | None = None, home: Path | None = None) -> list[str]:
    """[lead, its successor, that one's successor, ...] up to the agent no completed handoff replaces."""
    out = [lead]
    while True:
        nxt = successor_of(out[-1], state_dir, home)
        if nxt is None:
            return out
        if nxt in out:
            raise SuccessionError(f"lead succession from {lead} is cyclic")
        out.append(nxt)


def effective_lead(lead: str, state_dir: Path | None = None, home: Path | None = None) -> str:
    """The current holder of `lead`'s role: the end of its chain (`lead` itself when it was never replaced)."""
    return chain(lead, state_dir, home)[-1]


def predecessors_by_distance(lead: str, state_dir: Path | None = None, home: Path | None = None) -> list[str]:
    """Every archived agent whose completed-handoff chain ends at `lead` (not `lead` itself), nearest handoff first. A chain
    that comes back to `lead` is a cycle: SuccessionError."""
    state = state_dir or default_state_dir()
    home = home or default_home()
    by_successor: dict[str, set[str]] = {}
    try:
        names = sorted(p.name for p in state.iterdir())
    except OSError:
        return []
    for name in names:
        m = RECORD_RE.fullmatch(name)
        if m:
            nxt = _link(_read_record(state / name), m.group(1), home)
            if nxt:
                by_successor.setdefault(nxt, set()).add(m.group(1))
    found: list[str] = []
    level = [lead]
    while level:
        nxt_level: list[str] = []
        for cur in level:
            for pred in sorted(by_successor.get(cur, ())):
                if pred == lead:
                    raise SuccessionError(f"lead succession reaches {lead} again: the ledger is cyclic")
                if pred not in found:
                    found.append(pred)
                    nxt_level.append(pred)
        level = nxt_level
    return found


def predecessors(lead: str, state_dir: Path | None = None, home: Path | None = None) -> set[str]:
    return set(predecessors_by_distance(lead, state_dir, home))


def lineage(lead: str, state_dir: Path | None = None, home: Path | None = None) -> set[str]:
    """`lead` plus every archived predecessor it inherits from: the ids whose registries, labels and windows are `lead`'s."""
    return {lead} | predecessors(lead, state_dir, home)


def recent_lineage(lead: str, state_dir: Path | None = None, home: Path | None = None,
                   limit: int = RECENT_PREDECESSORS) -> list[str]:
    """`lead` and its `limit` nearest predecessors: the ids worth one `paseo ls --label` call each."""
    return [lead, *predecessors_by_distance(lead, state_dir, home)[:limit]]
