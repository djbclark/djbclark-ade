"""omp history adapter (audit A7-A11, 2026-11-03): every store, file-scoped keys, a header id for odd names, a FIFO and non-object
lines that cannot hang or poison the index, and an exact liveness answer from `omp session lease`."""
import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

SF = Path(__file__).resolve().parents[1] / "skills/session-finder"
STAMP = "2026-11-03T14-30-49-957Z"


def load(name, home, tag="omp"):
    spec = importlib.util.spec_from_file_location(f"t_{tag}_{name}", SF / f"{name}.py")
    with mock.patch.object(Path, "home", return_value=home):
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def session(path, sid, cwd="/w", text="okapi question here"):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "title", "v": 1, "title": "", "pad": " " * 200},
            {"type": "session", "version": 3, "id": sid, "cwd": cwd},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR"):
        monkeypatch.setenv(name, "")
    return tmp_path


def test_every_store_is_indexed_with_file_scoped_keys(home, monkeypatch):
    default = session(home / f".omp/agent/sessions/-src-a/{STAMP}_same-id.jsonl", "same-id")
    profile = session(home / f".omp/profiles/company/agent/sessions/-src-a/{STAMP}_same-id.jsonl", "same-id")
    agent_dir = session(home / f"elsewhere/sessions/-src-a/{STAMP}_agent-id.jsonl", "agent-id")
    flat = session(home / f"flat/{STAMP}_flat-id.jsonl", "flat-id")
    session(home / f"flat/{STAMP}_flat-id/{STAMP}_subagent.jsonl", "subagent-id")  # an artifact directory is not a session store
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(home / "elsewhere"))
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(home / "flat"))
    omp = load("adapters/omp", home)
    rows = {r["key"]: r for r in omp.sessions()}
    assert set(rows) == {f"omp:{p.resolve()}" for p in (default, profile, agent_dir, flat)}
    assert rows[f"omp:{default.resolve()}"]["sid"] == rows[f"omp:{profile.resolve()}"]["sid"] == "same-id"
    assert rows[f"omp:{flat.resolve()}"]["supersedes"] == ["omp:flat-id"]
    assert omp.ROOT_ENV == ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
    cwd, _, msgs = rows[f"omp:{profile.resolve()}"]["load"]()
    assert (cwd, msgs) == ("/w", [("user", "okapi question here")])


def test_resume_names_the_id_only_for_the_default_store_and_a_file_for_the_rest(home):
    default = session(home / f".omp/agent/sessions/-src-a/{STAMP}_default-id.jsonl", "default-id")
    profile = session(home / f".omp/profiles/co mpany/agent/sessions/-src-a/{STAMP}_profile-id.jsonl", "profile-id")
    odd = session(home / ".omp/agent/sessions/-src-a/daily work.jsonl", "daily-id")
    omp = load("adapters/omp", home)
    keys = {r["sid"]: r["key"] for r in omp.sessions()}
    assert omp.RESUME(keys["default-id"], "/w") == "omp --resume=default-id"
    for sid, path in (("profile-id", profile), ("daily-id", odd)):  # no profile or directory variable needed by the caller
        assert shlex.split(omp.RESUME(keys[sid], "/w")) == ["omp", f"--resume={path.resolve()}"]
    assert default.exists() and omp.RESUME("omp:daily", "/w") == ""  # an unscoped legacy key has no safe hint


def test_noncanonical_names_use_the_header_id_and_never_collide(home):
    q = session(home / ".omp/agent/sessions/-q/daily.jsonl", "id-q")
    r = session(home / ".omp/agent/sessions/-r/daily.jsonl", "id-r")
    (home / ".omp/agent/sessions/-s").mkdir()
    (home / ".omp/agent/sessions/-s/no-header.jsonl").write_text('{"type":"message"}\n')
    (home / ".omp/agent/sessions/-s/bad-id.jsonl").write_text(json.dumps({"type": "session", "id": "../x y"}) + "\n")
    (home / ".omp/agent/sessions/-s/array-header.jsonl").write_text("[1,2]\n7\n")
    omp = load("adapters/omp", home)
    rows = list(omp.sessions())
    assert {(x["sid"], x["key"]) for x in rows} == {("id-q", f"omp:{q.resolve()}"), ("id-r", f"omp:{r.resolve()}")}


