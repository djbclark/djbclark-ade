#!/usr/bin/env python3
"""Tests for acp-dispatch's dead-slice handling (2026-10-18).

A detached slice that died without finalize (a reboot's SIGTERM, SIGKILL, power loss) left
`exit: null, finished: null` forever and every reader showed it running (trackpad-settings,
pid 51407, 2026-10-17). Prevention: the runner traps TERM/HUP/INT and finalizes with 128+signal.
Detection: one rule, `dead_reason`, over pid + `pid_start`; `reap` finalizes such a record once;
check/wait/resume apply it. Also the wait/resume race on the agent's own `.done` touch and the
model alias on resume. Processes here are the fake acp-run, `sleep`, or this test process; the
fake launchctl only records or answers `print`.
"""
from __future__ import annotations

import json
import os
import runpy
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any, override
from unittest.mock import patch

from test_acp_dispatch import SCRIPT, Base, run


class ReapBase(Base):
    bindir: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        # the launchctl the runner script calls by name (`launchctl remove`) must be a fake too
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        _ = (self.bindir / "launchctl").write_text(f'#!/bin/bash\necho "$@" >> "{self.launchctl_calls}"\nexit 0\n')
        (self.bindir / "launchctl").chmod(0o755)

    def record_path(self, name: str = "s1") -> Path:
        return self.out / "jobs" / f"{name}.json"

    def write_record(self, rec: dict[str, Any], name: str = "s1") -> None:
        _ = self.record_path(name).write_text(json.dumps(rec))

    def unfinished(self, name: str = "s1", keep_report: bool = False, **fields: Any) -> dict[str, Any]:
        """A finished record turned back into a running one, as a crash leaves it: no `.done`, no
        finalize, and (unless keep_report) a half-written report without DONE."""
        rec = self.record(name)
        Path(rec["done"]).unlink(missing_ok=True)
        if not keep_report:
            _ = Path(rec["report"]).write_text("STATUS: working\nhalf done\n")
        rec.update(finished=None, exit=None, status="running", pid=None, pid_start=None)
        rec.pop("failure", None)
        rec.pop("reaped", None)
        rec.update(fields)
        self.write_record(rec, name)
        return rec

    def mod(self):
        return runpy.run_path(str(SCRIPT))


