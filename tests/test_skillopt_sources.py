"""bin/skillopt_sources.py: the zcode, agy and crush adapters against synthetic stores.

Each test builds a tiny store in the formats observed on 2026-10-12 (OpenCode-style
SQLite for zcode, per-conversation SQLite with protobuf steps for agy, crush.db plus
projects.json for crush) and checks what is kept and what is dropped.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))  # bin/ is not a package
import skillopt_sources as src  # pyright: ignore[reportMissingImports]

SECRET = "sk-" + "a1b2c3d4e5" * 3


# ── protobuf encoding for agy fixtures ──────────────────────────────────────

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _ld(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def _vi(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _user_step(text: str) -> bytes:
    return _ld(5, _ld(12, b"meta-id")) + _ld(19, _ld(2, text.encode()) + _ld(3, _ld(1, text.encode())))


def _model_step(reply: str, thinking: str, tool: str, args: str) -> bytes:
    call = _ld(1, b"call_1") + _ld(2, tool.encode()) + _ld(3, args.encode())
    return _ld(20, _ld(1, reply.encode()) + _ld(3, thinking.encode()) + _ld(7, call))


def _meta(epoch: int) -> bytes:
    return _ld(1, _vi(1, epoch) + _vi(2, 5))


@pytest.fixture
def tmp(tmp_path):
    return tmp_path


@pytest.fixture(autouse=True)
def _restore_globals():
    """main() sets the process umask and EXCLUDE_PROJECTS; keep tests independent."""
    old = os.umask(0o022)
    os.umask(old)
    yield
    os.umask(old)
    src.EXCLUDE_PROJECTS[:] = []


def test_redaction_and_cap():
    long = "x" * 5000
    assert SECRET not in src.clean(f"key {SECRET} here")
    assert len(src.clean(long)) == src.MAX_CHARS


def test_excluded_roots():
    assert src.excluded("/private/tmp/x")
    assert src.excluded("/var/folders/ab/T/failover-123/work")
    assert src.excluded(str(Path.home() / ".local" / "state" / "bigteam" / "x"))
    assert not src.excluded("/Users/x/src/proj")


def test_to_epoch_naive_is_local():
    assert src.to_epoch("2026-10-12T10:00:00Z") == src.to_epoch("2026-10-12T10:00:00+00:00")
    assert src.to_epoch("") is None and src.to_epoch("garbage") is None


# ── zcode ────────────────────────────────────────────────────────────────────

def _zcode_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
      CREATE TABLE session (id text primary key, project_id text, parent_id text, directory text,
        title text, time_created integer, time_updated integer);
      CREATE TABLE message (id text primary key, session_id text, time_created integer, data text);
      CREATE TABLE part (id text primary key, message_id text, session_id text,
        time_created integer, data text);
    """)
    rows = [("s1", None, "/Users/x/src/proj", 1_791_800_000_000, 1_791_800_600_000),
            ("s2", "s1", "/Users/x/src/proj", 1_791_800_000_000, 1_791_800_600_000),   # child
            ("s3", None, "/private/tmp/scratch", 1_791_800_000_000, 1_791_800_600_000),  # excluded
            ("s4", None, "/Users/x/src/old", 1_600_000_000_000, 1_600_000_100_000)]      # too old
    for sid, parent, d, c, u in rows:
        con.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?)", (sid, "p", parent, d, "t", c, u))
        con.execute("INSERT INTO message VALUES (?,?,?,?)", (f"{sid}-u", sid, c, json.dumps({"role": "user"})))
        con.execute("INSERT INTO message VALUES (?,?,?,?)", (f"{sid}-a", sid, c + 1, json.dumps({"role": "assistant"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)", (f"{sid}-p1", f"{sid}-u", sid, c,
                    json.dumps({"type": "text", "text": f"please fix the bug, token={SECRET}"})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)", (f"{sid}-p2", f"{sid}-u", sid, c,
                    json.dumps({"type": "text", "text": "SYSTEM NOTE", "synthetic": True})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)", (f"{sid}-p3", f"{sid}-a", sid, c + 1,
                    json.dumps({"type": "tool", "tool": "bash", "state": {"output": "TOOL OUTPUT"}})))
        con.execute("INSERT INTO part VALUES (?,?,?,?,?)", (f"{sid}-p4", f"{sid}-a", sid, c + 2,
                    json.dumps({"type": "text", "text": "fixed it"})))
    con.commit()
    con.close()


