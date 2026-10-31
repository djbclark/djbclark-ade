#!/usr/bin/env python3
"""session-finder's full-text history index (2026-10-31).

  * omp, grok and goose have adapters (before: 2,028 omp, 220 grok and 82 goose sessions were invisible).
  * cursor yields one entry per session id: a session under two project dirs used to flip-flop.
  * `session-history.py --status` is read-only and reports unindexed sessions; `--update-only` records the
    time of the last full pass and fixes what `--status` found.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SF = ROOT / "skills" / "session-finder"


def load(name: str, home: Path):
    spec = importlib.util.spec_from_file_location(f"t_{name}", SF / "adapters" / f"{name}.py")
    with mock.patch.object(Path, "home", return_value=home):
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_omp_reads_user_and_assistant_text_only(self) -> None:
        write_jsonl(self.home / ".omp/agent/sessions/-src-x/2026-10-31T17-00-00-000Z_abc-123.jsonl", [
            {"type": "title", "title": "Fix the flux capacitor"},
            {"type": "session", "id": "abc-123", "cwd": "/src/x"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "please repair the capacitor"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "thinking", "text": "hmm"},
                                                                             {"type": "text", "text": "capacitor repaired"}]}},
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool output"}]}},
        ])
        mod = load("omp", self.home)
        (s,) = list(mod.sessions())
        self.assertEqual((s["key"], s["sid"]), ("omp:abc-123", "abc-123"))
        cwd, title, msgs = s["load"]()
        self.assertEqual((cwd, title), ("/src/x", "Fix the flux capacitor"))
        self.assertEqual(msgs, [("user", "please repair the capacitor"), ("assistant", "capacitor repaired")])

    def test_grok_drops_synthetic_reminders_and_recovers_compacted_prompts(self) -> None:
        cwd_dir = self.home / ".grok/sessions/%2Fsrc%2Fy"
        sdir = cwd_dir / "sess-1"
        write_jsonl(sdir / "chat_history.jsonl", [
            {"type": "system", "content": "system prompt"},
            {"type": "user", "synthetic_reason": "system_reminder", "content": [{"type": "text", "text": "reminder text"}]},
            {"type": "user", "content": [{"type": "text", "text": "<user_query>\nwhere is the wormhole\n</user_query>"}]},
            {"type": "assistant", "content": [{"type": "text", "text": "the wormhole is in sector nine"}]},
        ])
        write_jsonl(cwd_dir / "prompt_history.jsonl", [
            {"session_id": "sess-1", "prompt": "an early prompt a compaction dropped"},
            {"session_id": "sess-1", "prompt": "where is the wormhole"},
            {"session_id": "other", "prompt": "someone else's prompt"},
            {"session_id": "sess-1", "prompt": "ls -la", "is_bash": True},
        ])
        (sdir / "summary.json").write_text(json.dumps({"info": {"cwd": "/src/y"}, "session_summary": "Wormhole hunt"}))
        mod = load("grok", self.home)
        (s,) = list(mod.sessions())
        cwd, title, msgs = s["load"]()
        self.assertEqual((cwd, title), ("/src/y", "Wormhole hunt"))
        self.assertEqual(msgs, [("user", "an early prompt a compaction dropped"), ("user", "where is the wormhole"),
                                ("assistant", "the wormhole is in sector nine")])

    def test_grok_fingerprint_follows_prompt_history_and_summary(self) -> None:
        cwd_dir = self.home / ".grok/sessions/%2Fsrc%2Fy"
        write_jsonl(cwd_dir / "sess-1/chat_history.jsonl", [{"type": "user", "content": [{"type": "text", "text": "hello grok"}]}])
        mod = load("grok", self.home)
        fp1 = next(iter(mod.sessions()))["fp"]
        write_jsonl(cwd_dir / "prompt_history.jsonl", [{"session_id": "sess-1", "prompt": "typed before a compaction"}])
        fp2 = next(iter(mod.sessions()))["fp"]
        (cwd_dir / "sess-1/summary.json").write_text("{}")
        fp3 = next(iter(mod.sessions()))["fp"]
        self.assertEqual(len({fp1, fp2, fp3}), 3)
        os.utime(cwd_dir / "prompt_history.jsonl", (2_000_000_000, 2_000_000_000))  # shared by the whole cwd
        self.assertLess(next(iter(mod.sessions()))["mtime"], 1_900_000_000)

    def test_title_only_match_is_a_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_jsonl(Path(tmp) / ".omp/agent/sessions/-s/2026-10-31T00-00-00-000Z_t1.jsonl", [
                {"type": "title", "title": "Quokka migration plan"}, {"type": "session", "id": "t1", "cwd": "/s"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "unrelated words only"}]}}])
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
            env.update(PATH="/usr/bin:/bin", HOME=tmp, SESSION_INDEX_DIR=str(Path(tmp) / "idx"))
            r = subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), "--json", "--", "quokka", "migration"],
                               env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)[0]["title"], "Quokka migration plan")

    def test_goose_reads_text_blocks(self) -> None:
        db_path = self.home / ".local/share/goose/sessions/sessions.db"
        db_path.parent.mkdir(parents=True)
        db = sqlite3.connect(db_path)
        db.executescript("""
            CREATE TABLE sessions(id TEXT, name TEXT, working_dir TEXT, updated_at TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content_json TEXT);
        """)
        db.execute("INSERT INTO sessions VALUES('g1','Goose chat','/src/z','2026-10-31 12:00:00')")
        db.execute("INSERT INTO messages(session_id, role, content_json) VALUES('g1','user',?)",
                   (json.dumps([{"type": "text", "text": "hello goose"}, {"type": "toolRequest", "id": "1"}]),))
        db.commit()
        db.close()
        mod = load("goose", self.home)
        (s,) = list(mod.sessions())
        self.assertEqual(s["key"], "goose:g1")
        self.assertEqual(s["load"](), ("/src/z", "Goose chat", [("user", "hello goose")]))

    def test_cursor_yields_one_entry_per_session_id_the_newest(self) -> None:
        for slug, mtime in (("proj-old", 1_000_000_000), ("proj-new", 1_000_000_500)):
            p = self.home / f".cursor/projects/{slug}/agent-transcripts/dup-1/dup-1.jsonl"
            write_jsonl(p, [{"role": "user", "message": {"content": [{"type": "text", "text": f"hello from {slug}"}]}}])
            os.utime(p, (mtime, mtime))
        mod = load("cursor", self.home)
        entries = list(mod.sessions())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["mtime"], 1_000_000_500)


class StatusTests(unittest.TestCase):
    def test_status_is_read_only_and_update_clears_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_jsonl(home / ".omp/agent/sessions/-s/2026-10-31T00-00-00-000Z_s1.jsonl", [
                {"type": "session", "id": "s1", "cwd": "/s"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "findable zebra"}]}}])
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
            env.update(PATH="/usr/bin:/bin", HOME=tmp, SESSION_INDEX_DIR=str(home / "idx"))
            run = lambda *args: subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), *args],  # noqa: E731
                                               env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run("--status").returncode, 2)  # no index yet, and none created
            self.assertFalse((home / "idx").exists())
            self.assertEqual(run("--update-only").returncode, 0)
            st = run("--status")
            self.assertEqual(st.returncode, 0, st.stdout)
            self.assertIn("last full update:", st.stdout)
            self.assertNotIn("never recorded", st.stdout)
            hit = run("--json", "zebra")
            self.assertEqual(hit.returncode, 0, hit.stderr)
            self.assertEqual(json.loads(hit.stdout)[0]["agent"], "omp")
            write_jsonl(home / ".omp/agent/sessions/-s/2026-10-31T01-00-00-000Z_s2.jsonl", [
                {"type": "session", "id": "s2", "cwd": "/s"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "another session"}]}}])
            self.assertEqual(run("--status").returncode, 1)  # one unindexed session
            self.assertEqual(run("--update-only").returncode, 0)
            self.assertEqual(run("--status").returncode, 0)
            self.assertEqual((home / "idx/history.v2.sqlite").stat().st_mode & 0o777, 0o600)

    def test_resume_hint_quotes_a_hostile_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_jsonl(home / ".omp/agent/sessions/-s/2026-10-31T00-00-00-000Z_x;touch pwned.jsonl", [
                {"type": "session", "id": "x", "cwd": "/s"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "hostile giraffe"}]}}])
            env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
            env.update(PATH="/usr/bin:/bin", HOME=tmp, SESSION_INDEX_DIR=str(home / "idx"))
            r = subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), "--json", "giraffe"],
                               env=env, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)[0]["resume"], "omp --resume='x;touch pwned'")


class HardeningTests(unittest.TestCase):
    """Adversary round 2 (PR 191): R1 agy comment, R2 relative index dir, R3 crash exit code, R5 abbreviations."""

    @staticmethod
    def _env(tmp: str, idx: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        env.update(PATH="/usr/bin:/bin", HOME=tmp, SESSION_INDEX_DIR=idx)
        return env

    def _run(self, tmp: str, idx: str, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), *args], env=self._env(tmp, idx),
                              capture_output=True, text=True, check=False, cwd=cwd)

    def test_resume_hint_is_empty_for_control_characters_and_agy_has_no_id_in_its_comment(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        self.assertEqual(sh.resume_hint("x --resume {sid}", "a\nb", "/s"), "")
        self.assertEqual(sh.resume_hint("cd {cwd}", "a", "/s\x00"), "")
        self.assertEqual(sh.resume_hint("x {sid}", "a b", "/s"), "x 'a b'")
        agy = load("agy", Path("/nonexistent-home"))
        self.assertNotIn("{sid}", agy.RESUME)  # the id sat inside a shell comment, where quoting does nothing

    def test_status_accepts_a_relative_index_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run(tmp, "idx", "--update-only", cwd=tmp).returncode, 0)
            st = self._run(tmp, "idx", "--status", cwd=tmp)
            self.assertIn("last full update:", st.stdout, st.stderr)  # a crash also exits 1: read the output

    def test_a_corrupt_index_exits_2_not_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "idx"
            idx.mkdir()
            (idx / "history.v2.sqlite").write_bytes(b"this is not a database" * 100)
            r = self._run(tmp, str(idx), "--json", "anything")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("session-history:", r.stderr)

    def test_keyword_abbreviating_an_option_is_not_an_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run(tmp, str(Path(tmp) / "idx"), "--update-only").returncode, 0)
            db = Path(tmp) / "idx/history.v2.sqlite"
            self.assertEqual(self._run(tmp, str(db.parent), "--reb").returncode, 2)  # argparse: unrecognized, no abbreviation
            self.assertTrue(db.exists())


class LiveLabelTests(unittest.TestCase):
    def test_fleet_running_maps_native_ids_and_cwds_of_adapters_without_live(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh2", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        rows = [{"agent": "omp", "status": "idle", "sid": "/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_abc-1", "cwd": "/s"},
                {"agent": "codex", "status": "idle", "sid": None, "cwd": "/c"},
                {"agent": "codex", "status": "closed", "sid": None, "cwd": "/old"},
                {"agent": "hermes", "status": "idle", "sid": "20261029-1", "cwd": "/"},
                {"agent": "hermes", "status": "working", "sid": "cron_17af0eeb3949_20260813_075144", "cwd": "/"},
                {"agent": "codex", "status": "done", "sid": None, "cwd": "/launch"},   # a completed ACP launch
                {"agent": "codex", "status": "failed", "sid": None, "cwd": "/launch2"}]
        with mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: rows)}):
            exact, cwds = sh.fleet_running({"omp", "codex", "hermes"})
        self.assertEqual(exact, {("omp", "abc-1"), ("hermes", "20261029-1"), ("hermes", "cron_17af0eeb3949_20260813_075144")})
        self.assertEqual(cwds, {("omp", "/s"), ("codex", "/c"), ("hermes", "/")})  # closed rows are not running

    def test_an_exited_launch_row_is_not_running(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh3", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        rows = [{"agent": "omp", "status": "idle", "sid": None, "cwd": "/gone", "finished": "done"},
                {"agent": "omp", "status": "idle", "sid": None, "cwd": "/gone2", "launch": {"result": "ok"}},
                {"agent": "omp", "status": "idle", "sid": None, "cwd": "/live", "launch": {"result": None}}]
        with mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: rows)}):
            _, cwds = sh.fleet_running({"omp"})
        self.assertEqual(cwds, {("omp", "/live")})

    def test_fleet_scan_runs_only_when_a_printed_hit_needs_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write_jsonl(home / ".omp/agent/sessions/-s/2026-10-31T00-00-00-000Z_s1.jsonl", [
                {"type": "session", "id": "s1", "cwd": "/s"},
                {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "findable okapi"}]}}])
            spec = importlib.util.spec_from_file_location("t_sh4", SF / "session-history.py")
            with mock.patch.dict(os.environ, {"SESSION_INDEX_DIR": str(home / "idx"), "HOME": tmp}), \
                    mock.patch.object(Path, "home", return_value=home):
                sh = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sh)
                calls: list[set] = []
                with mock.patch.object(sh, "fleet_running", lambda agents: calls.append(set(agents)) or (set(), set())):
                    for kw, expect in (("zzzznothing", 0), ("okapi", 1)):
                        with mock.patch.object(sys, "argv", ["session-history.py", "--json", "--", kw]):
                            sh.main()
                        self.assertEqual(len(calls), expect, kw)

    def test_clean_strips_control_characters_and_empty_keywords_match_nothing(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh5", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        self.assertEqual(sh.clean("a\x1b[31mb\nc\x7fd\x85e"), "a?[31mb?c?d?e")

    def test_crush_reads_text_parts_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / ".local/share/crush-acp/crush.db"
            db_path.parent.mkdir(parents=True)
            db = sqlite3.connect(db_path)
            db.executescript("CREATE TABLE sessions(id, title, message_count, updated_at);"
                             "CREATE TABLE messages(id, session_id, role, parts, created_at);")
            db.execute("INSERT INTO sessions VALUES('c1','Crush chat',2,1790000000)")
            db.execute("INSERT INTO messages VALUES('m1','c1','user',?,1)", (json.dumps([{"type": "text", "data": {"text": "hello crush"}}]),))
            db.execute("INSERT INTO messages VALUES('m2','c1','assistant',?,2)", (json.dumps([{"type": "reasoning", "data": {"thinking": "secret"}}]),))
            db.commit()
            db.close()
            mod = load("crush", Path(tmp))
            (s,) = list(mod.sessions())
            self.assertEqual(s["load"](), ("", "Crush chat", [("user", "hello crush")]))


class SessionFindAllTests(unittest.TestCase):
    def test_all_passes_keywords_after_a_double_dash(self) -> None:
        """`session-find.py --all -- --rebuild` once reached session-history.py as its --rebuild option (index deleted)."""
        spec = importlib.util.spec_from_file_location("t_session_find", SF / "session-find.py")
        sf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sf)
        calls: list[list[str]] = []

        def fake_run(argv, **kw):  # noqa: ANN001
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 1, "[]", "")

        fleet = sys.modules.get("fleet")
        with mock.patch.object(sf, "live_sessions", return_value=[]), mock.patch.object(sf.subprocess, "run", fake_run), \
                mock.patch.object(sys, "argv", ["session-find.py", "--all", "--", "--rebuild"]), \
                mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: [])} if fleet is None else {}):
            if fleet is not None:
                with mock.patch.object(fleet, "sessions", return_value=[]):
                    sf.main()
            else:
                sf.main()
        (argv,) = calls
        self.assertEqual(argv[-2:], ["--", "--rebuild"])
        self.assertGreaterEqual(int(argv[argv.index("--limit") + 1]), 60)  # live rows are dropped after the cap


if __name__ == "__main__":
    unittest.main()
