"""The id a history adapter reports for a fleet row's session (shared by session-history.py and session-find.py)."""
import os
from pathlib import Path


def native_id(sid) -> str:
    """Keep plain IDs intact; strip only the timestamp from Pi/OMP transcript paths."""
    sid = str(sid)
    if "/" not in sid:
        return sid
    stem = Path(sid).stem
    return stem.partition("_")[2] if "_" in stem else stem


def history_identity(agent, sid, cwd="", key=""):
    """Pi custom IDs are project-local. Prefer file identity when it is available."""
    if agent != "pi":
        return (agent, native_id(sid))
    path = key[3:] if key.startswith("pi:/") else str(sid) if "/" in str(sid) else ""
    if path and os.path.isabs(path):  # a relative path must never resolve against the caller's cwd
        return (agent, "file", str(Path(path).expanduser().resolve()))
    # Never consider an unscoped Pi ID exact-live.
    return (agent, "id", str(sid), str(Path(cwd).expanduser().resolve()) if cwd else "")