def test_zcode_adapter(tmp):
    db = tmp / "db.sqlite"
    _zcode_db(db)
    work = tmp / "work"
    work.mkdir()
    out = list(src.harvest_zcode(1_700_000_000, work, db=db))
    assert [d["session_id"] for d in out] == ["s1"]
    d = out[0]
    assert d["project"] == "/Users/x/src/proj"
    assert d["user_prompts"] == ["please fix the bug, token=[REDACTED]"] or SECRET not in json.dumps(d)
    assert d["assistant_finals"] == ["fixed it"] and d["tools_used"] == ["bash"]
    assert "SYSTEM NOTE" not in json.dumps(d) and "TOOL OUTPUT" not in json.dumps(d)
    assert d["started_at"].startswith("2026-") and d["n_user_turns"] == 1


# ── agy ──────────────────────────────────────────────────────────────────────

def test_agy_adapter(tmp, monkeypatch):
    convs = tmp / "antigravity-cli" / "conversations"
    convs.mkdir(parents=True)
    con = sqlite3.connect(convs / "c1.db")
    con.execute("CREATE TABLE steps (idx integer primary key, step_type integer, metadata blob, step_payload blob)")
    con.execute("INSERT INTO steps VALUES (0, 14, ?, ?)", (_meta(1_791_800_000), _user_step("add a test")))
    con.execute("INSERT INTO steps VALUES (1, 15, ?, ?)", (_meta(1_791_800_100), _model_step(
        "test added", "**Thinking** secret plan", "write_to_file", '{"TargetFile": "/x/FILE BODY"}')))
    con.execute("INSERT INTO steps VALUES (2, 90, ?, ?)", (_meta(1_791_800_200), _ld(103, _ld(1, b"EPHEMERAL"))))
    con.commit()
    con.close()
    summ = tmp / "antigravity-cli" / "conversation_summaries.db"
    con = sqlite3.connect(summ)
    con.execute("CREATE TABLE conversation_summaries (conversation_id text, workspace_uris text)")
    con.execute("INSERT INTO conversation_summaries VALUES ('c1', '[\"file:///Users/x/src/agyproj\"]')")
    con.commit()
    con.close()
    monkeypatch.setattr(src, "AGY_DIRS", (convs,))
    monkeypatch.setattr(src, "AGY_SUMMARIES", (summ,))
    work = tmp / "work"
    work.mkdir()
    (d,) = list(src.harvest_agy(None, work))
    assert d["session_id"] == "c1" and d["project"] == "/Users/x/src/agyproj"
    assert d["user_prompts"] == ["add a test"] and d["assistant_finals"] == ["test added"]
    assert d["tools_used"] == ["write_to_file"]
    blob = json.dumps(d)
    assert "Thinking" not in blob and "FILE BODY" not in blob and "EPHEMERAL" not in blob
    assert d["started_at"] == "2026-10-02T03:33:20Z" or d["started_at"].startswith("2026-")
    assert src.store_present("agy")


def test_pb_fields_rejects_garbage():
    assert src.pb_fields(b"\xff\xff\xff") == []
    assert src.pb_text(_ld(1, b"\xff\xfe"), (1,)) == []


# ── crush ────────────────────────────────────────────────────────────────────

def _crush_project(root: Path, name: str) -> dict[str, Any]:
    proj = root / name
    data = proj / ".crush"
    data.mkdir(parents=True)
    con = sqlite3.connect(data / "crush.db")
    con.executescript("""
      CREATE TABLE sessions (id text primary key, parent_session_id text, title text,
        updated_at integer, created_at integer);
      CREATE TABLE messages (id text primary key, session_id text, role text, parts text,
        created_at integer);
    """)
    con.execute("INSERT INTO sessions VALUES ('k1', NULL, 't', 1791800600, 1791800000)")
    con.execute("INSERT INTO sessions VALUES ('k2', 'k1', 't', 1791800600, 1791800000)")
    con.execute("INSERT INTO messages VALUES ('m1','k1','user',?,1791800000)",
                (json.dumps([{"type": "text", "data": {"text": "run the tests"}}]),))
    con.execute("INSERT INTO messages VALUES ('m2','k1','assistant',?,1791800001)", (json.dumps([
        {"type": "reasoning", "data": {"thinking": "PRIVATE THOUGHT"}},
        {"type": "tool_call", "data": {"name": "bash", "input": "INPUT ARGS"}},
        {"type": "text", "data": {"text": "tests pass"}}]),))
    con.execute("INSERT INTO messages VALUES ('m3','k1','tool',?,1791800002)",
                (json.dumps([{"type": "tool_result", "data": {"content": "TOOL RESULT"}}]),))
    con.commit()
    con.close()
    return {"path": str(proj), "data_dir": str(data)}


