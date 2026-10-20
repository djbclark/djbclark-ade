"""bin/ade-backup-stores: WAL-consistent copies, sidecars, exclusions, manifest, refusals (2026-10-20)."""
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
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
    (fs / "p1/mcp-auth.json").write_text('{"clientInfo": {"client_secret": "SENTINEL-MCP-CLIENT-SECRET"}}')
    (fs / "p1/mcp_auth.json").write_text('{"tools": []}')
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
                   "link.jsonl", "mcp-auth.json"):
        assert banned not in names
    assert "mcp_auth.json" in names  # a tool descriptor, not a credential
    assert b"SENTINEL-MCP-CLIENT-SECRET" not in b"".join(p.read_bytes() for p in dest.rglob("*") if p.is_file())
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


def test_read_only_open_of_a_quiet_db_adds_only_empty_wal_and_shm(env):
    mod, home, dest, _ = env
    con = make_wal_db(home / ".fake/state.db", ["quiet"])
    con.close()  # the last connection closing removes -wal and -shm
    src_dir = home / ".fake"
    before = {p.name for p in src_dir.iterdir()}
    assert before == {"state.db"}
    db_bytes = (src_dir / "state.db").read_bytes()
    assert run_main(mod, "--dest", str(dest), "--only", "walstore") == 0
    new = {p.name: p.stat().st_size for p in src_dir.iterdir() if p.name not in before}
    assert set(new) <= {"state.db-wal", "state.db-shm"}
    assert new.get("state.db-wal", 0) == 0  # the -shm index may be one page; the -wal stays empty
    assert (src_dir / "state.db").read_bytes() == db_bytes


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


def test_missing_store_is_recorded_as_missing_not_an_error(env):
    mod, home, dest, _ = env
    assert run_main(mod, "--dest", str(dest)) == 0
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert manifest["errors"] == []
    assert {e["store"]: e["status"] for e in manifest["stores"]} == {
        "walstore": "missing", "tree": "missing", "filestore": "missing"}


def test_unknown_only_name_is_usage_error(env):
    mod, _, dest, _ = env
    assert run_main(mod, "--dest", str(dest), "--only", "nope") == 2


def test_exclude_names_cover_the_inventory_key_files():
    mod = load()
    for name in ("mcp.json", "mcp.json.bak-2026-10-12", "opencode.json.bak", "mcp_config.json.bak-2026-10-18",
                 "acp_token.json", "x.key", "auth.json", "credential-bak", "opencode.bak", ".env", "agent.db",
                 "mcp-auth.json", "mcp-auth.json.bak-2026-10-20"):
        assert mod.is_excluded_name(name), name
    for name in ("chat.jsonl", "store.db", "meta.json", "opencode.jsonc", "state.db", "mcp_auth.json"):
        assert not mod.is_excluded_name(name), name


def write_fake_hermes(path, oversize_id):
    path.write_text(f"""#!/bin/sh
# argv: sessions export OUT [--session-id=ID]; FAKE_HERMES_LOG gets HERMES_HOME and whether it holds state.db
out="$3"
if [ -n "$FAKE_HERMES_LOG" ]; then
  if [ -f "$HERMES_HOME/state.db" ]; then echo "$HERMES_HOME has-state" >> "$FAKE_HERMES_LOG"; else echo "$HERMES_HOME no-state" >> "$FAKE_HERMES_LOG"; fi
fi
case "$4" in
  --session-id=*)
    sid="${{4#--session-id=}}"
    if [ "$sid" = "{oversize_id}" ]; then echo "Error: Session '$sid' has more than 20,000 exportable messages"; exit 0; fi
    echo '{{"id": "'"$sid"'"}}' > "$out"; printf 'Exported 1 session to %s \\377\\n' "$out"; exit 0;;
esac
echo "Error: Session '{oversize_id}' has more than 20,000 exportable messages; capped"; exit 0
""")
    path.chmod(0o755)


def make_hermes_db(home, sessions):
    db = home / ".hermes/state.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE sessions (id TEXT)")
    con.execute("CREATE TABLE messages (session_id TEXT, body TEXT)")
    for sid, n in sessions:
        con.execute("INSERT INTO sessions VALUES (?)", (sid,))
        con.executemany("INSERT INTO messages VALUES (?, 'm')", [(sid,)] * n)
    con.commit()
    con.close()
    return db


def test_hermes_export_falls_back_per_session_and_reports_truncation(env, monkeypatch):
    mod, home, dest, tmp = env
    make_hermes_db(home, (("small", 2), ("big", 5), ("-dash", 1), ("Dot.id-1", 1)))
    (home / ".hermes/config.yaml").write_text("sessions:\n  max_export_messages: 3\n")
    fake = tmp / "hermes"
    write_fake_hermes(fake, "big")
    log = tmp / "hermes.log"
    monkeypatch.setenv("ADE_BACKUP_HERMES", str(fake))
    monkeypatch.setenv("FAKE_HERMES_LOG", str(log))
    assert run_main(mod, "--dest", str(dest), "--only", "walstore,hermes-export") == 1  # walstore db missing
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    entry = next(s for s in manifest["stores"] if s["store"] == "hermes-export")
    info = entry["hermes_export"]
    assert info["mode"] == "per-session" and info["truncated"] is True
    assert info["oversize"] == [{"id": "big", "messages": 5}]
    assert info["sessions_exported"] == 2 and info["sessions_total"] == 4
    assert info["failed"] == [{"id": "-dash", "error": "unsafe session id"}]
    assert (dest / "hermes-export/sessions/small.jsonl").is_file()
    assert (dest / "hermes-export/sessions/Dot.id-1.jsonl").is_file()
    assert not (dest / "hermes-export/sessions/big.jsonl").exists()
    assert [e["error"] for e in entry["errors"]] == ["RuntimeError: unsafe session id"]
    # every hermes call ran against a scratch HERMES_HOME holding the state.db copy, never ~/.hermes
    lines = log.read_text().splitlines()
    assert lines and all(l.endswith(" has-state") for l in lines)
    homes = {l.split()[0] for l in lines}
    assert len(homes) == 1 and not homes & {str(home / ".hermes")}
    assert not Path(homes.pop()).exists()
    assert not list(dest.rglob(".hermes-scratch"))
    assert entry["destination"] == str(dest / "hermes-export")


def test_hermes_export_bulk_and_unparsable_output(env, monkeypatch):
    mod = env[0]
    assert mod.exported_count("Exported 12 sessions to x") == 12
    assert mod.exported_count("Exported sessions") is None and mod.exported_count("") is None


def test_cli_dry_run_runs_as_a_program(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    proc = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--only", "handoffs", "--json",
                           "--dest", str(tmp_path / "d" / "x")],
                          capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    assert proc.returncode == 0  # the handoffs store is missing in the empty home: recorded, not an error
    data = json.loads(proc.stdout)
    assert data["dry_run"] is True and data["errors"] == []
    assert data["stores"][0]["store"] == "handoffs" and data["stores"][0]["status"] == "missing"
    assert "store handoffs: missing" in proc.stderr
    assert not (tmp_path / "d").exists()


# --- credential scrubbing and the schema guard (adversary findings 1, 2) ---

SENTINEL_KEY = b"SENTINEL-OPENCODE-API-KEY-7f3a"
SENTINEL_FREED = b"SENTINEL-FREED-PAGE-9c1d"
SENTINEL_SECRET = b"SENTINEL-SHARE-SECRET-42b0"


def make_opencode_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE session (id TEXT, title TEXT, tokens_input INTEGER, input_tokens INTEGER)")
    con.execute("INSERT INTO session VALUES ('s1', 'keep me', 5, 7)")
    con.execute("CREATE TABLE credential (id TEXT, integration_id TEXT, value TEXT)")
    con.execute("INSERT INTO credential VALUES ('c1', 'opencode', ?)", (SENTINEL_KEY.decode(),))
    con.execute("INSERT INTO credential VALUES ('c2', 'big', ?)", (SENTINEL_FREED.decode() * 400,))
    con.execute("DELETE FROM credential WHERE id = 'c2'")  # leaves the bytes on a freed page
    for table in ("account", "control_account"):
        con.execute(f"CREATE TABLE {table} (id TEXT, access_token TEXT, refresh_token TEXT)")
        con.execute(f"INSERT INTO {table} VALUES ('a1', 'x', 'y')")
    con.execute("CREATE TABLE account_state (active_account_id TEXT)")
    con.execute("INSERT INTO account_state VALUES ('a1')")
    con.execute("CREATE TABLE session_share (id TEXT, url TEXT, secret TEXT)")
    con.execute("INSERT INTO session_share VALUES ('sh1', 'https://example.invalid/s', ?)", (SENTINEL_SECRET.decode(),))
    return con


def opencode_stores(mod, home):
    return [{"name": "opencode", "kind": "sqlite", "files": [home / ".local/share/opencode/opencode.db"]}]


def all_bytes(root):
    return b"".join(p.read_bytes() for p in Path(root).rglob("*") if p.is_file())


