"""bin/skillopt_sources.py: the zcode, agy, crush, hermes, grok, muse, cline and
acp_dispatch adapters against synthetic stores.

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


# ── 2026-10-13 adapters: hermes, grok, muse, cline, acp_dispatch ─────────────
# Synthetic stores in the formats observed on this Mac on 2026-10-13. Every store's
# mtime is set a day back so the age guard (AGE_GUARD_S) passes; a store written "now"
# is the session being written and must be skipped.

OLD = 1_791_800_000  # 2026-10-12, about a day before these adapters landed


def _age(*paths: Path, epoch: float = OLD) -> None:
    for p in paths:
        os.utime(p, (epoch, epoch))


def _jsonl(path: Path, rows: list[Any], corrupt: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    if corrupt:
        lines.insert(1, '{"type": "user", "content": "CUT LINE')  # a torn write
    path.write_text("\n".join(lines) + "\n")
    return path


def _digest_blob(d: dict[str, Any]) -> str:
    return json.dumps(d)


@pytest.fixture
def plain_roots(monkeypatch):
    # pytest's tmp dir is under /var/folders, an excluded root; keep only /private/tmp
    monkeypatch.setattr(src, "EXCLUDED_ROOTS", ("/private/tmp/",))


# ── hermes ───────────────────────────────────────────────────────────────────

def _hermes_db(path: Path, now: float) -> None:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
      CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, parent_session_id TEXT,
        started_at REAL NOT NULL, ended_at REAL, cwd TEXT, git_repo_root TEXT, git_branch TEXT,
        last_activity_at REAL);
      CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT, tool_calls TEXT, timestamp REAL NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, compacted INTEGER NOT NULL DEFAULT 0,
        display_kind TEXT, _compressed_summary INTEGER NOT NULL DEFAULT 0);
    """)
    sessions = [
        ("h1", "cli", None, OLD, OLD + 600, "/Users/x/src/proj", "main", OLD + 600),
        ("h2", "subagent", "h1", OLD, OLD + 60, "/Users/x/src/proj", None, OLD + 60),
        ("h3", "telegram", None, OLD - 900, None, None, None, OLD - 800),
        ("c1", "cron", None, OLD - 100, OLD - 90, None, None, OLD - 90),
        ("c2", "cron", None, OLD - 50, OLD - 40, None, None, OLD - 40),      # same prompt, newer
        ("live", "cli", None, now - 60, None, "/Users/x/src/proj", None, now - 5),  # being written
        ("tmp", "oneshot", None, OLD, OLD + 5, "/private/tmp", None, OLD + 5),
        ("old", "cli", None, 1_600_000_000, 1_600_000_100, "/Users/x/src/old", None, 1_600_000_100),
    ]
    for sid, source, parent, start, end, cwd, branch, last in sessions:
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, source, parent, start, end, cwd, None, branch, last))
    rows = [
        ("h1", "user", f"rotate the deploy key, password={SECRET}", None, 0, 1, None, 0),
        ("h1", "user", "[process complete] PROCESS NOTICE", None, 0, 0, "process_complete", 0),
        ("h1", "user", "SUMMARY OF EARLIER TURNS", None, 0, 1, None, 1),
        ("h1", "assistant", "THINKING ONLY", '[{"function": {"name": "terminal"}}]', 0, 1, None, 0),
        ("h1", "tool", "TOOL OUTPUT", None, 0, 1, None, 0),
        ("h1", "user", "now tag the release", None, 1, 0, "steer", 0),
        ("h1", "assistant", "tagged v1.2", '[{"function": {"name": "git_tag", "arguments": "{\\"name\\": \\"x\\"}"', 1, 0, None, 0),
        ("h1", "assistant", "HIDDEN TURN", None, 1, 0, "hidden", 0),
        ("h2", "user", "subagent brief", None, 1, 0, None, 0),
        ("h3", "user", "what is on my calendar", None, 1, 0, None, 0),
        ("h3", "assistant", "two meetings", None, 1, 0, None, 0),
        ("c1", "user", "daily digest prompt", None, 1, 0, None, 0),
        ("c2", "user", "daily digest prompt", None, 1, 0, None, 0),
        ("live", "user", "still typing", None, 1, 0, None, 0),
        ("tmp", "user", "scratch", None, 1, 0, None, 0),
        ("old", "user", "ancient", None, 1, 0, None, 0),
    ]
    for n, (sid, role, content, calls, active, compacted, kind, summary) in enumerate(rows):
        con.execute("INSERT INTO messages (session_id, role, content, tool_calls, timestamp, active, "
                    "compacted, display_kind, _compressed_summary) VALUES (?,?,?,?,?,?,?,?,?)",
                    (sid, role, content, calls, OLD + n, active, compacted, kind, summary))
    con.commit()
    con.close()


