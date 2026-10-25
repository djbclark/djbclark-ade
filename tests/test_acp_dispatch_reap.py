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
        # a private stamp and no throttle: two reapers must not share (or be skipped by) the machine's stamp
        env = {**os.environ, **self.base_env(ACP_DISPATCH_REAP_STAMP=str(self.tmp / "reap.stamp"),
                                             ACP_DISPATCH_REAP_MIN_INTERVAL="0")}
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

    def test_a_loaded_job_whose_label_holds_a_path_is_not_reaped_as_gone(self):
        # 2026-10-25: `launchctl print gui/UID/<label>` splits the label on "/", so every --task dispatch
        # (the label carries the absolute task dir) read "not loaded" after 120 s in the load gate and was
        # reaped as lost while its launchd job was alive and waiting.
        self.dispatch()
        mod = self.mod()
        label = f"acp-dispatch.{self.out}.s1"
        self.assertIn("/", label)
        rec = self.unfinished(pid=None, label=label, started=time.time() - 600)
        calls = self.tmp / "launchctl-calls"
        lc = self.tmp / "launchctl-path-label"
        lc.write_text(
            "#!/bin/bash\necho \"$@\" >> " + str(calls) + "\n"
            "[ \"$1\" = print ] && exit 113            # print cannot address a label with a slash\n"
            "[ \"$1\" = list ] && [ -f " + str(self.tmp / "loaded") + " ] && { echo '{ \"Label\" = \"x\"; };'; exit 0; }\n"
            "exit 113\n")
        lc.chmod(0o755)
        (self.tmp / "loaded").write_text("")
        with patch.dict(os.environ, {"ACP_DISPATCH_LAUNCHCTL": str(lc)}):
            self.assertIsNone(mod["dead_reason"](rec))         # loaded: still running
            self.assertIsNone(mod["launchd_last_exit"](label))  # unknown, not guessed
        self.assertIn("list " + label, calls.read_text())
        self.assertNotIn("print", calls.read_text())
        (self.tmp / "loaded").unlink()
        with patch.dict(os.environ, {"ACP_DISPATCH_LAUNCHCTL": str(lc)}):
            self.assertIn("never started", mod["dead_reason"](rec))  # really gone: still reaped


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


