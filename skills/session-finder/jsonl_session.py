"""Reading Pi/omp JSONL session files safely (shared by adapters/pi.py and adapters/omp.py; 2026-11-03).

Both name a session file `<ISO timestamp with ":" and "." as "-">_<id>.jsonl` (2026-11-03T15-25-31-559Z_<id>.jsonl) and start it
with a `session` header record that carries the native id. A file passed with `--session /x/daily.jsonl` keeps its own name.
"""
import json
import os
import re
import stat

STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d{3})?Z")
SID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
HEADER_MAX = 64 * 1024


def open_regular(path):
    """Binary stream of a regular, non-symlink file; OSError otherwise. Never blocks on a FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def records(path):
    """The JSON objects of a session file, one per line; lines that are not objects (`7`, `[1,2]`, garbage) are skipped."""
    with open_regular(path) as raw:
        for line in raw:
            try:
                entry = json.loads(line.decode("utf-8", errors="replace"))
            except (ValueError, RecursionError):
                continue
            if isinstance(entry, dict):
                yield entry


def header_id(path, lines=1):
    """The id of the `session` header within the first LINES lines of a noncanonically named file; "" when absent, malformed or
    oversized (each line is read up to HEADER_MAX bytes)."""
    try:
        with open_regular(path) as fh:
            for _ in range(lines):
                line = fh.readline(HEADER_MAX + 1)
                if not line or len(line) > HEADER_MAX:
                    return ""
                try:
                    entry = json.loads(line.decode("utf-8"))
                except (ValueError, RecursionError):
                    return ""
                if isinstance(entry, dict) and entry.get("type") == "session":
                    sid = entry.get("id")
                    return sid if isinstance(sid, str) and SID.fullmatch(sid) else ""
    except OSError:
        return ""
    return ""


def native_sid(path, header_lines=1):
    """The native session id of PATH (a pathlib.Path): from a canonical `<timestamp>_<id>` name without opening the file (listing
    stays stat-only), else from the header; "" when neither yields one."""
    timestamp, separator, sid = path.stem.partition("_")
    if separator and STAMP.fullmatch(timestamp) and SID.fullmatch(sid):
        return sid
    return header_id(path, header_lines)
