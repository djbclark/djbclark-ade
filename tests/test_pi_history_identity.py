"""Pi history identity/resume regressions; only synthetic stores and fleet rows."""
import importlib.util
import json
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SF = Path(__file__).resolve().parents[1] / "skills/session-finder"
sys.path.insert(0, str(SF))
from nativeid import history_identity, native_id  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location("pi_test_" + name.replace("/", "_"), SF / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    root = tmp_path / "custom 'root; $(not-executed)"
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(root))
    paths = []
    for project in ("a", "b"):
        path = root / project / "timestamp_daily_work.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(row) for row in [
            {"type": "session", "id": "daily_work", "cwd": str(tmp_path / project)},
            {"type": "message", "message": {"role": "user", "content": f"okapi project {project}"}},
        ]) + "\n")
        paths.append(path)
    return load("session-history"), load("adapters/pi"), paths


def search(sh, monkeypatch, capsys, rows):
    monkeypatch.setitem(sys.modules, "fleet", SimpleNamespace(sessions=lambda: rows))
    monkeypatch.setattr(sys, "argv", ["session-history.py", "--agent", "pi", "--json", "okapi"])
    assert sh.main() == 0
    return json.loads(capsys.readouterr().out)


def test_same_custom_id_indexes_both_files_and_retires_legacy_key(store):
    sh, adapter, paths = store
    db = sqlite3.connect(":memory:")
    db.executescript(sh.SCHEMA)
    db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", ("pi:daily_work", "pi", "daily_work", "old", str(paths[0].parents[2] / "a"), "old", 0))
    db.execute("INSERT INTO msgs VALUES (?,?,?)", ("pi:daily_work", "user", "legacy okapi"))
    assert sh.update(db, [adapter], {"pi"}) == {"pi": (2, 2)}
    assert set(db.execute("SELECT key,sid FROM files")) == {(f"pi:{p.resolve()}", "daily_work") for p in paths}
    assert db.execute("SELECT count(*) FROM msgs WHERE key='pi:daily_work'").fetchone() == (0,)
    assert sh.update(db, [adapter], {"pi"}) == {"pi": (2, 0)}
    assert db.execute("SELECT count(*) FROM msgs WHERE msgs MATCH 'okapi'").fetchone() == (2,)


def test_legacy_orphan_in_another_project_is_preserved(store):
    sh, adapter, _ = store
    db = sqlite3.connect(":memory:")
    db.executescript(sh.SCHEMA)
    db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", ("pi:daily_work", "pi", "daily_work", "old", "/orphan", "old", 0))
    db.execute("INSERT INTO msgs VALUES (?,?,?)", ("pi:daily_work", "user", "orphan okapi"))
    sh.update(db, [adapter], {"pi"})
    assert db.execute("SELECT count(*) FROM files").fetchone() == (3,)
    assert db.execute("SELECT count(*) FROM msgs WHERE key='pi:daily_work'").fetchone() == (1,)


@pytest.mark.parametrize("kind", ["file", "id", "unscoped", "other-file"])
def test_live_match_is_file_or_project_scoped_and_resume_is_exact(store, monkeypatch, capsys, kind):
    sh, adapter, paths = store
    cwd = str(paths[0].parents[2] / "a")
    sid = str(paths[0]) if kind == "file" else "daily_work"
    if kind == "other-file":
        sid = str(paths[0].with_name("another_daily_work.jsonl"))
    rows = [{"agent": "pi", "status": "idle", "sid": sid, "cwd": "" if kind == "unscoped" else cwd}]
    hits = search(sh, monkeypatch, capsys, rows)
    assert len(hits) == 2
    for hit in hits:
        path = Path(hit["sessionKey"][3:])
        assert hit["sessionId"] == "daily_work"
        assert hit["live"] == (path == paths[0] and kind == "file")
        if kind == "id":  # ID+cwd cannot name a storage root: both roots stay uncertain, never exact LIVE
            assert hit["state"] in {"LIVE?", "ended"} and hit["state"] != "LIVE"
        # No caller cwd, session-root environment or shell metacharacters can change this target.
        assert shlex.split(hit["resume"]) == ["pi", "--session", str(path)]
    assert adapter.RESUME("pi:daily_work", cwd) == ""  # orphan legacy key is not safe to resume
    assert sh.resume_hint(adapter.RESUME, "pi:/bad\npath.jsonl", cwd) == ""