class RestartBase(ReapBase):
    BOOT = 1_760_880_691.0

    def killed(self, name: str = "s1", before_boot: float = 60, signame: str = "SIGTERM", rc: int = 143,
               session_id: str | None = "sess-1") -> Path:
        """A slice a signal ended and finalize recorded, `finished` set `before_boot` s before BOOT."""
        self.dispatch(name=name)
        _ = self.unfinished(name=name, signal=signame, session_id=session_id)
        path = self.record_path(name)
        r = run(["finalize", str(path), "--exit", str(rc)], env=self.base_env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rec = json.loads(path.read_text())
        rec["finished"] = self.BOOT - before_boot
        self.write_record(rec, name)
        return path

    def reap(self, path: Path, boot: float | None = BOOT, resume: bool = False) -> subprocess.CompletedProcess[str]:
        """`reap PATH` as the login sweep. The attribution tests run it with the auto-resume off (the
        resume rewrites the record); TestRestartResume asks for it."""
        extra = {} if boot is None else {"ACP_DISPATCH_BOOTTIME": str(boot)}
        if not resume:
            extra["ACP_DISPATCH_NO_AUTO_RESUME"] = "1"
        return run(["reap", str(path)], env=self.base_env(**extra))


class TestRestartAttribution(RestartBase):
    """A slice SIGTERMed by a Mac restart/logout says so (2026-10-19, ime-listener: the record said
    only "killed: SIGTERM" and sent the lead hunting for a harness bug). `reap` at login compares
    `finished` with kern.boottime; ACP_DISPATCH_BOOTTIME stands in for the sysctl."""
    def test_sigterm_just_before_boot_is_attributed_to_the_restart(self):
        path = self.killed()
        r = self.reap(path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith(f"restart-killed\ts1\t{path}\tsystem restart/logout (boot "), r.stdout)
        rec = self.record()
        self.assertRegex(rec["killed_by"], r"^system restart/logout \(boot \d\d:\d\d\)$")
        self.assertTrue(rec["failure"].startswith("NO-REPORT: killed: SIGTERM (system restart) (codex, m1)"), rec["failure"])
        self.assertIn("NO-REPORT: killed: SIGTERM (system restart) (codex, m1)", Path(rec["report"]).read_text())
        c = run(["check", str(path)])
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertIn("killed: SIGTERM (system restart)", c.stdout)
        # idempotent: the second sweep finds the mark and says nothing
        before = path.read_text()
        r2 = self.reap(path)
        self.assertEqual(r2.stdout, "")
        self.assertEqual(path.read_text(), before)
        self.assertEqual(Path(rec["report"]).read_text().count("(system restart)"), 1)

    def test_sighup_counts_too(self):
        path = self.killed(signame="SIGHUP", rc=129)
        self.assertIn("restart-killed", self.reap(path).stdout)
        self.assertIn("killed: SIGHUP (system restart)", self.record()["failure"])

    def test_outside_the_window_or_not_a_signal_is_left_alone(self):
        for name, kw in (("early", {"before_boot": 400}), ("after", {"before_boot": -30}),
                         ("plain", {"signame": "SIGKILL", "rc": 137})):
            path = self.killed(name=name, **kw)
            r = self.reap(path)
            self.assertEqual(r.stdout, "", (name, r.stdout))
            self.assertNotIn("killed_by", self.record(name), name)
            self.assertNotIn("system restart", self.record(name)["failure"], name)
        # an unreadable boot time attributes nothing either
        path = self.killed(name="noboot")
        self.assertEqual(run(["reap", str(path)], env=self.base_env(ACP_DISPATCH_BOOTTIME="garbage")).stdout, "")
        self.assertNotIn("killed_by", self.record("noboot"))

    def test_a_done_slice_is_never_marked(self):
        self.dispatch()
        self.assertEqual(self.reap(self.record_path()).stdout, "")
        self.assertNotIn("killed_by", self.record())

    def test_fallback_class_renders_the_attribution(self):
        fc = self.mod()["fallback_class"]
        self.assertEqual(fc({"signal": "SIGTERM"}), "killed: SIGTERM")
        self.assertEqual(fc({"signal": "SIGTERM", "killed_by": "system restart/logout (boot 09:31)"}),
                         "killed: SIGTERM (system restart)")

    def test_boot_time_parses_sysctl_output(self):
        mod = self.mod()
        out = "{ sec = 1760880691, usec = 262310 } Mon Oct 19 09:31:31 2026\n"
        done = subprocess.CompletedProcess([], 0, stdout=out)
        with patch.dict(os.environ, {"ACP_DISPATCH_BOOTTIME": ""}), \
                patch.object(subprocess, "run", return_value=done) as sysctl:
            self.assertEqual(mod["boot_time"](), 1760880691.0)
        self.assertEqual(sysctl.call_args.args[0], ["sysctl", "-n", "kern.boottime"])
        no_sysctl = subprocess.CompletedProcess([], 1, stdout="")   # Linux: kern.boottime is unknown
        with patch.dict(os.environ, {"ACP_DISPATCH_BOOTTIME": ""}), \
                patch.object(subprocess, "run", return_value=no_sysctl), \
                patch.object(Path, "read_text", side_effect=OSError("no /proc/stat")):
            self.assertIsNone(mod["boot_time"]())
        with patch.dict(os.environ, {"ACP_DISPATCH_BOOTTIME": ""}), \
                patch.object(subprocess, "run", return_value=no_sysctl), \
                patch.object(Path, "read_text", return_value="cpu  1 2 3\nbtime 1760880691\nprocesses 9\n"):
            self.assertEqual(mod["boot_time"](), 1760880691.0)   # /proc/stat on Linux
        with patch.dict(os.environ, {"ACP_DISPATCH_BOOTTIME": "1700000000"}):
            self.assertEqual(mod["boot_time"](), 1700000000.0)
        with patch.dict(os.environ, {"ACP_DISPATCH_BOOTTIME": ""}):
            real = mod["boot_time"]()                        # the machine's own sysctl or /proc/stat really parses
        self.assertTrue(real is not None and 0 < real <= time.time(), real)


class TestSignalResumeHint(ReapBase):
    """finalize appends the resume command to a signal kill that has a session (2026-10-19)."""

    def finalize(self, signame: str | None, session_id: str | None, rc: int = 143) -> str:
        self.dispatch()
        extra: dict[str, str] = {} if session_id else {"log": str(self.tmp / "no-session.jsonl")}  # the fake's log names one
        _ = self.unfinished(session_id=session_id, **extra, **({"signal": signame} if signame else {}))
        r = run(["finalize", str(self.record_path()), "--exit", str(rc)], env=self.base_env())
        return r.stdout

    def test_killed_with_a_session_gets_the_resume_command(self):
        out = self.finalize("SIGTERM", "sess-1")
        self.assertTrue(out.startswith("no-report\t"), out)
        self.assertRegex(out, r"; resume in place: \S+acp-dispatch resume \S+s1\.json --detach --no-wait")
        self.assertNotIn("after the reset", out)

    def test_killed_without_a_session_gets_none(self):
        out = self.finalize("SIGTERM", None)
        self.assertNotIn("resume in place", out)

    def test_an_ordinary_failure_gets_none(self):
        out = self.finalize(None, "sess-1", rc=1)
        self.assertNotIn("resume in place", out)

    def test_the_quota_hint_keeps_its_wording(self):
        hint = self.mod()["manual_resume_hint"]({"failure": "NO-REPORT: quota (codex, m1, retry at Oct 18th 9am)",
                                                "record": "/x/s1.json"}, Path("/x/s1.json"))
        self.assertTrue(hint.startswith("resume in place after Oct 18th 9am: "), hint)


class TestCheckSignalHint(ReapBase):
    """`check` on a signal-killed or lost slice (2026-10-20): resume in place, never `--escalate`;
    the hint follows the failure class actually recorded (adversary, PR 18)."""

    def checked(self, failure: str | None = None, session: str | None = "sess-1", **fields: Any) -> str:
        """Finalize a signal-killed slice, then rewrite the record as asked and run `check`."""
        self.dispatch()
        extra: dict[str, Any] = {} if session else {"log": str(self.tmp / "no-session.jsonl")}
        _ = self.unfinished(session_id=session, signal="SIGTERM", kind="code", **extra)
        r = run(["finalize", str(self.record_path()), "--exit", "143"], env=self.base_env())
        self.assertTrue(r.stdout.startswith("no-report\t"), r.stdout)
        rec = json.loads(self.record_path().read_text())
        if failure:
            rec["failure"] = failure
        rec.update(fields)
        self.write_record(rec)
        return run(["check", str(self.record_path())], env=self.base_env()).stdout

    def test_signal_with_a_session_resumes_and_never_escalates(self):
        out = self.checked()
        self.assertRegex(out, r"; resume in place: \S+acp-dispatch resume \S+s1\.json --detach --no-wait")
        self.assertNotIn("after the reset", out)
        self.assertNotIn("escalate", out)

    def test_a_lost_slice_resumes_with_no_reset_wording(self):
        self.dispatch()
        _ = self.unfinished(session_id="sess-1", kind="code", pid=2**22 - 41, pid_start="x")
        out = run(["check", str(self.record_path())], env=self.base_env()).stdout
        self.assertIn("lost (pid", out)
        self.assertRegex(out, r"; resume in place: \S+acp-dispatch resume ")
        self.assertNotIn("after the reset", out)
        self.assertNotIn("escalate", out)

    def test_signal_without_a_session_says_so(self):
        out = self.checked(session=None)
        self.assertIn("no resumable session", out)
        self.assertNotIn("resume in place", out)
        self.assertNotIn("escalate", out)

    def test_a_record_without_log_or_command_cannot_be_resumed(self):
        out = self.checked(cmd="")
        self.assertIn("no resumable session (the record has no log or command", out)

    def test_the_login_sweep_resuming_it_is_said(self):
        out = self.checked(restart_resume={"state": "resuming"})
        self.assertIn("resume-scheduled: the login sweep is resuming it in place", out)
        self.assertNotIn("escalate", out)

    def test_a_failed_restart_resume_is_noted_beside_the_command(self):
        out = self.checked(restart_resume={"state": "failed", "detail": "boom"})
        self.assertIn("resume in place", out)
        self.assertIn("restart-resume failed: boom", out)

    def test_agy_on_a_non_gemini_model_resumes_in_a_new_session(self):
        # resume_record continues such a slice with a checkpoint instead of refusing it
        out = self.checked(agent="agy", model="claude-sonnet-4-5")
        self.assertIn("resume in place", out)
        self.assertIn("continues in a new session with a checkpoint", out)
        self.assertNotIn("no resumable session", out)

    def test_refused_and_auth_keep_their_own_hint(self):
        out = self.checked("NO-REPORT: refused (the model declined)")
        self.assertNotIn("resume in place", out)
        self.assertIn("escalate", out)                      # an ordinary class keeps the one-rung hint
        # a login the agent cannot refresh is not a tier problem: the login hint, never a climb
        # (adversary PR 18 follow-up, finding I; the record's agent here is codex)
        out = self.checked("NO-REPORT: auth (login expired)")
        self.assertNotIn("resume in place", out)
        self.assertNotIn("escalate", out)
        self.assertIn("codex login", out)

    def test_a_quota_stop_with_a_signal_prints_the_resume_hint_once(self):
        out = self.checked("NO-REPORT: quota (codex, m1, retry at Oct 18th 9am)")
        self.assertEqual(out.count("resume in place"), 1, out)
        self.assertIn("after Oct 18th 9am", out)

    def test_manual_hint_for_a_lost_record_has_no_reset(self):
        hint = self.mod()["manual_resume_hint"]({"failure": "NO-REPORT: lost (pid 9 gone)", "record": "/x/s1.json"},
                                               Path("/x/s1.json"))
        self.assertTrue(hint.startswith("resume in place: "), hint)


class TestRestartResume(RestartBase):
    """The login sweep resumes a restart-killed slice in place, once per boot (operator 2026-10-19)."""

    def test_restart_killed_slice_is_resumed_once(self):
        path = self.killed()
        r = self.reap(path, resume=True)
        self.assertTrue(r.stdout.splitlines()[0].startswith("restart-killed\ts1\t"), r.stdout)
        self.assertRegex(r.stdout, r"restart-resumed\ts1\t\S+\tin place, session fake-session")
        rec = self.record()
        self.assertEqual(rec["resume_count"], 1)
        self.assertEqual(rec["session_id"], "fake-session")      # the fake agent's log names it
        self.assertIsNone(rec["finished"])
        self.assertIn("--resume fake-session", rec["cmd"])
        self.assertIn("Mac was restarted or logged out", Path(rec["brief"]).read_text())
        self.assertTrue(any(c.startswith("submit") for c in self.launchctl()), self.launchctl())
        # a second sweep in the same boot does nothing: the resumed slice is running again
        calls = len(self.launchctl())
        self.assertEqual(self.reap(path, resume=True).stdout, "")
        self.assertEqual(len(self.launchctl()), calls)

    def test_the_marker_blocks_a_second_try_this_boot_and_an_old_kill_is_not_revived(self):
        path = self.killed()
        rec = json.loads(path.read_text())
        rec["restart_resume"] = {"boot": int(self.BOOT), "state": "failed", "detail": "x"}
        self.write_record(rec)
        self.assertNotIn("restart-resume", self.reap(path, resume=True).stdout)
        self.assertFalse(any(c.startswith("submit") for c in self.launchctl()), self.launchctl())
        # a later boot: this kill finished before that boot's window
        r = self.reap(path, boot=self.BOOT + 3600, resume=True)
        self.assertNotIn("restart-resume", r.stdout)
        self.assertFalse(any(c.startswith("submit") for c in self.launchctl()), self.launchctl())

    def test_skips(self):
        cases = {
            "off": ({"auto_resume": {"state": "off", "detail": "--no-auto-resume"}}, "auto-resume is off"),
            "pending": ({"auto_resume": {"state": "scheduled", "attempt": 1}}, "quota auto-resume is already scheduled"),
            "closed": ({"closed": True}, None),
            "nosession": ({"log": "/nonexistent/log.jsonl", "session_id": None}, "no ACP session id"),
        }
        for name, (fields, why) in cases.items():
            path = self.killed(name=name, session_id=None if name == "nosession" else "sess-1")
            rec = json.loads(path.read_text())
            rec.update(fields)
            self.write_record(rec, name)
            r = self.reap(path, resume=True)
            self.assertNotIn("restart-resumed", r.stdout, (name, r.stdout))
            if why:
                self.assertIn(why, r.stdout, name)
            after = self.record(name)
            self.assertIsNotNone(after["finished"], name)
            self.assertNotIn("resume_count", {k: v for k, v in after.items() if v}, name)
        self.assertFalse(any(c.startswith("submit") for c in self.launchctl()), self.launchctl())

    def test_a_delivered_report_skips(self):
        path = self.killed()
        _ = Path(self.record()["report"]).write_text("the result\nDONE\n")
        r = self.reap(path, resume=True)
        self.assertIn("restart-resume-skipped", r.stdout)
        self.assertIn("slice delivered", r.stdout)
        self.assertFalse(any(c.startswith("submit") for c in self.launchctl()))

    def test_env_opt_out(self):
        path = self.killed()
        r = run(["reap", str(path)], env=self.base_env(ACP_DISPATCH_BOOTTIME=str(self.BOOT),
                                                        ACP_DISPATCH_NO_AUTO_RESUME="1"))
        self.assertIn("auto-resume is off", r.stdout)

    def test_a_refused_resume_is_recorded_not_retried(self):
        path = self.killed()
        rec = json.loads(path.read_text())
        rec["cmd"] = ""                                   # resume dies: nothing to rebuild the command from
        self.write_record(rec)
        r = self.reap(path, resume=True)
        self.assertIn("restart-resume-failed", r.stdout)
        self.assertIn("resume in place: ", r.stdout)
        self.assertEqual(self.record()["restart_resume"]["state"], "failed")
        self.assertNotIn("restart-resume", self.reap(path, resume=True).stdout)


if __name__ == "__main__":
    unittest.main()
