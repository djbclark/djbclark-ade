"""crush adapter: every Crush data dir's crush.db (sessions + messages tables; added 2026-10-31).

Databases: the shared `~/.local/share/crush-acp/crush.db`, plus the `<data_dir>/crush.db` of every project in
`~/.local/share/crush-acp/projects.json` and `~/.local/share/crush/projects.json` (the same two registries
`bin/skillopt_sources.py::crush_dbs` reads; most sessions live in per-project `.crush` dirs). A project
database's sessions carry the project path as their cwd, and `resume()` names the database's data dir.

`messages.parts` is a JSON list of `{type, data}`; only `text` parts of user/assistant rows are
indexed (no reasoning, no tool calls). The shared database has no project, so its cwd is empty.
"""
import json
import shlex
import sqlite3
from pathlib import Path

AGENT = "crush"
DATA = Path.home() / ".local" / "share" / "crush-acp"
DB = DATA / "crush.db"
PROJECTS = (DATA / "projects.json", Path.home() / ".local" / "share" / "crush" / "projects.json")


def _conn(db):
    return sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True, timeout=5)


def _projects():
    """(project path, data dir) of every registered project, registry order, first entry per path."""
    out, seen = [], set()
    for pf in PROJECTS:
        try:
            rows = json.loads(pf.read_text()).get("projects") or []
        except (OSError, ValueError, AttributeError):
            continue
        for row in rows if isinstance(rows, list) else []:
            path, data_dir = str(row.get("path") or ""), str(row.get("data_dir") or "")
            if path and data_dir and path not in seen:
                seen.add(path)
                out.append((path, data_dir))
    return out


def _databases():
    """(cwd, db path): the shared database first (cwd empty), then each project's distinct database."""
    out, seen = [("", DB)], {DB.resolve()}
    for path, data_dir in _projects():
        db = Path(data_dir) / "crush.db"
        try:
            real = db.resolve()
        except OSError:
            continue
        if real not in seen and db.is_file():
            seen.add(real)
            out.append((path, db))
    return out


def resume(sid, cwd):
    """The resume command: a project's session is resumed from its project directory with its own data dir."""
    q = shlex.quote
    if cwd:
        for path, data_dir in _projects():
            if path == cwd:
                return f"cd {q(cwd)} && crush -D {q(data_dir)} --session {q(sid)}"
    return f"crush -D ~/.local/share/crush-acp --session {q(sid)}"


RESUME = resume


def _text(parts_json):
    try:
        parts = json.loads(parts_json)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parts, list):
        return ""
    return "\n".join(str((p.get("data") or {}).get("text", "")) for p in parts
                     if isinstance(p, dict) and p.get("type") == "text").strip()


def sessions():
    for cwd, path in _databases():
        if not path.exists():
            continue
        try:
            db = _conn(path)
            try:
                rows = db.execute("SELECT id, title, message_count, updated_at FROM sessions").fetchall()
            finally:
                db.close()
        except sqlite3.Error:
            continue
        for sid, title, n, updated in rows:
            def load(path=path, cwd=cwd, sid=sid, title=title):
                c = _conn(path)
                try:
                    msgs = [(r, t) for r, t in ((r, _text(p)) for r, p in c.execute(
                        "SELECT role, parts FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                        "ORDER BY created_at", (sid,))) if len(t) > 3]
                finally:
                    c.close()
                title = (title or "").strip() or " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
                return cwd, title, msgs

            # the shared database keeps the plain key; a project's sessions are keyed by their database
            key = f"crush:{sid}" if path == DB else f"crush:{path}#{sid}"
            yield {"key": key, "sid": sid, "fp": f"{n}:{updated}", "mtime": float(updated or 0), "load": load}