class TestSignalledRunner(ReapBase):
    def test_sigterm_to_the_runner_finalizes_with_143(self):
        # a dry-run style detached dispatch: the runner script is written but launchctl is fake
        r = self.dispatch("--detach", "--no-wait", mode="slow")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        runner = Path(rec["runner"])
        self.assertIn('trap \'kill -TERM "$child" 2>/dev/null\' TERM HUP INT', runner.read_text())
        env = {**os.environ, **self.base_env("slow"), "PATH": f"{self.bindir}:{os.environ['PATH']}"}
        with subprocess.Popen(["bash", str(runner)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as proc:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not self.record().get("pid"):
                time.sleep(0.05)
            self.assertTrue(self.record().get("pid"), "the agent never started")
            self.assertTrue(self.record().get("pid_start"), "pid_start not stored")
            proc.send_signal(signal.SIGTERM)
            _, err = proc.communicate(timeout=30)
        rec = self.record()
        self.assertEqual(rec["exit"], 143, err)
        self.assertEqual(rec["signal"], "SIGTERM")
        self.assertEqual(rec["status"], "no-report")
        self.assertTrue(rec["finished"])
        self.assertIsNone(rec["pid"])
        self.assertTrue(rec["failure"].startswith("NO-REPORT: killed: SIGTERM (codex, m1): acp-run exit 143"), rec["failure"])
        self.assertEqual(Path(rec["log"]).with_suffix(".exit").read_text().strip(), "143")
        self.assertTrue(any("remove acp-dispatch.out.s1" in c for c in self.launchctl()), self.launchctl())
        self.assertEqual(run(["check", str(self.record_path())]).returncode, 3)


class TestReap(ReapBase):
    def test_dead_pid_without_finalize_is_reaped_once(self):
        self.dispatch()
        gone = 2**22 - 7                                  # above pid_max on macOS: never alive
        rec = self.unfinished(pid=gone, pid_start="Sat Oct 17 20:00:00 2026")
        before = Path(rec["log"]).stat().st_mtime
        r = run(["reap", str(self.record_path())])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("reaped\ts1\t"), r.stdout)
        self.assertIn("lost (pid", r.stdout)
        rec = self.record()
        self.assertEqual(rec["exit"], 255)
        self.assertEqual(rec["status"], "no-report")
        self.assertEqual(rec["reaped"]["exit_source"], "lost")
        self.assertIn(f"pid {gone} gone without finalize", rec["reaped"]["reason"])
        self.assertAlmostEqual(rec["finished"], before, delta=2)   # the log's last write, not now
        self.assertTrue(Path(rec["done"]).exists())
        self.assertTrue(rec["failure"].startswith(f"NO-REPORT: lost (pid {gone} gone without finalize) (codex, m1): acp-run exit 255"), rec["failure"])
        # idempotent: the second reap finds it finished
        r2 = run(["reap", str(self.record_path())])
        self.assertEqual((r2.returncode, r2.stdout), (0, ""))
        self.assertIn("nothing to reap", r2.stderr)
        self.assertEqual(Path(rec["report"]).read_text().count("NO-REPORT:"), 1)

    def test_pid_reuse_is_reaped_live_slice_is_not(self):
        self.dispatch()
        mod = self.mod()
        me = os.getpid()
        # alive pid, wrong start time: another process got the number (a reboot)
        self.unfinished(pid=me, pid_start="Thu Jan  1 00:00:00 1970")
        self.assertIn("another process now", mod["dead_reason"](self.record()))
        r = run(["reap", str(self.record_path())])
        self.assertIn("reaped\ts1\t", r.stdout)
        self.assertEqual(self.record()["exit"], 255)
        # alive pid with its own start time: running, never reaped
        self.dispatch(name="live")
        self.unfinished(name="live", pid=me, pid_start=mod["proc_start"](me))
        self.assertIsNone(mod["dead_reason"](self.record("live")))
        r = run(["reap", str(self.record_path("live"))])
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIsNone(self.record("live")["finished"])
        c = run(["check", str(self.record_path("live"))])
        self.assertEqual(c.returncode, 1)
        self.assertTrue(c.stdout.startswith(("pending\tlive\t", "running\tlive\t", "partial\tlive\t")), c.stdout)
        self.assertNotIn("reaped", self.record("live"))

    def test_ps_timeout_is_not_pid_reuse(self):
        # 2026-10-18: at load 35+ `ps -o lstart=` hit its 10 s timeout, proc_start returned None,
        # and a live slice (hermes-forgejo-ci) was called reused and reaped as lost
        self.dispatch()
        mod = self.mod()
        me = os.getpid()
        self.unfinished(pid=me, pid_start=mod["proc_start"](me))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["ps"], 10)):
            self.assertIsNone(mod["dead_reason"](self.record()))

    def test_resume_clears_the_last_runs_exit_file(self):
        # a stale <name>.exit from the run before a resume was read as the resumed run's exit code
        self.dispatch()
        exit_path = Path(self.record()["log"]).with_suffix(".exit")
        _ = exit_path.write_text("1\n")
        r = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(exit_path.exists())

    def test_old_format_record_without_pid_start(self):
        self.dispatch()
        mod = self.mod()
        # a process whose command line still looks like the slice: running
        with subprocess.Popen(["bash", "-c", 'exec -a "acp-run codex -C /x" sleep 30']) as proc:
            try:
                time.sleep(0.3)
                self.unfinished(pid=proc.pid)
                self.assertIsNone(mod["dead_reason"](self.record()))
                self.assertEqual(run(["reap", str(self.record_path())]).stdout, "")
            finally:
                proc.kill()
        # this test process: alive, but not an acp-run: reaped
        self.unfinished(pid=os.getpid())
        self.assertIn("another process now", mod["dead_reason"](self.record()))
        r = run(["reap", str(self.record_path())])
        self.assertIn("reaped", r.stdout)

    def test_done_report_with_marker_finalizes_as_done(self):
        self.dispatch()
        rec = self.unfinished(pid=2**22 - 9, pid_start="x", keep_report=True)
        Path(rec["done"]).touch()
        self.assertTrue(Path(rec["report"]).read_text().rstrip().endswith("DONE"))
        r = run(["reap", str(self.record_path())])
        self.assertIn("reaped\ts1\t", r.stdout)
        self.assertIn("done: STATUS: working", r.stdout)
        self.assertEqual(self.record()["reaped"]["exit_source"], "lost")   # 0 by delivery, not by an exit file
        rec = self.record()
        self.assertEqual((rec["status"], rec["exit"]), ("done", 0))
        self.assertNotIn("NO-REPORT", Path(rec["report"]).read_text())
        self.assertEqual(run(["check", str(self.record_path())]).returncode, 0)

    def test_exit_from_exit_file_then_launchd(self):
        self.dispatch()
        rec = self.unfinished(pid=2**22 - 11, pid_start="x", label="acp-dispatch.out.s1")
        Path(rec["log"]).with_suffix(".exit").write_text("137\n")
        run(["reap", str(self.record_path())])
        rec = self.record()
        self.assertEqual((rec["exit"], rec["reaped"]["exit_source"]), (137, "exit file"))
        self.assertIn("NO-REPORT: lost", rec["failure"])
        # no exit file: launchd's last exit status for the label
        self.dispatch(name="s2")
        self.unfinished(name="s2", pid=2**22 - 13, pid_start="x", label="acp-dispatch.out.s2")
        lc = self.tmp / "launchctl-print"
        lc.write_text('#!/bin/bash\n[ "$1" = print ] && { echo "	state = not running"; echo "	last exit code = 143"; exit 0; }\nexit 0\n')
        lc.chmod(0o755)
        run(["reap", str(self.record_path("s2"))], env={"ACP_DISPATCH_LAUNCHCTL": str(lc)})
        rec = self.record("s2")
        self.assertEqual((rec["exit"], rec["reaped"]["exit_source"]), (143, "launchd"))

    def test_reaped_quota_stderr_follows_the_quota_path(self):
        self.dispatch(mode="quota_codex_date")
        self.unfinished(pid=2**22 - 15, pid_start="x", auto_resume=None)
        report = Path(self.record()["report"])
        report.write_text("\n".join(ln for ln in report.read_text().splitlines() if not ln.startswith("NO-REPORT")) + "\n")
        self.launchctl_calls.unlink(missing_ok=True)
        r = run(["reap", str(self.record_path())], env=self.base_env())
        self.assertIn("resume-scheduled", r.stdout)
        rec = self.record()
        self.assertTrue(rec["failure"].startswith("NO-REPORT: quota (codex, m1, retry at Oct 18th"), rec["failure"])
        self.assertEqual(rec["auto_resume"]["state"], "scheduled")
        self.assertEqual(len(self.launchctl()), 1)

    def test_reap_a_directory_and_two_concurrent_reapers(self):
        for name in ("a", "b", "c"):
            self.dispatch(name=name)
        self.unfinished(name="a", pid=2**22 - 17, pid_start="x")
        self.unfinished(name="b", pid=2**22 - 19, pid_start="x")
        env = {**os.environ, **self.base_env()}
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "reap", str(self.out)], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0, 0])
        lines = [ln for out in outs for ln in out.splitlines()]
        self.assertEqual(sorted(ln.split("\t")[1] for ln in lines), ["a", "b"], lines)
        self.assertEqual(self.record("c")["status"], "done")
        for name in ("a", "b"):
            self.assertEqual(Path(self.record(name)["report"]).read_text().count("NO-REPORT:"), 1)

    def test_check_and_wait_apply_the_rule(self):
        self.dispatch()
        self.unfinished(pid=2**22 - 21, pid_start="x")
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertTrue(c.stdout.startswith("no-report\ts1\t"), c.stdout)
        self.assertIn("lost (pid", c.stdout)
        self.assertEqual(self.record()["exit"], 255)
        # wait returns promptly on a dead slice instead of sitting until the timeout
        self.dispatch(name="w")
        self.unfinished(name="w", pid=2**22 - 23, pid_start="x", wait_timeout=10 ** 6)
        mod = self.mod()
        with patch("time.sleep") as sleep:
            self.assertEqual(mod["wait_record"](self.record_path("w")), 0)
        sleep.assert_not_called()
        self.assertEqual(self.record("w")["status"], "no-report")
        self.assertEqual(run(["check", str(self.record_path("w"))]).returncode, 3)

    def test_resume_of_a_reaped_record_works(self):
        self.dispatch()
        self.unfinished(pid=2**22 - 25, pid_start="x")
        r = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual((rec["status"], rec["resume_count"]), ("done", 1))
        self.assertIn("NO-REPORT: lost", (self.out / "s1-r1-report.md").read_text())

    def test_launchd_job_gone_before_the_agent_started(self):
        self.dispatch()
        mod = self.mod()
        rec = self.unfinished(pid=None, label="acp-dispatch.out.s1", started=time.time() - 600)
        lc = self.tmp / "launchctl-missing"
        lc.write_text("#!/bin/bash\nexit 113\n")          # launchctl print: no such service
        lc.chmod(0o755)
        with patch.dict(os.environ, {"ACP_DISPATCH_LAUNCHCTL": str(lc)}):
            self.assertIn("never started", mod["dead_reason"](rec))
        # a young record without a pid is just not started yet
        rec["started"] = time.time()
        self.write_record(rec)
        with patch.dict(os.environ, {"ACP_DISPATCH_LAUNCHCTL": str(lc)}):
            self.assertIsNone(mod["dead_reason"](rec))


