"""Pi's native JSONL session history (session-format.md, verified 2026-11-03).

Index user/assistant text only, not system prompts, tool results or thinking.
Session names are append-only session_info records; the last nonempty name wins.
"""
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the shared reader lives beside session-history.py
from jsonl_session import native_sid, records  # noqa: E402

AGENT = "pi"
ROOT_ENV = ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
RESUME_USES_KEY = True


def RESUME(key, cwd):
    # File targets bypass directory-sensitive ID lookup, including custom roots.
    # Pi restores the recorded cwd itself; a missing cwd gets Pi's normal prompt.
    return shlex.join(["pi", "--session", key[3:]]) if key.startswith("pi:/") else ""


ROOT = Path.home() / ".pi/agent/sessions"


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
    for entry in records(path):
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
        # Pi filenames are <timestamp>_<id>. Keep listing stat-only so the history index reads content only when the
        # fingerprint changes; `pi --session /x/daily.jsonl` keeps its filename and costs one bounded header read.
        sid = native_sid(path)
        if not sid:
            continue
        yield {"key": f"pi:{path.resolve()}", "sid": sid,
               "supersedes": [f"pi:{sid}"],  # retire the old, globally colliding key after a successful load
               "fp": f"{stat.st_size}:{stat.st_mtime_ns}", "mtime": stat.st_mtime,
               "load": lambda p=path: _read(p)}
