#!/usr/bin/env python3
"""Search retained session history without launching a client or pruning data.

Normal searches use SQLite read-only. Explicit --update-only refreshes restored
data adapters; absence of a client, adapter or log never deletes indexed history.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
READERS = ("omp", "opencode", "crush", "pi")
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(key TEXT PRIMARY KEY, agent TEXT, sid TEXT, fp TEXT, cwd TEXT, title TEXT, mtime REAL);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS msgs USING fts5(key UNINDEXED, role UNINDEXED, text, tokenize='porter unicode61');
"""


def database_path() -> Path:
    root = Path(os.environ.get("SESSION_INDEX_DIR") or Path.home() / ".local/state/session-index")
    return root.expanduser().resolve() / "history.v2.sqlite"


def connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    mode = "rw" if writable else "ro"
    return sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=30)


def status(db: sqlite3.Connection) -> dict:
    return {
        "sessions": dict(db.execute("SELECT agent,count(*) FROM files GROUP BY agent ORDER BY agent")),
        "messages": db.execute("SELECT count(*) FROM msgs").fetchone()[0],
        "refresh": dict(db.execute("SELECT k,v FROM meta WHERE k LIKE 'updated:%'")),
    }


def search(db: sqlite3.Connection, words: list[str], agents: list[str], limit: int,
           *, literal: bool = False) -> list[dict]:
    params: list = []
    where = []
    if agents:
        where.append("f.agent IN (" + ",".join("?" for _ in agents) + ")")
        params.extend(agents)
    if literal:
        where.append("instr(lower(m.text),lower(?)) > 0")
        params.append(" ".join(words))
        text = "substr(m.text,1,500)"
        order = "f.mtime DESC"
    else:
        where.append("msgs MATCH ?")
        params.append(" AND ".join('"' + w.replace('"', '""') + '"' for w in words))
        text = "snippet(msgs,2,'[',']',' … ',30)"
        order = "bm25(msgs),f.mtime DESC"
    sql = ("SELECT f.key,f.agent,f.sid,f.cwd,f.title,f.mtime," + text +
           " FROM msgs m JOIN files f ON f.key=m.key WHERE " + " AND ".join(where) +
           " ORDER BY " + order)
    # Stream until enough distinct sessions have matched. An arbitrary message
    # cutoff can hide every other session behind one long conversation.
    results, seen = [], set()
    for key, agent, sid, cwd, title, mtime, excerpt in db.execute(sql, params):
        if key in seen:
            continue
        seen.add(key)
        results.append(dict(key=key, agent=agent, sid=sid, cwd=cwd, title=title,
                            mtime=mtime, excerpt=excerpt))
        if len(results) == limit:
            break
    return results


def load_reader(name: str):
    # Isolated Python omits the script directory from sys.path. Load the owned
    # helper explicitly, then the selected fixed-name reader; never import a CLI.
    if name not in READERS:
        raise ValueError("No refresh reader for " + name)
    if "jsonl_session" not in sys.modules:
        spec = importlib.util.spec_from_file_location("jsonl_session", HERE / "jsonl_session.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["jsonl_session"] = module
        spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location("archive_reader_" + name,
                                                 HERE / "adapters" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh(db: sqlite3.Connection, readers) -> dict:
    """Upsert successfully parsed sources; never prune an absent agent/source."""
    stats = {}
    for reader in readers:
        seen = updated = skipped = 0
        if reader.AGENT == "crush":
            retained = []
            for key, cwd in db.execute("SELECT key,cwd FROM files WHERE agent='crush'"):
                if key.startswith("crush:/") and ".db#" in key:
                    retained.append((cwd, Path(key[len("crush:"):].rsplit("#", 1)[0])))
            entries = reader.sessions(retained_databases=retained)
        else:
            entries = reader.sessions()
        for entry in entries:
            seen += 1
            old = db.execute("SELECT fp FROM files WHERE key=?", (entry["key"],)).fetchone()
            if old and old[0] == entry["fp"]:
                continue
            try:
                cwd, title, messages = entry["load"]()
                messages = [(role, text[:4000 if role == "user" else 2000])
                            for role, text in messages
                            if role in ("user", "assistant") and isinstance(text, str) and len(text) > 3]
            except (OSError, ValueError, TypeError, sqlite3.Error):
                skipped += 1
                continue
            if not messages:
                skipped += 1
                continue
            with db:
                db.execute("DELETE FROM msgs WHERE key=?", (entry["key"],))
                db.executemany("INSERT INTO msgs(key,role,text) VALUES(?,?,?)",
                               [(entry["key"], role, text) for role, text in messages])
                db.execute("INSERT OR REPLACE INTO files(key,agent,sid,fp,cwd,title,mtime) VALUES(?,?,?,?,?,?,?)",
                           (entry["key"], reader.AGENT, entry["sid"], entry["fp"],
                            cwd or "", title or "", entry["mtime"]))
            updated += 1
        with db:
            db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)",
                       ("updated:" + reader.AGENT, time.time()))
        stats[reader.AGENT] = dict(seen=seen, updated=updated, skipped=skipped)
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("words", nargs="*")
    parser.add_argument("--agent", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--literal", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--update-only", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be between 1 and 200")
    if not args.words and not (args.status or args.check or args.update_only):
        parser.error("supply query words or --status/--check/--update-only")
    path = database_path()
    try:
        if args.update_only:
            # Resolve all readers BEFORE any DB mutation; a missing reader is an
            # error, never a reason to delete the histories belonging to it.
            readers = [load_reader(n) for n in (args.agent or READERS)]
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with sqlite3.connect(path) as db:
                    db.executescript(SCHEMA)
                path.chmod(0o600)
            with connect(path, writable=True) as db:
                result = refresh(db, readers)
        else:
            with connect(path) as db:
                if args.status:
                    result = status(db)
                elif args.check:
                    check = db.execute("PRAGMA quick_check").fetchone()[0]
                    db.execute("SELECT rowid FROM msgs WHERE msgs MATCH ? LIMIT 1", ("agent",)).fetchone()
                    result = {"integrity": check, "fts": "ok"}
                    if check != "ok":
                        print(json.dumps(result))
                        return 2
                else:
                    result = search(db, args.words, args.agent, args.limit, literal=args.literal)
                    if not result:
                        print("[]" if args.json else "No indexed session matched.")
                        return 1
        if args.json or not isinstance(result, list):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for row in result:
                print(f"{row['agent']} {row['sid']} — {row['title']}\n{row['excerpt']}\n")
        return 0
    except (OSError, ValueError, sqlite3.Error, ImportError) as error:
        print("session-history: " + type(error).__name__ +
              "; retained index unchanged except completed explicit refreshes", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