class TestWaitResumeRace(ReapBase):
    def test_wait_returns_only_once_finalized(self):
        # the agent touched .done; acp-run and finalize are still running (pid alive, same process)
        self.dispatch()
        mod = self.mod()
        me = os.getpid()
        rec = self.unfinished(pid=me, pid_start=mod["proc_start"](me))
        Path(rec["done"]).touch()
        ticks = [0]

        def tick(seconds: float) -> None:
            if seconds < 1:                                   # subprocess.run(timeout=) polls with
                return                                        # sub-second sleeps; only wait_record's count
            ticks[0] += 1
            if ticks[0] == 2:                                 # finalize lands
                r = self.record()
                r.update(finished=time.time(), exit=0, pid=None, status="done")
                self.write_record(r)
        with patch("time.sleep", side_effect=tick):
            self.assertEqual(mod["wait_record"](self.record_path()), 0)
        self.assertEqual(ticks[0], 2)

    def test_resume_waits_for_finalize_then_works(self):
        self.dispatch()
        mod = self.mod()
        me = os.getpid()
        rec = self.unfinished(pid=me, pid_start=mod["proc_start"](me))
        Path(rec["done"]).touch()

        def tick(_: float) -> None:                           # finalize lands during resume's wait
            r = self.record()
            r.update(finished=time.time(), exit=0, pid=None, status="done")
            self.write_record(r)
        with patch.dict(os.environ, self.base_env()), patch("time.sleep", side_effect=tick):
            rc = mod["main"](["resume", str(self.record_path()), "--timeout", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.record()["resume_count"], 1)
        # never finalized within the bound: refused, as before
        self.unfinished(pid=me, pid_start=mod["proc_start"](me))
        Path(self.record()["done"]).touch()
        r = run(["resume", str(self.record_path())], env=self.base_env(ACP_DISPATCH_FINALIZE_WAIT="0"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("still running; wait for finalize", r.stderr)
        # no .done and alive: a running slice
        Path(self.record()["done"]).unlink()
        r = run(["resume", str(self.record_path())], env=self.base_env(ACP_DISPATCH_FINALIZE_WAIT="0"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("cannot resume a running slice", r.stderr)


class TestModelApplied(ReapBase):
    def test_resume_passes_the_model_acp_run_applied(self):
        r = self.dispatch_model("fable", env={"FAKE_APPLIED": "claude-fable-5-1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual((rec["model"], rec["model_applied"]), ("fable", "claude-fable-5-1"))
        rr = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(rr.returncode, 0, rr.stderr)
        self.assertIn("--model claude-fable-5-1", self.record()["cmd"])
        self.assertNotIn("--model fable", self.record()["cmd"])

    def test_without_an_applied_row_the_alias_is_kept(self):
        self.dispatch()
        self.assertIsNone(self.record()["model_applied"])
        run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertIn("--model m1", self.record()["cmd"])


class TestReapInstall(ReapBase):
    def test_install_copies_the_plist_and_bootstraps(self):
        agents = self.tmp / "LaunchAgents"
        env = self.base_env(ACP_DISPATCH_LAUNCH_AGENTS=str(agents))
        r = run(["reap", "--install"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = agents / "com.djbclark.acp-dispatch-reap.plist"
        self.assertTrue(dest.exists())
        text = dest.read_text()
        self.assertIn("<string>reap</string>", text)
        self.assertIn("<key>RunAtLoad</key><true/>", text)
        self.assertIn("<integer>1800</integer>", text)
        calls = self.launchctl()
        self.assertTrue(any(c.startswith("bootstrap gui/") and c.endswith(str(dest)) for c in calls), calls)
        r = run(["reap", "--uninstall"], env=env)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(dest.exists())
        self.assertTrue(any(c.startswith("bootout gui/") for c in self.launchctl()))


if __name__ == "__main__":
    unittest.main()