def test_crush_adapter(tmp, monkeypatch):
    # pytest's tmp dir is under /var/folders, itself an excluded root; keep only /private/tmp here
    monkeypatch.setattr(src, "EXCLUDED_ROOTS", ("/private/tmp/",))
    real = _crush_project(tmp / "home-src", "proj")
    pf = tmp / "projects.json"
    pf.write_text(json.dumps({"projects": [real, {"path": "/private/tmp/bench", "data_dir": "/nope"}]}))
    work = tmp / "work"
    work.mkdir()
    out = list(src.harvest_crush(None, work, projects_files=(pf,)))
    assert len(out) == 1
    d = out[0]
    assert d["project"] == real["path"] and d["user_prompts"] == ["run the tests"]
    assert d["assistant_finals"] == ["tests pass"] and d["tools_used"] == ["bash"]
    blob = json.dumps(d)
    assert "PRIVATE THOUGHT" not in blob and "INPUT ARGS" not in blob and "TOOL RESULT" not in blob
    assert list(src.harvest_crush(1_900_000_000, work, projects_files=(pf,))) == []


def test_cli_stats_and_out(tmp, monkeypatch, capsys):
    db = tmp / "db.sqlite"
    _zcode_db(db)
    monkeypatch.setattr(src, "ZCODE_DB", db)
    monkeypatch.setitem(src.ADAPTERS, "zcode", lambda since, work: src.harvest_zcode(since, work, db=db))
    assert src.main(["zcode", "--stats"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["digests"] == 2  # s1 and s4 (no --since); s2 is a child, s3 excluded
    out = tmp / "digests.json"
    assert src.main(["zcode", "--since", "2026-01-01T00:00:00Z", "--out", str(out)]) == 0
    assert [d["session_id"] for d in json.loads(out.read_text())] == ["s1"]


# ── adversary-review hardening (2026-10-12) ─────────────────────────────────

@pytest.mark.parametrize(("text", "gone"), [
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1rZXk"),
    ("the password is hunter22 ok", "hunter22"),
    ("value aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z here", "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z"),
])
def test_extra_redaction(text, gone):
    assert gone not in src.clean(text)


@pytest.mark.parametrize("keep", ["commit 3671c56a1b2c3d4e5f60718293a4b5c6d7e8f901",
                                  "class ReadWriteLockManagerFactory2",
                                  "android.permission.BIND_ACCESSIBILITY_SERVICE",
                                  "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk"])
def test_redaction_keeps_ordinary_identifiers(keep):
    assert src.clean(keep) == keep


@pytest.mark.parametrize("first", [
    "Complete the following task for the user. Follow the skill and memory rules.",
    "Your working directory for this task is /x\n\nYou are mining a user's past AI-assistant sessions",
    "Score how well the response satisfies the rubric, 0..1.",
    "Reply with exactly: OK",
    "Use your tools to create an empty file named canary in the current working directory",
])
def test_engine_sessions_dropped(first):
    d = {"project": "/Users/x/src/p", "user_prompts": [first], "assistant_finals": ["x"]}
    assert src.engine_session(d) and src.finalize(dict(d)) is None


def test_finalize_redacts_excludes_and_caps(monkeypatch):
    monkeypatch.setattr(src, "EXCLUDE_PROJECTS", ["/Users/x/src/secret"])
    keep = {"project": "/Users/x/src/p", "user_prompts": [f"use {SECRET}", ""],
            "assistant_finals": [str(i) for i in range(9)]}
    d = src.finalize(keep)
    assert d is not None and SECRET not in json.dumps(d)
    assert d["user_prompts"] == ["use [REDACTED]"] or len(d["user_prompts"]) == 1
    assert d["assistant_finals"] == [str(i) for i in range(4, 9)]
    assert src.finalize({"project": "/Users/x/src/secret/sub", "user_prompts": ["hi"]}) is None
    assert src.finalize({"project": "/var/folders/ab/T/failover-1/work", "user_prompts": ["hi"]}) is None


def test_native_mode_needs_the_tool_python(monkeypatch):
    monkeypatch.setattr(src, "have_upstream", False)
    with pytest.raises(SystemExit, match="skillopt tool's Python"):
        src.harvest_native("claude", None, 10)


def test_cli_exclude_project(tmp, monkeypatch, capsys):
    db = tmp / "db.sqlite"
    _zcode_db(db)
    monkeypatch.setitem(src.ADAPTERS, "zcode", lambda since, work: src.harvest_zcode(since, work, db=db))
    assert src.main(["zcode", "--stats", "--exclude-project", "/Users/x/src/proj"]) == 0
    assert json.loads(capsys.readouterr().out)["digests"] == 1  # only s4 (/Users/x/src/old) is left