def test_opencode_credential_tables_are_scrubbed_from_the_copy(env, monkeypatch):
    mod, home, dest, _ = env
    monkeypatch.setattr(mod, "build_stores", lambda h: opencode_stores(mod, h))
    live = make_opencode_db(home / ".local/share/opencode/opencode.db")
    assert SENTINEL_KEY in all_bytes(home / ".local/share/opencode")  # the fixture really holds the sentinel
    assert mod.main(["--dest", str(dest), "--only", "opencode"]) == 0
    copy = dest / "opencode/opencode.db"
    con = sqlite3.connect(str(copy))
    assert con.execute("SELECT title, tokens_input, input_tokens FROM session").fetchall() == [("keep me", 5, 7)]
    for table in ("credential", "account", "control_account", "account_state"):
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,), table
    assert con.execute("SELECT id, url, secret FROM session_share").fetchall() == [("sh1", "https://example.invalid/s", None)]
    con.close()
    blob = all_bytes(dest)
    for sentinel in (SENTINEL_KEY, SENTINEL_FREED, SENTINEL_SECRET):
        assert sentinel not in blob
    if shutil.which("rg"):  # the same check the adversary asked for
        for sentinel in (SENTINEL_KEY, SENTINEL_FREED, SENTINEL_SECRET):
            proc = subprocess.run(["rg", "-a", "-l", "-F", sentinel.decode(), str(dest)], capture_output=True, text=True)
            assert proc.returncode == 1, proc.stdout
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    store = manifest["stores"][0]
    assert store["scrubbed"] == ["account", "account_state", "control_account", "credential", "session_share.secret"]
    assert store["files"][0]["scrubbed"] == ["credential", "account", "control_account", "account_state",
                                              "session_share.secret"]
    assert manifest["errors"] == []
    live.close()


def test_scrub_skips_tables_a_newer_or_older_opencode_lacks(env, monkeypatch):
    mod, home, dest, _ = env
    monkeypatch.setattr(mod, "build_stores", lambda h: opencode_stores(mod, h))
    (home / ".local/share/opencode").mkdir(parents=True)
    con = sqlite3.connect(str(home / ".local/share/opencode/opencode.db"))
    con.execute("CREATE TABLE credential (id TEXT, value TEXT)")
    con.execute("INSERT INTO credential VALUES ('c', 'SENTINEL-ONLY-CREDENTIAL')")
    con.commit()
    con.close()
    assert mod.main(["--dest", str(dest), "--only", "opencode"]) == 0
    assert b"SENTINEL-ONLY-CREDENTIAL" not in all_bytes(dest)
    assert json.loads((dest / "MANIFEST.json").read_text())["stores"][0]["scrubbed"] == ["credential"]


def test_schema_guard_fails_a_new_credential_table_and_drops_the_copy(env):
    mod, home, dest, _ = env
    con = make_wal_db(home / ".fake/state.db", ["row"])
    con.execute("CREATE TABLE provider_oauth (id TEXT, refresh_token TEXT)")
    con.execute("CREATE TABLE ok (author TEXT, total_tokens INTEGER, cache_read_tokens INTEGER, tokens INTEGER)")
    assert run_main(mod, "--dest", str(dest), "--only", "walstore") == 1
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    [err] = manifest["errors"]
    assert err["store"] == "walstore" and "SchemaGuardError" in err["error"]
    assert "provider_oauth" in err["error"] and "provider_oauth.refresh_token" in err["error"]
    assert "author" not in err["error"] and "total_tokens" not in err["error"] and "tokens" not in err["error"].split(": ", 2)[-1]
    assert not (dest / "walstore/state.db").exists() and not list(dest.rglob("*.part*"))
    con.close()


def test_schema_guard_allowlist_and_counters(env, monkeypatch):
    mod, home, dest, _ = env
    con = make_wal_db(home / ".fake/state.db", ["row"])
    con.execute("CREATE TABLE usage (input_tokens INTEGER, tokens_used INTEGER, output_tokens INTEGER, tokens INTEGER)")
    con.execute("CREATE TABLE users (author_name TEXT, session_token TEXT)")
    assert run_main(mod, "--dest", str(dest), "--only", "walstore") == 1  # session_token is not a counter
    monkeypatch.setattr(mod, "ALLOW", [("walstore", "users", "session_token", "test: a public token")])
    assert run_main(mod, "--dest", str(dest.parent / "bk2"), "--only", "walstore") == 0
    con.close()


def test_check_schemas_is_read_only_and_prints_names_only(env, capsys):
    mod, home, dest, _ = env
    con = make_wal_db(home / ".fake/state.db", ["SENTINEL-ROW-CONTENT"])
    con.execute("CREATE TABLE accounts (secret_blob TEXT)")
    con.execute("INSERT INTO accounts VALUES ('SENTINEL-ACCOUNT-CONTENT')")
    con.commit()
    assert run_main(mod, "--check-schemas", "--only", "walstore") == 1
    out = capsys.readouterr().out
    assert "walstore: state.db: accounts: UNEXPLAINED" in out and "accounts.secret_blob: UNEXPLAINED" in out
    assert "SENTINEL" not in out
    assert not dest.exists()
    con.close()


# --- destination refusals (adversary finding 3) ---

def with_local_share_store(mod, home, monkeypatch):
    def stores(h):
        return make_stores(mod, h) + [{"name": "crush-acp", "kind": "sqlite",
                                        "files": [h / ".local/share/crush-acp/crush.db"]}]
    monkeypatch.setattr(mod, "build_stores", stores)
    con = make_wal_db(home / ".local/share/crush-acp/crush.db", ["live"])
    con.close()
    return home / ".local/share/crush-acp/crush.db"


@pytest.mark.parametrize("where", [".local/share", ""])
def test_dest_holding_a_source_store_is_refused_and_nothing_changes(env, monkeypatch, capsys, where):
    mod, home, _, _ = env
    db = with_local_share_store(mod, home, monkeypatch)
    wal, tree_db = populate(home)  # keep the writers open: closing them would delete -wal/-shm mid-test
    home.chmod(0o755)
    before = (db.stat().st_ino, db.read_bytes(), sorted(p.name for p in db.parent.iterdir()))
    modes = {p: stat.S_IMODE(p.stat().st_mode) for p in [home, *home.rglob("*")]}
    dest = home / where if where else home
    assert mod.main(["--dest", str(dest), "--only", "crush-acp"]) == 2
    err = capsys.readouterr().err
    assert "refusing" in err and ("holds" in err or "inside" in err)
    assert (db.stat().st_ino, db.read_bytes(), sorted(p.name for p in db.parent.iterdir())) == before
    assert {p: stat.S_IMODE(p.stat().st_mode) for p in [home, *home.rglob("*")]} == modes
    assert not list(home.rglob("*.part"))
    wal.close()
    tree_db.close()


def test_refuse_reason_names_a_store_under_the_dest(env):
    mod, home, _, _ = env
    populate(home)
    reason = mod.refuse_reason(home.resolve(), make_stores(mod, home))
    assert "holds the" in reason


def test_existing_dest_is_refused_and_never_chmodded(env, capsys):
    mod, home, dest, _ = env
    populate(home)
    for existing in (dest, ):
        existing.mkdir()
        existing.chmod(0o755)
        assert run_main(mod, "--dest", str(existing)) == 2
        assert "already exists" in capsys.readouterr().err
        assert stat.S_IMODE(existing.stat().st_mode) == 0o755
        assert list(existing.iterdir()) == []


