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
    assert proc.returncode == 1  # the handoffs store is missing in the empty home
    data = json.loads(proc.stdout)
    assert data["dry_run"] is True and data["errors"][0]["store"] == "handoffs"
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
    orig = mod.make_ignore

    def racy(run, excluder):  # the links appear after the check: the ignore function does not see them
        inner = orig(run, excluder)
        return lambda directory, names: [n for n in inner(directory, names) if n not in ("racelink", "racedir")]

    monkeypatch.setattr(mod, "make_ignore", racy)
    assert run_main(mod, "--dest", str(dest)) == 0
    assert not list(dest.rglob("racelink")) and not list(dest.rglob("racedir"))
    assert b"SENTINEL-LINK-TARGET" not in all_bytes(dest)
    assert not any(p.is_symlink() for p in dest.rglob("*"))
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    fs_store = next(s for s in manifest["stores"] if s["store"] == "filestore")
    raced = [x for x in fs_store["skipped"] if x["why"].startswith("symlink (appeared")]
    assert {Path(x["path"]).name for x in raced} == {"racelink", "racedir"}
    assert secret.read_text() == "SENTINEL-LINK-TARGET"


def test_help_documents_exit_codes_exclusions_and_the_hermes_override():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    for needle in ("ADE_BACKUP_HERMES", "Exit: 0 clean", "MANIFEST.json", "scrubbed", "--check-schemas", ".part"):
        assert needle in proc.stdout, needle
