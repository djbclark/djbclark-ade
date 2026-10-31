"""goose adapter: ~/.local/share/goose/sessions/sessions.db (sessions + messages tables; added 2026-10-31)."""
import json
import sqlite3
import time
from pathlib import Path

AGENT = "goose"
RESUME = "goose session --resume --session-id {sid}"
DB = Path.home() / ".local" / "share" / "goose" / "sessions" / "sessions.db"


def _conn():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)


def _text(content_json):
    try:
        blocks = json.loads(content_json)
    except ValueError:
        return ""
    if isinstance(blocks, dict):
        blocks = [blocks]
    return "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()


def _epoch(v):
    try:
        return time.mktime(time.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S")) - time.timezone  # CURRENT_TIMESTAMP is UTC
    except ValueError:
        return 0.0


def sessions():
    if not DB.exists():
        return
    db = _conn()
    try:
        rows = db.execute(
            "SELECT s.id, s.name, s.working_dir, s.updated_at, (SELECT count(*) FROM messages m WHERE m.session_id = s.id) "
            "FROM sessions s").fetchall()
    except sqlite3.Error:
        return
    finally:
        db.close()
    for sid, name, cwd, updated, n in rows:
        def load(sid=sid, name=name, cwd=cwd):
            c = _conn()
            try:
                msgs = [(r, t) for r, t in ((r, _text(j)) for r, j in c.execute(
                    "SELECT role, content_json FROM messages WHERE session_id=? ORDER BY id", (sid,))) if len(t) > 3]
            finally:
                c.close()
            title = (name or "").strip() or " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
            return cwd or "", title, msgs

        yield {"key": f"goose:{sid}", "sid": sid, "fp": f"{n}:{updated}", "mtime": _epoch(updated), "load": load}
