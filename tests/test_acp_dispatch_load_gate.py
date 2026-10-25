#!/usr/bin/env python3
"""acp-dispatch load gate: `load-watch admit` runs before a slice launches (operator 2026-10-19).
A fake load-watch stands in (ACP_DISPATCH_LOAD_WATCH); conftest turns the gate off for every other suite."""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
import time
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import SCRIPT, run
from test_acp_dispatch_routing import RoutingDispatch

FAKE_LW = textwrap.dedent("""\
    #!/bin/bash
    # fake load-watch: records its arguments, prints FAKE_LW_OUT, exits FAKE_LW_RC
    echo "$@" >> "$FAKE_LW_ARGS"
    env | grep -E '^LW_' >> "$FAKE_LW_ARGS.env"
    # while "waiting", the machine changes: write a file (a new quota snapshot, a competing in-flight row)
    [ -n "$FAKE_LW_WRITE" ] && { mkdir -p "$(dirname "$FAKE_LW_WRITE")"; printf '%s' "$FAKE_LW_BODY" > "$FAKE_LW_WRITE"; }
    [ -n "$FAKE_LW_OUT" ] && echo "$FAKE_LW_OUT"
    exit "${FAKE_LW_RC:-0}"
    """)


class LoadGate(RoutingDispatch):
    lw: Path = Path()
    lw_args: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.lw = self.tmp / "load-watch"
        self.lw.write_text(FAKE_LW)
        self.lw.chmod(0o755)
        self.lw_args = self.tmp / "load-watch.args"

    def gate_env(self, rc: int = 0, out: str = "", **extra: str) -> dict[str, str]:
        # "" overrides conftest's ACP_DISPATCH_NO_LOAD_GATE=1 (only "1" skips the gate)
        return {"ACP_DISPATCH_NO_LOAD_GATE": "", "ACP_DISPATCH_LOAD_WATCH": str(self.lw),
                "FAKE_LW_ARGS": str(self.lw_args), "FAKE_LW_RC": str(rc), "FAKE_LW_OUT": out,
                "ACP_DISPATCH_LOAD_WAIT": "", **extra}

    def calls(self) -> list[str]:
        return self.lw_args.read_text().splitlines() if self.lw_args.exists() else []


HOT = '{"status": "hot", "load1": 31.2, "per_core": 3.9, "cores": 8, "max_per_core": 1.5, "waited_s": 5}'
OK = '{"status": "ok", "load1": 2.4, "per_core": 0.3, "cores": 8, "max_per_core": 1.5, "waited_s": 12}'


class TestLoadGateRefuses(LoadGate):
    def test_hot_exits_75_and_does_not_launch(self):
        r = self.dispatch("--no-model-check", "--load-wait", "5", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 75, r.stderr + r.stdout)
        self.assertIn("load1=31.2", r.stdout)
        self.assertIn("after waiting 5s", r.stdout)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertEqual(self.calls(), ["admit --wait 5 --json"])
        self.assertFalse((self.out / "s1-report.md").exists())          # acp-run never ran
        self.assertEqual(self.preflight_probes(), 0)                    # the gate sits before the live probe
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "load", 75))
        self.assertEqual(rec["load_gate"], {"load1": 31.2, "per_core": 3.9, "waited_s": 5})


class TestLoadGateAdmits(LoadGate):
    def test_ok_records_load_gate_and_launches(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(0, OK))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.record()["load_gate"], {"load1": 2.4, "per_core": 0.3, "waited_s": 12})
        self.assertTrue((self.out / "s1-report.md").exists())
        self.assertEqual(self.preflight_probes(), 1)

    def test_default_wait_is_1800(self):
        self.assertEqual(self.dispatch("--no-model-check", env=self.gate_env(0, OK)).returncode, 0)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])

    def test_env_overrides_the_default_and_the_flag_overrides_the_env(self):
        env = self.gate_env(0, OK, ACP_DISPATCH_LOAD_WAIT="42")
        self.assertEqual(self.dispatch("--no-model-check", env=env).returncode, 0)
        self.assertEqual(self.dispatch("--no-model-check", "--load-wait", "7", name="s2", env=env).returncode, 0)
        self.assertEqual(self.calls(), ["admit --wait 42 --json", "admit --wait 7 --json"])

    def test_no_load_gate_skips_it(self):
        r = self.dispatch("--no-model-check", "--no-load-gate", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.record()["load_gate"])

    def test_env_flag_skips_it(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(75, HOT, ACP_DISPATCH_NO_LOAD_GATE="1"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])

    def test_dry_run_does_not_wait(self):
        r = self.dispatch("--no-model-check", "--dry-run", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])