def test_hermes_adapter(tmp, plain_roots):
    import hashlib
    import time
    db = tmp / "state.db"
    _hermes_db(db, time.time())
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    out = list(src.harvest_hermes(1_700_000_000, tmp / "work", db=db))
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before  # never written
    by_id = {d["session_id"]: d for d in out}
    # subagent child, the live session, the /private/tmp session, the old one and the
    # older duplicate cron run are gone; the order is newest activity first
    assert list(by_id) == ["h1", "c2", "h3"]
    h1 = by_id["h1"]
    assert h1["project"] == "/Users/x/src/proj" and h1["git_branch"] == "main"
    assert h1["user_prompts"][1] == "now tag the release" and len(h1["user_prompts"]) == 2
    assert SECRET not in h1["user_prompts"][0] and "rotate the deploy key" in h1["user_prompts"][0]
    assert h1["assistant_finals"] == ["THINKING ONLY", "tagged v1.2"]
    assert h1["tools_used"] == ["terminal", "git_tag"]  # the second call is torn JSON
    blob = _digest_blob(h1)
    for gone in ("PROCESS NOTICE", "SUMMARY OF EARLIER", "TOOL OUTPUT", "HIDDEN TURN"):
        assert gone not in blob
    assert by_id["h3"]["project"] == "" and by_id["h3"]["user_prompts"] == ["what is on my calendar"]


def test_hermes_absent_or_garbage(tmp):
    assert list(src.harvest_hermes(None, tmp, db=tmp / "missing.db")) == []
    bad = tmp / "bad.db"
    bad.write_bytes(b"not a sqlite file at all" * 100)
    assert list(src.harvest_hermes(None, tmp, db=bad)) == []


# ── grok ─────────────────────────────────────────────────────────────────────

def _grok_store(root: Path) -> Path:
    cwd_dir = root / "%2FUsers%2Fx%2Fsrc%2Fgrokproj"
    s1 = cwd_dir / "g1"
    _jsonl(s1 / "chat_history.jsonl", [
        {"type": "system", "content": "SYSTEM PROMPT"},
        {"type": "user", "synthetic_reason": "compaction_meta", "content": [{"type": "text", "text": "COMPACTION NOTE"}]},
        {"type": "user", "content": [{"type": "text", "text": f"<user_query>\nship it, token={SECRET}\n</user_query>"}]},
        {"type": "user", "synthetic_reason": "system_reminder", "content": [{"type": "text", "text": "REMINDER"}]},
        {"type": "reasoning", "encrypted_content": "ENCRYPTED", "summary": ["REASONING SUMMARY"]},
        {"type": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "read_file", "arguments": "{\"path\": \"ARGS\"}"}]},
        {"type": "tool_result", "tool_call_id": "1", "content": "TOOL RESULT"},
        {"type": "assistant", "content": "shipped", "tool_calls": []},
    ])
    (s1 / "summary.json").write_text(json.dumps({
        "info": {"id": "g1", "cwd": "/Users/x/src/grokproj"}, "head_branch": "dev",
        "created_at": "2026-10-11T10:00:00Z", "last_active_at": "2026-10-11T11:00:00Z"}))
    _jsonl(cwd_dir / "prompt_history.jsonl", [
        {"session_id": "g1", "prompt": "first prompt before compaction", "is_bash": False},
        {"session_id": "g1", "prompt": "ls -la", "is_bash": True},
        {"session_id": "g1", "prompt": f"ship it, token={SECRET}", "is_bash": False},  # also in chat_history
        {"session_id": "other", "prompt": "not this session", "is_bash": False},
    ], corrupt=False)
    _age(s1 / "chat_history.jsonl", s1 / "summary.json", s1)
    live = cwd_dir / "g2"  # written just now: skipped by the age guard
    _jsonl(live / "chat_history.jsonl", [{"type": "user", "content": "<user_query>live</user_query>"}])
    return cwd_dir


