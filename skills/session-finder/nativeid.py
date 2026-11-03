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


def omp_native_id(sid) -> str:
    """The id the omp history adapter reports for SID, which is a plain id or (a fleet row's id) the absolute path of a transcript with
    or without `.jsonl`: the canonical `<timestamp>_<id>` name's id, else the id in the file's bounded header read
    (`jsonl_session.native_sid`, as adapters/omp.py does), else, for an unreadable file, the name-derived `native_id`."""
    sid = str(sid)
    path = Path(sid)
    if "/" in sid and path.is_absolute():
        from jsonl_session import native_sid  # lazy: callers put this directory on sys.path
        found = native_sid(path if path.suffix == ".jsonl" else path.with_name(path.name + ".jsonl"), header_lines=4)
        if found:
            return found
    return native_id(sid)


def history_identity(agent, sid, cwd="", key=""):
    """Pi custom IDs are project-local. Prefer file identity when it is available."""
    if agent == "omp":
        return (agent, omp_native_id(sid))
    if agent != "pi":
        return (agent, native_id(sid))
    path = key[3:] if key.startswith("pi:/") else str(sid) if "/" in str(sid) else ""
    if path and os.path.isabs(path):  # a relative path must never resolve against the caller's cwd
        return (agent, "file", str(Path(path).expanduser().resolve()))
    # Never consider an unscoped Pi ID exact-live.
    return (agent, "id", str(sid), str(Path(cwd).expanduser().resolve()) if cwd else "")