def test_a_fifo_named_like_a_session_does_not_hang_the_indexer(home):
    bucket = home / ".omp/agent/sessions/-src-a"
    session(bucket / f"{STAMP}_real-id.jsonl", "real-id")
    os.mkfifo(bucket / "trap.jsonl")
    os.mkfifo(bucket / f"{STAMP}_fifo-id.jsonl")  # canonical name: listed stat-only, but its content is never opened
    omp = load("adapters/omp", home)
    out = {}
    worker = threading.Thread(target=lambda: out.update(rows=list(omp.sessions())), daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "listing blocked on a FIFO"
    by_sid = {r["sid"]: r for r in out["rows"]}
    assert "real-id" in by_sid and "trap" not in by_sid
    fifo = by_sid["fifo-id"]
    reader = threading.Thread(target=lambda: out.update(error=_catch(fifo["load"])), daemon=True)
    reader.start()
    reader.join(10)
    assert not reader.is_alive(), "loading blocked on a FIFO"
    assert isinstance(out["error"], OSError)


def _catch(fn):
    try:
        return fn()
    except Exception as e:  # the history core skips a session whose load raises
        return e


def test_non_object_and_deeply_nested_lines_do_not_make_a_session_unsearchable(home):
    path = session(home / f".omp/agent/sessions/-src-a/{STAMP}_odd-lines.jsonl", "odd-lines")
    with path.open("a") as fh:
        fh.write("[1,2]\n7\nnull\n\"text\"\n" + "[" * 50000 + "]" * 50000 + "\n")
        fh.write(json.dumps({"type": "message", "message": {"role": "assistant", "content": [{"type": "text", "text": "kept answer"}]}}) + "\n")
        fh.write(json.dumps({"type": "message", "message": [1]}) + "\n" + json.dumps({"type": "message", "message": {"role": "user", "content": 5}}) + "\n")
        fh.write(json.dumps({"type": "title", "title": 7}) + "\n")
    omp = load("adapters/omp", home)
    (row,) = omp.sessions()
    cwd, title, msgs = row["load"]()
    assert (cwd, msgs) == ("/w", [("user", "okapi question here"), ("assistant", "kept answer")])
    assert title == "okapi question here"


def test_symlinked_session_files_and_buckets_are_skipped(home):
    real = session(home / f"real/{STAMP}_real-id.jsonl", "real-id")
    bucket = home / ".omp/agent/sessions/-src-a"
    bucket.mkdir(parents=True)
    (bucket / f"{STAMP}_link-id.jsonl").symlink_to(real)
    (home / ".omp/agent/sessions/-link").symlink_to(real.parent)
    assert list(load("adapters/omp", home).sessions()) == []


# ---- liveness: a fake `omp` first on PATH --------------------------------------------------------------------------------------

def fake_omp(tmp_path, body):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "omp"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def test_live_among_asks_omp_with_an_argv_list_and_reads_held_and_unknown(home, monkeypatch):
    log = home / "argv.txt"
    bin_dir = fake_omp(home, f'printf "%s\\n" "$@" > {shlex.quote(str(log))}\n'
                             'echo \'{"held":["live-1","not-asked"],"unknown":["maybe-2"]}\'\n')
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    omp = load("adapters/omp", home)
    assert omp.live_among(["live-1", "maybe-2", "gone-3", "--evil; touch pwned", "live-1"]) == ({"live-1"}, {"maybe-2"})
    assert log.read_text().split("\n")[:5] == ["session", "lease", "--json", "--", "live-1"]
    assert "--evil; touch pwned" in log.read_text().split("\n")  # one argv element, never a shell word
    assert not (home / "pwned").exists()


@pytest.mark.parametrize("body", ["echo '{\"held\":\"abc\",\"unknown\":[]}'\n", "echo '{\"held\":[],\"unknown\":\"a-1\"}'\n", "exit 1\n", "echo not json\n", "echo '{\"held\": 3}'\n", "echo '[1]'\n", "echo '{\"held\":[1],\"unknown\":[]}'\n",
                                  "exec sleep 30\n", "echo '{\"held\":[],\"unknown\":[]}'; exit 3\n"])
def test_a_failed_probe_leaves_every_id_unknown_never_ended(home, monkeypatch, body):
    monkeypatch.setenv("PATH", f"{fake_omp(home, body)}:/usr/bin:/bin")
    omp = load("adapters/omp", home)
    monkeypatch.setattr(omp, "LEASE_TIMEOUT", 1)
    assert omp.live_among(["a-1", "b-2"]) == (set(), {"a-1", "b-2"})


def test_a_missing_omp_leaves_every_id_unknown(home, monkeypatch):
    monkeypatch.setenv("PATH", str(home / "empty"))
    assert load("adapters/omp", home).live_among(["a-1"]) == (set(), {"a-1"})


def test_ids_are_probed_in_bounded_batches(home, monkeypatch):
    log = home / "count.txt"
    bin_dir = fake_omp(home, f'echo x >> {shlex.quote(str(log))}\necho \'{{"held":[],"unknown":[]}}\'\n')
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    omp = load("adapters/omp", home)
    monkeypatch.setattr(omp, "LEASE_BATCH", 3)
    assert omp.live_among([f"id-{i}" for i in range(7)]) == (set(), set())
    assert len(log.read_text().split()) == 3


# ---- the history command ---------------------------------------------------------------------------------------------------------

def history(home, bin_dir, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR")}
    env.update(HOME=str(home), SESSION_INDEX_DIR=str(home / "idx"), PATH=f"{bin_dir}:/usr/bin:/bin")
    done = subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), "--json", *args, "--", "okapi"],
                          env=env, capture_output=True, text=True, check=False, timeout=120)
    assert done.returncode == 0, done.stderr
    return {r["sessionId"]: r for r in json.loads(done.stdout)}