def test_flat_custom_session_root_is_supported(store):
    _, adapter, paths = store
    direct = paths[0].parent.parent / "timestamp_flat_id.jsonl"
    direct.write_text('{"type":"session","id":"flat_id"}\n')
    assert {s["sid"] for s in adapter.sessions()} == {"daily_work", "flat_id"}


@pytest.mark.parametrize("value,want", [
    ("/sessions/project/timestamp_custom_id_with_underscores.jsonl", "custom_id_with_underscores"),
    ("/omp/project/2026-11-03T00-00-00Z_uuid-123.jsonl", "uuid-123"),
    ("cron_17af0eeb3949_20260813_075144", "cron_17af0eeb3949_20260813_075144"),
    ("daily_work", "daily_work"),
])
def test_native_filename_keeps_full_id(value, want):
    assert native_id(value) == want


def test_pi_different_roots_same_project_do_not_match():
    assert history_identity("pi", "/one/timestamp_daily_work.jsonl", "/project") != history_identity(
        "pi", "/two/timestamp_daily_work.jsonl", "/project")


def test_session_find_does_not_hide_another_projects_custom_id(tmp_path, monkeypatch, capsys):
    import claude_identity
    monkeypatch.setattr(claude_identity, "own_session_id", lambda: None)
    monkeypatch.setenv("SESSION_INDEX_DIR", str(tmp_path))
    sf = load("session-find")
    monkeypatch.setattr(sf, "live_sessions", lambda: [])
    row = {"agent": "pi", "id": "pid123", "sid": "daily_work", "status": "idle", "cwd": "/a",
           "title": "okapi", "where": "", "focus": "", "reach": "native"}
    monkeypatch.setitem(sys.modules, "fleet", SimpleNamespace(sessions=lambda: [row]))
    hits = [{"agent": "pi", "sessionId": "daily_work", "cwd": "/b", "live": False,
             "title": "okapi", "snippet": "okapi b", "resume": "pi --session /b/file"}]
    monkeypatch.setattr(sf.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, json.dumps(hits), ""))
    monkeypatch.setattr(sys, "argv", ["session-find.py", "--all", "--json", "okapi"])
    assert sf.main() == 0
    got = json.loads(capsys.readouterr().out)
    assert {r["cwd"] for r in got} == {"/a", "/b"}
    assert next(r for r in got if r["cwd"] == "/b")["live"] is False


def test_session_find_all_keeps_other_root_history_for_live_id(tmp_path, monkeypatch, capsys):
    import claude_identity
    monkeypatch.setattr(claude_identity, "own_session_id", lambda: None)
    monkeypatch.setenv("SESSION_INDEX_DIR", str(tmp_path))
    sf = load("session-find")
    monkeypatch.setattr(sf, "live_sessions", lambda: [])
    row = {"agent": "pi", "id": "pid1", "sid": "daily_work", "status": "idle", "cwd": "/project",
           "title": "okapi", "where": "", "focus": "", "reach": "native"}
    monkeypatch.setitem(sys.modules, "fleet", SimpleNamespace(sessions=lambda: [row]))
    hits = [{"agent": "pi", "sessionId": "daily_work", "sessionKey": "pi:/root-b/timestamp_daily_work.jsonl",
             "cwd": "/project", "live": False, "title": "okapi", "snippet": "okapi b", "resume": "x"}]
    monkeypatch.setattr(sf.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, json.dumps(hits), ""))
    monkeypatch.setattr(sys, "argv", ["session-find.py", "--all", "--json", "okapi"])
    assert sf.main() == 0
    got = json.loads(capsys.readouterr().out)
    assert any(r.get("resume") == "x" and r["live"] is False for r in got)


