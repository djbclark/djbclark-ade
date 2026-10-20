#!/usr/bin/env python3
"""Tests for bin/self-slash on a Paseo host.

Paseo runs only its own built-ins (clear, compact, ...) itself; /quit, /exit and /new reach
Claude as plain text and do nothing (2026-10-20).  So on Paseo `--finish` (and `/quit`, mapped
to it) waits for idle and archives the agent WITHOUT --force, `/new` is sent as `/clear`
followed by one `/baton`, and a per-agent lock keeps two lifecycle waiters from racing.

The script runs under a temporary HOME and a PATH whose first entry holds a fake `paseo`
that records its argv, one call per line, to $FAKE_LOG.  The waiter is detached (nohup), so
tests poll the self-slash log for its last line.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("SELF_SLASH_SCRIPT", str(ROOT / "bin" / "self-slash")))

FAKE_PASEO = textwrap.dedent("""\
    #!/bin/bash
    # fake paseo: record argv, answer the few calls self-slash makes
    echo "$*" >> "$FAKE_LOG"
    case "$1 $2" in
      "agent inspect") echo '{"Status": "idle"}';;
      "agent archive")
        if [ -n "$FAKE_ARCHIVE_FAIL" ]; then
          echo "Agent is running. Use --force to archive a running agent (it will interrupt the active run), or stop it first with: paseo agent stop." >&2
          exit 1
        fi
        echo archived;;
    esac
    case "$1" in
      wait) [ -n "$FAKE_WAIT_SLEEP" ] && sleep "$FAKE_WAIT_SLEEP"; echo '{}';;
      send) echo '{}';;
    esac
    exit 0
