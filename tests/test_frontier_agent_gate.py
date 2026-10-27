"""claude/hooks/frontier_agent_gate.py: Agent-tool sub-agents on Fable or astra are logged and asked."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HOOK = Path(__file__).resolve().parents[1] / "claude/hooks/frontier_agent_gate.py"


class TestFrontierAgentGate(unittest.TestCase):
    def run_hook(self, tool_input: dict, tool: str = "Agent", home: Path | None = None, **env: str) -> tuple[dict | None, Path]:
        home = home or Path(tempfile.mkdtemp(prefix="fgate-"))
        base = {k: v for k, v in os.environ.items() if k not in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF")}
        proc = subprocess.run(["python3", str(HOOK)], input=json.dumps(
            {"tool_name": tool, "tool_input": tool_input, "session_id": "s1", "cwd": "/x"}),
            capture_output=True, text=True, env={**base, "HOME": str(home), **env}, check=True, timeout=10)
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        return out, home / ".local/state/frontier-gate/agent-calls.jsonl"

    def test_fable_deep_asks_and_logs(self):
        out, log = self.run_hook({"subagent_type": "fable-deep", "description": "adjudicate"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        row = json.loads(log.read_text())
        self.assertEqual(row["subagent_type"], "fable-deep")

    def test_model_fable_asks(self):
        for tool_input in ({"subagent_type": "general-purpose", "model": "fable"},
                           {"subagent_type": "backend", "model": "Fable"}):
            out, _ = self.run_hook(tool_input)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask", tool_input)

    def test_retired_ocx_agents_no_longer_gate(self):
        # the opencodex proxy and its ocx-* sub-agents were uninstalled 2026-10-19
        for tool_input in ({"subagent_type": "ocx-self"}, {"subagent_type": "ocx-gpt-6-astra"}):
            out, log = self.run_hook(tool_input)
            self.assertIsNone(out, tool_input)
            self.assertFalse(log.exists())

    def test_ordinary_agents_pass_silently(self):
        for tool_input in ({"subagent_type": "Explore"}, {"subagent_type": "general-purpose", "model": "opus"}):
            out, log = self.run_hook(tool_input)
            self.assertIsNone(out)
            self.assertFalse(log.exists())
        out, _ = self.run_hook({"command": "ls"}, tool="Bash")
        self.assertIsNone(out)

    def test_approval_logs_without_asking(self):
        out, log = self.run_hook({"subagent_type": "fable-deep"}, ACP_OPERATOR_APPROVED="omp,fable-deep")
        self.assertIsNone(out)
        self.assertTrue(json.loads(log.read_text())["approved_env"])


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


REASON = "frontier-reason: the cross-file invariant needs frontier-level adjudication"


class TestAwayAllowance(unittest.TestCase):
    """C6 of docs/model-tiers-design.md: each step, the cap boundary and the spoofing cases (2026-10-27)."""

    run_hook = TestFrontierAgentGate.run_hook

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="fgate-away-"))
        self.state = self.home / "ade"
        self.state.mkdir()
        self.log = self.home / ".local/state/frontier-gate/agent-calls.jsonl"
        self.counter = self.home / ".local/state/frontier-gate/agent-calls-day.json"

    def profile(self, **over):
        now = datetime.now(UTC)
        s = {"schema": 1, "profile": "away", "since": _ts(now - timedelta(hours=1)), "until": _ts(now + timedelta(hours=60)),
             "reason": "away", "set_by": "test", **over}
        path = self.state / "gate-profile.json"
        path.write_text(json.dumps(s))
        return str(path)

    def guard(self, **over):
        st = {"level": "ok", "reasons": [], "stale": False, "fable_left": 60.0,
              "checked_at": _ts(datetime.now(UTC) - timedelta(minutes=5)), **over}
        st = {k: v for k, v in st.items() if v is not None}
        path = self.state / "quota-guard.json"
        path.write_text(json.dumps(st))
        return str(path)

    def call(self, prompt: str | None = REASON, profile=True, guard=True, tool_input=None, env=None):
        env = {"GATE_PROFILE_STATE": self.profile() if profile is True else (profile or str(self.state / "none.json")),
               "CLAUDE_QUOTA_GUARD_STATE": self.guard() if guard is True else (guard or str(self.state / "none2.json")),
               **(env or {})}
        ti = {"subagent_type": "general-purpose", "model": "fable", "description": "adjudicate",
              **({"prompt": prompt} if prompt is not None else {}), **(tool_input or {})}
        out, _ = self.run_hook(ti, home=self.home, **env)
        return out

    def rows(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def assertAsks(self, out, why=None):
        self.assertIsNotNone(out)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        if why:
            self.assertIn(why, out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_away_with_a_reason_is_allowed_and_logged(self):
        self.assertIsNone(self.call())
        row = self.rows()[-1]
        self.assertEqual((row["decision"], row["profile"], row["n_today"]), ("allowed-judged", "away", 1))
        self.assertEqual(row["frontier_reason"], REASON.split(": ", 1)[1])
        self.assertIsNotNone(row["profile_until"])
        self.assertEqual(json.loads(self.counter.read_text())["n"], 1)

    def test_baseline_asks_whatever_the_prompt_says(self):
        out = self.call(profile=False)                       # no profile file: baseline, calls_per_day 0
        self.assertAsks(out)
        self.assertNotIn("away allowance", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.rows()[-1]["decision"], "asked")

    def test_an_expired_profile_gives_baseline(self):
        now = datetime.now(UTC)
        path = self.profile(since=_ts(now - timedelta(hours=80)), until=_ts(now - timedelta(minutes=1)))
        self.assertAsks(self.call(profile=path))
        self.assertFalse(self.counter.exists())

    def test_a_profile_that_expires_between_two_calls_ends_the_allowance(self):
        self.assertIsNone(self.call())
        now = datetime.now(UTC)
        path = self.profile(since=_ts(now - timedelta(hours=80)), until=_ts(now - timedelta(seconds=1)))
        self.assertAsks(self.call(profile=path))

    def test_a_missing_or_unreadable_guard_state_asks(self):
        self.assertAsks(self.call(guard=False), "missing or unreadable")
        bad = self.state / "bad.json"
        bad.write_text("{")
        self.assertAsks(self.call(guard=str(bad)), "missing or unreadable")

    def test_a_stale_or_future_guard_state_asks(self):
        for minutes in (31, -5):
            old = self.guard(checked_at=_ts(datetime.now(UTC) - timedelta(minutes=minutes)))
            self.assertAsks(self.call(guard=old), "min old")
        self.assertIsNone(self.call(guard=self.guard(checked_at=_ts(datetime.now(UTC) - timedelta(minutes=29)))))

    def test_guard_levels_and_reasons(self):
        cases = [({"level": "tight"}, "tight"), ({"level": "critical"}, "critical"), ({"level": "bogus"}, "bogus"),
                 ({"stale": True}, "stale"), ({"stale": None}, "stale"),
                 ({"level": "watch", "reasons": ["fable"]}, "reason other than the weekly"),
                 ({"level": "watch", "reasons": ["weekly", "alert"]}, "reason other than the weekly"),
                 ({"level": "watch", "reasons": []}, "reason other than the weekly"),
                 ({"level": "watch", "reasons": None}, "reason other than the weekly"),
                 ({"level": "ok", "reasons": ["weekly"]}, "at level ok")]
        for over, why in cases:
            self.assertAsks(self.call(guard=self.guard(**over)), why)
        self.assertIsNone(self.call(guard=self.guard(level="watch", reasons=["weekly"])))     # the one watch that spends

    def test_the_frontier1_cap_floor_boundary(self):
        self.assertAsks(self.call(guard=self.guard(fable_left=9.9)), "frontier-1 cap has 9.9%")
        self.assertAsks(self.call(guard=self.guard(fable_left=None)), "fable_left")
        self.assertAsks(self.call(guard=self.guard(fable_left="60")), "fable_left")
        self.assertIsNone(self.call(guard=self.guard(fable_left=10.0)))

    def test_no_reason_asks_and_names_the_format(self):
        out = self.call(prompt=None)
        self.assertAsks(out, "frontier-reason: TEXT")
        self.assertAsks(self.call(prompt="do it\nfrontier-reason:   \n"), "frontier-reason: TEXT")
        # a reason anywhere but the prompt (the description, the agent type) is not one
        self.assertAsks(self.call(prompt="x", tool_input={"description": REASON}))

    def test_reason_length_bounds_and_form(self):
        for text, ok in (("a" * 9, False), ("a" * 10, True), ("a" * 200, True), ("a" * 201, False)):
            out = self.call(prompt=f"hi\nfrontier-reason: {text}\nbye")
            self.assertEqual(out is None, ok, len(text))
            if not ok:
                self.assertAsks(out, "10-200")
        self.assertAsks(self.call(prompt="frontier-reason: ok\x07 but too\x07 bad"), "control")

    def test_the_daily_cap_boundary(self):
        for n in range(1, 5):                                 # away allows 4 a day
            self.assertIsNone(self.call(), n)
        out = self.call()
        self.assertAsks(out, "4 of 4")
        self.assertEqual([r["decision"] for r in self.rows()], ["allowed-judged"] * 4 + ["asked"])

    def test_yesterdays_calls_do_not_count(self):
        self.log.parent.mkdir(parents=True)
        two_days = time.time() - 2 * 86400
        self.log.write_text("".join(json.dumps({"at": two_days, "decision": "allowed-judged"}) + "\n" for _ in range(6)))
        self.counter.write_text(json.dumps({"day": "2000-01-01", "n": 9}))
        self.assertIsNone(self.call())

    def test_the_counter_survives_a_truncated_log_and_the_log_survives_a_deleted_counter(self):
        for _ in range(4):
            self.assertIsNone(self.call())
        self.log.write_text("")                                # spoof 1: empty the log
        self.assertAsks(self.call(), "4 of 4")
        # spoof 2: delete the counter, keep the log (the ask above logged a row, the 4 allowed rows were emptied: rebuild them)
        self.log.write_text("".join(json.dumps({"at": time.time(), "decision": "allowed-judged"}) + "\n" for _ in range(4)))
        self.counter.unlink()
        self.assertAsks(self.call(), "4 of 4")

    def test_a_tampered_log_or_counter_asks(self):
        self.log.parent.mkdir(parents=True)
        for text, why in (("not json\n", "check failed"),
                          (json.dumps({"decision": "asked"}) + "\n", "check failed"),                    # no `at`
                          (json.dumps({"at": "x", "decision": "asked"}) + "\n", "past time"),
                          (json.dumps({"at": time.time() + 3600, "decision": "asked"}) + "\n", "past time")):
            self.log.write_text(text)
            self.assertAsks(self.call(), why)
        self.log.write_text("")
        for text in ("{", json.dumps({"day": "x", "n": "3"}), json.dumps([1])):
            self.counter.write_text(text)
            out = self.call()
            if text.startswith("{\""):                         # a counter for another day is simply not today's
                self.assertIsNone(out)
            else:
                self.assertAsks(out, "check failed")
        today = datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        for bad in (-1, True, 1.5):
            self.counter.write_text(json.dumps({"day": today, "n": bad}))
            self.assertAsks(self.call(), "usable count")

    def test_a_symlinked_log_asks(self):
        self.log.parent.mkdir(parents=True)
        target = self.home / "elsewhere.jsonl"
        target.write_text("")
        self.log.symlink_to(target)
        self.assertAsks(self.call(), "could not use its own state")
        self.assertEqual(target.read_text(), "")                 # never followed

    def test_a_broken_gates_toml_is_baseline(self):
        bad = self.home / "gates.toml"
        bad.write_text("[frontier\n")
        self.assertAsks(self.call(env={"GATES_TOML": str(bad)}))

    def test_no_env_variable_widens_the_allowance(self):
        env = {"FRONTIER_GATE_THRESHOLDS": json.dumps({"frontier1_judged": 1, "frontier1_agent_calls_per_day": 99}),
               "CLAUDE_QUOTA_GUARD_THRESHOLDS": json.dumps({"frontier1_judged": 1})}
        self.assertAsks(self.call(profile=False, env=env))

    def test_the_off_switch_and_the_approval_keywords_skip_the_allowance(self):
        out, log = self.run_hook({"subagent_type": "fable-deep"}, home=self.home, FRONTIER_GATE_OFF="1")
        self.assertIsNone(out)
        self.assertFalse(self.log.exists())
        for kw in ("frontier-agent", "omp,fable-deep"):
            out, _ = self.run_hook({"subagent_type": "fable-deep"}, home=self.home, ACP_OPERATOR_APPROVED=kw)
            self.assertIsNone(out)
            self.assertEqual(self.rows()[-1]["decision"], "allowed-approved")
        self.assertFalse(self.counter.exists())               # an operator approval is not an allowance call

    def test_a_non_frontier_model_is_untouched(self):
        self.assertIsNone(self.call(tool_input={"model": "opus"}))
        self.assertFalse(self.log.exists())

    def test_parallel_calls_cannot_both_take_the_last_slot(self):
        env = {**os.environ, "HOME": str(self.home), "GATE_PROFILE_STATE": self.profile(),
               "CLAUDE_QUOTA_GUARD_STATE": self.guard()}
        for k in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF"):
            env.pop(k, None)
        payload = json.dumps({"tool_name": "Agent", "session_id": "s", "cwd": "/x", "tool_input": {
            "model": "fable", "prompt": REASON}})
        procs = [subprocess.Popen(["python3", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
                 for _ in range(10)]
        outs = [p.communicate(payload)[0] for p in procs]
        self.assertEqual(sum(1 for o in outs if not o.strip()), 4)       # exactly the cap

    def test_the_decision_waits_for_the_lock(self):
        """Deterministic: while another process holds agent-calls.lock the hook must not decide (a held lock is a parallel call in
        the middle of its count-and-append); it finishes once the lock is released."""
        import fcntl
        env = {**os.environ, "HOME": str(self.home), "GATE_PROFILE_STATE": self.profile(),
               "CLAUDE_QUOTA_GUARD_STATE": self.guard()}
        for k in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF"):
            env.pop(k, None)
        lock = self.home / ".local/state/frontier-gate/agent-calls.lock"
        lock.parent.mkdir(parents=True)
        payload = json.dumps({"tool_name": "Agent", "session_id": "s", "cwd": "/x", "tool_input": {
            "model": "fable", "prompt": REASON}})
        with open(lock, "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            proc = subprocess.Popen(["python3", str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
            proc.stdin.write(payload)
            proc.stdin.close()
            time.sleep(1.5)
            self.assertIsNone(proc.poll(), "the hook decided while the lock was held")
            self.assertFalse(self.log.exists())
        self.assertEqual(proc.wait(timeout=20), 0)
        self.assertEqual(self.rows()[-1]["decision"], "allowed-judged")

    # -- the gate's own state is unusable: a frontier call asks, at baseline and under away (adversary round 1, A1) ------------

    def asks_both_ways(self, why_part: str):
        for label, profile in (("baseline", False), ("away", True)):
            with self.subTest(label):
                out = self.call(profile=profile)
                self.assertAsks(out, "could not use its own state")
                self.assertIn(why_part, out["hookSpecificOutput"]["permissionDecisionReason"])

    @property
    def gate_dir(self) -> Path:
        return self.home / ".local/state/frontier-gate"

    def test_a_log_path_that_is_a_directory_asks(self):
        self.log.mkdir(parents=True)
        self.asks_both_ways("IsADirectoryError")

    def test_a_lock_path_that_is_a_symlink_asks(self):
        self.gate_dir.mkdir(parents=True)
        (self.gate_dir / "agent-calls.lock").symlink_to(self.home / "elsewhere")
        self.asks_both_ways("OSError")

    def test_a_state_dir_that_is_a_file_asks(self):
        self.gate_dir.parent.mkdir(parents=True)
        self.gate_dir.write_text("not a directory")
        self.asks_both_ways("FileExistsError")

    def test_a_lock_held_by_another_process_asks_after_the_wait(self):
        import fcntl
        self.gate_dir.mkdir(parents=True)
        with open(self.gate_dir / "agent-calls.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            started = time.monotonic()
            self.asks_both_ways("held by another process")
            self.assertGreaterEqual(time.monotonic() - started, 9.0)         # two calls, 5 s each, never an indefinite wait
        self.assertFalse(self.log.exists())

    # -- a FIFO in place of a state file asks within seconds and never hangs (adversary round 2, A1; run_hook has a 10 s timeout) --

    def fifo(self, name: str) -> Path:
        self.gate_dir.mkdir(parents=True, exist_ok=True)
        path = self.gate_dir / name
        os.mkfifo(path)
        return path

    def test_a_lock_path_that_is_a_fifo_asks(self):
        self.fifo("agent-calls.lock")
        self.asks_both_ways("OSError")

    def test_a_log_path_that_is_a_fifo_asks(self):
        self.fifo("agent-calls.jsonl")
        self.asks_both_ways("OSError")

    def test_a_quota_guard_state_that_is_a_fifo_is_no_guard(self):
        fifo = self.state / "quota-guard.json"
        os.mkfifo(fifo)
        out = self.call(guard=str(fifo))
        self.assertAsks(out, "away allowance")
        self.assertEqual(self.rows()[-1]["decision"], "asked")

    def test_a_counter_temp_path_that_is_a_fifo_asks_and_logs_no_grant(self):
        self.fifo(".agent-calls-day.json.4242")                  # the hook below is run with its pid pinned to 4242
        base = {k: v for k, v in os.environ.items() if k not in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF")}
        runner = f"import os, runpy; os.getpid = lambda: 4242; runpy.run_path({str(HOOK)!r}, run_name='__main__')"
        proc = subprocess.run(["python3", "-c", runner], input=json.dumps({"tool_name": "Agent", "tool_input": {
            "model": "fable", "prompt": REASON}}), capture_output=True, text=True, timeout=10, check=True,
            env={**base, "HOME": str(self.home), "GATE_PROFILE_STATE": self.profile(), "CLAUDE_QUOTA_GUARD_STATE": self.guard()})
        self.assertAsks(json.loads(proc.stdout), "FileExistsError")
        self.assertEqual([r["decision"] for r in self.rows()] if self.log.exists() else [], [])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_a_failed_counter_write_leaves_no_allowed_row(self):
        """The counter is written before the row, so a call that asks never has an `allowed-judged` row (adversary round 2, A2)."""
        self.gate_dir.mkdir(parents=True)
        for name in ("agent-calls.jsonl", "agent-calls.lock"):
            (self.gate_dir / name).touch()
        self.gate_dir.chmod(0o555)                               # the files stay writable, a new temp file cannot be created
        self.addCleanup(self.gate_dir.chmod, 0o755)
        self.assertAsks(self.call(), "could not use its own state")
        self.assertNotIn("allowed-judged", [r["decision"] for r in self.rows()])

    def test_an_approved_session_still_passes_when_the_state_is_unusable(self):
        self.log.mkdir(parents=True)
        self.assertIsNone(self.call(env={"ACP_OPERATOR_APPROVED": "frontier-agent"}))

    def test_an_import_failure_at_baseline_does_not_advertise_the_allowance(self):
        hooks = self.home / "tree/claude/hooks"                  # no bin/ beside it and no ~/src checkout under the test HOME
        hooks.mkdir(parents=True)
        copy = hooks / HOOK.name
        copy.write_text(HOOK.read_text())
        base = {k: v for k, v in os.environ.items() if k not in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF")}
        proc = subprocess.run(["python3", str(copy)], input=json.dumps({"tool_name": "Agent", "tool_input": {
            "model": "fable", "prompt": REASON}}), capture_output=True, text=True, env={**base, "HOME": str(self.home)}, check=True)
        out = json.loads(proc.stdout)
        self.assertAsks(out)
        self.assertNotIn("allowance", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("ImportError", self.rows()[-1]["ask_reason"])


class TestStateReads(unittest.TestCase):
    """`_count_today` reads the log and the day counter through `_open_regular` (adversary round 3, P3-1): a file swapped for a
    FIFO between a type check and the read must raise, never block. A racing test would be flaky, so the swap is done inside
    `_open_regular`'s call, which is the only place a check and an open meet."""

    def setUp(self):
        import sys
        import types
        self.hook = types.ModuleType("frontier_agent_gate_under_test")
        self.hook.__file__ = str(HOOK)
        exec(compile(HOOK.read_text().split("\ntry:\n    data = json.load", 1)[0], str(HOOK), "exec"), self.hook.__dict__)   # the defs, not main
        sys.path.insert(0, str(HOOK.parents[2] / "bin"))
        import ade_gates
        self.g = ade_gates
        self.dir = Path(tempfile.mkdtemp(prefix="fgate-read-"))
        self.hook.LOG, self.hook.DAY_COUNTER = self.dir / "agent-calls.jsonl", self.dir / "agent-calls-day.json"
        self.now = datetime.now(UTC)

    def swap_in_a_fifo_before_the_open(self, target: Path):
        real = self.hook._open_regular

        def racing(path, flags, mode=0o600):
            if path == target:
                tmp = path.with_name(path.name + ".swap")
                os.mkfifo(tmp)
                os.replace(tmp, path)
            return real(path, flags, mode)
        self.hook._open_regular = racing

    def count(self):
        import signal
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(AssertionError("the read blocked on a FIFO")))
        signal.alarm(5)
        try:
            return self.hook._count_today(self.g, self.now)
        finally:
            signal.alarm(0)

    def test_absent_files_count_zero(self):
        self.assertEqual(self.count()[0], 0)

    def test_a_log_swapped_for_a_fifo_during_the_read_raises_instead_of_blocking(self):
        self.hook.LOG.write_text("")
        self.swap_in_a_fifo_before_the_open(self.hook.LOG)
        with self.assertRaises(OSError):
            self.count()

    def test_a_counter_swapped_for_a_fifo_during_the_read_raises_instead_of_blocking(self):
        self.hook.DAY_COUNTER.write_text("{}")
        self.swap_in_a_fifo_before_the_open(self.hook.DAY_COUNTER)
        with self.assertRaises(OSError):
            self.count()

    def test_a_symlinked_log_raises(self):
        target = self.dir / "elsewhere"
        target.write_text("")
        self.hook.LOG.symlink_to(target)
        with self.assertRaises(OSError):
            self.count()


class TestSettingsTemplate(unittest.TestCase):
    """The hook entry blocks on failure and times out well under Claude Code's 600 s default (djbclark, 2026-10-27)."""

    def test_the_frontier_hook_entry_has_a_timeout_and_blocks_on_failure(self):
        tmpl = json.loads((HOOK.parents[2] / "agents/claude/settings.json.tmpl").read_text())
        hooks = [h for grp in tmpl["hooks"]["PreToolUse"] for h in grp["hooks"]
                 if "frontier_agent_gate.py" in h["command"]]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0].get("onFailure"), "block")
        self.assertEqual(hooks[0].get("timeout"), 15)

    def test_a_plain_agent_call_exits_0_under_an_old_python(self):
        # `onFailure: block` turns any startup failure into a block of every Agent/Task call; macOS /usr/bin/python3 is 3.9.
        old = "/usr/bin/python3"
        if not os.path.exists(old):
            self.skipTest("no /usr/bin/python3")
        r = subprocess.run([old, str(HOOK)], capture_output=True, text=True, timeout=10, input=json.dumps(
            {"tool_name": "Agent", "tool_input": {"subagent_type": "general-purpose", "prompt": "x"}}))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)


if __name__ == "__main__":
    unittest.main()
