#!/usr/bin/env python3
"""Tests for the cheap waiter and the reap throttle (2026-10-18).

26 resident `acp-dispatch wait` interpreters were 306 MB of RSS during the load-60-90 memory
stall on this 16 GB Mac. The `rearm` line is now one call to bin/acp-dispatch-wait (bash,
sleep and grep while the slice runs; a `wait --once` Python pass every 60 s and the moment the
cheap check trips), and `reap` throttles itself through a machine-wide stamp so no caller can
put it in a tight poll again (one did: load 110).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import unittest
from pathlib import Path

from test_acp_dispatch import SCRIPT, ROOT
from test_acp_dispatch_reap import ReapBase

HELPER = ROOT / "bin" / "acp-dispatch-wait"


class WaiterBase(ReapBase):
    def run_acp(self, args, env=None):
        e = dict(os.environ)
        e.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), *args], check=False,
                              capture_output=True, text=True, env=e)

    def throttle_env(self, **extra: str) -> dict[str, str]:
        return self.base_env(**{"ACP_DISPATCH_REAP_MIN_INTERVAL": "60",
                                "ACP_DISPATCH_REAP_STAMP": str(self.tmp / "reap.stamp"), **extra})

    def live(self, name: str = "s1") -> None:
        """Turn a dispatched record back into a genuinely running slice (this test process)."""
        mod = self.mod()
        me = os.getpid()
        self.unfinished(name=name, pid=me, pid_start=mod["proc_start"](me))


class TestWaitOnce(WaiterBase):
    def test_running_slice_returns_75(self):
        self.dispatch()
        self.live()
        r = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(r.returncode, 75, (r.stdout, r.stderr))
        self.assertIsNone(self.record()["finished"])

    def test_finished_slice_returns_0(self):
        self.dispatch()
        r = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))

    def test_past_wait_timeout_returns_124(self):
        self.dispatch()
        self.unfinished(started=0, wait_timeout=2)
        r = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(r.returncode, 124, (r.stdout, r.stderr))

    def test_dead_pid_is_reaped_and_returns_0(self):
        self.dispatch()
        gone = 2**22 - 31                                 # above pid_max on macOS: never alive
        self.unfinished(pid=gone, pid_start="x")
        r = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        rec = self.record()
        self.assertTrue(rec["finished"])
        self.assertIn(f"pid {gone} gone without finalize", rec["reaped"]["reason"])

    def test_auto_resume_notice_prints_once(self):
        self.dispatch(mode="quota_codex_date")            # schedules the in-place resume
        first = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(first.returncode, 75)
        self.assertEqual(first.stderr.count("quota stop; resumes in place"), 1, first.stderr)
        self.assertEqual(self.record()["wait_resume_noted"], 1)
        second = self.run_acp(["wait", "--once", str(self.record_path())])
        self.assertEqual(second.returncode, 75)
        self.assertNotIn("quota stop; resumes in place", second.stderr)

    def test_stale_checkpoint_notice_prints_once_per_episode(self):
        self.dispatch()
        self.unfinished(checkpoint=True, started=time.time() - 7200, wait_timeout=0)
        rec = self.record()
        env = {"ACP_DISPATCH_STALE_CHECKPOINT_MIN": "1"}
        Path(rec["log"]).write_text('{"kind":"initialize"}\n')   # active agent log
        os.utime(rec["report"], (time.time() - 7200,) * 2)       # report not refreshed
        first = self.run_acp(["wait", "--once", str(self.record_path())], env=env)
        self.assertEqual(first.returncode, 75)
        self.assertEqual(first.stderr.count("checkpoint stale"), 1, first.stderr)
        second = self.run_acp(["wait", "--once", str(self.record_path())], env=env)
        self.assertEqual(second.returncode, 75)
        self.assertNotIn("checkpoint stale", second.stderr)
        # the report is refreshed: the episode ends and the next one warns again
        Path(rec["report"]).write_text("STATUS: working\nstill going\n")
        quiet = self.run_acp(["wait", "--once", str(self.record_path())], env=env)
        self.assertEqual(quiet.returncode, 75)
        self.assertNotIn("checkpoint stale", quiet.stderr)
        self.assertIsNone(self.record().get("wait_stale_warned"))
        os.utime(rec["report"], (time.time() - 7200,) * 2)
        again = self.run_acp(["wait", "--once", str(self.record_path())], env=env)
        self.assertEqual(again.stderr.count("checkpoint stale"), 1, again.stderr)


class TestRearmHintMatchesTheWait(WaiterBase):
    """Codex 4324164145 (PR 28): the hint always said `timeout 7200000`, so a slice whose waiter runs past 2 h
    (--wait-timeout over 7200, a --timeout that gives more, or --timeout 0 = unlimited) lost its waiter at 2 h.
    7200000 ms is Claude Code Bash's maximum background timeout; no hint may name more than that."""

    def hint(self, *extra: str) -> str:
        r = self.dispatch("--detach", "--no-wait", *extra, mode="slow", name=f"h{len(extra)}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.rec_name = f"h{len(extra)}"
        lines = r.stdout.strip().splitlines()
        self.assertTrue(lines[-1].startswith("rearm: "), r.stdout)
        self.assertTrue(lines[-2].startswith("waiter: "), r.stdout)
        return lines[-2]

    def assert_within_the_maximum(self, hint: str) -> None:
        for n in re.findall(r"timeout (\d+)", hint):
            self.assertLessEqual(int(n), 7200000, hint)

    def test_a_wait_that_fits_in_two_hours_keeps_the_maximum_tool_timeout(self):
        for extra in ((), ("--wait-timeout", "7200")):
            hint = self.hint(*extra)
            self.assertIn("timeout 7200000", hint)
            self.assertNotIn("longer than", hint)
            self.assertLessEqual(self.record(self.rec_name)["wait_timeout"], 7200)
            self.assert_within_the_maximum(hint)

    def test_a_wait_past_two_hours_says_so_and_gives_the_rearm_rule(self):
        hint = self.hint("--wait-timeout", "7201")
        self.assertEqual(self.record(self.rec_name)["wait_timeout"], 7201)
        self.assertIn("longer than", hint)
        self.assertIn("re-arm", hint)
        self.assert_within_the_maximum(hint)

    def test_a_timeout_that_pushes_the_wait_past_two_hours(self):
        hint = self.hint("--timeout", "9000")
        self.assertGreater(self.record(self.rec_name)["wait_timeout"], 7200)
        self.assertIn("longer than", hint)
        self.assert_within_the_maximum(hint)

    def test_an_unlimited_wait_says_so_and_gives_the_rearm_rule(self):
        hint = self.hint("--timeout", "0")
        self.assertEqual(self.record(self.rec_name)["wait_timeout"], 0)
        self.assertIn("unlimited", hint)
        self.assertIn("re-arm", hint)
        self.assert_within_the_maximum(hint)


class TestRearmLine(WaiterBase):
    def test_record_rearm_line_calls_the_helper(self):
        self.dispatch()
        rearm = self.record()["rearm"]
        self.assertTrue(rearm.startswith(f"{HELPER} "), rearm)
        self.assertIn(str(self.record_path().resolve()), rearm)
        self.assertIn(self.record()["done"], rearm)
        r = subprocess.run(["bash", "-c", rearm], check=False, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertTrue(r.stdout.startswith("done\ts1\t"), r.stdout)

    def test_rearm_line_runs_end_to_end_when_the_slice_finishes_mid_wait(self):
        # a detached dispatch: the runner exists but the fake launchctl never starts it, so the
        # record sits running while the waiter polls
        r = self.dispatch("--detach", "--no-wait", mode="slow", name="e2e")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()           # the waiter hint sits above `rearm:` (2026-10-20)
        self.assertTrue(lines[-1].startswith("rearm: "), r.stdout)
        self.assertIn("timeout 7200000", lines[-2])
        rec = self.record("e2e")
        self.assertIsNone(rec["finished"])
        proc = subprocess.Popen(["bash", "-c", rec["rearm"]], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        time.sleep(2)                                      # the waiter is mid-wait now
        Path(rec["report"]).write_text("STATUS: working\nfinished the work\nDONE\n")
        row = json.loads(self.record_path("e2e").read_text())
        row.update(finished=time.time(), exit=0, status="done", pid=None)
        self.record_path("e2e").write_text(json.dumps(row, indent=1, sort_keys=True) + "\n")
        Path(rec["done"]).touch()
        out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, (out, err))
        self.assertTrue(out.startswith("done\te2e\t"), out)

    def test_a_quota_wait_does_not_run_python_every_tick(self):
        """Review 2026-10-18: a resume-scheduled record keeps `finished` set while it waits, so
        the cheap check is true on every tick; only its turning true may force a pass."""
        self.dispatch(mode="quota_codex_date")            # schedules the in-place resume
        calls = self.tmp / "passes.log"
        wrapper = self.tmp / "acp-dispatch-logged"
        wrapper.write_text(f'#!/bin/bash\necho "$*" >> {calls}\nexec {sys.executable} {SCRIPT} "$@"\n')
        wrapper.chmod(0o755)
        env = {**os.environ, "ACP_DISPATCH_BIN": str(wrapper), "ACP_DISPATCH_WAIT_TICK": "1"}
        proc = subprocess.Popen(["bash", "-c", self.record()["rearm"]], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(5)
        proc.kill()
        proc.wait()
        self.assertEqual(calls.read_text().count("wait --once"), 1, calls.read_text())

    def test_rearm_line_exits_124_when_wait_timeout_passes(self):
        self.dispatch()
        self.unfinished(wait_timeout=1, started=time.time() - 5)
        rearm = self.record()["rearm"]
        r = subprocess.run(["bash", "-c", rearm], check=False, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 124, (r.stdout, r.stderr))


class TestReapThrottle(WaiterBase):
    def gone(self, name: str = "s1") -> None:
        self.dispatch(name=name)
        self.unfinished(name=name, pid=2**22 - 33, pid_start="x")

    def fresh_stamp(self) -> Path:
        stamp = self.tmp / "reap.stamp"
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(f"{time.time()}\n")
        return stamp

    def test_a_fresh_stamp_skips_the_sweep(self):
        self.gone()
        self.fresh_stamp()
        r = self.run_acp(["reap", str(self.out)], env=self.throttle_env())
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertIsNone(self.record()["finished"], "a throttled sweep read no record")

    def test_an_expired_stamp_sweeps_and_touches_it(self):
        self.gone()
        stamp = self.tmp / "reap.stamp"
        r = self.run_acp(["reap", str(self.out)], env=self.throttle_env())
        self.assertIn("reaped\ts1\t", r.stdout)
        self.assertTrue(stamp.exists())
        # inside the interval now: the next one skips
        r2 = self.run_acp(["reap", str(self.out)], env=self.throttle_env())
        self.assertEqual((r2.returncode, r2.stdout), (0, ""))

    def test_force_sweeps_anyway(self):
        self.gone()
        self.fresh_stamp()
        r = self.run_acp(["reap", "--force", str(self.out)], env=self.throttle_env())
        self.assertIn("reaped\ts1\t", r.stdout)
        self.assertTrue(self.record()["finished"])

    def test_a_single_record_is_never_throttled(self):
        self.gone()
        self.fresh_stamp()
        r = self.run_acp(["reap", str(self.record_path())], env=self.throttle_env())
        self.assertIn("reaped\ts1\t", r.stdout)
        self.assertTrue(self.record()["finished"])

    def test_zero_interval_disables_the_throttle(self):
        self.gone()
        self.fresh_stamp()
        r = self.run_acp(["reap", str(self.out)], env=self.throttle_env(ACP_DISPATCH_REAP_MIN_INTERVAL="0"))
        self.assertIn("reaped\ts1\t", r.stdout)


class TestNoRoutingImport(WaiterBase):
    """reap and wait --once must not import route_agent (python -X importtime proves it): the
    module-level import made every invocation pay for the routing module and its config parse."""

    def importtime(self, args: list[str], rc: int, env: dict[str, str] | None = None) -> str:
        e = dict(os.environ)
        e.update(env or {})
        r = subprocess.run([sys.executable, "-X", "importtime", str(SCRIPT), *args], check=False,
                           capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, rc, r.stderr)
        return r.stderr

    def test_reap_with_nothing_to_reap_imports_no_route_agent(self):
        (self.out / "jobs").mkdir(parents=True, exist_ok=True)
        err = self.importtime(["reap", str(self.out)], rc=0, env=self.base_env())
        self.assertIn("nothing to reap", err)
        self.assertNotIn("route_agent", err)

    def test_wait_once_on_a_running_slice_imports_no_route_agent(self):
        self.dispatch()
        self.live()
        err = self.importtime(["wait", "--once", str(self.record_path())], rc=75)
        self.assertNotIn("route_agent", err)


if __name__ == "__main__":
    unittest.main()