def test_pi_target_keeps_flag_kind(monkeypatch):
    import fleet
    assert fleet._pi_sid(["pi", "--session-id", "daily.jsonl"]) == "daily.jsonl"
    assert fleet._pi_sid(["pi", "--session", "/abs/t_x.jsonl"]) == "/abs/t_x.jsonl"
    assert fleet._pi_sid(["pi", "--session", "abc12345"]) == "abc12345"
    # relative files depend on the launch cwd, which a scan cannot prove
    assert fleet._pi_sid(["pi", "--session", "sessions/t_x.jsonl"]) is None
    assert fleet._pi_sid(["pi", "--session", "t_x.jsonl"]) is None


def test_proc_scan_never_fabricates_file_identity(monkeypatch):
    import fleet
    seen = {}
    for argv, want in [("--session-id daily.jsonl", "daily.jsonl"), ("--session sessions/t_x.jsonl", None)]:
        line = f"12345 1 Tue Nov 3 12:00:00 2026 node /tmp/pi {argv}"
        monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: "/dev/pts/4")
        monkeypatch.setattr(fleet, "run", lambda *a, **kw: (0, line))
        monkeypatch.setattr(fleet, "_where", SimpleNamespace(env_of=lambda pid: {}, lookup=lambda *a: {"cwd": "/project"}))
        rows = fleet._proc_scan(set(), set(), {})
        assert rows[0]["sid"] == want


def test_relative_pi_path_is_not_a_file_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert history_identity("pi", "sessions/t_x.jsonl", "/p")[1] == "id"
    assert history_identity("pi", "x", "/p", "pi:rel/t_x.jsonl")[1] == "id"


def test_pi_sid_follows_pi_parser(tmp_path):
    import fleet
    assert fleet._pi_sid(["pi", "--session", "aaaa", "--session", "bbbb"]) == "bbbb"
    assert fleet._pi_sid(["pi", "--session=bbbb"]) is None
    assert fleet._pi_sid(["pi", "--session", "bbbb", "--no-session"]) is None
    assert fleet._pi_sid(["pi", "--fork", "x", "--session", "bbbb"]) is None


def test_lossy_ps_path_with_spaces_is_not_fabricated(tmp_path):
    import fleet
    real = tmp_path / "My Docs" / "t_x.jsonl"
    real.parent.mkdir()
    real.write_text("{}")
    truncated = ["pi", "--session", str(tmp_path / "My")]
    assert fleet._pi_sid(truncated, lossy=True) is None
    assert fleet._pi_sid(["pi", "--session", str(real)], lossy=True) == str(real)
    assert fleet._pi_sid(["pi", "--session", str(tmp_path / "gone.jsonl")], lossy=True) is None
    assert fleet._pi_sid(["pi", "--session", str(tmp_path / "gone.jsonl")]) == str(tmp_path / "gone.jsonl")


def test_flat_store_under_symlinked_root_is_indexed(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "timestamp_flat_id.jsonl").write_text('{"type":"session","id":"flat_id"}\n')
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(link))
    assert [s["sid"] for s in load("adapters/pi").sessions()] == ["flat_id"]


def test_noncanonical_filename_uses_header_id_and_tolerates_bad_headers(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "daily.jsonl").write_text('{"type":"session","id":"native_id","cwd":"/w"}\n'
                                      '{"type":"message","message":{"role":"user","content":"okapi"}}\n')
    (root / "malformed.jsonl").write_text("not json\n")
    (root / "nonsession.jsonl").write_text('{"type":"message","id":"x1y2z3"}\n')
    (root / "badid.jsonl").write_text('{"type":"session","id":"../escape"}\n')
    (root / "huge.jsonl").write_text('{"type":"session","id":"huge_id","pad":"' + "a" * 70000 + '"}\n')
    (root / "empty.jsonl").write_text("")
    (root / "linked.jsonl").symlink_to(root / "daily.jsonl")
    (root / "timestamp_canonical.jsonl").write_text("garbage never read\n")
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(root))
    rows = {r["sid"]: r for r in load("adapters/pi").sessions()}
    assert set(rows) == {"native_id", "canonical"}
    assert rows["native_id"]["key"] == f"pi:{(root / 'daily.jsonl').resolve()}"
    assert rows["native_id"]["load"]()[0] == "/w"