class TestLoadGateDegrades(LoadGate):
    def test_missing_load_watch_warns_and_continues(self):
        env = self.gate_env(0, OK, ACP_DISPATCH_LOAD_WATCH=str(self.tmp / "no-such-load-watch"))
        r = self.dispatch("--no-model-check", env=env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("warning", r.stderr)
        self.assertIn("load gate", r.stderr)
        self.assertIn("not found", self.record()["load_gate"]["error"])   # said so in the record, not just stderr

    def test_exit_0_with_unreadable_output_is_an_unknown_result_not_a_silent_admit(self):
        # a wrapper that exits 0 but is not load-watch: empty, non-JSON, or JSON without the admit fields
        for n, out in enumerate(("", "all good, go ahead", '{"status": "ok"}', "[1, 2]")):
            with self.subTest(stdout=out):
                r = self.dispatch("--no-model-check", name=f"u{n}", env=self.gate_env(0, out))
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)           # same unknown behaviour: warn, start
                self.assertIn("warning", r.stderr)
                self.assertIn("output the gate cannot read", r.stderr)
                gate = self.record(f"u{n}")["load_gate"]
                self.assertIsNotNone(gate)                                       # never `load_gate: null`
                self.assertIn("cannot read", gate["error"])
                self.assertIsNone(gate["load1"])

    def test_broken_load_watch_warns_and_continues(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(1, "boom"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("load-watch admit exited 1", r.stderr)
        self.assertEqual(self.record()["load_gate"]["error"], "load-watch admit exited 1")


class TestLoadGateScrubsTestHooks(LoadGate):
    def test_lw_hooks_never_reach_load_watch(self):
        env = self.gate_env(0, OK, LW_FAKE_LOAD1="0", LW_ADMIT_POLL_S="0", LW_ADMIT_STAGGER_S="0,0",
                            LW_LOAD_PER_CORE="abc", LW_STATE_DIR=str(self.tmp / "lw-state"))
        self.assertEqual(self.dispatch("--no-model-check", env=env).returncode, 0)
        seen = Path(str(self.lw_args) + ".env")
        self.assertTrue(not seen.exists() or seen.read_text() == "", seen.read_text() if seen.exists() else "")

    def test_a_bad_lw_setting_cannot_crash_the_real_load_watch(self):
        # N4: LW_LOAD_PER_CORE=abc made load-watch die at import (exit 1), which the gate read as "warn and start"
        real = str(Path(__file__).resolve().parent.parent / "bin" / "load-watch")
        env = self.gate_env(0, OK, ACP_DISPATCH_LOAD_WATCH=real, LW_LOAD_PER_CORE="abc", LW_FAKE_LOAD1="80")
        r = self.dispatch("--no-model-check", "--load-wait", "0", env=env)
        self.assertNotIn("admit exited", r.stderr)               # it ran and answered: 0 (cool) or 75 (hot host)
        self.assertIn(r.returncode, (0, 75), r.stderr + r.stdout)


class TestLoadGateBeforeQuotaChecks(LoadGate):
    """Adversary review of e6c538c, finding 1: the pool reading, in-flight reservation, headroom and cap
    checks must describe the machine AFTER the wait, so they run after the gate."""

    def test_headroom_is_read_after_the_wait(self):
        env = {**self.snap_codex(90.0)}
        snap = Path(env["AIUSE_SNAPSHOT"])
        low = json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [
            {"provider": "codex", "windows": [{"label": "5h", "remaining_percent": 3.0}]}]}})
        gate = self.gate_env(0, OK, FAKE_LW_WRITE=str(snap), FAKE_LW_BODY=low, **env)
        r = self.dispatch("--no-model-check", "--no-preflight", env=gate)
        self.assertEqual(r.returncode, 5, r.stderr + r.stdout)       # refused on the post-wait 3%, not the 90% before
        self.assertIn("class=headroom", r.stdout)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])

    def test_competing_slice_started_during_the_wait_counts_against_the_cap(self):
        planted = self.tmp / "state" / "other-task" / "jobs" / "busy.json"
        gate = self.gate_env(0, OK, FAKE_LW_WRITE=str(planted), FAKE_LW_BODY=json.dumps(self.busy_row(estimated_usage_pct=65.0)),
                             **self.snap_codex(70.0))
        r = self.dispatch("--no-model-check", "--no-preflight", env=gate)
        self.assertEqual(r.returncode, 5, r.stderr + r.stdout)
        self.assertIn("class=inflight", r.stdout)
        self.assertFalse((self.out / "s1-report.md").exists())

    def test_hot_machine_refuses_before_any_quota_reading(self):
        # a 3% pool would refuse as headroom; the load refusal must win because the gate comes first
        r = self.dispatch("--no-model-check", "--no-preflight", env=self.gate_env(75, HOT, **self.snap_codex(3.0)))
        self.assertEqual(r.returncode, 75, r.stderr + r.stdout)
        self.assertIn("class=load", r.stdout)

    def judgment(self, *extra: str, env: dict[str, str]):
        return self.dispatch_agent("codex", "gpt-6.1-sol", "--kind", "judgment", "--effort", "high",
                                   "--no-model-check", "--no-preflight", *extra, env=env)

    def drains_to_40(self) -> dict[str, str]:
        """A fresh 90% snapshot that the fake load-watch rewrites to 40% while it admits."""
        env = self.snap_codex(90.0)
        low = json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [
            {"provider": "codex", "windows": [{"label": "5h", "remaining_percent": 40.0}]}]}})
        return {**env, "FAKE_LW_WRITE": env["AIUSE_SNAPSHOT"], "FAKE_LW_BODY": low}

    def test_the_plenty_gate_is_judged_on_the_reading_after_the_wait(self):
        """Adversary 7802361, A1: judgment passed the 50% gate on 90%, the wait drained it to 40%, and
        only the minimum-headroom and fit checks saw the new reading: the slice launched."""
        r = self.judgment("--min-headroom", "0", env=self.gate_env(0, OK, **self.drains_to_40()))
        self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
        self.assertIn("codex is not eligible for --kind judgment", r.stderr)
        self.assertIn("now: 40% left", r.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())      # nothing launched, no record
        self.assertFalse((self.out / "s1-report.md").exists())

    def test_route_override_still_skips_the_gate_after_the_wait(self):
        r = self.judgment("--min-headroom", "0", env={
            **self.gate_env(0, OK, **self.drains_to_40()), "ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.record()["kind"], "judgment")

    def test_the_detached_runner_rechecks_the_plenty_gate_after_its_own_wait(self):
        env = self.snap_codex(90.0)
        d = self.judgment("--detach", "--no-wait", env=self.gate_env(0, OK, **env))
        self.assertEqual(d.returncode, 0, d.stderr + d.stdout)
        self.assertTrue(self.record()["plenty_gate"])
        path = str(self.out / "jobs" / "s1.json")
        r = run(["execute", path], env={**self.base_env(), **self.gate_env(0, OK, **self.drains_to_40())})
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "headroom", 5))
        self.assertIn("now: 40% left", rec["detail"])
        self.assertFalse(rec["load_gate_pending"])
        self.assertFalse((self.out / "s1-report.md").exists())          # no agent started

    def test_the_runner_finalize_keeps_the_headroom_refusal(self):
        """Adversary bcdd223, A2: the generated runner always runs `finalize` after `execute`, and
        finalize turned the headroom refusal into a no-report with a usage sample made from the wait."""
        d = self.judgment("--detach", "--no-wait", env=self.gate_env(0, OK, **self.snap_codex(90.0)))
        self.assertEqual(d.returncode, 0, d.stderr + d.stdout)
        path = str(self.out / "jobs" / "s1.json")
        env = {**self.base_env(), **self.gate_env(0, OK, **self.drains_to_40())}
        self.assertEqual(run(["execute", path], env=env).returncode, 5)
        for argv in (["finalize", path, "--exit", "5"], ["check", path]):
            r = run(argv, env=env)
            self.assertEqual(r.returncode, 5, (argv, r.stdout, r.stderr))
            self.assertNotIn("no-report", r.stdout.lower())
            self.assertNotIn("--escalate", r.stdout)
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "headroom", 5))
        self.assertIn("now: 40% left", rec["detail"])
        self.assertFalse([k for k in rec if k.startswith("measured_usage")], rec)

    def test_a_route_override_runner_does_not_recheck(self):
        d = self.judgment("--detach", "--no-wait", env={
            **self.gate_env(0, OK, **self.snap_codex(90.0)), "ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(d.returncode, 0, d.stderr + d.stdout)
        self.assertNotIn("plenty_gate", self.record())
        r = run(["execute", str(self.out / "jobs" / "s1.json")],
                env={**self.base_env(), **self.gate_env(0, OK, **self.drains_to_40())})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class TestLoadGateCheck(LoadGate):
    def test_check_says_retry_later_and_never_exclude(self):
        self.assertEqual(self.dispatch("--no-model-check", env=self.gate_env(75, HOT)).returncode, 75)
        r = run(["check", str(self.out / "jobs" / "s1.json")], env=self.base_env())
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.assertIn("machine too hot; retry later", r.stdout)
        self.assertNotIn("--exclude", r.stdout)


class TestLoadGateResume(LoadGate):
    """A resume that reaches dispatch() starts a new agent process (resume refuses a running slice first),
    so it passes the gate too (finding 9)."""

    def land(self) -> Path:
        self.assertEqual(self.dispatch("--no-model-check", "--no-preflight").returncode, 0)
        return self.out / "jobs" / "s1.json"

    def test_resume_is_refused_while_hot_and_the_record_survives(self):
        rec = self.land()
        env = {**self.base_env(), **self.gate_env(75, HOT)}
        r = run(["resume", str(rec), "--timeout", "0"], env=env)
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])
        kept = json.loads(rec.read_text())
        self.assertIn("log", kept)                                       # not overwritten by the refusal
        self.assertIn("cmd", kept)
        self.assertEqual(kept["refusals"][-1]["class"], "load")

    def test_resume_is_gated_and_records_load_gate_when_cool(self):
        rec = self.land()
        env = {**self.base_env(), **self.gate_env(0, OK)}
        r = run(["resume", str(rec), "--timeout", "0"], env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])
        self.assertEqual(json.loads(rec.read_text())["load_gate"], {"load1": 2.4, "per_core": 0.3, "waited_s": 12})


