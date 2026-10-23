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
    echo "$1 $2: PASEO_AGENT_ID=${PASEO_AGENT_ID-unset} PASEO_AGENT_CWD=${PASEO_AGENT_CWD-unset}" >> "$FAKE_LOG.env"
    case "$1 $2" in
      "agent inspect")
        if [ "$3" = new-agent-1 ]; then
          parent=null; [ -n "$FAKE_NEW_PARENT" ] && parent="\\"$FAKE_NEW_PARENT\\""
          printf '{"Id": "new-agent-1", "Model": "%s", "Status": "%s", "ParentAgentId": %s}\\n' \\
            "${FAKE_NEW_MODEL-claude-opus-5-5}" "${FAKE_NEW_STATUS-idle}" "$parent"
        else
          printf '{"Id": "test-agent", "Name": "%s", "Status": "idle", "Mode": "bypassPermissions", "Cwd": "%s", "ParentAgentId": null}\\n' \\
            "${FAKE_NAME-Lead}" "$FAKE_CWD"
        fi;;
      "agent archive")
        if [ -n "$FAKE_ARCHIVE_FAIL" ]; then
          echo "Agent is running. Use --force to archive a running agent (it will interrupt the active run), or stop it first with: paseo agent stop." >&2
          exit 1
        fi
        echo archived;;
      "workspace ls")
        if [ -n "$FAKE_WS_JSON" ]; then echo "$FAKE_WS_JSON"
        else printf '[{"workspaceId": "ws-1", "cwd": "%s", "background": false}]\\n' "$FAKE_CWD"; fi;;
    esac
    case "$1" in
      wait) [ -n "$FAKE_WAIT_SLEEP" ] && sleep "$FAKE_WAIT_SLEEP"; echo '{}';;
      send) echo '{}';;
      run)
        if [ -n "$FAKE_RUN_FAIL" ]; then echo "Provider claude is unavailable" >&2; exit 1; fi
        echo '{"agentId": "new-agent-1", "status": "created", "provider": "claude", "cwd": "x", "title": "t"}';;
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
               if not k.startswith(("HERDR_", "ORCA_", "PASEO_", "SELF_SLASH_", "FAKE_", "ACP_RUN_AGENT"))}
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

    @staticmethod
    def stamp(pid: int) -> str:
        """The lock file content self-slash writes: pid, TAB, ps lstart squeezed to single spaces."""
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False)
        return f"{pid}\t{' '.join(out.stdout.split())}\n"

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
        self.assertEqual([calls[i] for i in archives], ["agent archive -- test-agent"])
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
        self.assertIn("agent archive -- test-agent", calls)
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
        self.assertEqual([c for c in calls if c.startswith("agent archive")], ["agent archive -- test-agent"])
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
        self.lifecycle_lock().write_text(self.stamp(holder.pid))
        for args in (["--finish"], ["/quit"], ["/exit"], ["/new"], ["/clear"]):
            r = self.run_ss(*args)
            self.assertEqual(r.returncode, 7, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn("already queued", r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        self.assertEqual(self.lifecycle_lock().read_text(), self.stamp(holder.pid))

    def test_concurrent_finish_archives_once(self) -> None:
        first = self.run_ss("--finish", FAKE_WAIT_SLEEP="2")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_ss("--finish")
        self.assertEqual(second.returncode, 7, second.stdout + second.stderr)
        self.wait_log("finish: archived test-agent")
        self.assertEqual([c for c in self.paseo_calls() if c.startswith("agent archive")], ["agent archive -- test-agent"])
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
        self.assertEqual(list(self.lockdir.glob("*.stale.*")), [])

    def test_lock_naming_a_live_pid_that_is_not_self_slash_is_stale(self) -> None:
        # a pid reused after a SIGKILL or reboot: alive, but not the process that took the lock
        self.lockdir.mkdir(parents=True)
        self.lifecycle_lock().write_text(f"{os.getpid()}\n")  # bare pid (old format): the test runner
        r = self.run_ss("--finish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_log("finish: archived test-agent")
        self.wait_lock_gone()

    def test_pid_lock_naming_a_process_that_only_mentions_self_slash_is_stale(self) -> None:
        # adversary round 2 (2026-10-20): a reused pid now running `tail -f .../self-slash.log` must not
        # count as the queued waiter; only a "<script> --delay ..." process does
        self.lockdir.mkdir(parents=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.touch()
        holder = subprocess.Popen(["tail", "-f", str(self.log)], stdout=subprocess.DEVNULL)
        self.children.append(holder.pid)
        (self.lockdir / "test-agent.pid").write_text(f"{holder.pid}\n")
        r = self.run_ss("/compact x")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_log("sent /compact x")

    def test_lock_with_a_different_start_time_is_stale(self) -> None:
        self.lockdir.mkdir(parents=True)
        holder = subprocess.Popen(["sleep", "60"])
        self.children.append(holder.pid)
        self.lifecycle_lock().write_text(f"{holder.pid}\tMon Jan  1 00:00:00 2001\n")
        r = self.run_ss("--finish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_log("finish: archived test-agent")
        self.wait_lock_gone()
        self.assertEqual(list(self.lockdir.glob("*.stale.*")), [])

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

    # adversary 2026-10-20, finding 1b: a dispatched agent (acp-run sets ACP_RUN_AGENT=1) must
    # never run a lifecycle action; it would reach the parent's agent
    def test_dispatched_agent_is_refused_every_lifecycle_action(self) -> None:
        for args in (["/new"], ["/clear"], ["/reset"], ["/compact x"], ["--finish"],
                     ["/quit"], ["/exit"], ["--dry-run", "/clear"], ["--dry-run", "--finish"]):
            r = self.run_ss(*args, ACP_RUN_AGENT="1")
            self.assertEqual(r.returncode, 9, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn("ACP_RUN_AGENT=1", r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        self.assertFalse(self.log.exists())
        self.assertFalse(self.lockdir.exists() and list(self.lockdir.iterdir()))

    def test_dispatched_agent_marker_does_not_block_other_commands(self) -> None:
        r = self.run_ss("--dry-run", "/context", ACP_RUN_AGENT="1")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_top_level_session_without_the_marker_is_not_refused(self) -> None:
        r = self.run_ss("--dry-run", "/new", ACP_RUN_AGENT="")
        self.assertEqual(r.returncode, 0, r.stderr)

    # finding 4
    def test_paseo_then_quit_or_exit_is_rejected(self) -> None:
        for then in ("/quit", "/exit", "/quit now"):
            r = self.run_ss("--then", then, "/compact x")
            self.assertEqual(r.returncode, 2, f"{then}: {r.stdout}{r.stderr}")
            self.assertIn("not a Paseo command", r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        self.assertFalse(self.lockdir.exists() and list(self.lockdir.iterdir()))

    def test_finish_with_a_then_is_rejected(self) -> None:
        for args in (["--finish", "--then", "/baton"], ["--then", "/baton", "--finish"],
                     ["--then", "/baton", "/quit"]):
            r = self.run_ss(*args)
            self.assertEqual(r.returncode, 2, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn("no --then", r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        r = self.run_ss("--dry-run", "--finish", "--no-then")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_finish_with_a_then_is_rejected_on_orca_too(self) -> None:
        r = self.run_ss("--finish", "--then", "/baton", ORCA_TERMINAL_HANDLE="t1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no --then", r.stderr)

    # finding 6: /quit and /exit are lifecycle actions on herdr and Orca too
    def test_quit_and_exit_take_the_lifecycle_lock_on_orca(self) -> None:
        fake_orca = Path(self.env["PATH"].split(":")[0]) / "orca"
        _ = fake_orca.write_text("#!/bin/bash\nexit 0\n")
        fake_orca.chmod(0o755)
        self.lockdir.mkdir(parents=True)
        holder = subprocess.Popen(["sleep", "60"])
        self.children.append(holder.pid)
        (self.lockdir / "orca_t1.lifecycle").write_text(self.stamp(holder.pid))
        for text in ("/quit", "/exit", "/quit now", "/exit now"):
            r = self.run_ss(text, ORCA_TERMINAL_HANDLE="t1")
            self.assertEqual(r.returncode, 7, f"{text}: {r.stdout}{r.stderr}")
        r = self.run_ss("--dry-run", "/rename x", ORCA_TERMINAL_HANDLE="t1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # INFO 2: the mapping notice is for a typed /quit or /exit, not for --finish
    def test_mapping_notice_only_when_quit_was_typed(self) -> None:
        r = self.run_ss("--dry-run", "--finish")
        self.assertNotIn("mapping to --finish", r.stderr)
        for text in ("/quit", "/exit"):
            r = self.run_ss("--dry-run", text)
            self.assertIn("mapping to --finish", r.stderr)

    def test_finish_rejects_a_command(self) -> None:
        r = self.run_ss("--finish", "/compact")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--finish takes no command", r.stderr)

    def test_no_text_prints_usage_with_finish(self) -> None:
        r = self.run_ss()
        self.assertEqual(r.returncode, 2)
        self.assertIn("--finish", r.stderr)

    # --- --finish --successor (2026-10-23) ---
    SUCCESSOR = ("--finish", "--successor", "claude/claude-opus-5-5")

    def succ_env(self, **extra: str) -> dict[str, str]:
        cwd = str(Path(self._tmp.name) / "work")
        Path(cwd).mkdir(exist_ok=True)
        return {"FAKE_CWD": cwd, "PASEO_AGENT_CWD": cwd, "SELF_SLASH_SUCCESSOR_SETTLE": "0", **extra}

    def run_waiter(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        """The waiter itself, in the foreground, as the parent spawns it (its exit code is observable)."""
        env = {**self.env, **self.succ_env(), "SELF_SLASH_CHILD": "1", "SELF_SLASH_FINISH": "1",
               "SELF_SLASH_SUCCESSOR": "claude/claude-opus-5-5", "SELF_SLASH_S_THINKING": "high", **extra}
        return subprocess.run([str(SCRIPT), "--delay", "0", "/quit"], env=env, text=True,
                              capture_output=True, timeout=60, check=False)

    def test_successor_starts_baton_then_archives_in_order(self) -> None:
        r = self.run_ss(*self.SUCCESSOR, **self.succ_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_log("archived test-agent (successor new-agent-1)")
        calls = self.paseo_calls()
        cwd = self.succ_env()["FAKE_CWD"]
        steps = [c.split(" -- ")[0] if c.startswith("agent archive") else c for c in calls]
        self.assertEqual(steps[0].split(" --timeout")[0], "wait test-agent")
        self.assertEqual(steps[1:], [
            "agent inspect test-agent --json",
            "workspace ls --background --json",
            f"run /baton --provider claude/claude-opus-5-5 --thinking high --mode bypassPermissions "
            f"--workspace ws-1 --cwd {cwd} --title Lead → claude-opus-5-5 --no-wait --json",
            "agent inspect new-agent-1 --json",
            "agent archive",
        ])
        self.assertEqual([c for c in calls if c.startswith("agent archive")], ["agent archive -- test-agent"])
        self.assertFalse(any("--force" in c for c in calls), calls)
        self.wait_lock_gone()

    def test_successor_calls_run_without_the_callers_agent_id(self) -> None:
        # with PASEO_AGENT_ID set, `paseo run` hands the caller id to the daemon and the new
        # agent becomes a subagent even with --workspace
        _ = self.run_ss(*self.SUCCESSOR, **self.succ_env())
        self.wait_log("archived test-agent (successor new-agent-1)")
        envlog = Path(f"{self.calls}.env").read_text().splitlines()
        self.assertTrue(envlog and all("PASEO_AGENT_ID=unset PASEO_AGENT_CWD=unset" in line for line in envlog), envlog)

    def test_successor_flags_override_the_defaults(self) -> None:
        _ = self.run_ss(*self.SUCCESSOR, "--thinking", "max", "--mode", "plan", "--title", "Next lead", **self.succ_env())
        self.wait_log("archived test-agent (successor new-agent-1)")
        run = next(c for c in self.paseo_calls() if c.startswith("run "))
        self.assertIn("--thinking max --mode plan ", run)
        self.assertIn("--title Next lead --no-wait", run)

    def test_successor_run_failure_exits_11_and_archives_nothing(self) -> None:
        r = self.run_waiter(FAKE_RUN_FAIL="1")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("successor: paseo run failed", r.stdout)
        self.assertIn("NOT archived", r.stdout)
        self.assertFalse(any(c.startswith("agent archive") for c in self.paseo_calls()))

    def test_successor_that_is_a_subagent_exits_11_and_archives_nothing(self) -> None:
        r = self.run_waiter(FAKE_NEW_PARENT="test-agent")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("is a subagent", r.stdout)
        self.assertFalse(any(c.startswith("agent archive") for c in self.paseo_calls()))

    def test_successor_on_the_wrong_model_or_in_error_exits_11(self) -> None:
        for extra, needle in ((dict(FAKE_NEW_MODEL="claude-sonnet-5-5"), "not claude-opus-5-5"),
                              (dict(FAKE_NEW_STATUS="error"), "error status")):
            r = self.run_waiter(**extra)
            self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
            self.assertIn(needle, r.stdout)
        self.assertFalse(any(c.startswith("agent archive") for c in self.paseo_calls()))

    def test_successor_needs_exactly_one_workspace_for_the_cwd(self) -> None:
        cwd = self.succ_env()["FAKE_CWD"]
        two = f'[{{"workspaceId": "a", "cwd": "{cwd}"}}, {{"workspaceId": "b", "cwd": "{cwd}"}}]'
        r = self.run_waiter(FAKE_WS_JSON=two)
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("several workspaces", r.stdout)
        r = self.run_waiter(FAKE_WS_JSON="[]")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("no Paseo workspace", r.stdout)
        r = self.run_waiter(FAKE_WS_JSON=two, SELF_SLASH_WORKSPACE="b")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--workspace b ", next(c for c in self.paseo_calls() if c.startswith("run ")))
        # the same cwd with one background and one visible workspace picks the visible one
        both = f'[{{"workspaceId": "bg", "cwd": "{cwd}", "background": true}}, {{"workspaceId": "vis", "cwd": "{cwd}", "background": false}}]'
        self.calls.unlink()
        r = self.run_waiter(FAKE_WS_JSON=both)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--workspace vis ", next(c for c in self.paseo_calls() if c.startswith("run ")))

    def test_successor_archive_refusal_exits_8_and_leaves_the_successor(self) -> None:
        r = self.run_waiter(FAKE_ARCHIVE_FAIL="1")
        self.assertEqual(r.returncode, 8, r.stdout + r.stderr)
        self.assertIn("successor new-agent-1 left running", r.stdout)

    def test_successor_outside_paseo_exits_2(self) -> None:
        fake_orca = Path(self.env["PATH"].split(":")[0]) / "orca"
        _ = fake_orca.write_text("#!/bin/bash\nexit 0\n")
        fake_orca.chmod(0o755)
        for host_env in (dict(ORCA_TERMINAL_HANDLE="t1"), dict(HERDR_ENV="1", HERDR_PANE_ID="p1")):
            r = self.run_ss(*self.SUCCESSOR, **host_env)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("successor needs Paseo", r.stderr)
            self.assertIn("claude --model", r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    def test_successor_usage_errors(self) -> None:
        for args, needle in ((["--successor", "claude/claude-opus-5-5", "/compact"], "needs --finish"),
                             (["--finish", "--thinking", "high"], "only go with --successor"),
                             (["--finish", "--successor", "claude/x y"], "plain ids"),
                             (["--finish", "--successor", "/x"], "PROVIDER")):
            r = self.run_ss(*args)
            self.assertEqual(r.returncode, 2, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    def test_successor_dispatched_agent_is_refused(self) -> None:
        for extra in ([], ["--dry-run"]):
            r = self.run_ss(*extra, *self.SUCCESSOR, ACP_RUN_AGENT="1")
            self.assertEqual(r.returncode, 9, r.stdout + r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    def test_successor_dry_run_prints_the_commands_and_runs_nothing(self) -> None:
        r = self.run_ss("--dry-run", *self.SUCCESSOR, **self.succ_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for needle in ("workspace ls --background --json",
                       "run /baton --provider claude/claude-opus-5-5 --thinking high --mode <agent mode>",
                       "--title \"<old name> → claude-opus-5-5\" --no-wait --json",
                       "agent archive -- test-agent", "never --force"):
            self.assertIn(needle, r.stdout)
        self.assertEqual(self.paseo_calls(), [])
        self.assertFalse(self.log.exists())
        self.assertFalse(self.lockdir.exists() and list(self.lockdir.iterdir()))

    def test_successor_takes_the_lifecycle_lock(self) -> None:
        self.lockdir.mkdir(parents=True)
        holder = subprocess.Popen(["sleep", "60"])
        self.children.append(holder.pid)
        self.lifecycle_lock().write_text(self.stamp(holder.pid))
        r = self.run_ss(*self.SUCCESSOR, **self.succ_env())
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertEqual(self.paseo_calls(), [])


if __name__ == "__main__":
    unittest.main()
