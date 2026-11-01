"""The id a history adapter reports for a fleet row's session (shared by session-history.py and session-find.py)."""
from pathlib import Path


def native_id(sid) -> str:
    """A plain id (hermes, which may contain underscores) as is, an omp transcript path as the id after the `_`
    in its file stem."""
    sid = str(sid)
    return Path(sid).stem.split("_")[-1] if "/" in sid else sid