class TestLoadGateDetachNoWait(LoadGate):
    """--detach --no-wait must return at once: the wait moves into the detached runner (finding 5)."""

    def detach(self, **extra: str) -> subprocess.CompletedProcess[str]:
        return self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait",
                             env=self.gate_env(75, HOT, **extra))

    def test_returns_at_once_without_calling_load_watch(self):
        r = self.detach()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])                              # no synchronous wait
        rec = self.record()
        self.assertTrue(rec["load_gate_pending"])
        self.assertEqual(rec["load_gate"], {"state": "pending", "wait_s": 1800})
        self.assertEqual(rec["load_gate_wait"], 1800)
        self.assertGreaterEqual(rec["wait_timeout"], 1800 + 300)        # the wait comes out of nobody's budget

    def deadline_record(self) -> tuple[str, dict]:
        r = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", "--wait-timeout", "600",
                          "--load-wait", "100", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return str(self.out / "jobs" / "s1.json"), self.record()

    def test_deadline_covers_the_load_wait_and_the_hung_load_watch_grace(self):
        # Codex P2: a hung load-watch holds the runner for load_wait + LOAD_GATE_SUBPROCESS_GRACE before the
        # gate fails open; the record deadline (what the rearm waiter reads) must outlast that
        grace = int(re.search(r"^LOAD_GATE_SUBPROCESS_GRACE = (\d+)", SCRIPT.read_text(), re.M).group(1))
        self.assertGreater(grace, 0)
        _, rec = self.deadline_record()
        self.assertGreaterEqual(rec["wait_timeout"], 600 + 100 + grace)
        self.assertGreaterEqual(rec["started"] + rec["wait_timeout"], rec["started"] + 600 + 100 + grace)
        self.assertEqual(rec["load_gate_wait"], 100)

    def test_the_waiter_does_not_time_out_while_the_gate_can_still_be_waiting(self):
        path, rec = self.deadline_record()
        loaded = self.tmp / "launchctl-loaded"                          # the runner's launchd job is still loaded
        loaded.write_text("#!/bin/bash\necho loaded\n")
        loaded.chmod(0o755)
        env = {**self.base_env(), "ACP_DISPATCH_LAUNCHCTL": str(loaded)}
        # a runner stuck in a hung load-watch: load_wait + grace into the gate, past the old deadline (600 + 100)
        self.set_started(path, time.time() - (600 + 100 + 60))
        # the rearm waiter loops on `wait --once`: 75 is "still running", 124 its wait_timeout
        c = run(["wait", "--once", path], env=env)
        self.assertEqual(c.returncode, 75, c.stdout + c.stderr)
        # and the deadline is still a real one
        self.set_started(path, time.time() - rec["wait_timeout"] - 30)
        c = run(["wait", "--once", path], env=env)
        self.assertEqual(c.returncode, 124, c.stdout + c.stderr)

    def set_started(self, path: str, started: float) -> None:
        rec = json.loads(Path(path).read_text())
        rec["started"] = started
        Path(path).write_text(json.dumps(rec))

    def test_a_relative_load_watch_override_is_stored_absolute(self):
        # Codex P2: the launchd runner has another cwd, so a relative string read as "missing" and failed open
        rel = os.path.relpath(self.lw, os.getcwd())
        self.assertFalse(os.path.isabs(rel))
        r = self.detach(ACP_DISPATCH_LOAD_WATCH=rel)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        stored = self.record()["load_watch"]
        self.assertTrue(os.path.isabs(stored), stored)
        self.assertTrue(os.path.exists(stored), stored)
        self.assertEqual(stored, str(self.lw.resolve()))

    def test_a_bare_load_watch_name_is_looked_up_on_path_and_stored_absolute(self):
        r = self.detach(ACP_DISPATCH_LOAD_WATCH="load-watch", PATH=f"{self.tmp}{os.pathsep}{os.environ['PATH']}")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        stored = self.record()["load_watch"]
        self.assertTrue(os.path.isabs(stored), stored)
        self.assertEqual(stored, str(self.lw.resolve()))

    def test_runner_refuses_when_still_hot_and_finalize_leaves_it_alone(self):
        self.assertEqual(self.detach().returncode, 0)
        path = str(self.out / "jobs" / "s1.json")
        env = {**self.base_env(), **self.gate_env(75, HOT)}
        r = run(["execute", path], env=env)
        self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])
        self.assertFalse((self.out / "s1-report.md").exists())          # no agent started
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "load", 75))
        self.assertFalse(rec["load_gate_pending"])
        f = run(["finalize", path, "--exit", "75"], env=env)
        self.assertEqual(f.returncode, 75, f.stdout + f.stderr)
        self.assertEqual(self.record()["status"], "unavailable")
        c = run(["check", path], env=env)
        self.assertEqual(c.returncode, 75)
        self.assertIn("machine too hot; retry later", c.stdout)

    def test_runner_starts_the_agent_when_cool(self):
        self.assertEqual(self.detach().returncode, 0)
        path = str(self.out / "jobs" / "s1.json")
        r = run(["execute", path], env={**self.base_env(), **self.gate_env(0, OK)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual(rec["load_gate"], {"load1": 2.4, "per_core": 0.3, "waited_s": 12})
        self.assertFalse(rec["load_gate_pending"])
        self.assertTrue(rec.get("pid"))                                  # the agent really ran


class TestPendingRunnersHoldTheCap(LoadGate):
    """Re-review N1: a runner waiting for the load has no pid; it must count as in flight however long it waits."""

    def plant(self, name: str, **fields: object) -> None:
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        row = self.busy_row(name=name, **fields)
        row.update({k: v for k, v in fields.items()})
        (jobs / f"{name}.json").write_text(json.dumps(row))

    def test_pending_record_older_than_the_spawn_grace_counts_against_the_reservation(self):
        # Leave only 5% of the 70% pool, below the everyday Codex model's 10% floor.
        self.plant("waiting", pid=None, pid_start=None, started=time.time() - 2000,
                   load_gate_pending=True, estimated_usage_pct=65.0)
        r = self.dispatch("--no-model-check", "--no-preflight", env=self.snap_codex(70.0))
        self.assertEqual(r.returncode, 5, r.stderr + r.stdout)
        self.assertIn("class=inflight", r.stdout)
        self.assertIn("waiting", r.stdout)

    def test_a_pid_less_record_that_is_not_pending_stops_counting_after_the_grace(self):
        self.plant("stale", pid=None, pid_start=None, started=time.time() - 2000)
        r = self.dispatch("--no-model-check", "--no-preflight", env=self.snap_codex(70.0))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def deferred(self, **extra: str) -> str:
        r = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait",
                          env=self.gate_env(0, OK, ACP_DISPATCH_INFLIGHT="codex=1", **extra))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return str(self.out / "jobs" / "s1.json")

    def test_runner_refuses_when_the_cap_filled_during_the_wait(self):
        path = self.deferred()
        self.plant("started-meanwhile", started=time.time())                 # running, has a pid
        r = run(["execute", path], env={**self.base_env(), **self.gate_env(0, OK, ACP_DISPATCH_INFLIGHT="")})
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "inflight", 5))
        self.assertFalse(rec["load_gate_pending"])
        self.assertFalse((self.out / "s1-report.md").exists())               # nothing started
        f = run(["finalize", path, "--exit", "5"], env=self.base_env())
        self.assertEqual(f.returncode, 5, f.stdout + f.stderr)
        self.assertEqual(self.record()["status"], "unavailable")

    def test_queued_ahead_blocks_but_queued_behind_does_not(self):
        path = self.deferred()
        mine = self.record()["started"]
        env = {**self.base_env(), **self.gate_env(0, OK, ACP_DISPATCH_INFLIGHT="")}
        self.plant("behind", pid=None, pid_start=None, started=mine + 100, load_gate_pending=True)
        r = run(["execute", path], env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)                # the later runner does not block us
        self.assertTrue(self.record().get("pid"))

    def test_dispatch_records_what_the_launchd_runner_cannot_see(self):
        # L1/I1: the runner has no load_policy(), ACP_DISPATCH_INFLIGHT, ACP_DISPATCH_STATE or our load-watch path
        self.deferred()
        rec = self.record()
        self.assertEqual(rec["inflight_cap"], 1)
        self.assertEqual(rec["state_root"], str(self.tmp / "state"))
        self.assertEqual(rec["load_watch"], str(self.lw.resolve()))

    def test_a_resume_record_is_exempt_from_the_recheck(self):
        path = self.deferred()
        self.plant("started-meanwhile", started=time.time())
        p = Path(path)
        rec = json.loads(p.read_text())
        p.write_text(json.dumps({**rec, "resume_count": 1}))               # dispatch exempts a resume from the cap
        r = run(["execute", path], env={**self.base_env(), **self.gate_env(0, OK, ACP_DISPATCH_INFLIGHT="")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def twin_run(self, twin: str) -> subprocess.CompletedProcess[str]:
        """A pending runner with the very same `started`, in the same out dir; only the record path orders them."""
        path = self.deferred()
        mine = self.record()["started"]
        jobs = self.out / "jobs"
        (jobs / f"{twin}.json").write_text(json.dumps(self.busy_row(
            name=twin, pid=None, pid_start=None, started=mine, load_gate_pending=True)))
        return run(["execute", path], env={**self.base_env(), **self.gate_env(0, OK, ACP_DISPATCH_INFLIGHT="")})

    def test_equal_started_is_broken_by_the_record_path(self):
        # I2: with cap 1 exactly one of two equal-`started` runners launches
        behind = self.twin_run("z-twin")                                    # sorts after s1.json: we go first
        self.assertEqual(behind.returncode, 0, behind.stdout + behind.stderr)

    def test_equal_started_the_other_way_refuses_us(self):
        ahead = self.twin_run("a-twin")                                     # sorts before s1.json: it goes first
        self.assertEqual(ahead.returncode, 5, ahead.stdout + ahead.stderr)
        self.assertEqual(self.record()["unavailable_class"], "inflight")


class TestPendingStaysUntilThePidIsWritten(LoadGate):
    """Re-review 3, L2: between admission and the pid write (wait_for_capacity can hold 900 s) the row must
    still count as in flight; a pid-less row that is not pending drops out after the 600 s spawn grace."""

    def load_module(self):
        import importlib.machinery
        import importlib.util
        script = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"
        loader = importlib.machinery.SourceFileLoader("acp_dispatch_under_test", str(script))
        spec = importlib.util.spec_from_loader("acp_dispatch_under_test", loader)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def test_admitted_runner_is_still_pending_and_counted_before_its_pid(self):
        from unittest.mock import patch
        r = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", env=self.gate_env(0, OK))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        path = self.out / "jobs" / "s1.json"
        rec = json.loads(path.read_text())
        path.write_text(json.dumps({**rec, "started": time.time() - 1700}))      # it waited ~28 minutes for the load
        loaded = self.tmp / "launchctl-loaded"                                   # the launchd job is still loaded
        loaded.write_text("#!/bin/bash\necho loaded\n")
        loaded.chmod(0o755)
        env = {**self.gate_env(0, OK), "ACP_DISPATCH_STATE": str(self.tmp / "state"),
               "ACP_DISPATCH_LAUNCHCTL": str(loaded)}
        with patch.dict("os.environ", env):
            mod = self.load_module()
            self.assertIsNone(mod.runner_load_gate(path))                      # admitted; wait_for_capacity is next
            row = json.loads(path.read_text())
            self.assertTrue(row["load_gate_pending"])                          # not cleared until the pid is written
            self.assertIsNone(row["pid"])
            counted = mod.inflight_records("codex", self.tmp / "someone-else.json", self.out, agent="codex")
        self.assertEqual([p.name for p in counted], ["s1.json"])



class TestRecordWaitingOnTheGateIsNotOverwritten(LoadGate):
    """Re-review N2: re-dispatching the --name of a waiting runner must not overwrite its record."""

    def test_same_name_is_refused_while_the_runner_waits(self):
        env = self.gate_env(75, HOT)
        first = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", env=env)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        before = (self.out / "jobs" / "s1.json").read_text()
        again = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", env=env)
        self.assertEqual(again.returncode, 2, again.stderr + again.stdout)
        self.assertIn("waiting for the load to drop", again.stderr)
        self.assertEqual((self.out / "jobs" / "s1.json").read_text(), before)

    def test_force_still_overrides(self):
        env = self.gate_env(75, HOT)
        self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", env=env)
        again = self.dispatch("--no-model-check", "--no-preflight", "--detach", "--no-wait", "--force", env=env)
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)

    def test_a_refused_record_can_be_redispatched(self):
        self.assertEqual(self.dispatch("--no-model-check", env=self.gate_env(75, HOT)).returncode, 75)
        again = self.dispatch("--no-model-check", env=self.gate_env(0, OK))
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)


if __name__ == "__main__":
    unittest.main()