def test_interrupted_run_leaves_only_a_part_dir_and_blocks_the_next_run(env, monkeypatch, capsys):
    mod, home, dest, _ = env
    populate(home)
    with monkeypatch.context() as m:
        m.setattr(mod, "seal_and_hash", lambda run: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            run_main(mod, "--dest", str(dest))
    assert not dest.exists() and (dest.parent / "bk.part").is_dir()
    assert not (dest.parent / "bk.part/MANIFEST.json").exists()
    assert run_main(mod, "--dest", str(dest)) == 2
    assert "bk.part" in capsys.readouterr().err


def test_finished_generation_has_a_manifest_and_no_part_dir(env):
    mod, home, dest, _ = env
    populate(home)
    assert run_main(mod, "--dest", str(dest)) == 0
    assert (dest / "MANIFEST.json").is_file() and not dest.with_name("bk.part").exists()
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert all(s["destination"].startswith(str(dest)) for s in manifest["stores"])


def test_main_restores_the_umask(env):
    mod, home, dest, _ = env
    populate(home)
    old = os.umask(0o022)
    try:
        run_main(mod, "--dest", str(dest))
        assert os.umask(old) == 0o022
    finally:
        os.umask(old)


# --- raced symlinks (adversary finding 9) ---

def test_a_link_that_slips_past_the_check_is_dropped_not_followed(env, monkeypatch):
    mod, home, dest, _ = env
    populate(home)
    secret = home / ".fake/outside-secret.txt"
    secret.write_text("SENTINEL-LINK-TARGET")
    os.symlink(secret, home / ".fake/sessions/p1/racelink")
    os.symlink(home / ".fake", home / ".fake/sessions/racedir")
    real_skip = mod.skip_reason

    def racy(directory, name, mode, excluder):  # the links appear after the check: the walk's check does not see them
        return None if name in ("racelink", "racedir") else real_skip(directory, name, mode, excluder)

    monkeypatch.setattr(mod, "skip_reason", racy)
    assert run_main(mod, "--dest", str(dest)) == 1  # opened O_NOFOLLOW: refused with an error, never followed
    assert not list(dest.rglob("racelink")) and not list(dest.rglob("racedir"))
    assert b"SENTINEL-LINK-TARGET" not in all_bytes(dest)
    assert not any(p.is_symlink() for p in dest.rglob("*"))
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    fs_store = next(s for s in manifest["stores"] if s["store"] == "filestore")
    assert fs_store["status"] == "partial"
    assert {Path(e["source"]).name for e in fs_store["errors"]} == {"racelink", "racedir"}
    assert all("became a symlink" in e["error"] for e in fs_store["errors"])
    assert secret.read_text() == "SENTINEL-LINK-TARGET"


def test_help_documents_exit_codes_exclusions_and_the_hermes_override():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    for needle in ("ADE_BACKUP_HERMES", "Exit: 0 clean", "MANIFEST.json", "scrubbed", "--check-schemas", ".part"):
        assert needle in proc.stdout, needle


# --- missing stores and required sidecars (Codex review of PR 24, 2026-10-20) ---

@pytest.fixture
def real(tmp_path, monkeypatch):
    """The real store list under a temporary HOME (nothing outside tmp_path is read or written)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return load(), home, tmp_path


def default_generation(home):
    gens = [p for p in (home / ".local/state/ade/backups").iterdir() if not p.name.endswith(".part")]
    assert len(gens) == 1
    return gens[0]


def test_missing_handoffs_store_keeps_its_own_root_so_the_default_dest_is_accepted(real, capsys):
    mod, home, _ = real
    assert mod.main(["--only", "handoffs"]) == 0
    manifest = json.loads((default_generation(home) / "MANIFEST.json").read_text())
    entry = manifest["stores"][0]
    assert entry["store"] == "handoffs" and entry["status"] == "missing"
    assert entry["missing"] == [str(home / ".local/state/handoffs")] and manifest["errors"] == []
    assert "store handoffs: missing" in capsys.readouterr().err


def test_missing_hermes_memory_store_does_not_make_home_a_root(real, capsys):
    mod, home, _ = real
    dest = home / "out" / "bk"
    assert mod.main(["--only", "hermes-memory", "--dest", str(dest)]) == 0
    entry = json.loads((dest / "MANIFEST.json").read_text())["stores"][0]
    assert entry["status"] == "missing"
    assert mod.main(["--only", "hermes-memory"]) == 0  # the default dest under ~/.local/state too


def test_strict_stores_exits_1_on_a_missing_store_and_still_writes_the_generation(real, capsys):
    mod, home, _ = real
    dest = home / "out" / "bk"
    assert mod.main(["--only", "handoffs", "--dest", str(dest), "--strict-stores"]) == 1
    assert json.loads((dest / "MANIFEST.json").read_text())["stores"][0]["status"] == "missing"
    assert mod.main(["--only", "handoffs", "--dry-run", "--strict-stores", "--dest", str(home / "o2")]) == 1
    assert mod.main(["--only", "handoffs", "--dry-run", "--dest", str(home / "o2")]) == 0


def test_a_store_with_some_paths_missing_is_recorded_per_path(real):
    mod, home, _ = real
    con = make_wal_db(home / ".zcode/cli/db/db.sqlite", ["x"])
    con.close()  # .zcode/v2/tasks-index.sqlite is absent
    dest = home / "out" / "bk"
    assert mod.main(["--only", "zcode-db", "--dest", str(dest)]) == 0
    entry = json.loads((dest / "MANIFEST.json").read_text())["stores"][0]
    assert entry["status"] == "ok" and entry["missing"] == [str(home / ".zcode/v2/tasks-index.sqlite")]
    assert entry["file_count"] == 1


def test_refuse_reason_still_refuses_around_existing_and_missing_stores(real):
    mod, home, _ = real
    (home / ".local/state/handoffs").mkdir(parents=True)
    stores = mod.build_stores(home)
    inside = (home / ".local/state/handoffs/x").resolve()
    holds = (home / ".local/state").resolve()
    assert "inside the handoffs" in mod.refuse_reason(inside, stores)
    assert "holds the handoffs" in mod.refuse_reason(holds, stores)
    # hermes-memory does not exist: its own path is still a root
    assert "inside the hermes-memory" in mod.refuse_reason((home / "hermes-memory/x").resolve(), stores)
    assert mod.refuse_reason((home / ".local/state/ade/backups/s").resolve(), stores) is None


def make_cursor_session(home, with_meta=True, sub="chats/hashA/uuid1"):
    sdir = home / ".cursor" / sub
    sdir.mkdir(parents=True)
    con = make_wal_db(sdir / "store.db", ["row"])
    con.close()
    if with_meta:
        (sdir / "meta.json").write_text('{"name": "kept"}')
    return sdir


def manifest_of(dest):
    return json.loads((dest / "MANIFEST.json").read_text())


def test_cursor_session_with_its_meta_is_clean(real):
    mod, home, _ = real
    make_cursor_session(home)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and (dest / "cursor-chats/hashA/uuid1/meta.json").is_file()


def test_cursor_session_without_meta_json_is_a_warning_and_the_store_stays_ok(real, capsys):
    mod, home, _ = real
    make_cursor_session(home, with_meta=False)
    make_cursor_session(home, sub="chats/hashA/uuid2")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    manifest = manifest_of(dest)
    entry = manifest["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and manifest["errors"] == []
    assert entry["sidecar_missing"] == ["hashA/uuid1/meta.json"]
    assert "ade-backup-stores: cursor-chats: 1 session(s) without meta.json (copied without it)" in capsys.readouterr().err
    assert (dest / "cursor-chats/hashA/uuid1/store.db").is_file()  # the db is copied without it
    assert not (dest / "cursor-chats/hashA/uuid1/meta.json").exists()
    assert (dest / "cursor-chats/hashA/uuid2/meta.json").is_file()


def test_strict_stores_makes_an_absent_meta_json_an_error_and_the_store_partial(real):
    mod, home, _ = real
    make_cursor_session(home, with_meta=False)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest), "--strict-stores"]) == 1
    manifest = manifest_of(dest)
    entry = manifest["stores"][0]
    assert entry["status"] == "partial" and entry["sidecar_missing"] == ["hashA/uuid1/meta.json"]
    assert [e["source"] for e in entry["errors"]] == ["hashA/uuid1"]  # the session dir, relative, no content
    assert "meta.json" in entry["errors"][0]["error"] and "kept" not in json.dumps(manifest["errors"])
    assert (dest / "cursor-chats/hashA/uuid1/store.db").is_file()  # the generation still completed


def test_cursor_meta_json_symlink_is_an_error(real):
    mod, home, _ = real
    sdir = make_cursor_session(home, with_meta=False)
    (home / "elsewhere.json").write_text("{}")
    os.symlink(home / "elsewhere.json", sdir / "meta.json")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and "symlink" in entry["errors"][0]["error"]
    assert not (dest / "cursor-chats/hashA/uuid1/meta.json").exists()


def test_cursor_meta_json_vanishing_between_listing_and_copy_is_an_error(real, monkeypatch):
    mod, home, _ = real
    make_cursor_session(home)
    real_copy = mod.copy_regular

    def vanishing(src, dst, **kw):
        victim = Path(kw.get("shown") or src)
        if victim.name == "meta.json":
            victim.unlink()
        return real_copy(src, dst, **kw)

    monkeypatch.setattr(mod, "copy_regular", vanishing)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["errors"][0]["source"] == "hashA/uuid1"
    assert "vanished" in entry["errors"][0]["error"]


def test_dry_run_reports_the_same_absent_sidecars_as_the_copy(real, capsys):
    mod, home, _ = real
    make_cursor_session(home, with_meta=False)
    make_cursor_session(home, sub="chats/hashA/uuid2")
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)["stores"][0]
    assert plan["status"] == "ok" and plan["errors"] == [] and plan["sidecar_missing"] == ["hashA/uuid1/meta.json"]
    assert "cursor-chats: 1 session(s) without meta.json (copied without it)" in cap.err
    assert plan["file_count"] == 3  # both dbs and the one sidecar that exists
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    assert manifest_of(dest)["stores"][0]["sidecar_missing"] == plan["sidecar_missing"]
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--strict-stores", "--dest", str(home / "o")]) == 1
    capsys.readouterr()


def test_check_schemas_counts_an_unopenable_database_apart_from_credential_names(real, capsys):
    mod, home, _ = real
    sdir = make_cursor_session(home)
    (sdir / "store.db").write_bytes(b"this is not a sqlite database" * 100)
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "0 unexplained credential-looking name(s), 0 symlink problem(s), 0 missing, 1 unopenable, 0 excluded" in out


# --- Codex pass 2 on PR 24 (2026-10-20): grok memory roots, symlinked roots, dry-run sidecars ---

def test_grok_memory_v2_and_memtrace_are_backed_up_and_counted_by_the_dry_run(real, capsys):
    mod, home, _ = real
    (home / ".grok/memory-v2").mkdir(parents=True)
    (home / ".grok/memory-v2/x.json").write_text('{"m": 1}')
    (home / ".grok/memtrace/t1").mkdir(parents=True)
    (home / ".grok/memtrace/t1/trace.jsonl").write_text('{"t": 1}\n')
    assert mod.main(["--only", "grok", "--dry-run", "--json", "--dest", str(home / "dry")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 0
    assert (dest / "grok/memory-v2/x.json").read_text() == '{"m": 1}'
    assert (dest / "grok/memtrace/t1/trace.jsonl").is_file()
    entry = manifest_of(dest)["stores"][0]
    assert plan["file_count"] == entry["file_count"] == 2 and plan["bytes"] >= entry["bytes"]  # plan counts the -wal too
    # sessions is absent: recorded per path, the store stays ok because other roots exist
    assert entry["status"] == "ok" and entry["missing"] == [str(home / ".grok/sessions")]


def codex_layout(home):
    """This Mac's layout: ~/.codex/sessions and ~/.codex/session_index.jsonl are links into a runtime dir under HOME."""
    runtime = home / "ops-private/.codex-runtime"
    (runtime / "sessions/2026/10").mkdir(parents=True)
    (runtime / "sessions/2026/10/rollout-a.jsonl").write_text('{"codex": "rollout-a"}\n')
    (runtime / "sessions/x").mkdir()
    (runtime / "session_index.jsonl").write_text('{"codex": "index"}\n')
    (home / ".codex").mkdir()
    (home / ".codex/auth.json").write_text("SENTINEL-CODEX-AUTH")
    os.symlink(home / ".codex/auth.json", runtime / "sessions/x/leak.jsonl")
    os.symlink(runtime / "sessions", home / ".codex/sessions")
    os.symlink(runtime / "session_index.jsonl", home / ".codex/session_index.jsonl")
    return runtime


def contents(dest):
    return "".join(p.read_text(errors="replace") for p in dest.rglob("*") if p.is_file() and not p.is_symlink())


def test_codex_root_links_into_home_are_followed_and_recorded(real, capsys):
    mod, home, _ = real
    runtime = codex_layout(home)
    assert mod.main(["--only", "codex-files", "--dry-run", "--json", "--dest", str(home / "dry")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "codex-files", "--dest", str(dest)]) == 0
    assert (dest / "codex-files/sessions/2026/10/rollout-a.jsonl").read_text() == '{"codex": "rollout-a"}\n'
    index = dest / "codex-files/session_index.jsonl"
    assert index.is_file() and not index.is_symlink() and index.read_text() == '{"codex": "index"}\n'
    assert not any(p.is_symlink() for p in dest.rglob("*"))
    assert "SENTINEL-CODEX-AUTH" not in contents(dest) and not (dest / "codex-files/sessions/x/leak.jsonl").exists()
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == []
    assert entry["root_symlinks"] == [
        {"root": "sessions", "link": str(home / ".codex/sessions"), "target": str(runtime / "sessions")},
        {"root": "session_index.jsonl", "link": str(home / ".codex/session_index.jsonl"),
         "target": str(runtime / "session_index.jsonl")}]
    assert entry["file_count"] == plan["file_count"] == 2
    assert entry["bytes"] == plan["bytes"] and plan["root_symlinks"] == entry["root_symlinks"]
    assert any(s["path"].endswith("leak.jsonl") for s in entry["skipped"])  # the inner link is still dropped


def test_destination_inside_a_followed_root_target_is_refused(real, capsys):
    mod, home, _ = real
    runtime = codex_layout(home)
    for inside in (runtime / "sessions/new-gen", runtime / "new-gen"):  # a directory root, a file root's directory
        assert mod.main(["--only", "codex-files", "--dest", str(inside)]) == 2
        assert "source store" in capsys.readouterr().err and not inside.exists()


def test_a_chain_of_root_links_inside_home_is_followed_and_recorded_with_the_final_target(real):
    mod, home, _ = real
    final = home / "data/final"
    final.mkdir(parents=True)
    (final / "chat.jsonl").write_text("CHAIN-FILE")
    os.symlink(final, home / "data/hop")
    (home / ".grok").mkdir()
    os.symlink(home / "data/hop", home / ".grok/sessions")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 0
    assert (dest / "grok/sessions/chat.jsonl").read_text() == "CHAIN-FILE"
    entry = manifest_of(dest)["stores"][0]
    assert entry["root_symlinks"] == [{"root": "sessions", "link": str(home / ".grok/sessions"), "target": str(final)}]


def test_a_symlinked_file_root_outside_home_is_an_error_not_copied(real, capsys):
    mod, home, tmp = real
    outside = tmp / "outside.json"
    outside.write_text("SENTINEL-SYMLINK-ROOT-TARGET")
    (home / ".config/herdr").mkdir(parents=True)
    link = home / ".config/herdr/session.json"
    os.symlink(outside, link)
    assert mod.main(["--only", "herdr", "--dry-run", "--json", "--dest", str(home / "dry")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 0 and "symlink target outside HOME" in plan["errors"][0]["error"]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "herdr", "--dest", str(dest)]) == 1
    assert "SENTINEL-SYMLINK-ROOT-TARGET" not in contents(dest)
    entry = manifest_of(dest)["stores"][0]
    assert entry["file_count"] == 0 and entry["status"] == "partial" and entry["root_symlinks"] == []
    assert entry["errors"][0]["source"] == str(link)
    assert "symlink target outside HOME" in entry["errors"][0]["error"] and str(link) in entry["errors"][0]["error"]


def test_a_symlinked_directory_root_outside_home_is_an_error_not_walked(real, capsys):
    mod, home, tmp = real
    outside = tmp / "outside-dir"
    outside.mkdir()
    (outside / "chat.jsonl").write_text("SENTINEL-SYMLINK-DIR-TARGET")
    (home / ".grok").mkdir()
    link = home / ".grok/sessions"
    os.symlink(outside, link)
    assert mod.main(["--only", "grok", "--dry-run", "--json", "--dest", str(home / "dry")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 0 and "symlink target outside HOME" in plan["errors"][0]["error"]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 1
    assert "SENTINEL-SYMLINK-DIR-TARGET" not in contents(dest) and not (dest / "grok/sessions").exists()
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and "symlink target outside HOME" in entry["errors"][0]["error"]


def test_a_dangling_root_link_is_an_error_not_a_missing_store(real, capsys):
    mod, home, _ = real
    (home / ".grok").mkdir()
    link = home / ".grok/sessions"
    os.symlink(home / "gone", link)
    assert mod.main(["--only", "grok", "--dry-run", "--json", "--dest", str(home / "dry")]) == 1
    assert "dangling symlink" in json.loads(capsys.readouterr().out)["stores"][0]["errors"][0]["error"]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and str(link) not in entry["missing"]
    assert entry["errors"][0]["source"] == str(link) and "dangling symlink" in entry["errors"][0]["error"]


def test_a_root_link_to_a_credential_path_inside_home_is_an_error(real):
    mod, home, _ = real
    (home / ".codex").mkdir()
    (home / ".codex/auth.json").write_text("SENTINEL-LINKED-CREDENTIAL")
    (home / ".config/herdr").mkdir(parents=True)
    os.symlink(home / ".codex/auth.json", home / ".config/herdr/session.json")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "herdr", "--dest", str(dest)]) == 1
    assert "SENTINEL-LINKED-CREDENTIAL" not in contents(dest)
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and "symlink target excluded" in entry["errors"][0]["error"]


def test_a_store_with_existing_roots_and_no_files_says_so_on_stderr(real, capsys):
    mod, home, _ = real
    (home / ".local/state/handoffs").mkdir(parents=True)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "handoffs", "--dest", str(dest)]) == 0
    assert "handoffs: 0 files copied although its roots exist" in capsys.readouterr().err
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["file_count"] == 0
    assert mod.main(["--only", "herdr", "--dest", str(home / "out2")]) == 0  # nothing exists: "missing", not this line
    assert "0 files copied" not in capsys.readouterr().err



