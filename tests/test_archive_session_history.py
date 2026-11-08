"""Archive search remains available without clients and never prunes history."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/session-finder/session-history.py"
spec = importlib.util.spec_from_file_location("archive_session_history", SCRIPT)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "history.v2.sqlite"
    db = sqlite3.connect(path)
    db.executescript(history.SCHEMA)
    for agent in ("omp", "opencode", "crush", "zcode"):
        db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?)",
                   (agent + ":one", agent, "one", "old", "/project", agent + " title", 1))
        db.execute("INSERT INTO msgs VALUES(?,?,?)",
                   (agent + ":one", "user", "archive needle retained message"))
    db.commit()
    yield path, db
    db.close()


@pytest.mark.parametrize("agent", ["omp", "opencode", "crush"])
def test_cli_search_with_no_tui_executables_is_read_only(database, agent):
    path, db = database
    before = path.read_bytes()
    env = {**os.environ, "SESSION_INDEX_DIR": str(path.parent), "PATH": ""}
    result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--json",
                             "--agent", agent, "needle"], env=env,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    assert len(rows) == 1 and rows[0]["agent"] == agent
    assert path.read_bytes() == before


def test_empty_refresh_retains_all_seventeen_client_types(database):
    _, db = database
    for number in range(13):
        name = f"legacy{number}"
        db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?)",
                   (name, name, name, "old", "", "", 0))
    db.commit()
    before = db.execute("SELECT * FROM files ORDER BY key").fetchall()
    history.refresh(db, [SimpleNamespace(AGENT="pi", sessions=lambda: iter(()))])
    assert db.execute("SELECT * FROM files ORDER BY key").fetchall() == before
    assert db.execute("SELECT count(DISTINCT agent) FROM files").fetchone()[0] == 17


@pytest.mark.parametrize("empty", [False, True])
def test_failed_or_empty_source_does_not_erase_indexed_text(database, empty):
    _, db = database
    def load():
        if not empty:
            raise ValueError("malformed retained source")
        return "", "", []
    entry = dict(key="omp:one", sid="one", fp="changed", mtime=2, load=load)
    stats = history.refresh(db, [SimpleNamespace(AGENT="omp", sessions=lambda: iter([entry]))])
    assert stats["omp"]["skipped"] == 1
    assert history.search(db, ["needle"], ["omp"], 10)
    assert db.execute("SELECT fp FROM files WHERE key='omp:one'").fetchone()[0] == "old"


def test_changed_source_refreshes_only_its_own_successful_record(database):
    _, db = database
    entry = dict(key="omp:one", sid="one", fp="changed", mtime=2,
                 load=lambda: ("/project", "new title", [("user", "updated source content")]))
    history.refresh(db, [SimpleNamespace(AGENT="omp", sessions=lambda: iter([entry]))])
    assert history.search(db, ["updated"], ["omp"], 10)
    assert not history.search(db, ["needle"], ["omp"], 10)
    assert len(history.search(db, ["needle"], [], 10)) == 3


def test_many_matching_messages_cannot_hide_other_sessions(database):
    _, db = database
    db.executemany("INSERT INTO msgs VALUES(?,?,?)",
                   [("omp:one", "user", "needle needle") for _ in range(250)])
    db.commit()
    assert {r["agent"] for r in history.search(db, ["needle"], [], 4)} == {
        "omp", "opencode", "crush", "zcode"}


def test_query_input_is_data_and_literal_search_still_works(database):
    _, db = database
    assert history.search(db, ["archive needle"], ["crush"], 1, literal=True)
    assert history.search(db, ['"; DROP TABLE files; --'], [], 10) == []
    assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 4


def test_missing_database_search_does_not_create_one(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_INDEX_DIR", str(tmp_path / "absent"))
    assert history.main(["needle"]) == 2
    assert not (tmp_path / "absent").exists()


def test_unsupported_refresh_does_not_mutate_existing_database(database, monkeypatch):
    path, _ = database
    monkeypatch.setenv("SESSION_INDEX_DIR", str(path.parent))
    before = path.read_bytes()
    assert history.main(["--update-only", "--agent", "unknown-client"]) == 2
    assert path.read_bytes() == before


def test_jsonl_adapter_refresh_without_client_executable(tmp_path, monkeypatch):
    adapter = history.load_reader("pi")
    source = tmp_path / "retained-pi"
    source.mkdir()
    sid = "11111111-1111-4111-8111-111111111111"
    log = source / ("2026-11-08T00-00-00_" + sid + ".jsonl")
    log.write_text(json.dumps({"type": "session", "id": sid, "cwd": "/archived"}) + "\n" +
                   json.dumps({"type": "message", "message": {"role": "user",
                                    "content": [{"type": "text", "text": "archived pi canary"}]}}) + "\n")
    monkeypatch.setattr(adapter, "ROOT", source)
    for name in adapter.ROOT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", "")
    db = sqlite3.connect(":memory:")
    db.executescript(history.SCHEMA)
    stats = history.refresh(db, [adapter])
    assert stats["pi"]["updated"] == 1
    assert history.search(db, ["canary"], ["pi"], 1)[0]["sid"] == sid
    db.close()


def test_crush_refresh_uses_retained_project_path_without_registry(database, tmp_path, monkeypatch):
    _, db = database
    source = tmp_path / "retained-project" / "crush.db"
    source.parent.mkdir()
    with sqlite3.connect(source) as native:
        native.execute("CREATE TABLE sessions(id,title,message_count,updated_at)")
        native.execute("CREATE TABLE messages(session_id,role,parts,created_at)")
        native.execute("INSERT INTO sessions VALUES('saved','retained',1,2)")
        native.execute("INSERT INTO messages VALUES(?,?,?,1)",
                       ("saved", "user", json.dumps([{"type": "text", "data": {"text": "crush source canary"}}])))
    before = source.read_bytes()
    key = f"crush:{source}#saved"
    db.execute("INSERT INTO files VALUES(?,?,?,?,?,?,?)",
               (key, "crush", "saved", "old", "/retained-project", "old", 1))
    db.commit()
    reader = history.load_reader("crush")
    monkeypatch.setattr(reader, "DB", tmp_path / "absent-shared.db")
    monkeypatch.setattr(reader, "PROJECTS", ())
    monkeypatch.setenv("PATH", "")
    assert history.refresh(db, [reader])["crush"]["updated"] == 1
    assert history.search(db, ["canary"], ["crush"], 1)[0]["key"] == key
    assert source.read_bytes() == before