def test_grok_adapter(tmp):
    root = tmp / "sessions"
    _grok_store(root)
    (d,) = list(src.harvest_grok(None, tmp, root=root))
    assert d["session_id"] == "g1" and d["project"] == "/Users/x/src/grokproj" and d["git_branch"] == "dev"
    assert d["user_prompts"][0] == "first prompt before compaction"
    assert d["user_prompts"][1].startswith("ship it") and SECRET not in d["user_prompts"][1]
    assert len(d["user_prompts"]) == 2  # the prompt in both files is kept once
    assert d["assistant_finals"] == ["shipped"] and d["tools_used"] == ["read_file"]
    blob = _digest_blob(d)
    for gone in ("SYSTEM PROMPT", "COMPACTION NOTE", "REMINDER", "ENCRYPTED", "REASONING", "ARGS",
                 "TOOL RESULT", "ls -la", "not this session", "CUT LINE"):
        assert gone not in blob
    assert d["started_at"] == "2026-10-11T10:00:00Z" and d["ended_at"] == "2026-10-11T11:00:00Z"
    assert list(src.harvest_grok(2_000_000_000, tmp, root=root)) == []
    assert list(src.harvest_grok(None, tmp, root=tmp / "absent")) == []


# ── muse ─────────────────────────────────────────────────────────────────────

def _muse_event(ptype: str, payload: dict[str, Any], at: int) -> dict[str, Any]:
    return {"record_type": "event", "payload_type": ptype, "payload": payload, "recorded_at": at,
            "sequence": at, "schema_version": 1, "stream": "s"}


def test_muse_adapter(tmp, plain_roots):
    root = tmp / "sessions"
    sdir = root / "2026" / "10" / "11" / "m1"
    us = OLD * 1_000_000
    f = _jsonl(sdir / "session.jsonl", [
        _muse_event("runtime.session.metadata", {"kind": "x", "record": {"workspace_root": "/Users/x/src/museproj"}}, us),
        _muse_event("runtime.user_intent.accepted", {"surface": "main", "semantic_kind": {"kind": "chat"},
                    "model_messages": [{"content": [{"kind": "text", "text": f"add quota api_key={SECRET}"}]}]}, us + 1),
        _muse_event("runtime.user_intent.accepted", {"surface": "reminder",
                    "model_messages": [{"content": [{"kind": "text", "text": "REMINDER SURFACE"}]}]}, us + 2),
        _muse_event("runtime.session", {"kind": "run", "event": {"kind": "reasoning_committed", "text": "PRIVATE REASONING"}}, us + 3),
        _muse_event("runtime.session", {"kind": "run", "event": {"kind": "assistant_tool_calls_committed",
                    "tool_calls": [{"name": "read_file", "args": "{\"path\": \"ARGS\"}"}]}}, us + 4),
        _muse_event("runtime.session", {"kind": "run", "event": {"kind": "tool_result_batch_committed",
                    "results": [{"output": "TOOL RESULT"}]}}, us + 5),
        _muse_event("runtime.session", {"kind": "run", "event": {"kind": "assistant_message_committed",
                    "text": "quota collector added"}}, us + 60_000_000),
        {"omitted_record": True, "position": 9},
    ])
    child = _jsonl(sdir / "subagent" / "k1" / "session.jsonl", [
        _muse_event("runtime.user_intent.accepted", {"surface": "main",
                    "model_messages": [{"content": [{"kind": "text", "text": "CHILD BRIEF"}]}]}, us)])
    _age(f, child)
    (d,) = list(src.harvest_muse(None, tmp, root=root))
    assert d["session_id"] == "m1" and d["project"] == "/Users/x/src/museproj"
    assert d["user_prompts"][0].startswith("add quota") and SECRET not in d["user_prompts"][0]
    assert d["assistant_finals"] == ["quota collector added"] and d["tools_used"] == ["read_file"]
    blob = _digest_blob(d)
    for gone in ("REMINDER SURFACE", "PRIVATE REASONING", "ARGS", "TOOL RESULT", "CHILD BRIEF"):
        assert gone not in blob
    assert d["started_at"] == src.iso(OLD) and d["ended_at"] == src.iso(OLD + 60)
    os.utime(f)  # touched now: the session being written
    assert list(src.harvest_muse(None, tmp, root=root)) == []