def test_dry_run_counts_the_sidecar_a_cursor_store_would_copy(real, capsys):
    mod, home, _ = real
    make_cursor_session(home)
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert plan["file_count"] == entry["file_count"] == 2
    assert plan["bytes"] >= entry["bytes"]  # the estimate adds the -wal file


def test_a_symlinked_store_db_inside_a_cursor_tree_is_skipped_not_opened(real, capsys):
    mod, home, tmp = real
    sdir = make_cursor_session(home)  # a real session, copied
    link_dir = home / ".cursor/chats/hashB/uuid2"
    link_dir.mkdir(parents=True)
    outside = tmp / "outside.db"
    con = make_wal_db(outside, ["SECRET-OUTSIDE-ROW"])
    con.close()
    os.symlink(outside, link_dir / "store.db")
    (link_dir / "meta.json").write_text("{}")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and (dest / "cursor-chats/hashA/uuid1/store.db").is_file()
    assert not (dest / "cursor-chats/hashB/uuid2/store.db").exists()
    assert any(s["why"] == "symlink" and s["path"].endswith("hashB/uuid2/store.db") for s in entry["skipped"])
    assert b"SECRET-OUTSIDE-ROW" not in all_bytes(dest)
    capsys.readouterr()  # drop the real run's stdout before the JSON dry run
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 2 and plan["skipped_count"] == 1
    assert sdir.name == "uuid1"


def test_dry_run_sqlite_estimate_includes_the_wal_file(real, capsys):
    mod, home, _ = real
    sdir = home / ".cursor/chats/hashA/uuid1"
    con = make_wal_db(sdir / "store.db", ["x" * 4096] * 64)  # the rows live only in -wal while the writer is open
    (sdir / "meta.json").write_text("{}")
    main_size = (sdir / "store.db").stat().st_size
    wal_size = (sdir / "store.db-wal").stat().st_size
    assert wal_size > main_size
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["bytes"] == main_size + wal_size + (sdir / "meta.json").stat().st_size
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["bytes"] <= plan["bytes"]  # the snapshot folds the WAL pages in: the estimate is an upper bound
    assert entry["bytes"] > main_size  # and the WAL rows did reach the copy
    con.close()


def link_session_dir(home, tmp, marker="SECRET-LINKED-DIR-ROW"):
    """~/.cursor/chats/hashB/uuid2 is a link to a session directory outside HOME holding a marker db and meta.json."""
    outside = tmp / "sess"
    con = make_wal_db(outside / "store.db", [marker])
    con.close()
    (outside / "meta.json").write_text("{}")
    link = home / ".cursor/chats/hashB/uuid2"
    link.parent.mkdir(parents=True)
    os.symlink(outside, link)
    return link


def test_a_database_under_a_symlinked_session_directory_is_skipped_not_copied(real, capsys):
    mod, home, tmp = real
    make_cursor_session(home)
    link_session_dir(home, tmp)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    err = capsys.readouterr().err
    skipped = home / ".cursor/chats/hashB/uuid2/store.db"
    assert err.splitlines().count(f"ade-backup-stores: cursor-chats: skipped {skipped}: symlink") == 1  # DECIDED: a skip stays ok, but is printed
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and (dest / "cursor-chats/hashA/uuid1/store.db").is_file()
    assert not (dest / "cursor-chats/hashB").exists()
    assert any(s["why"] == "symlink" and s["path"].endswith("hashB/uuid2/store.db") for s in entry["skipped"])
    assert b"SECRET-LINKED-DIR-ROW" not in all_bytes(dest)
    capsys.readouterr()
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 2 and plan["skipped_count"] == 1


