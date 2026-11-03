"""Pi's native JSONL session history (session-format.md, verified 2026-11-03).

Index user/assistant text only, not system prompts, tool results or thinking.
Session names are append-only session_info records; the last nonempty name wins.
"""
import json
import os
import re
import shlex
from pathlib import Path

AGENT = "pi"
ROOT_ENV = ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
RESUME_USES_KEY = True


def RESUME(key, cwd):
    # File targets bypass directory-sensitive ID lookup, including custom roots.
    # Pi restores the recorded cwd itself; a missing cwd gets Pi's normal prompt.
    return shlex.join(["pi", "--session", key[3:]]) if key.startswith("pi:/") else ""


ROOT = Path.home() / ".pi/agent/sessions"
SID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")


def _records(path):
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except ValueError:
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
            title = entry["name"].strip() or title
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
        if path.is_symlink() or path.parent.is_symlink():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        # Pi filenames are <timestamp>_<id>. Keep listing stat-only so the
        # history index reads content only when the fingerprint changes.
        timestamp, separator, sid = path.stem.partition("_")
        if not timestamp or not separator or not SID.fullmatch(sid):
            continue
        yield {"key": f"pi:{path.resolve()}", "sid": sid,
               "supersedes": [f"pi:{sid}"],  # retire the old, globally colliding key after a successful load
               "fp": f"{stat.st_size}:{stat.st_mtime_ns}", "mtime": stat.st_mtime,
               "load": lambda p=path: _read(p)}