# ── cline ────────────────────────────────────────────────────────────────────

def _cline_session(root: Path, sid: str, meta: dict[str, Any], messages: list[dict[str, Any]]) -> None:
    sdir = root / sid
    sdir.mkdir(parents=True)
    (sdir / f"{sid}.json").write_text(json.dumps({"session_id": sid, **meta}))
    (sdir / f"{sid}.messages.json").write_text(json.dumps({"version": 1, "messages": messages}))
    _age(sdir / f"{sid}.json", sdir / f"{sid}.messages.json")


def test_cline_adapter(tmp, plain_roots):
    root = tmp / "sessions"
    _cline_session(root, "c1", {"cwd": "/Users/x/src/clineproj", "is_subagent": False,
                                "started_at": "2026-10-11T10:00:00.000Z", "ended_at": "2026-10-11T10:30:00.000Z"}, [
        {"role": "user", "content": [{"type": "text", "text": f'<user_input mode="act">fix lint, secret={SECRET}</user_input>'}]},
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "PRIVATE THOUGHT"},
                                          {"type": "tool_use", "id": "t", "name": "run_commands", "input": {"cmd": "INPUT ARGS"}}]},
        {"role": "user", "content": [{"type": "tool_result", "content": "TOOL RESULT"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "lint is clean"}]},
    ])
    _cline_session(root, "c2", {"cwd": "/Users/x/src/clineproj", "is_subagent": True},
                   [{"role": "user", "content": "SUBAGENT TASK"}])
    _cline_session(root, "c3", {"cwd": "/private/tmp/rulestest"}, [{"role": "user", "content": "bench"}])
    (root / "broken").mkdir()
    (root / "broken" / "broken.messages.json").write_text("{not json")
    _age(root / "broken" / "broken.messages.json")
    (d,) = list(src.harvest_cline(None, tmp, root=root))
    assert d["session_id"] == "c1" and d["project"] == "/Users/x/src/clineproj"
    assert d["user_prompts"][0].startswith("fix lint") and "user_input" not in d["user_prompts"][0]
    assert SECRET not in d["user_prompts"][0]
    assert d["assistant_finals"] == ["lint is clean"] and d["tools_used"] == ["run_commands"]
    blob = _digest_blob(d)
    for gone in ("PRIVATE THOUGHT", "INPUT ARGS", "TOOL RESULT", "SUBAGENT TASK"):
        assert gone not in blob
    assert d["started_at"] == "2026-10-11T10:00:00Z"


# ── acp_dispatch ─────────────────────────────────────────────────────────────