""")


class SelfSlashPaseoTests(unittest.TestCase):
    _tmp: tempfile.TemporaryDirectory[str]
    home: Path
    calls: Path
    log: Path
    lockdir: Path
    env: dict[str, str]
    children: list[int]

    @override
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.home = tmp / "home"
        self.home.mkdir()
        bindir = tmp / "bin"
        bindir.mkdir()
        fake = bindir / "paseo"
        _ = fake.write_text(FAKE_PASEO)
        fake.chmod(0o755)
        self.calls = tmp / "paseo-calls.txt"
        self.log = self.home / ".local" / "state" / "self-slash.log"
        self.lockdir = self.home / ".local" / "state" / "self-slash"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERDR_", "ORCA_", "PASEO_", "SELF_SLASH_", "FAKE_"))}
        env.update(HOME=str(self.home), PATH=f"{bindir}:{os.environ['PATH']}",
                   PASEO_AGENT_ID="test-agent", PASEO_CLI=str(fake), FAKE_LOG=str(self.calls),
                   SELF_SLASH_THEN_DELAY="0", SELF_SLASH_WAIT="30")
        self.env = env
        self.children: list[int] = []
        self.addCleanup(self._kill_children)

    def _kill_children(self) -> None:
        for pid in self.children:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    def run_ss(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **extra}
        return subprocess.run([str(SCRIPT), "--delay", "0", *args], env=env, text=True,
                              capture_output=True, timeout=60, check=False)

    def paseo_calls(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def log_text(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def wait_log(self, needle: str, timeout: float = 20.0) -> str:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if needle in self.log_text():
                return self.log_text()
            time.sleep(0.1)
        self.fail(f"{needle!r} never reached the log:\n{self.log_text()}\ncalls: {self.paseo_calls()}")

    def wait_lock_gone(self, timeout: float = 20.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if not list(self.lockdir.glob("*.lifecycle")) and not list(self.lockdir.glob("*.pid")):
                return
            time.sleep(0.1)
        self.fail(f"locks left behind: {list(self.lockdir.iterdir())}")

    def lifecycle_lock(self) -> Path:
        return self.lockdir / "paseo_test-agent.lifecycle"

    # (a)
    def test_finish_waits_then_archives_without_force(self) -> None:
        r = self.run_ss("--finish")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_log("finish: archived test-agent")
        calls = self.paseo_calls()
        waits = [i for i, c in enumerate(calls) if c.startswith("wait test-agent")]
        archives = [i for i, c in enumerate(calls) if c.startswith("agent archive")]
        self.assertTrue(waits and archives, calls)
        self.assertLess(waits[0], archives[0])
        self.assertEqual([calls[i] for i in archives], ["agent archive test-agent"])
        self.assertFalse(any("--force" in c for c in calls), calls)
        self.assertFalse(any(c.startswith("send") for c in calls), calls)
        self.wait_lock_gone()

    # (b)
    def test_quit_on_paseo_maps_to_finish_and_sends_no_text(self) -> None:
        r = self.run_ss("/quit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mapping to --finish", r.stderr)
        self.wait_log("finish: archived test-agent")
        calls = self.paseo_calls()
        self.assertIn("agent archive test-agent", calls)
        self.assertFalse(any(c.startswith("send") for c in calls), calls)
        self.assertNotIn("sent /quit", self.log_text())

    # (c)
    def test_archive_refusal_is_logged_and_never_forced(self) -> None:
        r = self.run_ss("--finish", FAKE_ARCHIVE_FAIL="1")
        self.assertEqual(r.returncode, 0, r.stderr)  # the parent only queues
        text = self.wait_log("finish: archive refused")
        self.assertIn("Use --force", text)
        self.assertNotIn("archived test-agent", text)
        self.wait_lock_gone()
        calls = self.paseo_calls()
        self.assertEqual([c for c in calls if c.startswith("agent archive")], ["agent archive test-agent"])
        self.assertFalse(any("--force" in c for c in calls), calls)

    def test_archive_refusal_exits_8(self) -> None:
        # the waiter itself, run in the foreground the way the parent spawns it
        env = {**self.env, "SELF_SLASH_CHILD": "1", "SELF_SLASH_FINISH": "1", "FAKE_ARCHIVE_FAIL": "1"}
        r = subprocess.run([str(SCRIPT), "--delay", "0", "/quit"], env=env, text=True,
                           capture_output=True, timeout=60, check=False)
        self.assertEqual(r.returncode, 8, r.stdout + r.stderr)
        self.assertIn("finish: archive refused", r.stdout)

    # (d)
    def test_live_lock_refuses_a_second_lifecycle(self) -> None:
        self.lockdir.mkdir(parents=True)
        holder = subprocess.Popen(["sleep", "60"])
        self.children.append(holder.pid)
        self.lifecycle_lock().write_text(f"{holder.pid}\n")
        for args in (["--finish"], ["/quit"], ["/new"], ["/clear"]):
            r = self.run_ss(*args)
            self.assertEqual(r.returncode, 7, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn("already queued", r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        self.assertEqual(self.lifecycle_lock().read_text().strip(), str(holder.pid))

    def test_concurrent_finish_archives_once(self) -> None:
        first = self.run_ss("--finish", FAKE_WAIT_SLEEP="2")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_ss("--finish")
        self.assertEqual(second.returncode, 7, second.stdout + second.stderr)
        self.wait_log("finish: archived test-agent")
        self.assertEqual([c for c in self.paseo_calls() if c.startswith("agent archive")], ["agent archive test-agent"])
        self.wait_lock_gone()

    def test_stale_lock_is_cleared(self) -> None:
        self.lockdir.mkdir(parents=True)
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.lifecycle_lock().write_text(f"{dead.pid}\n")
        r = self.run_ss("--finish")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_log("finish: archived test-agent")
        self.wait_lock_gone()

    # (e)
    def test_new_is_sent_as_clear_then_one_baton(self) -> None:
        r = self.run_ss("/new")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("then /baton", r.stdout)
        text = self.wait_log("sent /baton")
        self.assertIn("sent /clear", text)
        self.assertIn("then: /baton", text)
        self.assertLess(text.index("sent /clear"), text.index("sent /baton"))
        sends = [c for c in self.paseo_calls() if c.startswith("send")]
        self.assertEqual(len(sends), 2, sends)
        self.assertTrue(sends[0].endswith("--json /clear"), sends)
        self.assertTrue(sends[1].endswith("--json /baton"), sends)
        self.assertFalse(any("/new" in c or "archive" in c for c in self.paseo_calls()))
        self.assertEqual(text.count("sent /baton"), 1)
        self.wait_lock_gone()

    def test_lock_covers_the_whole_clear_then_baton_chain(self) -> None:
        r = self.run_ss("/new", FAKE_WAIT_SLEEP="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.lifecycle_lock().exists())
        second = self.run_ss("--finish")
        self.assertEqual(second.returncode, 7, second.stdout + second.stderr)
        self.wait_log("sent /baton")
        self.wait_lock_gone()
        self.assertFalse(any("archive" in c for c in self.paseo_calls()))

    # (f)
    def test_dry_run_runs_nothing(self) -> None:
        for args in (["--finish"], ["/quit"], ["/new"]):
            r = self.run_ss("--dry-run", *args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dry run", r.stdout)
        self.assertEqual(self.paseo_calls(), [])
        self.assertFalse(self.log.exists())
        self.assertFalse(self.lockdir.exists() and list(self.lockdir.iterdir()))
        r = self.run_ss("--dry-run", "--finish")
        self.assertIn("never --force", r.stdout)

    def test_finish_rejects_a_command(self) -> None:
        r = self.run_ss("--finish", "/compact")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--finish takes no command", r.stderr)

    def test_no_text_prints_usage_with_finish(self) -> None:
        r = self.run_ss()
        self.assertEqual(r.returncode, 2)
        self.assertIn("--finish", r.stderr)


if __name__ == "__main__":
    unittest.main()
