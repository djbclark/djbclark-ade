"""The id a history adapter reports for a fleet row's session (shared by session-history.py and session-find.py)."""
import os
from pathlib import Path


def native_id(sid) -> str:
    """Keep plain ids intact; Pi/OMP transcript names are ``<timestamp>_<id>.jsonl``.

    Split at the first underscore: custom native ids may themselves contain underscores.
    """
    sid = str(sid)
    if "/" not in sid:
        return sid
    stem = Path(sid).stem
    prefix, separator, native = stem.partition("_")
    return native if separator else prefix


def history_identity(agent, sid, cwd="", key=""):
    """Pi custom IDs are project-local. Prefer file identity when it is available."""
    if agent != "pi":
        return (agent, native_id(sid))
    path = key[3:] if key.startswith("pi:/") else str(sid) if "/" in str(sid) else ""
    if path and os.path.isabs(path):  # a relative path must never resolve against the caller's cwd
        return (agent, "file", str(Path(path).expanduser().resolve()))
    # Never consider an unscoped Pi ID exact-live.
    return (agent, "id", str(sid), str(Path(cwd).expanduser().resolve()) if cwd else "")