def test_acp_dispatch_adapter(tmp, plain_roots):
    import time
    root = tmp / "bigteam"
    task = root / "slice-a"
    (task / "jobs").mkdir(parents=True)
    report = task / "slice-a-report.md"
    report.write_text(f"STATUS: done\nfixed the parser; key AKIA{'A1B2C3D4E5F6G7H8'}\nDONE\n")
    log = _jsonl(task / "slice-a.jsonl", [
        {"t": 1, "kind": "initialize", "data": {}},
        {"t": 2, "kind": "update", "data": {"sessionUpdate": "tool_call", "title": "skill", "rawInput": {}}},
        {"t": 3, "kind": "update", "data": {"sessionUpdate": "tool_call_update", "title": "skill", "rawInput": {"id": "RAW INPUT"}}},
        {"t": 4, "kind": "update", "data": {"sessionUpdate": "tool_call", "title": "Read /x/FILE", "kind": "read"}},
        {"t": 5, "kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {"text": "CHUNK"}}},
    ])
    done = {"task": "slice-a", "name": "slice-a", "agent": "opencode", "dir": "/Users/x/src/proj",
            "prompt": "# Slice: fix the parser", "report": str(report), "log": str(log),
            "status": "done", "exit": 0, "started": OLD, "finished": OLD + 600, "session_id": "ses_1"}
    (task / "jobs" / "slice-a.json").write_text(json.dumps(done))
    running = {**done, "name": "slice-b", "status": "running", "finished": None, "started": time.time() - 3600,
               "timeout": 21600, "session_id": "ses_2"}
    (task / "jobs" / "slice-b.json").write_text(json.dumps(running))
    brief = task / "slice-c-brief.md"
    brief.write_text("# Slice: from the brief file")
    final = task / "slice-c-final.txt"
    final.write_text("final text answer")
    only_brief = {"task": "slice-a", "name": "slice-c", "dir": "/Users/x/src/proj", "brief": str(brief),
                  "final": str(final), "report": str(task / "missing.md"), "status": "no-report",
                  "started": OLD - 100, "finished": OLD - 50}
    (task / "jobs" / "slice-c.json").write_text(json.dumps(only_brief))
    (task / "jobs" / "slice-d.json").write_text("{torn")
    for p in (task / "jobs").iterdir():
        _age(p)
    _age(task / "jobs" / "slice-a.json", epoch=OLD + 600)  # newest record first
    out = list(src.harvest_acp_dispatch(None, tmp, root=root))
    assert [d["session_id"] for d in out] == ["ses_1", "slice-a/slice-c"]
    d = out[0]
    assert d["project"] == "/Users/x/src/proj" and d["user_prompts"] == ["# Slice: fix the parser"]
    assert "fixed the parser" in d["assistant_finals"][0] and "AKIAA1B2C3D4E5F6G7H8" not in _digest_blob(d)
    assert d["tools_used"] == ["skill", "Read"]
    assert "RAW INPUT" not in _digest_blob(d) and "CHUNK" not in _digest_blob(d)
    assert out[1]["user_prompts"] == ["# Slice: from the brief file"]
    assert out[1]["assistant_finals"] == ["final text answer"]
    assert list(src.harvest_acp_dispatch(OLD + 1000, tmp, root=root)) == []


# ── bounds, presence, CLI ────────────────────────────────────────────────────

def test_read_bounded_keeps_head_and_tail(tmp):
    f = tmp / "big.jsonl"
    rows = [json.dumps({"n": i, "pad": "x" * 50}) for i in range(1000)]
    f.write_text("\n".join(rows) + "\n")
    got = [r["n"] for r in src.jsonl_records(f, cap=4096)]
    assert got[0] == 0 and got[-1] == 999 and len(got) < 100  # whole lines only, middle dropped
    assert src.read_bounded(tmp / "missing") == ""
    assert src.load_json(f, cap=10) is None


@pytest.mark.parametrize("name", ["hermes", "grok", "muse", "cline", "acp_dispatch"])
def test_new_sources_registered_and_absent_store_is_empty(tmp, monkeypatch, capsys, name):
    for const in ("HERMES_DB", "GROK_SESSIONS", "MUSE_SESSIONS", "CLINE_SESSIONS", "BIGTEAM_STATE"):
        monkeypatch.setattr(src, const, tmp / "absent" / const)
    assert name in src.ADAPTERS and not src.store_present(name)
    assert src.main([name, "--stats"]) == 0
    assert json.loads(capsys.readouterr().out)["digests"] == 0


def test_store_present_new_sources(tmp, monkeypatch):
    root = tmp / "grok"
    _grok_store(root)
    monkeypatch.setattr(src, "GROK_SESSIONS", root)
    assert src.store_present("grok")
    db = tmp / "state.db"
    sqlite3.connect(db).close()
    db.write_bytes(b"x")
    monkeypatch.setattr(src, "HERMES_DB", db)
    assert src.store_present("hermes")
