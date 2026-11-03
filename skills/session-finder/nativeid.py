"""The id a history adapter reports for a fleet row's session (shared by session-history.py and session-find.py)."""
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
