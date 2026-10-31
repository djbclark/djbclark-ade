"""crush adapter: ~/.local/share/crush-acp/crush.db (sessions + messages tables; added 2026-10-31).

`messages.parts` is a JSON list of `{type, data}`; only `text` parts of user/assistant rows are
indexed (no reasoning, no tool calls). The database has no cwd column, so the cwd is empty.
"""
import json
import sqlite3
from pathlib import Path

AGENT = "crush"
RESUME = "crush --session {sid}  # needs CRUSH_GLOBAL_DATA=~/.local/share/crush-acp"
DB = Path.home() / ".local" / "share" / "crush-acp" / "crush.db"


def _conn():
    return sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True, timeout=5)


def _text(parts_json):
    try:
        parts = json.loads(parts_json)
    except ValueError:
        return ""
    return "\n".join((p.get("data") or {}).get("text", "") for p in parts
                     if isinstance(p, dict) and p.get("type") == "text").strip()


def sessions():
    if not DB.exists():
        return
    db = _conn()
    try:
        rows = db.execute("SELECT id, title, message_count, updated_at FROM sessions").fetchall()
    except sqlite3.Error:
        return
    finally:
        db.close()
    for sid, title, n, updated in rows:
        def load(sid=sid, title=title):
            c = _conn()
            try:
                msgs = [(r, t) for r, t in ((r, _text(p)) for r, p in c.execute(
                    "SELECT role, parts FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                    "ORDER BY created_at", (sid,))) if len(t) > 3]
            finally:
                c.close()
            title = (title or "").strip() or " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
            return "", title, msgs

        yield {"key": f"crush:{sid}", "sid": sid, "fp": f"{n}:{updated}", "mtime": float(updated or 0), "load": load}
