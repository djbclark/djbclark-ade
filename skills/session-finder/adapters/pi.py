"""Pi's native JSONL session history (session-format.md, verified 2026-11-03).

Index user/assistant text only, not system prompts, tool results or thinking.
Session names are append-only session_info records; the last nonempty name wins.
"""
import json
import os
import re
import shlex
import stat
from pathlib import Path

AGENT = "pi"
ROOT_ENV = ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
RESUME_USES_KEY = True


def RESUME(key, cwd):
    # File targets bypass directory-sensitive ID lookup, including custom roots.
    # Pi restores the recorded cwd itself; a missing cwd gets Pi's normal prompt.
    return shlex.join(["pi", "--session", key[3:]]) if key.startswith("pi:/") else ""


ROOT = Path.home() / ".pi/agent/sessions"
# Pi names session files <ISO timestamp with ":" and "." as "-">_<id>, e.g. 2026-11-03T15-25-31-559Z_<id>.jsonl.
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d{3})?Z")
SID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def _open_regular(path):
    """Binary stream of a regular, non-symlink file; OSError otherwise. Never blocks on a FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _records(path):
    with _open_regular(path) as raw:
        for line in raw:
            try:
                entry = json.loads(line.decode("utf-8", errors="replace"))
            except (ValueError, RecursionError):
                continue
            if isinstance(entry, dict):
                yield entry


def _text(content):
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(block["text"] for block in content
                     if isinstance(block, dict) and block.get("type") == "text"
                     and isinstance(block.get("text"), str)).strip()


def _read(path):
    cwd, title, messages = "", "", []
    for entry in _records(path):
        if entry.get("type") == "session" and isinstance(entry.get("cwd"), str):
            cwd = entry["cwd"]
        elif entry.get("type") == "session_info" and isinstance(entry.get("name"), str):
            title = entry["name"].strip()  # an empty name clears the title (Pi getSessionName)
        elif entry.get("type") == "message":
            message = entry.get("message")
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant"):
                continue
            text = _text(message.get("content"))
            if text:
                messages.append((message["role"], text))
    if not title:
        title = " ".join(next((t for r, t in messages if r == "user"), "").split())[:80]
    return cwd, title, messages


HEADER_MAX = 64 * 1024


def _header_id(path):
    """The id in the first-line session header of a noncanonically named file; "" when absent, malformed or oversized."""
    try:
        with _open_regular(path) as fh:
            line = fh.readline(HEADER_MAX + 1)
        if len(line) > HEADER_MAX:
            return ""
        entry = json.loads(line.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return ""
    sid = entry.get("id") if isinstance(entry, dict) and entry.get("type") == "session" else None
    return sid if isinstance(sid, str) and SID.fullmatch(sid) else ""


def sessions():
    configured = os.environ.get("PI_CODING_AGENT_DIR")
    root = Path(configured).expanduser() / "sessions" if configured else ROOT
    if os.environ.get("PI_CODING_AGENT_SESSION_DIR"):
        root = Path(os.environ["PI_CODING_AGENT_SESSION_DIR"]).expanduser()
    for path in (*root.glob("*.jsonl"), *root.glob("*/*.jsonl")):
        if path.is_symlink() or path.parent != root and path.parent.is_symlink():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        # Pi filenames are <timestamp>_<id>. Keep listing stat-only so the
        # history index reads content only when the fingerprint changes.
        timestamp, separator, sid = path.stem.partition("_")
        if not separator or not STAMP.fullmatch(timestamp) or not SID.fullmatch(sid):
            # `pi --session /x/daily.jsonl` keeps its filename; the native id is in the header.
            sid = _header_id(path)
            if not sid:
                continue
        yield {"key": f"pi:{path.resolve()}", "sid": sid,
               "supersedes": [f"pi:{sid}"],  # retire the old, globally colliding key after a successful load
               "fp": f"{stat.st_size}:{stat.st_mtime_ns}", "mtime": stat.st_mtime,
               "load": lambda p=path: _read(p)}
