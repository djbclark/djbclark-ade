"""bin/ade-backup-stores: WAL-consistent copies, sidecars, exclusions, manifest, refusals (2026-10-20)."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin/ade-backup-stores"


def load():
    loader = importlib.machinery.SourceFileLoader("ade_backup_stores_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_backup_stores_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def make_wal_db(path, rows):
    """A WAL db whose newest rows live only in the -wal file while the writer stays open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE t (v TEXT)")
    for r in rows:
        con.execute("INSERT INTO t VALUES (?)", (r,))
    return con


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    mod = load()
    monkeypatch.setattr(mod, "build_stores", lambda h: make_stores(mod, h))
    (tmp_path / "dest").mkdir()
    return mod, home, tmp_path / "dest" / "bk", tmp_path


def make_stores(mod, home):
    return [
        {"name": "walstore", "kind": "sqlite", "files": [home / ".fake/state.db"]},
        {"name": "tree", "kind": "sqlite-tree", "root": home / ".fake/chats", "dbs": ["*/*/store.db"],
         "sidecars": ["meta.json"]},
        {"name": "filestore", "kind": "files", "roots": [("sessions", home / ".fake/sessions")]},
    ]


def populate(home):
    wal = make_wal_db(home / ".fake/state.db", ["one", "two"])
    wal.execute("INSERT INTO t VALUES ('wal-only-row')")
    assert (home / ".fake/state.db-wal").stat().st_size > 0
    sdir = home / ".fake/chats/hashA/uuid1"
    sdir.mkdir(parents=True)
    tree_db = make_wal_db(sdir / "store.db", ["tree-row"])
    (sdir / "meta.json").write_text('{"name": "session one"}')
    fs = home / ".fake/sessions"
    (fs / "p1").mkdir(parents=True)
    (fs / "p1/chat.jsonl").write_text('{"x": 1}\n')
    (fs / "p1/room.key").write_text("not-a-real-key")
    (fs / "mcp.json").write_text("{}")
    (fs / "mcp.json.bak-2026-10-12").write_text("{}")
    (fs / "credential-bak").mkdir()
    (fs / "credential-bak/MANIFEST.txt").write_text("x")
    (fs / "auth.json").write_text("{}")
    os.symlink(fs / "p1/chat.jsonl", fs / "p1/link.jsonl")
    return wal, tree_db


def run_main(mod, *args):
    """main() on the fake stores; hermes-export (a real `hermes` on PATH) only when a test asks for it."""
    argv = list(args)
    if "--only" not in argv:
        argv += ["--only", "walstore,tree,filestore"]
    return mod.main(argv)


def test_backup_has_wal_rows_sidecars_exclusions_and_manifest(env):
    mod, home, dest, _ = env
    wal, tree_db = populate(home)
    rc = run_main(mod, "--dest", str(dest), "--only", "walstore,tree,filestore")
    assert rc == 0
    con = sqlite3.connect(str(dest / "walstore/state.db"))
    assert [r[0] for r in con.execute("SELECT v FROM t ORDER BY rowid")] == ["one", "two", "wal-only-row"]
    con.close()
    assert not list(dest.rglob("*-wal")) and not list(dest.rglob("*.part*"))
    assert sqlite3.connect(str(dest / "tree/hashA/uuid1/store.db")).execute("SELECT v FROM t").fetchone() == ("tree-row",)
    assert json.loads((dest / "tree/hashA/uuid1/meta.json").read_text()) == {"name": "session one"}
    names = {p.name for p in dest.rglob("*")}
    assert "chat.jsonl" in names
    for banned in ("room.key", "mcp.json", "mcp.json.bak-2026-10-12", "credential-bak", "MANIFEST.txt", "auth.json",
                   "link.jsonl"):
        assert banned not in names
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert manifest["errors"] == []
    assert "*.key" in manifest["exclusions"]["names"]
    seen = 0
    for store in manifest["stores"]:
        assert store["started"] and store["ended"] and store["sources"]
        for f in store["files"]:
            p = dest / f["path"]
            assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"]
            assert p.stat().st_size == f["bytes"]
            seen += 1
    assert seen == sum(s["file_count"] for s in manifest["stores"]) >= 4
    fs_store = next(s for s in manifest["stores"] if s["store"] == "filestore")
    whys = {x["why"] for x in fs_store["skipped"]}
    assert "symlink" in whys and "excluded credential path" in whys
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    assert stat.S_IMODE((dest / "walstore/state.db").stat().st_mode) == 0o600
    assert stat.S_IMODE((dest / "filestore/sessions/p1").stat().st_mode) == 0o700
    wal.close()
    tree_db.close()


def test_sources_are_untouched(env):
    mod, home, dest, _ = env
    wal, tree_db = populate(home)
    before = {p: (p.stat().st_size, p.read_bytes()) for p in (home / ".fake").rglob("*") if p.is_file()
              and not p.name.endswith("-shm")}
    assert run_main(mod, "--dest", str(dest)) == 0
    after = {p: (p.stat().st_size, p.read_bytes()) for p in (home / ".fake").rglob("*") if p.is_file()
             and not p.name.endswith("-shm")}
    assert before == after
    wal.close()
    tree_db.close()