def test_history_labels_a_leased_session_live_and_never_ended_when_the_probe_fails(home):
    session(home / f".omp/agent/sessions/-src-a/{STAMP}_live-id.jsonl", "live-id")
    session(home / f".omp/profiles/company/agent/sessions/-src-b/{STAMP}_ended-id.jsonl", "ended-id")
    ok = fake_omp(home, 'echo \'{"held":["live-id"],"unknown":[]}\'\n')
    rows = history(home, ok, "--agent", "omp")
    assert (rows["live-id"]["live"], rows["live-id"]["state"]) == (True, "LIVE")
    assert (rows["ended-id"]["live"], rows["ended-id"]["state"]) == (False, "ended")
    ended_file = (home / f".omp/profiles/company/agent/sessions/-src-b/{STAMP}_ended-id.jsonl").resolve()
    assert shlex.split(rows["ended-id"]["resume"]) == ["omp", f"--resume={ended_file}"]  # a profile store: the file, not the id
    broken = fake_omp(home / "b", "exit 2\n")
    rows = history(home, broken, "--agent", "omp")
    assert {r["state"] for r in rows.values()} == {"LIVE?"}
    assert not any(r["live"] for r in rows.values())
    assert all(r["resume"] for r in rows.values())  # an unknown session still gets its resume hint


def test_the_legacy_filename_keyed_row_is_retired_not_duplicated(home):
    """The first adapter stored a noncanonical `daily.jsonl` as `omp:daily` with sid `daily`; the header id is `id-q`."""
    spec = importlib.util.spec_from_file_location("t_sh_legacy", SF / "session-history.py")
    with mock.patch.dict(os.environ, {"SESSION_INDEX_DIR": str(home / "idx"), "HOME": str(home)}), mock.patch.object(Path, "home", return_value=home):
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
    q = session(home / ".omp/agent/sessions/-q/daily.jsonl", "id-q", cwd="/q")
    omp = load("adapters/omp", home)
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.executescript(sh.SCHEMA)
    db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", ("omp:daily", "omp", "daily", "old", "/q", "old", 0))
    db.execute("INSERT INTO msgs VALUES (?,?,?)", ("omp:daily", "user", "legacy okapi"))
    assert sh.update(db, [omp], {"omp"}) == {"omp": (1, 1)}
    assert list(db.execute("SELECT key, sid FROM files")) == [(f"omp:{q.resolve()}", "id-q")]
    assert db.execute("SELECT count(*) FROM msgs WHERE key='omp:daily'").fetchone() == (0,)
    assert sh.update(db, [omp], {"omp"}) == {"omp": (1, 0)}


def test_a_lease_on_an_id_held_by_two_stores_is_uncertain_for_both_copies(home):
    """`omp session lease` is keyed by session id: with the default store and a profile both holding id `dup-id`, one running omp holds the
    lease and either file could be the one, so both are LIVE? with their resume hints; a unique id keeps the exact LIVE."""
    session(home / f".omp/agent/sessions/-src-a/{STAMP}_dup-id.jsonl", "dup-id")
    session(home / f".omp/profiles/company/agent/sessions/-src-a/{STAMP}_dup-id.jsonl", "dup-id")
    session(home / f".omp/agent/sessions/-src-b/{STAMP}_solo-id.jsonl", "solo-id")
    bin_dir = fake_omp(home, 'echo \'{"held":["dup-id","solo-id"],"unknown":[]}\'\n')
    env = {k: v for k, v in os.environ.items() if k not in ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "CODEX_HOME", "CLAUDE_CONFIG_DIR")}
    env.update(HOME=str(home), SESSION_INDEX_DIR=str(home / "idx"), PATH=f"{bin_dir}:/usr/bin:/bin")
    done = subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), "--json", "--agent", "omp", "--", "okapi"],
                          env=env, capture_output=True, text=True, check=False, timeout=120)
    assert done.returncode == 0, done.stderr
    rows = json.loads(done.stdout)
    dups = [r for r in rows if r["sessionId"] == "dup-id"]
    assert len(dups) == 2
    assert all((r["state"], r["live"]) == ("LIVE?", False) and r["resume"] for r in dups)
    (solo,) = [r for r in rows if r["sessionId"] == "solo-id"]
    assert (solo["state"], solo["live"]) == ("LIVE", True)
