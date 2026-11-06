#!/usr/bin/env python3
"""session-finder's full-text history index (2026-10-31).

  * omp and grok have adapters (before: 2,028 omp and 220 grok sessions were invisible; goose's went with goose, 2026-11-06).
  * cursor yields one entry per session id: a session under two project dirs used to flip-flop.
  * `session-history.py --status` is read-only and reports unindexed sessions; `--update-only` records the
    time of the last full pass and fixes what `--status` found.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
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
        pi_env = mock.patch.dict("os.environ", {"PI_CODING_AGENT_DIR": "", "PI_CODING_AGENT_SESSION_DIR": ""})
        pi_env.start()
        self.addCleanup(pi_env.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_omp_reads_user_and_assistant_text_only(self) -> None:
        path = self.home / ".omp/agent/sessions/-src-x/2026-10-31T17-00-00-000Z_abc-123.jsonl"
        write_jsonl(path, [
            {"type": "title", "title": "Fix the flux capacitor"},
            {"type": "session", "id": "abc-123", "cwd": "/src/x"},
            {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "please repair the capacitor"}]}},
            {"type": "message", "message": {"role": "assistant", "content": [{"type": "thinking", "text": "hmm"},
                                                                             {"type": "text", "text": "capacitor repaired"}]}},
            {"type": "message", "message": {"role": "toolResult", "content": [{"type": "text", "text": "tool output"}]}},
        ])
        mod = load("omp", self.home)
        (s,) = list(mod.sessions())
        self.assertEqual((s["key"], s["sid"]), (f"omp:{path.resolve()}", "abc-123"))
        self.assertEqual(s["supersedes"], ["omp:abc-123"])
        self.assertEqual(mod.RESUME(s["key"], "/src/x"), "omp --resume=abc-123")
        cwd, title, msgs = s["load"]()
        self.assertEqual((cwd, title), ("/src/x", "Fix the flux capacitor"))
        self.assertEqual(msgs, [("user", "please repair the capacitor"), ("assistant", "capacitor repaired")])

    def test_pi_reads_names_and_text_without_system_or_tool_content(self) -> None:
        path = self.home / ".pi/agent/sessions/--src-x--/2026-11-03T00-00-00Z_custom_id.jsonl"
        write_jsonl(path, [
            {"type": "session", "version": 3, "id": "custom_id", "cwd": "/src/x"},
            {"type": "message", "message": {"role": "system", "content": "private instructions"}},
            {"type": "message", "message": {"role": "user", "content": "Hi"}},
            {"type": "message", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "Hello"}]}},
            {"type": "message", "message": {"role": "toolResult", "content": "tool output"}},
            {"type": "session_info", "name": "First name"},
            {"type": "session_info", "name": "Final name"},
            {"type": "message", "message": None},
        ])
        with path.open("a") as handle:
            handle.write("null\n[]\ninvalid json\n")
        mod = load("pi", self.home)
        (session,) = list(mod.sessions())
        self.assertEqual(session["key"], f"pi:{path.resolve()}")
        self.assertEqual(session["sid"], "custom_id")
        self.assertEqual(session["load"](), ("/src/x", "Final name", [("user", "Hi"), ("assistant", "Hello")]))
        self.assertEqual(mod.RESUME(session["key"], "/src/x"), f"pi --session {path.resolve()}")

    def test_pi_listing_is_stat_only_and_skips_symlinks(self) -> None:
        path = self.home / ".pi/agent/sessions/--src-x--/timestamp_valid-id.jsonl"
        write_jsonl(path, [{"type": "session", "id": "valid-id"}])
        path.with_name("timestamp_link-id.jsonl").symlink_to(path)
        mod = load("pi", self.home)
        with mock.patch.object(mod, "records", side_effect=AssertionError("listing must not parse")):
            (session,) = list(mod.sessions())
        self.assertEqual(session["sid"], "valid-id")

    def test_pi_session_directory_overrides(self) -> None:
        agent = self.home / "custom-agent"
        direct = self.home / "custom-sessions"
        write_jsonl(agent / "sessions/--src--/2026-11-03T15-25-31-559Z_agent-id.jsonl", [{"type": "session"}])
        write_jsonl(direct / "--src--/2026-11-03T15-25-31-559Z_direct-id.jsonl", [{"type": "session"}])
        mod = load("pi", self.home)
        with mock.patch.dict("os.environ", {"PI_CODING_AGENT_DIR": str(agent)}):
            self.assertEqual([s["sid"] for s in mod.sessions()], ["agent-id"])
            with mock.patch.dict("os.environ", {"PI_CODING_AGENT_SESSION_DIR": str(direct)}):
                self.assertEqual([s["sid"] for s in mod.sessions()], ["direct-id"])
        self.assertEqual(mod.ROOT_ENV, ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR"))

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
            # the file name holds no valid id, so the header's "x" names the session and the hint names the file
            (hit,) = json.loads(r.stdout)
            self.assertEqual((hit["sessionId"], shlex.split(hit["resume"])), (
                "x", ["omp", f"--resume={(home / '.omp/agent/sessions/-s/2026-10-31T00-00-00-000Z_x;touch pwned.jsonl').resolve()}"]))


class HardeningTests(unittest.TestCase):
    """Adversary round 2 (PR 191): R1 agy comment (removed with agy), R2 relative index dir, R3 crash exit code, R5 abbreviations."""

    @staticmethod
    def _env(tmp: str, idx: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        env.update(PATH="/usr/bin:/bin", HOME=tmp, SESSION_INDEX_DIR=idx)
        return env

    def _run(self, tmp: str, idx: str, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(SF / "session-history.py"), *args], env=self._env(tmp, idx),
                              capture_output=True, text=True, check=False, cwd=cwd)

    def test_resume_hint_is_empty_for_control_characters(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        self.assertEqual(sh.resume_hint("x --resume {sid}", "a\nb", "/s"), "")
        self.assertEqual(sh.resume_hint("cd {cwd}", "a", "/s\x00"), "")
        self.assertEqual(sh.resume_hint("x {sid}", "a b", "/s"), "x 'a b'")

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
        # an omp fleet row's id is its transcript: the identity is that file (the same id may live in another store)
        self.assertEqual(exact, {("omp", "file", "/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_abc-1.jsonl"), ("hermes", "20261029-1"), ("hermes", "cron_17af0eeb3949_20260813_075144")})
        self.assertEqual(cwds, {("omp", "/s"), ("codex", "/c"), ("hermes", "/")})  # closed rows are not running

    def test_a_process_backed_unknown_row_is_running_only_while_its_process_is(self) -> None:
        spec = importlib.util.spec_from_file_location("t_sh_unk", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        rows = [{"agent": "codex", "status": "unknown", "sid": "uuid-1", "pid": os.getpid(), "cwd": "/live"},
                {"agent": "codex", "status": "unknown", "sid": "uuid-2", "pid": gone.pid, "cwd": "/gone"},
                {"agent": "codex", "status": "unknown", "sid": "uuid-3", "pid": None, "cwd": "/nopid"}]
        with mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: rows)}):
            exact, cwds = sh.fleet_running({"codex"})
        self.assertEqual(exact, {("codex", "uuid-1")})
        self.assertEqual(cwds, {("codex", "/live")})

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

    def test_install_renders_the_configured_index_directory_into_the_job(self) -> None:
        plist = (ROOT / "launchd" / "com.djbclark.session-history-update.plist").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            idx = Path(tmp) / "my <idx> & dir"
            with mock.patch.dict(os.environ, {"SESSION_INDEX_DIR": str(idx)}):
                spec = importlib.util.spec_from_file_location("t_sh_plist", SF / "session-history.py")
                sh = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(sh)
            with mock.patch.dict(os.environ, {"CODEX_HOME": "", "CLAUDE_CONFIG_DIR": ""}):
                out = sh.render_plist(plist, Path("/repo"))  # adapter roots unset or empty: none are written
            self.assertNotIn("CODEX_HOME", out)
            self.assertNotIn("__", out)  # no placeholder left, comment included
            import plistlib
            d = plistlib.loads(out.encode())
            self.assertEqual(d["EnvironmentVariables"]["SESSION_INDEX_DIR"], str(idx.resolve()))
            self.assertEqual(d["StandardOutPath"], f"{idx.resolve()}/update.out")
            self.assertEqual(d["StandardErrorPath"], f"{idx.resolve()}/update.err")
            self.assertEqual(d["ProgramArguments"][3], "/repo/skills/session-finder/session-history.py")


    def test_install_carries_every_set_adapter_root_variable_into_the_job(self) -> None:
        import plistlib
        plist = (ROOT / "launchd" / "com.djbclark.session-history-update.plist").read_text()
        spec = importlib.util.spec_from_file_location("t_sh_plist2", SF / "session-history.py")
        sh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sh)
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/alt/codex & co", "CLAUDE_CONFIG_DIR": "~/alt-claude"}):
            d = plistlib.loads(sh.render_plist(plist, Path("/repo")).encode())
        env = d["EnvironmentVariables"]
        self.assertEqual(env["CODEX_HOME"], "/alt/codex & co")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(Path.home() / "alt-claude"))  # launchd does not expand `~`
        self.assertIn("SESSION_INDEX_DIR", env)
        self.assertIn("PATH", env)
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/alt/codex"}):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            env = plistlib.loads(sh.render_plist(plist, Path("/repo")).encode())["EnvironmentVariables"]
        self.assertEqual(env["CODEX_HOME"], "/alt/codex")
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)  # only variables that are set

    def test_every_environment_variable_an_adapter_reads_is_declared_in_its_root_env(self) -> None:
        """An adapter that finds its store through an environment variable without declaring it would index a
        different store in the scheduled job than in an interactive search."""
        import re
        for p in sorted((SF / "adapters").glob("*.py")):
            src = p.read_text()
            used = set(re.findall(r"os\.environ(?:\.get\(|\[)\s*[\"']([A-Z0-9_]+)[\"']", src) + re.findall(r"os\.getenv\(\s*[\"']([A-Z0-9_]+)[\"']", src))
            declared = set(re.findall(r"[\"']([A-Z0-9_]+)[\"']", next(iter(re.findall(r"^ROOT_ENV\s*=\s*\(([^)]*)\)", src, re.M)), "")))
            self.assertEqual(used, declared, p.name)

class SessionFindAllTests(unittest.TestCase):
    def setUp(self) -> None:
        # session-find.py resolves its own session through claude_identity, which runs `ps` through the SAME subprocess module object these tests patch
        # (`sf.subprocess.run`), so the resolver's call would land in the recorded argv (PR 248 adversary, CI pytest-linux): not under test here.
        if str(SF) not in sys.path:
            sys.path.insert(0, str(SF))
        import claude_identity
        patcher = mock.patch.object(claude_identity, "own_session_id", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_session_index_dir_override_applies_to_session_find_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SESSION_INDEX_DIR": tmp}):
            spec = importlib.util.spec_from_file_location("t_sf_dir", SF / "session-find.py")
            sf = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sf)
            self.assertEqual(sf.INDEX_DIR, Path(tmp).resolve())

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

    def test_a_finished_launch_still_in_the_fleet_keeps_its_history_hit(self) -> None:
        """A finished ACP launch stays in fleet.sessions() until archived; its transcript-only keyword hit was dropped as 'live'."""
        spec = importlib.util.spec_from_file_location("t_session_find_fin", SF / "session-find.py")
        sf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sf)
        row = {"agent": "codex", "id": "L1", "sid": "S-done", "status": "idle", "cwd": "/w", "title": "unrelated", "name": "n1",
               "where": "", "focus": "", "finished": "done", "reach": "launch.py reply L1 \"<text>\""}
        running = {**row, "id": "L2", "sid": "S-run", "finished": "", "name": "n2"}
        omp = {**row, "id": "L3", "agent": "omp", "sid": "/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_abc-1", "name": "n3"}
        omp_run = {**running, "id": "L4", "agent": "omp", "sid": "/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_run-2", "name": "n4"}
        hits = [{"agent": "codex", "sessionId": sid, "live": False, "title": "", "cwd": "/w", "snippet": "okapi", "resume": f"r {sid}"}
                for sid in ("S-done", "S-run", "S-old")]
        hits += [{"agent": "omp", "sessionId": sid, "sessionKey": f"omp:/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_{sid}.jsonl",
                  "live": False, "title": "", "cwd": "/w", "snippet": "okapi", "resume": f"r {sid}"} for sid in ("abc-1", "run-2")]  # bare uuids + file keys

        def fake_run(argv, **kw):  # noqa: ANN001
            return subprocess.CompletedProcess(argv, 0, json.dumps(hits), "")

        fleet = mock.Mock(sessions=lambda: [row, running, omp, omp_run])
        out = []
        with mock.patch.object(sf, "live_sessions", return_value=[]), mock.patch.object(sf.subprocess, "run", fake_run), \
                mock.patch.dict(sys.modules, {"fleet": fleet}), \
                mock.patch.object(sys, "argv", ["session-find.py", "--all", "--json", "--", "okapi"]), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0])):
            self.assertEqual(sf.main(), 0)
        got = {r["sessionId"]: r for r in json.loads(out[-1])}
        self.assertEqual(sorted(got), ["/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_abc-1", "S-done", "S-old"])
        o = got["/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_abc-1"]  # the omp launch: one row, FINISHED, with the snippet
        self.assertEqual((o["match"], o["finished"], o["live"]), ("okapi", "done", True))  # the running one is not listed twice; the finished one is
        self.assertGreater(got["S-done"]["score"], 0)
        self.assertEqual(got["S-done"]["match"], "okapi")  # the history snippet, not the fleet's `launch.py reply` hint
        self.assertTrue(got["S-done"]["live"])  # still the fleet's row, with FINISHED set
        self.assertEqual(got["S-done"]["finished"], "done")
        self.assertEqual(got["S-old"]["status"], "ended")

    def test_an_omp_fleet_transcript_with_a_noncanonical_name_matches_its_header_id(self) -> None:
        """`daily.jsonl` with header id `header-id`: history reports `header-id`, the fleet row's id is the path; one row, and the fleet
        liveness fallback matches (2026-11-03, review of PR 274)."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "-s" / "daily.jsonl"
            write_jsonl(transcript, [{"type": "title", "title": ""}, {"type": "session", "id": "header-id", "cwd": "/w"}])
            spec = importlib.util.spec_from_file_location("t_session_find_hdr", SF / "session-find.py")
            sf = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sf)
            sh_spec = importlib.util.spec_from_file_location("t_sh_hdr", SF / "session-history.py")
            sh = importlib.util.module_from_spec(sh_spec)
            sh_spec.loader.exec_module(sh)
            row = {"agent": "omp", "id": "L3", "sid": str(transcript), "status": "idle", "cwd": "/w", "title": "okapi work", "name": "n3",
                   "where": "", "focus": "", "finished": ""}
            hits = [{"agent": "omp", "sessionId": "header-id", "sessionKey": f"omp:{transcript.resolve()}", "live": False, "title": "", "cwd": "/w", "snippet": "okapi", "resume": "r"}]
            out = []
            with mock.patch.object(sf, "live_sessions", return_value=[]), \
                    mock.patch.object(sf.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(hits), "")), \
                    mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: [row])}), \
                    mock.patch.object(sys, "argv", ["session-find.py", "--all", "--json", "--", "okapi"]), \
                    mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0])):
                sf.main()
                self.assertEqual([r["sessionId"] for r in json.loads(out[-1])], [str(transcript)])  # the fleet row only: no second, ended copy
                exact, _ = sh.fleet_running({"omp"})
            self.assertEqual(exact, {("omp", "file", str(transcript.resolve()))})
            self.assertEqual(sys.modules["nativeid"].history_identity("omp", "header-id", "/w", f"omp:{transcript.resolve()}"),
                             ("omp", "file", str(transcript.resolve())))
            # an unreadable file falls back to the name-derived id
            self.assertEqual(sys.modules["nativeid"].omp_native_id(str(Path(tmp) / "gone" / "nofile.jsonl")), "nofile")
            self.assertEqual(sys.modules["nativeid"].omp_native_id("/x/2026-11-03T14-30-49-957Z_abc-1"), "abc-1")

    def _find_all(self, hits, rows):
        spec = importlib.util.spec_from_file_location("t_session_find_live", SF / "session-find.py")
        sf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sf)
        out = []
        with mock.patch.object(sf, "live_sessions", return_value=[]), \
                mock.patch.object(sf.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, json.dumps(hits), "")), \
                mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: rows)}), \
                mock.patch.object(sys, "argv", ["session-find.py", "--all", "--json", "--", "okapi"]), \
                mock.patch("builtins.print", side_effect=lambda *a, **k: out.append(a[0])):
            sf.main()
        return {r["sessionId"]: r for r in json.loads(out[-1])}

    def test_a_lease_held_omp_hit_without_a_fleet_row_is_listed_with_its_own_fields_and_an_open_todo_stays_unlisted(self) -> None:
        """omp outside herdr has no fleet row: the history's `live` hit (omp session lease) used to be dropped as 'the fleet lists it', and
        the session vanished (exit 1, no output). An open todo note is `live` with state OPEN: unchanged, still not a session hit."""
        key = "omp:/h/.omp/agent/sessions/-s/2026-10-31T17-00-00-000Z_held-1.jsonl"
        hits = [{"agent": "omp", "sessionId": "held-1", "sessionKey": key, "live": True, "state": "LIVE", "title": "t", "cwd": "/w",
                 "snippet": "okapi", "resume": "omp --resume=held-1"},
                {"agent": "todo", "sessionId": "note-1", "sessionKey": "todo:p:note-1", "live": True, "state": "OPEN", "title": "[open] x",
                 "cwd": "", "snippet": "okapi", "resume": ""}]
        got = self._find_all(hits, [])
        self.assertEqual(sorted(got), ["held-1"])
        r = got["held-1"]
        self.assertEqual((r["live"], r["state"], r["status"], r["pid"], r["resume"], r["agent"]), (True, "LIVE", "LIVE", None, "", "omp"))
        # with a fleet row for that very transcript the hit is the fleet's, not listed twice
        row = {"agent": "omp", "id": "L1", "sid": key[4:-6], "status": "idle", "cwd": "/w", "title": "okapi work", "name": "n1",
               "where": "", "focus": "", "finished": ""}
        self.assertEqual(sorted(self._find_all(hits, [row])), [key[4:-6]])

    def test_the_same_omp_id_in_two_stores_is_two_sessions_for_liveness_and_listing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            name = "2026-11-03T14-30-49-957Z_same-id.jsonl"
            default = home / ".omp/agent/sessions/-s" / name
            profile = home / ".omp/profiles/company/agent/sessions/-s" / name
            for p in (default, profile):
                write_jsonl(p, [{"type": "session", "id": "same-id", "cwd": "/w"}])
            sh_spec = importlib.util.spec_from_file_location("t_sh_stores", SF / "session-history.py")
            sh = importlib.util.module_from_spec(sh_spec)
            sh_spec.loader.exec_module(sh)
            row = {"agent": "omp", "status": "idle", "sid": str(default.with_suffix("")), "cwd": "/w"}
            with mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: [row])}):
                exact, _ = sh.fleet_running({"omp"})
            ident = sys.modules["nativeid"].history_identity
            self.assertIn(ident("omp", "same-id", "/w", f"omp:{default.resolve()}"), exact)
            self.assertNotIn(ident("omp", "same-id", "/w", f"omp:{profile.resolve()}"), exact)  # the other store's copy is not live
            # session-find: the live default-store file is the fleet's row; the profile copy is still a hit of its own
            hit = lambda p: {"agent": "omp", "sessionId": "same-id", "sessionKey": f"omp:{p.resolve()}", "live": False,  # noqa: E731
                             "title": "", "cwd": "/w", "snippet": "okapi", "resume": f"omp --resume={p}"}
            frow = {"agent": "omp", "id": "L1", "sid": str(default.with_suffix("")), "status": "idle", "cwd": "/w", "title": "okapi", "name": "n",
                    "where": "", "focus": "", "finished": ""}
            got = self._find_all([hit(default), hit(profile)], [frow])
            self.assertEqual(sorted(got), sorted([str(default.with_suffix("")), "same-id"]))
            self.assertEqual(got["same-id"]["resume"], f"omp --resume={profile}")
            # a fleet row that carries no path (an id from argv) can only join by id
            got = self._find_all([hit(default), hit(profile)], [{**frow, "sid": "same-id"}])
            self.assertEqual(sorted(got), ["same-id"])

    def test_a_failed_history_search_is_exit_2_not_no_hits(self) -> None:
        spec = importlib.util.spec_from_file_location("t_session_find_fail", SF / "session-find.py")
        sf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sf)
        fleet_row = {"agent": "codex", "id": "L9", "sid": "S9", "status": "idle", "cwd": "/w", "title": "okapi work", "name": "n9",
                     "where": "", "focus": "", "finished": ""}

        def run(child, rows):  # noqa: ANN001
            with mock.patch.object(sf, "live_sessions", return_value=[]), mock.patch.object(sf.subprocess, "run", child), \
                    mock.patch.dict(sys.modules, {"fleet": mock.Mock(sessions=lambda: rows)}), \
                    mock.patch.object(sys, "argv", ["session-find.py", "--all", "--", "okapi"]), \
                    mock.patch("builtins.print"), mock.patch("sys.stderr"):
                return sf.main()

        def broken(argv, **kw):  # noqa: ANN001
            return subprocess.CompletedProcess(argv, 2, "", "index corrupt")

        def timeout(argv, **kw):  # noqa: ANN001
            raise subprocess.TimeoutExpired(argv, 600)

        def empty(argv, **kw):  # noqa: ANN001
            return subprocess.CompletedProcess(argv, 1, "[]", "")

        self.assertEqual(run(broken, []), 2)
        self.assertEqual(run(timeout, []), 2)
        self.assertEqual(run(empty, []), 1)             # a completed search with no hits stays 1
        self.assertEqual(run(broken, [fleet_row]), 0)   # a fleet hit is still a hit


if __name__ == "__main__":
    unittest.main()