def test_antigravity_conversations_behind_a_linked_directory_are_skipped(real):
    mod, home, tmp = real
    outside = tmp / "convs"
    make_wal_db(outside / "c1.db", ["SECRET-LINKED-CONV-ROW"]).close()
    (outside / "c1.meta").write_text("{}")
    agy = home / ".gemini/antigravity"
    agy.mkdir(parents=True)
    os.symlink(outside, agy / "conversations")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "antigravity-ide-db", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert any(s["why"] == "symlink" for s in entry["skipped"]) and entry["file_count"] == 0
    assert b"SECRET-LINKED-CONV-ROW" not in all_bytes(dest)


def test_check_schemas_does_not_open_a_database_under_a_linked_directory(real, capsys):
    mod, home, tmp = real
    make_cursor_session(home)
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 0  # nothing linked: clean
    assert "0 symlink problem(s)" in capsys.readouterr().out
    link_session_dir(home, tmp)
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 1  # DECIDED: a linked tree db is a problem
    out = capsys.readouterr().out
    assert "hashB/uuid2/store.db: symlink, not opened" in out
    assert "0 unexplained credential-looking name(s), 1 symlink problem(s)" in out


def link_codex_db(home, tmp, target="in-home"):
    """~/.codex/state_5.sqlite as a link; this Mac's four codex databases are links into a runtime dir under HOME."""
    paths = {"in-home": home / "ops-private/.codex-runtime/state_5.sqlite", "outside": tmp / "outside-state.sqlite",
             "excluded": home / ".codex/auth.json", "dangling": home / "nowhere/state_5.sqlite"}
    if target != "dangling":
        make_wal_db(paths[target], ["CODEX-ROW"]).close()
    (home / ".codex").mkdir(exist_ok=True)
    os.symlink(paths[target], home / ".codex/state_5.sqlite")
    return paths[target]


