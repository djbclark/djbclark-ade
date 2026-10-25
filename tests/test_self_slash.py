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
import json
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("SELF_SLASH_SCRIPT", str(ROOT / "bin" / "self-slash")))


def _bash3() -> str:
    """/bin/bash when it is bash 3.x (macOS ships 3.2), else an empty string."""
    try:
        out = subprocess.run(["/bin/bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return "/bin/bash" if out.stdout.strip() == "3" else ""


BASH3 = _bash3()

FAKE_PASEO = textwrap.dedent("""\
    #!/bin/bash
    # fake paseo: record argv, answer the few calls self-slash makes
    echo "$*" >> "$FAKE_LOG"
    # argv with clear boundaries: a marker line, then one argument per line (adv-selfslash-1, L5)
    { echo "@@call@@"; printf '%s\\n' "$@"; } >> "$FAKE_LOG.argv"
    echo "$1 $2: PASEO_AGENT_ID=${PASEO_AGENT_ID-unset} PASEO_AGENT_CWD=${PASEO_AGENT_CWD-unset}" >> "$FAKE_LOG.env"
    case "$1 $2" in
      "agent inspect")
        if [ "$3" = new-agent-1 ]; then
          [ -n "$FAKE_NEW_STDERR" ] && echo "$FAKE_NEW_STDERR" >&2
          if [ -n "$FAKE_NEW_JSON" ]; then echo "$FAKE_NEW_JSON"; else
          if [ -n "$FAKE_NEW_SEQ" ]; then
            n=$(cat "$FAKE_LOG.n" 2>/dev/null || echo 0); echo $((n+1)) > "$FAKE_LOG.n"
            IFS=, read -ra seq <<< "$FAKE_NEW_SEQ"; FAKE_NEW_STATUS="${seq[$n]:-${seq[${#seq[@]}-1]}}"
            [ "$FAKE_NEW_STATUS" = FAIL ] && { echo "daemon connection lost" >&2; exit 1; }
          fi
          parent=null; [ -n "$FAKE_NEW_PARENT" ] && parent="\\"$FAKE_NEW_PARENT\\""
          printf '{"Id": "new-agent-1", "Model": "%s", "Status": "%s", "ParentAgentId": %s}\\n' \\
            "${FAKE_NEW_MODEL-claude-opus-5-5}" "${FAKE_NEW_STATUS-idle}" "$parent"; fi
        elif [ -n "$FAKE_OLD_JSON" ]; then
          [ -n "$FAKE_OLD_STDERR" ] && echo "$FAKE_OLD_STDERR" >&2
          printf '%s\\n' "$FAKE_OLD_JSON"
        else
          [ -n "$FAKE_OLD_STDERR" ] && echo "$FAKE_OLD_STDERR" >&2
          printf '{"Id": "test-agent", "Name": "%s", "Status": "idle", "Mode": "%s", "Provider": "%s", "Cwd": "%s", "ParentAgentId": null}\\n' \\
            "${FAKE_NAME-Lead}" "${FAKE_OLD_MODE-bypassPermissions}" "${FAKE_OLD_PROVIDER-claude}" "$FAKE_CWD"
        fi;;
      "agent archive")
        if [ -n "$FAKE_ARCHIVE_FAIL" ]; then
          echo "Agent is running. Use --force to archive a running agent (it will interrupt the active run), or stop it first with: paseo agent stop." >&2
          exit 1
        fi
        echo archived;;
      "workspace archive")
        if [ -n "$FAKE_WSARCH_FAIL" ]; then echo "Workspace is busy" >&2; exit 1; fi
        echo archived;;
      "workspace ls")
        if [ -n "$FAKE_WS_JSON" ]; then echo "$FAKE_WS_JSON"
        else printf '[{"workspaceId": "ws-1", "cwd": "%s", "isolation": "local", "background": false}, {"workspaceId": "ws-2", "cwd": "%s", "isolation": "local", "background": false}]\\n' "$FAKE_CWD" "$FAKE_CWD2"; fi;;
      "terminal ls")
        if [ -n "$FAKE_TERM_FAIL" ]; then echo "no daemon" >&2; exit 1; fi
        echo "${FAKE_TERM_JSON-[]}";;
    esac
    case "$1" in
      ls) echo "${FAKE_LS_JSON-[]}";;
      wait) [ -n "$FAKE_WAIT_SLEEP" ] && sleep "$FAKE_WAIT_SLEEP"; echo '{}';;
      send) echo '{}';;
      run)
        if [ -n "$FAKE_RUN_FAIL" ]; then echo "Provider claude is unavailable" >&2; exit 1; fi
        # Paseo prints its status line (and any Node warning) on stderr, the JSON on stdout
        echo "Using workspace ${FAKE_RUN_WS-ws-1}" >&2
        [ -n "$FAKE_RUN_STDERR" ] && echo "$FAKE_RUN_STDERR" >&2
        if [ -n "$FAKE_RUN_JSON" ]; then printf '%s\\n' "$FAKE_RUN_JSON"; else
        echo '{"agentId": "new-agent-1", "status": "created", "provider": "claude", "cwd": "x", "title": "t"}'; fi;;
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
        self.watch = tmp / "fake-watch"
        _ = self.watch.write_text('#!/bin/bash\ncat "$FAKE_WATCH_JSON"\n')
        self.watch.chmod(0o755)
        self.watch_json = tmp / "watch.json"
        _ = self.watch_json.write_text("[]")
        self.calls = tmp / "paseo-calls.txt"
        self.log = self.home / ".local" / "state" / "self-slash.log"
        self.lockdir = self.home / ".local" / "state" / "self-slash"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("HERDR_", "ORCA_", "PASEO_", "SELF_SLASH_", "FAKE_", "ACP_RUN_AGENT"))}
        env.update(HOME=str(self.home), PATH=f"{bindir}:{os.environ['PATH']}",
                   PASEO_AGENT_ID="test-agent", PASEO_CLI=str(fake), FAKE_LOG=str(self.calls),
                   SELF_SLASH_THEN_DELAY="0", SELF_SLASH_WAIT="30",
                   SELF_SLASH_WATCH_CMD=str(self.watch), FAKE_WATCH_JSON=str(self.watch_json))
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

    def argv_of(self, verb: str) -> list[str]:
        """The exact argv (one element per argument) of the first paseo call whose first word is VERB."""
        argv_log = Path(f"{self.calls}.argv")
        blocks = argv_log.read_text().split("@@call@@\n")[1:] if argv_log.exists() else []
        for block in blocks:
            args = block.split("\n")[:-1]
            if args and args[0] == verb:
                return args
        self.fail(f"no {verb} call in {blocks}")

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

    def hold_watch(self, target: str) -> None:
        _ = self.watch_json.write_text(json.dumps([{"domain": "load", "holder": {"target": target, "name": "loadwatch"}},
                                                   {"domain": "paseo", "holder": None}]))

    def test_finish_and_quit_are_refused_for_a_watch_holder(self) -> None:
        self.hold_watch("test-agent")
        for args in (("--finish",), ("/quit",)):
            r = self.run_ss(*args)
            self.assertEqual(r.returncode, 12, r.stderr)
            self.assertIn("holds a watch role", r.stderr)
        self.assertFalse([c for c in self.paseo_calls() if c.startswith("agent archive")], self.paseo_calls())

    def test_finish_is_allowed_for_a_non_holder_and_with_the_override(self) -> None:
        self.hold_watch("some-other-agent")
        self.assertEqual(self.run_ss("--finish").returncode, 0)
        self.wait_log("finish: archived test-agent")
        self.wait_lock_gone()
        self.hold_watch("test-agent")
        r = self.run_ss("--finish", SELF_SLASH_ALLOW_WATCHER="1")
        self.assertEqual(r.returncode, 0, r.stderr)

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
        cwd2 = str(Path(self._tmp.name) / "work2")
        Path(cwd).mkdir(exist_ok=True)
        Path(cwd2).mkdir(exist_ok=True)
        return {"FAKE_CWD": cwd, "FAKE_CWD2": cwd2, "PASEO_AGENT_CWD": cwd,
                "SELF_SLASH_SUCCESSOR_SETTLE": "0", **extra}

    def run_waiter(self, *args: str, interp: str = "", **extra: str) -> subprocess.CompletedProcess[str]:
        """The waiter itself, in the foreground, as the parent spawns it (its exit code is observable).

        INTERP, when given, is the interpreter to run the script with (default: its shebang)."""
        env = {**self.env, **self.succ_env(), "SELF_SLASH_CHILD": "1", "SELF_SLASH_FINISH": "1",
               "SELF_SLASH_SUCCESSOR": "claude/claude-opus-5-5", "SELF_SLASH_S_THINKING": "high", **extra}
        return subprocess.run([*([interp] if interp else []), str(SCRIPT), "--delay", "0", "/quit"], env=env, text=True,
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
            f"--workspace ws-1 --cwd {cwd} --title Lead → opus-5-5 --no-wait --json",
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

    # --- first live run, 2026-10-23: three failures in a row ---
    def test_successor_reads_the_agent_id_from_stdout_beside_stderr_noise(self) -> None:
        # Paseo 0.13.0-beta.1 `run --json` prints "Using workspace <id>" on stderr (console.error), the
        # JSON on stdout; so does a Node warning with brackets, which broke the old merged parse (L4).
        r = self.run_waiter(FAKE_RUN_JSON='{"agentId": "new-agent-1", "status": "running"}',
                            FAKE_RUN_STDERR="(node:1) [DEP0040] DeprecationWarning: the punycode module is deprecated {x}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("archived test-agent (successor new-agent-1)", r.stdout)

    @unittest.skipUnless(BASH3, "/bin/bash is not bash 3.x")
    def test_successor_to_a_non_claude_provider_works_on_bash_3(self) -> None:
        # An empty mode_args array is "unbound variable" under set -u on bash < 4.4 (macOS /bin/bash
        # is 3.2); the other tests run the script's `env bash` shebang (adv-selfslash-1, L2).
        r = self.run_waiter(FAKE_OLD_PROVIDER="omp", FAKE_OLD_MODE="full", FAKE_NEW_MODEL="gpt-5.4",
                            SELF_SLASH_SUCCESSOR="codex/gpt-5.4", interp=BASH3)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("--mode", self.argv_of("run"))

    def test_successor_from_another_provider_never_copies_its_mode(self) -> None:
        # An omp agent's mode "full" is not a claude mode: `paseo run` refused it (AGENT_CREATE_FAILED).
        r = self.run_waiter(FAKE_OLD_PROVIDER="omp", FAKE_OLD_MODE="full")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = next(c for c in self.paseo_calls() if c.startswith("run "))
        self.assertIn("--mode bypassPermissions ", run)
        self.assertNotIn("full", run)

    def test_successor_to_a_non_claude_provider_from_another_provider_passes_no_mode(self) -> None:
        r = self.run_waiter(FAKE_OLD_PROVIDER="omp", FAKE_OLD_MODE="full", FAKE_NEW_MODEL="gpt-5.4",
                            SELF_SLASH_SUCCESSOR="codex/gpt-5.4")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = next(c for c in self.paseo_calls() if c.startswith("run "))
        self.assertNotIn("--mode", run)

    def test_successor_same_provider_still_copies_the_mode(self) -> None:
        r = self.run_waiter(FAKE_OLD_MODE="plan")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--mode plan ", next(c for c in self.paseo_calls() if c.startswith("run ")))

    def make_chain(self, name: str = "SESSION_LOG.md") -> str:
        path = Path(self._tmp.name) / "chains" / "standalone-x" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("chain\n")
        return str(path)

    def test_successor_baton_names_the_chain_log(self) -> None:
        # A lead whose chain lists the repo as a side workspace has no pointer at <repo>/main: a bare
        # /baton resumed another chain's work. --baton PATH gives the successor the chain explicitly.
        chain = self.make_chain()
        _ = self.run_ss(*self.SUCCESSOR, "--baton", chain, **self.succ_env())
        self.wait_log("archived test-agent (successor new-agent-1)")
        # ONE argument "/baton PATH" (the fake logs one argument per line): two would be a /baton with a
        # stray argument for paseo run, not the chain (adv-selfslash-1, L5)
        run = self.argv_of("run")
        self.assertEqual(run[1], f"/baton {chain}", run)
        self.assertEqual(run[2], "--provider", run)
        self.assertEqual(run.count(chain), 0, run)

    def test_baton_flag_needs_successor(self) -> None:
        r = self.run_ss("--finish", "--baton", "/x")
        self.assertEqual(r.returncode, 2)

    def test_l1_baton_must_be_an_absolute_printable_existing_file(self) -> None:
        chain = self.make_chain()
        forged = self.make_chain("a\n2026-10-23 18:00:00 FORGED test-agent: sent compact")
        tabbed = self.make_chain("a\tb")
        for bad, needle in (("SESSION_LOG.md", "absolute"),
                            (str(Path(chain).parent / "missing.md"), "existing regular file"),
                            (str(Path(chain).parent), "existing regular file"),
                            (forged, "printable"),
                            (tabbed, "printable")):
            for run in (lambda b: self.run_ss(*self.SUCCESSOR, "--baton", b, **self.succ_env()),
                        lambda b: self.run_waiter(SELF_SLASH_S_BATON=b)):
                r = run(bad)
                self.assertEqual(r.returncode, 2, f"{bad!r}: {r.stdout}{r.stderr}")
                self.assertIn(needle, r.stderr)
        self.assertEqual(self.paseo_calls(), [])
        self.assertNotIn("FORGED", self.log_text())
        r = self.run_waiter(SELF_SLASH_S_BATON=chain)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'prompt "/baton {chain}"', r.stdout)

    def test_successor_run_failure_exits_11_and_archives_nothing(self) -> None:
        r = self.run_waiter(FAKE_RUN_FAIL="1")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("successor: paseo run failed", r.stdout)
        self.assertIn("NOT archived", r.stdout)
        self.assertFalse(any(c.startswith("agent archive") for c in self.paseo_calls()))
        self.assertIn("Provider claude is unavailable", r.stdout)  # stderr of paseo run, only in the failure

    def test_successor_that_is_a_subagent_exits_11_and_archives_nothing(self) -> None:
        r = self.run_waiter(FAKE_NEW_PARENT="test-agent")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("is a subagent", r.stdout)
        self.assertFalse(any(c.startswith("agent archive") for c in self.paseo_calls()))

    def test_successor_on_the_wrong_model_or_in_error_exits_11(self) -> None:
        for extra, needle in ((dict(FAKE_NEW_MODEL="claude-sonnet-5-5"), "not claude-opus-5-5"),
                              (dict(FAKE_NEW_STATUS="error"), "in status 'error'")):
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

    def fake_herdr(self, known: str = "p1") -> None:
        """A herdr that knows exactly one pane (`pane get` is what self-slash asks), else pane_not_found."""
        fake = Path(self.env["PATH"].split(":")[0]) / "herdr"
        _ = fake.write_text('#!/bin/bash\nif [ "$1 $2" = "pane get" ] && [ "$3" = "%s" ]; then\n'
                            '  echo \'{"result":{"pane":{"pane_id":"%s","agent":"claude"}}}\'; exit 0; fi\n'
                            'echo \'{"error":{"code":"pane_not_found"}}\'; exit 1\n' % (known, known))
        fake.chmod(0o755)

    def test_herdr_is_the_host_when_herdr_knows_the_pane(self) -> None:
        # 1eda130 gated this on PASEO_SELF_TRUST_HERDR, which nothing sets: herdr sessions fell through
        self.fake_herdr()
        r = self.run_ss("--dry-run", "/new", HERDR_ENV="1", HERDR_PANE_ID="p1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would send to herdr p1", r.stdout + r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    def test_a_pane_herdr_does_not_know_is_not_a_host(self) -> None:
        # a Cline tool shell inherits the hub daemon's stale HERDR_PANE_ID: never type into it
        self.fake_herdr()
        r = self.run_ss("--dry-run", "/new", HERDR_ENV="1", HERDR_PANE_ID="w2F:p34")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would send to paseo test-agent", r.stdout + r.stderr)

    def test_a_claude_session_is_never_discovered_through_the_cline_hub(self) -> None:
        # paseo-self names the newest tool.started in the hub, another Cline agent's when the caller is Claude
        self.fake_herdr()
        env = {k: v for k, v in self.env.items() if k != "PASEO_AGENT_ID"}
        r = subprocess.run([str(SCRIPT), "--delay", "0", "--dry-run", "/new"], text=True, capture_output=True,
                           timeout=60, check=False, env={**env, "HERDR_ENV": "1", "HERDR_PANE_ID": "w2F:p34", "CLAUDECODE": "1"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("never discovered through the Cline hub", r.stderr)

    def test_successor_outside_paseo_exits_2(self) -> None:
        fake_orca = Path(self.env["PATH"].split(":")[0]) / "orca"
        _ = fake_orca.write_text("#!/bin/bash\nexit 0\n")
        fake_orca.chmod(0o755)
        self.fake_herdr()
        for host_env in (dict(ORCA_TERMINAL_HANDLE="t1"),):
            r = self.run_ss(*self.SUCCESSOR, **host_env)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("successor needs Paseo or herdr", r.stderr)
            self.assertIn("claude --model", r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    def test_herdr_successor_dry_run_names_launch_py(self) -> None:
        self.fake_herdr()
        r = self.run_ss("--dry-run", "--finish", "--successor", "claude/claude-sonnet-5-5", "--thinking", "medium",
                        HERDR_ENV="1", HERDR_PANE_ID="p1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("launch.py successor --pane p1 --model claude-sonnet-5-5 --effort medium", r.stdout)
        self.assertIn("never closed", r.stdout)

    def test_herdr_successor_takes_claude_only_and_no_paseo_options(self) -> None:
        self.fake_herdr()
        for args, needle in ((["--successor", "omp/anthropic/claude-opus-5-5"], "claude/MODEL"),
                             (["--successor", "claude"], "claude/MODEL"),
                             (["--successor", "claude/claude-opus-5-5", "--title", "x"], "Paseo options"),
                             (["--successor", "claude/claude-opus-5-5", "--keep-workspace"], "Paseo options")):
            r = self.run_ss("--dry-run", "--finish", *args, HERDR_ENV="1", HERDR_PANE_ID="p1")
            self.assertEqual(r.returncode, 2, f"{args}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stderr)

    def test_herdr_successor_hands_the_work_to_launch_py_and_keeps_its_exit(self) -> None:
        self.fake_herdr()
        stub = Path(self.env["PATH"].split(":")[0]) / "launch-stub.sh"
        argv = Path(f"{self.calls}.launch")
        _ = stub.write_text(f'#!/bin/bash\nprintf \'%s\\n\' "$@" > {argv}\nexit ${{STUB_RC:-0}}\n')
        stub.chmod(0o755)
        chain = Path(self.env["PATH"].split(":")[0]) / "SESSION_LOG.md"
        _ = chain.write_text("x")
        env = dict(HERDR_ENV="1", HERDR_PANE_ID="p1", SELF_SLASH_LAUNCH=str(stub), STUB_RC="11")
        r = self.run_ss("--finish", "--successor", "claude/claude-sonnet-5-5", "--thinking", "medium",
                        "--baton", str(chain), **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.wait_log("successor path ended with exit 11")
        self.assertEqual(argv.read_text().split(), ["successor", "--pane", "p1", "--model", "claude-sonnet-5-5",
                                                    "--effort", "medium", "--wait", "30", "--baton", str(chain)])
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
                       "run \"/baton\" --provider claude/claude-opus-5-5 --thinking high --mode <agent mode if the same provider; claude: bypassPermissions; else none>",
                       "--title \"<old name> → opus-5-5\" --no-wait --json",
                       "never --new-workspace", "workspace archive -- <old id>", "terminal ls --workspace <old id> --json",
                       "isolation local (never a worktree)", "polled up to 0s",
                       "agent archive -- test-agent", "never --force"):
            self.assertIn(needle, r.stdout)
        self.assertEqual(self.paseo_calls(), [])
        self.assertFalse(self.log.exists())
        self.assertFalse(self.lockdir.exists() and list(self.lockdir.iterdir()))

    def test_successor_dry_run_prints_a_given_mode_once(self) -> None:
        # `${s_mode:- ...}` expanded to the mode itself: "--mode planplan" (adv-selfslash-1, L3)
        r = self.run_ss("--dry-run", *self.SUCCESSOR, "--mode", "plan", **self.succ_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--thinking high --mode plan --workspace <id>", r.stdout)
        self.assertNotIn("planplan", r.stdout)
        self.assertNotIn("<agent mode", r.stdout)

    def test_successor_takes_the_lifecycle_lock(self) -> None:
        self.lockdir.mkdir(parents=True)
        holder = subprocess.Popen(["sleep", "60"])
        self.children.append(holder.pid)
        self.lifecycle_lock().write_text(self.stamp(holder.pid))
        r = self.run_ss(*self.SUCCESSOR, **self.succ_env())
        self.assertEqual(r.returncode, 7, r.stdout + r.stderr)
        self.assertEqual(self.paseo_calls(), [])

    # --- workspace rules (lead steers 1 and 2, 2026-10-23) ---
    def run_calls(self) -> str:
        return next(c for c in self.paseo_calls() if c.startswith("run "))

    def test_successor_never_creates_or_renames_a_workspace(self) -> None:
        r = self.run_waiter()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.paseo_calls()
        self.assertIn("--workspace ws-1 ", self.run_calls())
        self.assertFalse(any("--new-workspace" in c or "--worktree" in c for c in calls), calls)
        self.assertFalse(any(c.startswith(("workspace create", "workspace rename")) for c in calls), calls)
        # the successor shares this agent's workspace: archiving it would take the successor along
        self.assertFalse(any(c.startswith("workspace archive") for c in calls), calls)
        self.assertIn("workspace: ws-1 kept: the successor lives in it", r.stdout)

    def test_default_title_is_short(self) -> None:
        r = self.run_waiter(FAKE_NAME="A very long orchestrator session name that goes on and on")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        title = self.run_calls().split(" --title ")[1].split(" --no-wait")[0]
        self.assertEqual(title, "A very long orchestrator → opus-5-5")
        self.assertLessEqual(len(title), 40)

    def calls_of(self, *prefixes: str) -> list[str]:
        return [c for c in self.paseo_calls() if c.startswith(prefixes)]

    def archived_workspaces(self) -> list[str]:
        return self.calls_of("workspace archive")

    def test_old_workspace_is_archived_when_proven_unneeded(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        # the successor and the old agent do not count, an agent elsewhere does not either
        ls = (f'[{{"id": "new-agent-1", "shortId": "new-age", "cwd": "{cwd2}"}},'
              f' {{"id": "test-agent", "shortId": "test-ag", "cwd": "{cwd}"}},'
              ' {"id": "zzz", "shortId": "zzz", "cwd": "/somewhere/else"}]')
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_LS_JSON=ls)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.paseo_calls()
        # H1: the successor runs in the target workspace's own cwd, not this agent's
        self.assertIn(f"--workspace ws-2 --cwd {cwd2} ", self.run_calls())
        steps = [c for c in calls if c.startswith(("agent archive", "terminal ls", "ls ", "workspace archive"))]
        self.assertEqual(steps, ["agent archive -- test-agent", "terminal ls --workspace ws-1 --json",
                                 "ls --background --json", "workspace archive -- ws-1"])
        self.assertIn("workspace: archived ws-1", r.stdout)

    def test_old_workspace_is_kept_while_another_agent_may_be_in_it(self) -> None:
        cwd = self.succ_env()["FAKE_CWD"]
        rows = (
            f'[{{"id": "other-1", "shortId": "other-1", "cwd": "{cwd}"}}]',
            f'[{{"id": "other-1", "shortId": "other-1", "cwd": "{cwd}/sub/dir"}}]',  # M2: another cwd below it
            '[{"id": "other-1", "shortId": "other-1", "workspaceId": "ws-1", "cwd": "/elsewhere"}]',  # by id
            '[{"id": "other-1", "shortId": "other-1"}]',  # a row with no cwd: unknown, so kept
            "not json",
        )
        for ls in rows:
            self.calls.unlink(missing_ok=True)
            r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_LS_JSON=ls)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.archived_workspaces(), [], ls)
            self.assertIn("kept: other agents in it or below", r.stdout)

    def test_agent_rows_with_a_workspace_id_are_counted_by_it_not_by_cwd(self) -> None:
        cwd = self.succ_env()["FAKE_CWD"]
        ls = f'[{{"id": "o", "shortId": "o", "workspaceId": "ws-2", "cwd": "{cwd}"}}]'
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_LS_JSON=ls)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archived_workspaces(), ["workspace archive -- ws-1"])

    def test_h1_old_workspace_containing_the_successors_cwd_is_kept(self) -> None:
        cwd = self.succ_env()["FAKE_CWD"]
        ws = (f'[{{"workspaceId": "ws-1", "cwd": "{cwd}", "isolation": "local"}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd}/inner", "isolation": "local"}}]')
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_WS_JSON=ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"--workspace ws-2 --cwd {cwd}/inner ", self.run_calls())
        self.assertEqual(self.archived_workspaces(), [])
        self.assertIn("equals or contains the successor cwd", r.stdout)

    def test_h1_target_workspace_must_exist_and_gives_the_cwd(self) -> None:
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-nope")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("not in workspace ls", r.stdout)
        self.assertEqual(self.calls_of("run ", "agent archive"), [])

    def test_h1_worktree_or_unknown_isolation_is_never_archived(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        for iso in ('"isolation": "worktree", ', ""):
            ws = (f'[{{"workspaceId": "ws-1", {iso}"cwd": "{cwd}"}},'
                  f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
            r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_WS_JSON=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.archived_workspaces(), [])
            self.assertIn("archive it yourself", r.stdout)

    def test_h1_terminals_keep_the_workspace(self) -> None:
        for extra in (dict(FAKE_TERM_JSON='[{"id": "t1", "workspaceId": "ws-1"}]'), dict(FAKE_TERM_JSON="not json"),
                      dict(FAKE_TERM_FAIL="1")):
            r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", **extra)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.archived_workspaces(), [], extra)
            self.assertRegex(r.stdout, r"workspace: ws-1 kept: (terminals in it|terminal ls failed)")

    def test_m1_override_that_is_not_this_agents_workspace_is_never_archived(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        ws = (f'[{{"workspaceId": "ws-foreign", "cwd": "/somewhere/else", "isolation": "local"}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", SELF_SLASH_WORKSPACE="ws-foreign", FAKE_WS_JSON=ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archived_workspaces(), [])
        self.assertIn("never archived", r.stdout)
        # an override whose own row has this agent's cwd is proven
        ws = (f'[{{"workspaceId": "mine", "cwd": "{cwd}", "isolation": "local"}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", SELF_SLASH_WORKSPACE="mine", FAKE_WS_JSON=ws)
        self.assertEqual(self.archived_workspaces(), ["workspace archive -- mine"])

    def test_m1_prefer_foreground_tie_break_places_but_never_archives(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        ws = (f'[{{"workspaceId": "ws-main", "cwd": "{cwd}", "isolation": "local", "background": false}},'
              f' {{"workspaceId": "ws-bg", "cwd": "{cwd}", "isolation": "local", "background": true}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_WS_JSON=ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archived_workspaces(), [])
        self.assertIn("picked by preference and is never archived", r.stdout)
        # ... and without --workspace it still places the successor in the foreground one
        self.calls.unlink()
        r = self.run_waiter(FAKE_WS_JSON=ws)
        self.assertIn("--workspace ws-main ", self.run_calls())

    def test_keep_workspace_skips_the_close(self) -> None:
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", SELF_SLASH_S_KEEPWS="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls_of("workspace archive", "ls ", "terminal ls"), [])
        self.assertIn("workspace: kept (--keep-workspace)", r.stdout)

    def test_workspace_archive_failure_keeps_it_without_failing_the_handoff(self) -> None:
        r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_WSARCH_FAIL="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("workspace: ws-1 kept: workspace archive failed", r.stdout)

    # --- adversary round 1 low findings ---
    def test_l1_new_id_must_be_a_single_new_agent(self) -> None:
        for run_json, needle in (('{"agentId": "test-agent"}', "own id"),
                                 ('{"agentId": "test-ag"}', "own id"),
                                 ('[{"agentId": "sub-x"}]', "no single agent object"),
                                 ('{"status": "created"}', "no single agent object"),
                                 ('{"agentId": "a b"}', "unusable agent id")):
            r = self.run_waiter(FAKE_RUN_JSON=run_json)
            self.assertEqual(r.returncode, 11, f"{run_json}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stdout)
        self.assertEqual(self.calls_of("agent archive"), [])

    def test_l5_a_run_output_that_is_not_one_object_exits_11_and_archives_nothing(self) -> None:
        # The two worst cases of adv-selfslash-1 plus the plain two-objects case: whatever stdout holds
        # that is not exactly one JSON object must never pick an id, so nothing is archived.
        for run_json in ('Using workspace ws-1\n{"agentId":"new-agent-1"}\n{"agentId":"victim"}',
                         '[w]\n{"agentId":"new-agent-1"}',
                         '{"agentId":"new-agent-1"}\n{"agentId":"victim"}',
                         'Using workspace ws-1\n{"agentId":"new-agent-1"}'):
            r = self.run_waiter(FAKE_RUN_JSON=run_json)
            self.assertEqual(r.returncode, 11, f"{run_json!r}: {r.stdout}{r.stderr}")
            self.assertIn("no single agent object", r.stdout)
        self.assertEqual(self.calls_of("agent archive"), [])

    # --- adversary round 2 low findings ---
    def test_l1_stderr_on_this_agents_inspect_keeps_the_old_mode(self) -> None:
        # stderr text on `agent inspect` once emptied Name/Mode/Cwd/Provider and a plan-mode agent got a
        # bypassPermissions successor (adv-selfslash-2, L1)
        r = self.run_waiter(FAKE_OLD_MODE="plan", FAKE_OLD_STDERR="(node:1) ExperimentalWarning: x [y] {z}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.argv_of("run")
        self.assertEqual(run[run.index("--mode") + 1], "plan", run)

    def test_l1_this_agents_inspect_that_is_not_one_object_fails_closed(self) -> None:
        for old_json in ("not json", '[{"Mode": "plan"}]', "{}", '{"Id": "test-agent", "Mode": "plan"}\n{"Id": "x"}',
                         "Using x\n" + '{"Id": "test-agent", "Mode": "plan"}'):
            r = self.run_waiter(FAKE_OLD_JSON=old_json, FAKE_OLD_STDERR="warn")
            self.assertEqual(r.returncode, 11, f"{old_json!r}: {r.stdout}{r.stderr}")
            self.assertIn("inspect of this agent printed no single JSON object", r.stdout)
            self.assertIn("nothing was started", r.stdout)
        self.assertEqual(self.calls_of("run "), [])
        self.assertEqual(self.calls_of("agent archive"), [])

    def test_l1_stderr_on_the_successors_inspect_is_not_a_failure(self) -> None:
        r = self.run_waiter(FAKE_NEW_STDERR="(node:1) [DEP0040] DeprecationWarning {x}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("archived test-agent (successor new-agent-1)", r.stdout)

    def test_l2_no_stderr_file_is_left_behind_by_any_paseo_call(self) -> None:
        for extra in ({}, {"FAKE_RUN_FAIL": "1"}, {"FAKE_NEW_STDERR": "w"}, {"FAKE_OLD_STDERR": "w"},
                      {"FAKE_OLD_JSON": "not json"}, {"FAKE_NEW_JSON": "not json"}):
            _ = self.run_waiter(**extra)
            self.assertEqual([p.name for p in self.lockdir.glob("*err*")], [], extra)
        self.assertEqual([p for p in Path(self._tmp.name).rglob("tmp.*")], [])

    # --- adversary round 3 (F1): no mode this agent did not have ---
    OLD_BASE = '"Id": "test-agent", "Name": "Lead", "Status": "idle", "Cwd": "%s", "ParentAgentId": null'

    def old_json(self, *extra: str) -> str:
        return "{" + ", ".join([self.OLD_BASE % self.succ_env()["FAKE_CWD"], *extra]) + "}"

    def test_f1_an_inspect_without_a_provider_or_a_mode_value_starts_nothing(self) -> None:
        # P1 no Provider key, P2 Provider null, P3 no Mode key; P4 Mode null.  A plan agent must not
        # get bypassPermissions (or "default") because its inspect lacked a field.
        for extra, needle in ((['"Mode": "plan"'], "no Provider"),
                              (['"Mode": "plan"', '"Provider": null'], "no Provider"),
                              (['"Mode": "plan"', '"Provider": ""'], "no Provider"),
                              (['"Provider": "claude"'], "no Mode value"),
                              (['"Provider": "claude"', '"Mode": null'], "no Mode value"),
                              # adv-selfslash-4 F1: present but not a plain string id
                              (['"Mode": "plan"', '"Provider": {"id": "claude"}'], "no Provider"),
                              (['"Mode": "plan"', '"Provider": "Claude"'], "not a plain provider id"),
                              (['"Mode": "plan"', '"Provider": " claude"'], "not a plain provider id"),
                              (['"Provider": "claude"', '"Mode": {"id": "plan"}'], "no Mode value"),
                              (['"Provider": "claude"', '"Mode": false'], "no Mode value"),
                              (['"Provider": "claude"', '"Mode": "plan mode"'], "not a plain mode name")):
            r = self.run_waiter(FAKE_OLD_JSON=self.old_json(*extra))
            self.assertEqual(r.returncode, 11, f"{extra}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stdout)
            self.assertIn("nothing was started", r.stdout)
        self.assertEqual(self.calls_of("run "), [])
        self.assertEqual(self.calls_of("agent archive"), [])

    @unittest.skipUnless(BASH3, "/bin/bash is not bash 3.x")
    def test_f1_plain_id_guards_hold_on_bash_3_in_a_utf8_locale(self) -> None:
        # bash 3.2 matches a bracket range ([a-z]) by locale collation: under en_US.UTF-8 it took
        # "Claude", so a plan agent got a bypassPermissions claude successor (adversary pr35 B1).
        for provider in ("Claude", "cLAUDE", "é"):
            r = self.run_waiter(FAKE_OLD_JSON=self.old_json('"Mode": "plan"', f'"Provider": "{provider}"'),
                                LC_ALL="en_US.UTF-8", interp=BASH3)
            self.assertEqual(r.returncode, 11, f"{provider}: {r.stdout}{r.stderr}")
            self.assertIn("not a plain provider id", r.stdout)
        self.assertEqual(self.calls_of("run "), [])
        self.assertEqual(self.calls_of("agent archive"), [])

    def test_f1_plain_id_guard_holds_with_an_inherited_nocasematch(self) -> None:
        # bash >= 4.1 applies an exported BASHOPTS at startup: nocasematch made the Provider guard
        # case-blind, so "Claude" took the bypassPermissions branch (adversary pr35 round 2, L1).
        r = self.run_waiter(FAKE_OLD_JSON=self.old_json('"Mode": "plan"', '"Provider": "Claude"'),
                            BASHOPTS="nocasematch")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("not a plain provider id", r.stdout)
        self.assertEqual(self.calls_of("run "), [])

    def test_f1_an_explicit_mode_needs_nothing_from_the_inspect(self) -> None:
        r = self.run_waiter(FAKE_OLD_JSON=self.old_json(), SELF_SLASH_S_MODE="plan")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.argv_of("run")
        self.assertEqual(run[run.index("--mode") + 1], "plan", run)

    def test_f1_an_empty_mode_of_the_same_provider_passes_no_mode(self) -> None:
        # "Mode": "" is a mode value (none set): the provider's own default, never a made-up "default"
        r = self.run_waiter(FAKE_OLD_MODE="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.argv_of("run")
        self.assertNotIn("--mode", run)
        self.assertNotIn("default", run)

    def test_l2_top_level_check_needs_the_parent_and_status_keys(self) -> None:
        for new_json, needle in (('{"Model": "claude-opus-5-5", "Status": "idle", "parentAgentId": "test-agent"}', "no ParentAgentId"),
                                 ('{"Model": "claude-opus-5-5", "ParentAgentId": null}', "no Status key"),
                                 ('not json', "no ParentAgentId")):
            r = self.run_waiter(FAKE_NEW_JSON=new_json)
            self.assertEqual(r.returncode, 11, f"{new_json}: {r.stdout}{r.stderr}")
            self.assertIn(needle, r.stdout)
        self.assertEqual(self.calls_of("agent archive"), [])

    def test_l6_only_idle_running_initializing_pass_and_late_errors_are_seen(self) -> None:
        for status in ("idle", "running", "initializing"):
            self.assertEqual(self.run_waiter(FAKE_NEW_STATUS=status).returncode, 0, status)
        for status in ("closed", "stopped", "error", ""):
            r = self.run_waiter(FAKE_NEW_STATUS=status)
            self.assertEqual(r.returncode, 11, f"{status}: {r.stdout}{r.stderr}")
        self.calls.unlink(missing_ok=True)
        r = self.run_waiter(FAKE_NEW_SEQ="initializing,error", SELF_SLASH_SUCCESSOR_SETTLE="60")  # exits at the 2nd look, load-proof
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("in status 'error'", r.stdout)
        self.assertEqual(self.calls_of("agent archive"), [])
        self.assertEqual(len(self.calls_of("agent inspect new-agent-1")), 2)

    def test_l3_a_value_flag_as_the_last_argument_is_a_usage_error(self) -> None:
        for flag in ("--successor", "--thinking", "--mode", "--title", "--workspace", "--delay", "--then"):
            args = [*self.SUCCESSOR, flag] if flag != "--successor" else ["--finish", flag]
            r = subprocess.run([str(SCRIPT), *args], env={**self.env, **self.succ_env()}, text=True,
                               capture_output=True, timeout=10, check=False)
            self.assertEqual(r.returncode, 2, f"{flag}: {r.stdout}{r.stderr}")
            self.assertIn("needs a value", r.stderr)

    def test_l4_control_characters_cannot_forge_a_log_line(self) -> None:
        forged = "2026-10-23 07:00:00 paseo test-agent: sent /compact"
        r = self.run_waiter(SELF_SLASH_S_TITLE=f"x\n{forged}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(any(line.startswith(forged) for line in r.stdout.splitlines()), r.stdout)
        self.assertIn("--title x2026-10-23", self.run_calls())
        # even the joined text must not read as a sent /compact to the 30-minute gap check
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text(r.stdout)
        r2 = self.run_ss("--dry-run", "/compact x")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        # a real sent line still refuses
        self.log.write_text(f"{time.strftime('%F %T')} paseo test-agent: sent /compact\n")
        self.assertEqual(self.run_ss("--dry-run", "/compact x").returncode, 7)

    def test_workspace_flags_reach_the_waiter(self) -> None:
        r = self.run_ss(*self.SUCCESSOR, "--workspace", "ws-2", "--keep-workspace", **self.succ_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.wait_log("workspace: kept (--keep-workspace)")
        self.assertIn("--workspace ws-2 ", self.run_calls())
        r = self.run_ss("--finish", "--keep-workspace")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.run_ss(*self.SUCCESSOR, "--workspace", "w s")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    # --- adversary round 2 lows ---
    def test_r2_l1_a_malformed_settle_is_refused_before_run_and_never_archives(self) -> None:
        marker = Path(self._tmp.name) / "PWNED"
        for value in ("20s", "", "1+1", "-5", f"PATH[$(touch {marker})]"):
            self.calls.unlink(missing_ok=True)
            r = self.run_waiter(SELF_SLASH_SUCCESSOR_SETTLE=value)
            self.assertEqual(r.returncode, 11, f"{value!r}: {r.stdout}{r.stderr}")
            self.assertIn("must be whole seconds", r.stdout)
            self.assertEqual(self.calls_of("run ", "agent archive"), [], value)
            self.assertFalse(marker.exists())
        # a plain integer, 0 included, still works
        self.assertEqual(self.run_waiter(SELF_SLASH_SUCCESSOR_SETTLE="0").returncode, 0)

    def test_r2_l1_the_bare_archive_is_unreachable_with_a_successor(self) -> None:
        # a --successor chain must never reach finish_paseo: the guard before it exits 11
        text = SCRIPT.read_text()
        self.assertIn('[ -z "$successor" ]; then finish_paseo; fi', text)
        self.assertIn("successor path aborted; NOT archived", text)

    def test_r2_l2_an_inspect_failing_after_a_good_look_is_exit_11(self) -> None:
        r = self.run_waiter(FAKE_NEW_SEQ="idle,FAIL", SELF_SLASH_SUCCESSOR_SETTLE="60")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("answered inspect once and then failed", r.stdout)
        self.assertEqual(self.calls_of("agent archive"), [])
        self.assertEqual(len(self.calls_of("agent inspect new-agent-1")), 2)
        # failing every time is still the old "never answered" exit 11
        r = self.run_waiter(FAKE_NEW_SEQ="FAIL", SELF_SLASH_SUCCESSOR_SETTLE="0")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)

    def test_r2_l3_override_is_proven_only_as_the_single_row_with_this_cwd(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        # shape 1: a sibling workspace with the same cwd named by the override
        ws = (f'[{{"workspaceId": "mine", "cwd": "{cwd}", "isolation": "local"}},'
              f' {{"workspaceId": "sibling", "cwd": "{cwd}", "isolation": "local"}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
        for override in ("sibling", "mine"):
            self.calls.unlink(missing_ok=True)
            r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", SELF_SLASH_WORKSPACE=override, FAKE_WS_JSON=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.archived_workspaces(), [], override)
            self.assertIn("never archived", r.stdout)

    def test_r2_l3_a_workspace_above_the_cwd_means_no_proof(self) -> None:
        env = self.succ_env()
        cwd, cwd2 = env["FAKE_CWD"], env["FAKE_CWD2"]
        parent = str(Path(cwd).parent)
        # shape 2: the agent lives in a subdirectory of workspace "top"; "sub" has exactly that cwd
        ws = (f'[{{"workspaceId": "top", "cwd": "{parent}", "isolation": "local"}},'
              f' {{"workspaceId": "sub", "cwd": "{cwd}", "isolation": "local"}},'
              f' {{"workspaceId": "ws-2", "cwd": "{cwd2}", "isolation": "local"}}]')
        for extra in ({}, {"SELF_SLASH_WORKSPACE": "sub"}):
            self.calls.unlink(missing_ok=True)
            r = self.run_waiter(SELF_SLASH_S_WORKSPACE="ws-2", FAKE_WS_JSON=ws, **extra)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(self.archived_workspaces(), [], extra)
            self.assertRegex(r.stdout, r"workspace: sub kept: .*(above|never archived)")


if __name__ == "__main__":
    unittest.main()