def test_dest_inside_a_source_store_is_refused(env, capsys):
    mod, home, _, _ = env
    populate(home)
    bad = home / ".fake/sessions/inside"
    assert run_main(mod, "--dest", str(bad)) == 2
    assert "source store" in capsys.readouterr().err
    assert not bad.exists()
    assert run_main(mod, "--dest", str(home / ".fake")) == 2


def test_dest_inside_a_git_repo_is_refused(env, capsys):
    mod, home, _, tmp = env
    repo = tmp / "repo"
    (repo / ".git").mkdir(parents=True)
    assert run_main(mod, "--dest", str(repo / "backups/x")) == 2
    assert "git repository" in capsys.readouterr().err
    assert not (repo / "backups").exists()


def test_dry_run_writes_nothing(env, capsys):
    mod, home, dest, _ = env
    wal, tree_db = populate(home)
    assert run_main(mod, "--dest", str(dest), "--dry-run") == 0
    out = capsys.readouterr().out
    assert "walstore: 1 files" in out and "(dry run)" in out
    assert not dest.exists()
    wal.close()
    tree_db.close()


def test_unreadable_db_lands_in_errors_and_exit_1(env):
    mod, home, dest, _ = env
    wal, tree_db = populate(home)
    bad = home / ".fake/chats/hashB/uuid2"
    bad.mkdir(parents=True)
    (bad / "store.db").write_bytes(b"this is not a sqlite database" * 100)
    (bad / "meta.json").write_text("{}")
    rc = run_main(mod, "--dest", str(dest))
    assert rc == 1
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert any(e["store"] == "tree" and e["source"].endswith("hashB/uuid2/store.db") for e in manifest["errors"])
    # the run went on: the good session and the file store were still copied
    assert (dest / "tree/hashA/uuid1/store.db").is_file()
    assert (dest / "filestore/sessions/p1/chat.jsonl").is_file()
    assert not (dest / "tree/hashB/uuid2/store.db").exists()
    wal.close()
    tree_db.close()


def test_missing_store_is_an_error_not_a_crash(env):
    mod, home, dest, _ = env
    assert run_main(mod, "--dest", str(dest)) == 1
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert {e["store"] for e in manifest["errors"]} == {"walstore", "tree", "filestore"}


def test_unknown_only_name_is_usage_error(env):
    mod, _, dest, _ = env
    assert run_main(mod, "--dest", str(dest), "--only", "nope") == 2


def test_exclude_names_cover_the_inventory_key_files():
    mod = load()
    for name in ("mcp.json", "mcp.json.bak-2026-10-12", "opencode.json.bak", "mcp_config.json.bak-2026-10-18",
                 "acp_token.json", "x.key", "auth.json", "credential-bak", "opencode.bak", ".env", "agent.db"):
        assert mod.is_excluded_name(name), name
    for name in ("chat.jsonl", "store.db", "meta.json", "opencode.jsonc", "state.db"):
        assert not mod.is_excluded_name(name), name


def write_fake_hermes(path, oversize_id):
    path.write_text(f"""#!/bin/sh
# argv: sessions export OUT [--session-id ID]
out="$3"
if [ "$4" = "--session-id" ]; then
  if [ "$5" = "{oversize_id}" ]; then echo "Error: Session '$5' has more than 20,000 exportable messages"; exit 0; fi
  echo '{{"id": "'"$5"'"}}' > "$out"; echo "Exported 1 session to $out"; exit 0
fi
echo "Error: Session '{oversize_id}' has more than 20,000 exportable messages; capped"; exit 0
""")
    path.chmod(0o755)


def test_hermes_export_falls_back_per_session_and_reports_truncation(env, monkeypatch):
    mod, home, dest, tmp = env
    db = home / ".hermes/state.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE sessions (id TEXT)")
    con.execute("CREATE TABLE messages (session_id TEXT, body TEXT)")
    for sid, n in (("small", 2), ("big", 5)):
        con.execute("INSERT INTO sessions VALUES (?)", (sid,))
        con.executemany("INSERT INTO messages VALUES (?, 'm')", [(sid,)] * n)
    con.commit()
    con.close()
    (home / ".hermes/config.yaml").write_text("sessions:\n  max_export_messages: 3\n")
    fake = tmp / "hermes"
    write_fake_hermes(fake, "big")
    monkeypatch.setenv("ADE_BACKUP_HERMES", str(fake))
    assert run_main(mod, "--dest", str(dest), "--only", "walstore,hermes-export") == 1  # walstore db missing
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    entry = next(s for s in manifest["stores"] if s["store"] == "hermes-export")
    info = entry["hermes_export"]
    assert info["mode"] == "per-session" and info["truncated"] is True
    assert info["oversize"] == [{"id": "big", "messages": 5}]
    assert info["sessions_exported"] == 1 and info["sessions_total"] == 2
    assert (dest / "hermes-export/sessions/small.jsonl").is_file()
    assert not (dest / "hermes-export/sessions/big.jsonl").exists()
    assert entry["errors"] == []


def test_cli_dry_run_runs_as_a_program(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    proc = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--only", "handoffs", "--json",
                           "--dest", str(tmp_path / "d" / "x")],
                          capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    assert proc.returncode == 1  # the handoffs store is missing in the empty home
    data = json.loads(proc.stdout)
    assert data["dry_run"] is True and data["errors"][0]["store"] == "handoffs"
    assert not (tmp_path / "d").exists()