def test_a_linked_sqlite_path_under_home_is_backed_up_and_recorded(real, capsys):
    mod, home, tmp = real
    target = link_codex_db(home, tmp)
    assert mod.main(["--only", "codex-db", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "codex-db", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and entry["file_count"] == plan["file_count"] == 1
    link = {"root": "state_5.sqlite", "link": str(home / ".codex/state_5.sqlite"), "target": str(target)}
    assert entry["root_symlinks"] == plan["root_symlinks"] == [link]
    copy = dest / "codex-db/state_5.sqlite"
    assert not copy.is_symlink() and b"CODEX-ROW" in copy.read_bytes()
    assert plan["bytes"] >= entry["bytes"] > 0


@pytest.mark.parametrize("kind", ["outside", "excluded", "dangling"])
def test_a_linked_sqlite_path_that_may_not_be_followed_is_an_error(real, capsys, kind):
    mod, home, tmp = real
    link_codex_db(home, tmp, kind)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "codex-db", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["file_count"] == 0 and entry["root_symlinks"] == []
    assert len(entry["errors"]) == 1 and "RootSymlinkError" in entry["errors"][0]["error"]
    assert not list(dest.rglob("*.sqlite")) and b"CODEX-ROW" not in all_bytes(dest)
    capsys.readouterr()
    assert mod.main(["--only", "codex-db", "--dry-run", "--json", "--dest", str(home / "o")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 0 and plan["status"] == "partial" and len(plan["errors"]) == 1


def test_check_schemas_follows_an_allowed_sqlite_link_and_refuses_the_rest(real, capsys):
    mod, home, tmp = real
    target = link_codex_db(home, tmp)
    assert mod.main(["--check-schemas", "--only", "codex-db"]) == 0
    out = capsys.readouterr().out
    assert f"codex-db: {home / '.codex/state_5.sqlite'}: symlink -> {target}" in out
    assert "0 unexplained credential-looking name(s), 0 symlink problem(s)" in out
    (home / ".codex/state_5.sqlite").unlink()
    link_codex_db(home, tmp, "outside")
    assert mod.main(["--check-schemas", "--only", "codex-db"]) == 1
    out = capsys.readouterr().out
    assert "symlink refused: symlink target outside HOME" in out and "1 symlink problem(s)" in out


def link_tree_root(home, tmp, where, marker="SECRET-LINKED-ROOT-ROW"):
    """~/.cursor/chats is a link to a tree holding one session (a marker db and its meta.json)."""
    target = (tmp / "outside-chats") if where == "outside" else (home / "data/chats")
    sdir = target / "hashA/uuid1"
    make_wal_db(sdir / "store.db", [marker]).close()
    (sdir / "meta.json").write_text("{}")
    (home / ".cursor").mkdir(exist_ok=True)
    os.symlink(target, home / ".cursor/chats")
    return target


def test_a_tree_root_link_outside_home_is_an_error_and_nothing_is_searched(real, capsys):
    mod, home, tmp = real
    link_tree_root(home, tmp, "outside")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["file_count"] == 0 and entry["root_symlinks"] == []
    assert len(entry["errors"]) == 1 and "symlink target outside HOME" in entry["errors"][0]["error"]
    assert not (dest / "cursor-chats/hashA").exists() and b"SECRET-LINKED-ROOT-ROW" not in all_bytes(dest)
    capsys.readouterr()
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 0 and plan["status"] == "partial" and len(plan["errors"]) == 1
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 1
    out = capsys.readouterr().out
    assert f"cursor-chats: {home / '.cursor/chats'}: symlink refused: symlink target outside HOME" in out
    assert "0 unexplained credential-looking name(s), 1 symlink problem(s)" in out


def test_a_tree_root_link_under_home_is_followed_and_recorded(real, capsys, monkeypatch):
    mod, home, tmp = real
    target = link_tree_root(home, tmp, "home")
    link = {"root": str(home / ".cursor/chats"), "link": str(home / ".cursor/chats"), "target": str(target)}
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 2 and plan["skipped_count"] == 0 and plan["root_symlinks"] == [link]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and entry["file_count"] == 2
    assert entry["root_symlinks"] == [link] and entry["skipped"] == []
    assert b"SECRET-LINKED-ROOT-ROW" in (dest / "cursor-chats/hashA/uuid1/store.db").read_bytes()
    assert (dest / "cursor-chats/hashA/uuid1/meta.json").is_file()
    assert not any(p.is_symlink() for p in dest.rglob("*"))
    opened = []
    real_ro = mod.ro_connect
    monkeypatch.setattr(mod, "ro_connect", lambda p, base=None: (opened.append(Path(p)), real_ro(p, base))[1])
    capsys.readouterr()
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 0
    out = capsys.readouterr().out
    assert f"cursor-chats: {home / '.cursor/chats'}: symlink -> {target}" in out
    assert "0 unexplained credential-looking name(s), 0 symlink problem(s)" in out
    assert opened == [target / "hashA/uuid1/store.db"]


def test_destination_inside_a_followed_tree_root_target_is_refused(real, capsys):
    mod, home, tmp = real
    target = link_tree_root(home, tmp, "home")
    inside = target / "newdir"
    assert mod.main(["--only", "cursor-chats", "--dest", str(inside)]) == 2
    assert "source store" in capsys.readouterr().err and not inside.exists()


# --- adversary round 9 / 14 on PR 24: a root reached through a linked PARENT gets the root-link gate ---

PARENT_MARK = "SENTINEL-PARENT-LINK-ROW"
PARENT_LAYOUTS = {  # store -> (the linked parent below HOME, what it holds)
    "cursor-chats": (".cursor", "chats/hashA/uuid1/store.db"),
    "grok": (".grok", "sessions/s1/chat.jsonl"),
    "codex-db": (".codex", "state_5.sqlite"),
}


def parent_link(home, tmp, store, where):
    """~/<parent> is a link to a directory that holds the store's data; returns that directory."""
    parent, rel = PARENT_LAYOUTS[store]
    target = {"home": home / "data/linked", "outside": tmp / "outside-linked",
              "excluded": home / "credential-bak/linked"}[where]
    data = target / rel
    if rel.endswith((".db", ".sqlite")):
        make_wal_db(data, [PARENT_MARK]).close()
        if store == "cursor-chats":
            (data.parent / "meta.json").write_text("{}")
    else:
        data.parent.mkdir(parents=True)
        data.write_text(PARENT_MARK)
    os.symlink(target, home / parent)
    return target


@pytest.mark.parametrize("store", sorted(PARENT_LAYOUTS))
def test_a_root_below_a_linked_parent_under_home_is_followed_and_recorded(real, capsys, store):
    mod, home, tmp = real
    target = parent_link(home, tmp, store, "home")
    assert mod.main(["--only", store, "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", store, "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == plan["status"] == "ok" and entry["errors"] == plan["errors"] == []
    assert entry["file_count"] == plan["file_count"] > 0
    assert entry["root_symlinks"] == plan["root_symlinks"] != []
    parent = PARENT_LAYOUTS[store][0]
    for rec in entry["root_symlinks"]:
        assert rec["link"].startswith(str(home / parent) + os.sep)  # the configured root, as configured
        assert rec["target"].startswith(str(target) + os.sep)  # where it really is
    assert PARENT_MARK.encode() in all_bytes(dest)
    assert not any(p.is_symlink() for p in dest.rglob("*"))


@pytest.mark.parametrize("where, reason", [("outside", "symlink target outside HOME"),
                                           ("excluded", "symlink target excluded")])
@pytest.mark.parametrize("store", sorted(PARENT_LAYOUTS))
def test_a_root_below_a_linked_parent_that_may_not_be_followed_is_an_error_and_nothing_is_copied(
        real, capsys, store, where, reason):
    mod, home, tmp = real
    parent_link(home, tmp, store, where)
    dest = home / "out" / "bk"
    assert mod.main(["--only", store, "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["file_count"] == 0 and entry["root_symlinks"] == []
    assert entry["errors"] and all("RootSymlinkError" in e["error"] and reason in e["error"] for e in entry["errors"])
    assert all(str(home / PARENT_LAYOUTS[store][0]) in e["source"] for e in entry["errors"])
    assert PARENT_MARK.encode() not in all_bytes(dest)
    capsys.readouterr()
    assert mod.main(["--only", store, "--dry-run", "--json", "--dest", str(home / "o")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["status"] == "partial" and plan["file_count"] == 0 and plan["root_symlinks"] == []
    assert plan["errors"] == entry["errors"]


def test_a_dangling_linked_parent_is_an_error_not_a_missing_store(real, capsys):
    mod, home, _ = real
    os.symlink(home / "nowhere", home / ".cursor")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["missing"] == []
    assert "dangling symlink" in entry["errors"][0]["error"]


def test_a_missing_root_below_a_working_linked_parent_is_missing_not_an_error(real, capsys):
    mod, home, _ = real
    (home / "data/cursor").mkdir(parents=True)
    os.symlink(home / "data/cursor", home / ".cursor")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "missing" and entry["errors"] == [] and entry["file_count"] == 0
    assert capsys.readouterr().err.count("store cursor-chats: missing") == 1


def test_destination_inside_a_followed_parent_link_target_is_refused(real, capsys):
    mod, home, tmp = real
    target = parent_link(home, tmp, "cursor-chats", "home")
    inside = target / "chats/newdir"
    assert mod.main(["--only", "cursor-chats", "--dest", str(inside)]) == 2
    assert "source store" in capsys.readouterr().err and not inside.exists()


def test_check_schemas_gates_a_linked_parent_like_a_linked_root(real, capsys):
    mod, home, tmp = real
    target = parent_link(home, tmp, "cursor-chats", "home")
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 0
    assert f"cursor-chats: {home / '.cursor/chats'}: symlink -> {target / 'chats'}" in capsys.readouterr().out
    (home / ".cursor").unlink()
    parent_link(home, tmp, "cursor-chats", "outside")
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 1
    assert "symlink refused: symlink target outside HOME" in capsys.readouterr().out


# --- Codex passes 5-6 on PR 24 (2026-10-20): a source that turns into a symlink, the Hermes fallback, a pruned db ---

def test_a_file_that_becomes_a_symlink_after_listing_is_refused_not_dereferenced(real, monkeypatch):
    mod, home, tmp = real
    marker = tmp / "marker.txt"
    marker.write_text("SENTINEL-SWAPPED-IN-TARGET")
    (home / ".grok/sessions/p1").mkdir(parents=True)
    (home / ".grok/sessions/p1/chat.jsonl").write_text("swapped\n")
    (home / ".grok/sessions/p1/other.jsonl").write_text("kept\n")
    real_skip = mod.skip_reason

    def swapping(directory, name, mode, excluder):
        why = real_skip(directory, name, mode, excluder)  # the listing check passed: now the file becomes a link
        victim = Path(directory) / "chat.jsonl"
        if name == "chat.jsonl" and victim.is_file() and not victim.is_symlink():
            victim.unlink()
            os.symlink(marker, victim)
        return why

    monkeypatch.setattr(mod, "skip_reason", swapping)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 1
    assert b"SENTINEL-SWAPPED-IN-TARGET" not in all_bytes(dest)
    assert not (dest / "grok/sessions/p1/chat.jsonl").exists()
    assert (dest / "grok/sessions/p1/other.jsonl").read_text() == "kept\n"
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial"
    assert [e["source"] for e in entry["errors"]] == [str(home / ".grok/sessions/p1/chat.jsonl")]
    assert "became a symlink" in entry["errors"][0]["error"]


def hermes_only(mod, home, tmp, monkeypatch):
    fake = tmp / "hermes"
    write_fake_hermes(fake, "none")
    log = tmp / "hermes.log"
    monkeypatch.setenv("ADE_BACKUP_HERMES", str(fake))
    monkeypatch.setenv("FAKE_HERMES_LOG", str(log))
    dest = home / "out" / "bk"
    return dest, log, mod.main(["--only", "hermes-export", "--dest", str(dest)])


def test_hermes_export_does_not_follow_a_state_db_link_outside_home(real, monkeypatch):
    mod, home, tmp = real
    outside = make_hermes_db(tmp / "outside", (("SENTINEL-HERMES-OUTSIDE-SESSION", 2),))
    (home / ".hermes").mkdir()
    os.symlink(outside, home / ".hermes/state.db")
    dest, log, rc = hermes_only(mod, home, tmp, monkeypatch)
    assert rc == 1 and not log.exists()  # hermes never ran
    entry = manifest_of(dest)["stores"][0]
    assert entry["store"] == "hermes-export" and entry["status"] == "partial"
    assert "symlink target outside HOME" in entry["errors"][0]["error"]
    assert b"SENTINEL-HERMES-OUTSIDE-SESSION" not in all_bytes(dest)


def test_hermes_export_gates_a_linked_hermes_directory_like_a_linked_state_db(real, monkeypatch):
    mod, home, tmp = real
    outside = make_hermes_db(tmp / "outside-home", (("SENTINEL-HERMES-PARENT-OUTSIDE", 2),))
    os.symlink(outside.parent, home / ".hermes")
    dest, log, rc = hermes_only(mod, home, tmp, monkeypatch)
    assert rc == 1 and not log.exists()  # hermes never ran
    entry = manifest_of(dest)["stores"][0]
    assert entry["store"] == "hermes-export" and entry["status"] == "partial"
    assert "symlink target outside HOME" in entry["errors"][0]["error"]
    assert b"SENTINEL-HERMES-PARENT-OUTSIDE" not in all_bytes(dest)


def test_hermes_export_follows_a_state_db_link_that_stays_under_home(real, monkeypatch):
    mod, home, tmp = real
    inside = make_hermes_db(home / "data", (("linked-session", 2),))
    (home / ".hermes").mkdir()
    os.symlink(inside, home / ".hermes/state.db")
    dest, log, rc = hermes_only(mod, home, tmp, monkeypatch)
    assert rc == 0
    assert log.read_text().splitlines()[0].endswith(" has-state")  # exported from the scratch copy
    assert (dest / "hermes-export/sessions/linked-session.jsonl").is_file()
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == []


def test_a_db_pruned_between_listing_and_stat_is_an_error_and_the_dry_run_goes_on(real, monkeypatch, capsys):
    mod, home, _ = real
    gone = make_cursor_session(home)
    make_cursor_session(home, sub="chats/hashA/uuid2")
    real_dbs = mod.tree_dbs

    def pruning(store, root):
        dbs = sorted(real_dbs(store, root))
        (gone / "store.db").unlink()  # a session pruned after the listing
        return dbs

    monkeypatch.setattr(mod, "tree_dbs", pruning)
    assert mod.main(["--only", "cursor-chats", "--dry-run", "--json", "--dest", str(home / "o")]) == 1
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["status"] == "partial" and [e["source"] for e in plan["errors"]] == [str(gone / "store.db")]
    assert plan["file_count"] == 2  # the other session's db and meta.json


def test_copy_regular_refuses_a_fifo_without_blocking(real):
    """Adversary round 10 on PR 24: a FIFO swapped in after listing must raise, not hang the run."""
    import threading
    mod, home, tmp = real
    fifo = tmp / "fifo"
    os.mkfifo(fifo)
    done = threading.Event()
    result = {}

    def attempt():
        try:
            mod.copy_regular(fifo, tmp / "out")
        except OSError as exc:
            result["error"] = str(exc)
        done.set()

    threading.Thread(target=attempt, daemon=True).start()
    assert done.wait(5), "copy_regular blocked on the FIFO"
    assert "not a regular file" in result["error"] and not (tmp / "out").exists()


# --- Codex pass 8 on PR 24 (2026-10-20): Muse tui-history.jsonl, dry-run exclusion parity, strict schema check ---

def test_muse_backs_up_tui_history_and_records_it_missing_when_absent(real):
    mod, home, _ = real
    muse = home / ".local/share/muse"
    (muse / "sessions").mkdir(parents=True)
    (muse / "sessions/s1.jsonl").write_text('{"m": 1}\n')
    (muse / "tui-history.jsonl").write_text('{"h": 1}\n')
    dest = home / "out" / "bk"
    assert mod.main(["--only", "muse", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["file_count"] == 2 and entry["status"] == "ok" and entry["missing"] == []
    assert (dest / "muse/tui-history.jsonl").read_text() == '{"h": 1}\n'
    assert (dest / "muse/sessions/s1.jsonl").is_file()
    (muse / "tui-history.jsonl").unlink()
    dest2 = home / "out" / "bk2"
    assert mod.main(["--only", "muse", "--dest", str(dest2)]) == 0
    entry = manifest_of(dest2)["stores"][0]
    assert entry["status"] == "ok" and entry["file_count"] == 1
    assert entry["missing"] == [str(muse / "tui-history.jsonl")]


def test_dry_run_skips_an_excluded_sqlite_tree_db_like_the_real_copy(real, capsys):
    mod, home, _ = real
    db_dir = home / ".cline/data/db"
    make_wal_db(db_dir / "ok.db", ["row"]).close()
    make_wal_db(db_dir / "data.db", ["SENTINEL-EXCLUDED-DB"]).close()  # data.db is an excluded credential name
    assert mod.main(["--only", "cline-db", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cline-db", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert "SENTINEL-EXCLUDED-DB" not in contents(dest)
    assert plan["file_count"] == entry["file_count"] == 1
    assert plan["skipped_count"] == entry["skipped_count"] == 1
    assert plan["skipped"] == entry["skipped"] == [{"path": str(db_dir / "data.db"), "why": "excluded credential path"}]
    ok = db_dir / "ok.db"
    assert plan["bytes"] == ok.stat().st_size + mod.wal_size(ok)  # only the kept db: data.db's bytes are not counted


def test_check_schemas_counts_a_missing_database_and_fails_only_with_strict_stores(real, capsys):
    mod, home, _ = real
    assert mod.main(["--check-schemas", "--only", "grok-db"]) == 0  # ~/.grok/worktrees.db does not exist
    out = capsys.readouterr().out
    assert f"grok-db: {home / '.grok/worktrees.db'}: missing" in out
    assert "0 unexplained credential-looking name(s), 0 symlink problem(s), 1 missing" in out
    assert mod.main(["--check-schemas", "--strict-stores", "--only", "grok-db"]) == 1
    out = capsys.readouterr().out
    assert "0 symlink problem(s), 1 missing" in out
    make_wal_db(home / ".grok/worktrees.db", ["x"]).close()
    assert mod.main(["--check-schemas", "--strict-stores", "--only", "grok-db"]) == 0
    assert "0 symlink problem(s), 0 missing" in capsys.readouterr().out


# --- Codex pass 10 on PR 24 (2026-10-20): absent tree root in --check-schemas, sidecar/single-file/sqlite no-follow ---

def test_check_schemas_counts_an_absent_tree_root_as_missing(real, capsys):
    mod, home, _ = real
    assert not (home / ".cursor/chats").exists()
    assert mod.main(["--check-schemas", "--only", "cursor-chats"]) == 0
    out = capsys.readouterr().out
    assert f"cursor-chats: {home / '.cursor/chats'}: missing" in out
    assert out.strip().splitlines()[-1].endswith("1 missing, 0 unopenable, 0 excluded")
    assert mod.main(["--check-schemas", "--strict-stores", "--only", "cursor-chats"]) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1].endswith("1 missing, 0 unopenable, 0 excluded")
    make_cursor_session(home)
    assert mod.main(["--check-schemas", "--strict-stores", "--only", "cursor-chats"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].endswith("0 missing, 0 unopenable, 0 excluded")


@pytest.mark.parametrize("required", [True, False])
def test_a_sidecar_swapped_for_a_symlink_after_the_check_is_an_error_not_followed(real, monkeypatch, required):
    mod, home, tmp = real
    sdir = make_cursor_session(home)
    marker = tmp / "marker.json"
    marker.write_text("SENTINEL-SWAPPED-SIDECAR-TARGET")
    real_gap = mod.sidecar_gap

    def swapping(side, excluder):
        why = real_gap(side, excluder)  # the check passed: now the sidecar becomes a link
        if not why and side.is_file() and not side.is_symlink():
            side.unlink()
            os.symlink(marker, side)
        return why

    monkeypatch.setattr(mod, "sidecar_gap", swapping)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    assert b"SENTINEL-SWAPPED-SIDECAR-TARGET" not in all_bytes(dest)
    assert not (dest / "cursor-chats/hashA/uuid1/meta.json").exists()
    assert (dest / "cursor-chats/hashA/uuid1/store.db").is_file()  # the db itself is still backed up
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial"
    assert [e["source"] for e in entry["errors"]] == [str(sdir / "meta.json")]
    assert "became a symlink" in entry["errors"][0]["error"]


def test_a_single_file_root_is_copied_through_copy_regular_and_a_swapped_link_is_refused(real, monkeypatch):
    mod, home, tmp = real
    muse = home / ".local/share/muse"
    (muse / "sessions").mkdir(parents=True)
    history = muse / "tui-history.jsonl"
    history.write_text('{"h": 1}\n')
    dest = home / "out" / "bk"
    assert mod.main(["--only", "muse", "--dest", str(dest)]) == 0
    assert (dest / "muse/tui-history.jsonl").read_text() == '{"h": 1}\n'
    assert stat.S_IMODE((dest / "muse/tui-history.jsonl").stat().st_mode) == 0o600
    marker = tmp / "marker.jsonl"
    marker.write_text("SENTINEL-SWAPPED-HISTORY")
    real_copy = mod.copy_regular

    def swapping(src, dst):
        if Path(src) == history:
            history.unlink()  # the root passed every check: now it becomes a link
            os.symlink(marker, history)
        return real_copy(src, dst)

    monkeypatch.setattr(mod, "copy_regular", swapping)
    dest2 = home / "out" / "bk2"
    assert mod.main(["--only", "muse", "--dest", str(dest2)]) == 1
    assert b"SENTINEL-SWAPPED-HISTORY" not in all_bytes(dest2)
    assert not (dest2 / "muse/tui-history.jsonl").exists()
    entry = manifest_of(dest2)["stores"][0]
    assert entry["status"] == "partial" and "became a symlink" in entry["errors"][0]["error"]


def test_a_followed_single_file_root_link_is_copied_from_its_target(real):
    mod, home, _ = real
    muse = home / ".local/share/muse"
    (muse / "sessions").mkdir(parents=True)
    (home / "data").mkdir()
    (home / "data/hist.jsonl").write_text('{"linked": 1}\n')
    os.symlink(home / "data/hist.jsonl", muse / "tui-history.jsonl")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "muse", "--dest", str(dest)]) == 0
    assert (dest / "muse/tui-history.jsonl").read_text() == '{"linked": 1}\n'
    assert manifest_of(dest)["stores"][0]["root_symlinks"][0]["link"] == str(muse / "tui-history.jsonl")


def test_backup_sqlite_refuses_a_source_swapped_for_a_symlink_and_still_copies_a_plain_db(real, tmp_path):
    mod, home, tmp = real
    outside = tmp / "outside.db"
    make_wal_db(outside, ["SENTINEL-SWAPPED-DB-ROW"]).close()
    plain = home / "plain.db"
    make_wal_db(plain, ["plain-row"]).close()
    swapped = home / "swapped.db"
    os.symlink(outside, swapped)
    dst = tmp / "copies" / "swapped.db"
    with pytest.raises(OSError, match="symlink"):
        mod.backup_sqlite(swapped, dst, "anything")
    assert not dst.exists() and not list(dst.parent.glob("*.part*"))
    ok = tmp / "copies" / "plain.db"
    mod.backup_sqlite(plain, ok, "anything")
    assert [r[0] for r in sqlite3.connect(str(ok)).execute("SELECT v FROM t")] == ["plain-row"]


def test_ro_connect_refuses_a_swap_between_the_nofollow_open_and_sqlite_opening_the_path(real, monkeypatch):
    mod, home, tmp = real
    outside = tmp / "outside3.db"
    make_wal_db(outside, ["SENTINEL-RACED-DB-ROW"]).close()
    db = home / "raced.db"
    make_wal_db(db, ["row"]).close()
    real_connect = sqlite3.connect

    def racing(*args, **kw):
        db.unlink()  # after the O_NOFOLLOW open, before SQLite opens the path
        os.symlink(outside, db)
        return real_connect(*args, **kw)

    monkeypatch.setattr(mod.sqlite3, "connect", racing)
    with pytest.raises(OSError, match="symlink or was replaced"):
        mod.ro_connect(db)


def test_a_linked_sqlite_source_is_refused_when_swapped_after_the_check_through_the_store_path(real, monkeypatch):
    mod, home, tmp = real
    outside = tmp / "outside2.db"
    make_wal_db(outside, ["SENTINEL-SWAPPED-STORE-ROW"]).close()
    db = home / ".local/share/crush-acp/crush.db"
    make_wal_db(db, ["live"]).close()
    real_backup = mod.backup_sqlite

    def swapping(src, dst, store_name):
        if Path(src) == db:
            db.unlink()  # the store passed its checks: now the db becomes a link
            os.symlink(outside, db)
        return real_backup(src, dst, store_name)

    monkeypatch.setattr(mod, "backup_sqlite", swapping)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "crush-acp", "--dest", str(dest)]) == 1
    assert b"SENTINEL-SWAPPED-STORE-ROW" not in all_bytes(dest)
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and entry["errors"]


def test_wal_size_ignores_a_symlinked_wal(real):
    mod, home, tmp = real
    db = home / "x.db"
    db.write_bytes(b"")
    big = tmp / "big-wal"
    big.write_bytes(b"x" * 4096)
    os.symlink(big, home / "x.db-wal")
    assert mod.wal_size(db) == 0
    (home / "x.db-wal").unlink()
    (home / "x.db-wal").write_bytes(b"x" * 10)
    assert mod.wal_size(db) == 10


# --- Codex pass 11 on PR 24 (2026-10-20): Crush files, a walk that never trusts a path string, optional sidecars ---

def test_crush_json_is_never_backed_up_and_projects_json_is(real):
    mod, home, _ = real
    crush = home / ".local/share/crush"
    crush.mkdir(parents=True)
    (crush / "crush.json").write_text('{"api_key": "SENTINEL-CRUSH-API-KEY", "refresh_token": "SENTINEL-CRUSH-REFRESH"}')
    (crush / "projects.json").write_text('{"p": 1}')
    (crush / "hyper.json").write_text("SENTINEL-HYPER-LOGIN")
    (crush / "providers.json").write_text("SENTINEL-PROVIDERS")
    dest = home / "out" / "bk"
    assert mod.main(["--only", "crush-files", "--dest", str(dest)]) == 0
    manifest = manifest_of(dest)
    entry = manifest["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and entry["file_count"] == 1
    assert (dest / "crush-files/projects.json").read_text() == '{"p": 1}'
    assert not (dest / "crush-files/crush.json").exists() and not (dest / "crush-files/hyper.json").exists()
    blob = all_bytes(dest)
    for marker in (b"SENTINEL-CRUSH-API-KEY", b"SENTINEL-CRUSH-REFRESH", b"SENTINEL-HYPER-LOGIN", b"SENTINEL-PROVIDERS"):
        assert marker not in blob
    assert "~/.local/share/crush/crush.json" in manifest["exclusions"]["paths"]  # listed with the other credential paths
    assert mod.Excluder(home).path(crush / "crush.json")
    (crush / "projects.json").unlink()
    dest2 = home / "out" / "bk2"
    assert mod.main(["--only", "crush-files", "--dest", str(dest2)]) == 0
    entry = manifest_of(dest2)["stores"][0]
    assert entry["status"] == "missing" and len(entry["missing"]) == 1 and entry["file_count"] == 0


def test_dry_run_records_an_entry_whose_lstat_fails_as_an_error_like_the_copy(real, monkeypatch):
    mod, home, _ = real
    root = home / ".grok/sessions"
    root.mkdir(parents=True)
    (root / "a.jsonl").write_text("x")
    (root / "b.jsonl").write_text("y")
    real_lstat = os.lstat

    def flaky(p, *a, **k):
        if str(p).endswith("a.jsonl"):
            raise PermissionError(13, "denied", str(p))
        return real_lstat(p, *a, **k)

    monkeypatch.setattr(mod.os, "lstat", flaky)
    plan = mod.plan_store(next(s for s in mod.build_stores(home) if s["name"] == "grok"), mod.Excluder(home))
    assert plan["file_count"] == 1 and plan["skipped_count"] == 0
    assert len(plan["errors"]) == 1 and "a.jsonl" in plan["errors"][0]["source"]


def test_check_schemas_never_opens_an_excluded_tree_database(real, capsys, monkeypatch):
    mod, home, _ = real
    db_dir = home / ".cline/data/db"
    make_wal_db(db_dir / "ok.db", ["row"]).close()
    make_wal_db(db_dir / "data.db", ["SENTINEL-EXCLUDED-DB"]).close()
    real_ro = mod.ro_connect
    opened = []
    monkeypatch.setattr(mod, "ro_connect", lambda p, base=None: (opened.append(Path(p).name), real_ro(p, base))[1])
    assert mod.main(["--check-schemas", "--only", "cline-db"]) == 0
    out = capsys.readouterr().out
    assert opened == ["ok.db"]  # data.db is never opened, so no -wal/-shm can appear beside it
    assert f"cline-db: {db_dir / 'data.db'}: skipped (excluded credential path)" in out
    assert out.strip().splitlines()[-1].endswith("0 missing, 0 unopenable, 1 excluded")


def test_check_schemas_never_opens_an_excluded_single_file_database(real, capsys, monkeypatch):
    mod, home, _ = real
    db = home / ".copilot/data.db"  # an excluded credential path
    make_wal_db(db, ["SENTINEL-EXCLUDED-DB"]).close()
    stores = [{"name": "copilot-x", "kind": "sqlite", "files": [db]}]
    monkeypatch.setattr(mod, "ro_connect", lambda *a, **k: pytest.fail("an excluded database was opened"))
    assert mod.check_schemas(stores, mod.Excluder(home)) == 0
    out = capsys.readouterr().out
    assert f"copilot-x: {db}: skipped (excluded credential path)" in out
    assert out.strip().splitlines()[-1].endswith("0 missing, 0 unopenable, 1 excluded")


def test_check_schemas_strict_stores_counts_a_missing_file_store_root(real, capsys):
    mod, home, _ = real
    assert mod.main(["--check-schemas", "--only", "claude", "--strict-stores"]) == 1
    out = capsys.readouterr().out
    assert re.search(r"[1-9]\d* missing", out.strip().splitlines()[-1])
    assert f"claude: {home / '.claude/projects'}: missing" in out
    assert mod.main(["--check-schemas", "--only", "claude"]) == 0  # not strict: reported, exit unchanged
    capsys.readouterr()
    store = next(s for s in mod.build_stores(home) if s["name"] == "claude")
    for label, root in store["roots"]:
        if label in store["file_labels"]:
            root.parent.mkdir(parents=True, exist_ok=True)
            root.write_text("x")
        else:
            root.mkdir(parents=True)
    assert mod.main(["--check-schemas", "--only", "claude", "--strict-stores"]) == 0
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1].endswith("0 missing, 0 unopenable, 0 excluded")
    n = len(store["roots"])
    assert f"claude: {n} of {n} configured path(s) present" in out


def test_check_schemas_gates_a_file_store_root_link_like_the_copy(real, capsys):
    mod, home, tmp = real
    outside = tmp / "outside-dir"
    outside.mkdir()
    (home / ".grok").mkdir()
    os.symlink(outside, home / ".grok/sessions")
    assert mod.main(["--check-schemas", "--only", "grok"]) == 1
    out = capsys.readouterr().out
    assert f"grok: {home / '.grok/sessions'}: symlink refused: symlink target outside HOME" in out


def test_a_subdirectory_swapped_for_a_symlink_after_listing_is_a_store_error_and_nothing_is_copied(real, monkeypatch):
    mod, home, tmp = real
    outside = tmp / "outside-dir"
    outside.mkdir()
    (outside / "secret.jsonl").write_text("SENTINEL-OUTSIDE-DIR")
    sessions = home / ".grok/sessions"
    (sessions / "p1").mkdir(parents=True)
    (sessions / "p1/chat.jsonl").write_text("inside\n")
    (sessions / "p2").mkdir()
    (sessions / "p2/ok.jsonl").write_text("kept\n")
    real_open = mod.open_dir_at

    def swapping(name, parent_fd):
        victim = sessions / name
        if name == "p1" and victim.is_dir() and not victim.is_symlink():  # listed as a directory, now a link
            shutil.rmtree(victim)
            os.symlink(outside, victim)
        return real_open(name, parent_fd)

    monkeypatch.setattr(mod, "open_dir_at", swapping)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "grok", "--dest", str(dest)]) == 1
    assert b"SENTINEL-OUTSIDE-DIR" not in all_bytes(dest)
    assert not (dest / "grok/sessions/p1/secret.jsonl").exists()
    assert (dest / "grok/sessions/p2/ok.jsonl").read_text() == "kept\n"
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial"
    assert [e["source"] for e in entry["errors"]] == [str(sessions / "p1")]
    assert "became a symlink" in entry["errors"][0]["error"]


def test_a_session_directory_swapped_for_a_symlink_before_the_db_open_is_refused_and_not_copied(real, monkeypatch):
    mod, home, tmp = real
    sdir = make_cursor_session(home)
    outside = tmp / "outside-tree" / "uuid1"
    outside.mkdir(parents=True)
    make_wal_db(outside / "store.db", ["SENTINEL-OUTSIDE-DB-ROW"]).close()
    real_open = mod.open_dir_at

    def swapping(name, parent_fd):
        victim = home / ".cursor/chats" / name
        if name == "hashA" and not victim.is_symlink():  # listed and checked as a directory, now a link
            shutil.move(victim, tmp / "moved-hashA")
            os.symlink(outside.parent, victim)
        return real_open(name, parent_fd)

    monkeypatch.setattr(mod, "open_dir_at", swapping)
    dest = home / "out" / "bk"
    assert mod.main(["--only", "cursor-chats", "--dest", str(dest)]) == 1
    assert b"SENTINEL-OUTSIDE-DB-ROW" not in all_bytes(dest)
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "partial" and "symlink" in entry["errors"][0]["error"]
    assert sdir.name == "uuid1"


def test_ro_connect_refuses_a_parent_directory_swapped_for_a_symlink_and_reads_nothing_outside(real, monkeypatch):
    mod, home, tmp = real
    root = home / "root"
    (root / "a").mkdir(parents=True)
    db = root / "a/store.db"
    make_wal_db(db, ["inside"]).close()
    outside = tmp / "outside-parent"
    outside.mkdir()
    make_wal_db(outside / "store.db", ["SENTINEL-OUTSIDE-PARENT-ROW"]).close()
    real_open = mod.open_dir_at

    def swapping(name, parent_fd):
        if name == "a":
            shutil.move(root / "a", tmp / "moved-a")
            os.symlink(outside, root / "a")
        return real_open(name, parent_fd)

    monkeypatch.setattr(mod, "open_dir_at", swapping)
    opened = []
    real_connect = sqlite3.connect
    monkeypatch.setattr(mod.sqlite3, "connect", lambda *a, **k: (opened.append(a), real_connect(*a, **k))[1])
    with pytest.raises(OSError, match="symlink"):
        mod.ro_connect(db, root)
    assert opened == []
    monkeypatch.setattr(mod, "open_dir_at", real_open)
    (root / "a").unlink()
    shutil.move(tmp / "moved-a", root / "a")
    con = mod.ro_connect(db, root)  # the same call without a swap works
    assert [r[0] for r in con.execute("SELECT v FROM t")] == ["inside"]
    con.close()


def test_an_optional_sidecar_that_is_a_symlink_is_a_recorded_skip_and_the_store_stays_ok(real, capsys):
    mod, home, _ = real
    conv = home / ".gemini/antigravity-cli/conversations"
    conv.mkdir(parents=True)
    make_wal_db(conv / "c1.db", ["row"]).close()
    (home / "target.meta").write_text("SENTINEL-META-TARGET")
    os.symlink(home / "target.meta", conv / "c1.meta")
    skipped = [{"path": str(conv / "c1.meta"), "why": "symlink"}]
    assert mod.main(["--only", "antigravity-cli-db", "--dry-run", "--json", "--dest", str(home / "o")]) == 0
    plan = json.loads(capsys.readouterr().out)["stores"][0]
    assert plan["file_count"] == 1 and plan["skipped"] == skipped and plan["errors"] == []
    dest = home / "out" / "bk"
    assert mod.main(["--only", "antigravity-cli-db", "--dest", str(dest)]) == 0
    entry = manifest_of(dest)["stores"][0]
    assert entry["status"] == "ok" and entry["errors"] == [] and entry["skipped"] == skipped
    assert entry["skipped_count"] == 1 and entry["file_count"] == 1
    assert f"skipped {conv / 'c1.meta'}: symlink" in capsys.readouterr().err
    assert (dest / "antigravity-cli-db/conversations/c1.db").is_file()
    assert not (dest / "antigravity-cli-db/conversations/c1.meta").exists()
    assert b"SENTINEL-META-TARGET" not in all_bytes(dest)
