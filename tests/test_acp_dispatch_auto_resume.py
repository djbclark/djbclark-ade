#!/usr/bin/env python3
"""Tests for acp-dispatch's automatic in-place resume after a quota stop.

2026-10-18: three codex slices were stopped by the 5-hour limit; `check` said exit 3 and the
documented reaction was "re-task", which would have thrown away each session's reasoning. The
operator: tokens spent thinking are work; a quota stop is resumed in the same session, by default.

Reuses test_acp_dispatch's fake acp-run (FAKE_MODE selects its behaviour; `quota_codex_date`
is the real codex refusal of that night) and its fake launchctl, which only records the submit.
aiuse is a fake script that returns one headroom reading per call from FAKE_AIUSE_SEQ.
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import override
from unittest.mock import patch

from test_acp_dispatch import SCRIPT, Base, run

FAKE_AIUSE = """#!/bin/bash
# fake aiuse: `note-exhausted` is accepted silently; `--available --json --live` prints one
# headroom reading per call, walking FAKE_AIUSE_SEQ (the last value repeats)
[ "$1" = note-exhausted ] && exit 0
f="$FAKE_AIUSE_COUNT"; n=$(( $(cat "$f" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$f"
IFS=, read -ra seq <<< "$FAKE_AIUSE_SEQ"
v=${seq[$((n-1))]}; [ -z "$v" ] && v=${seq[$((${#seq[@]}-1))]}
echo "aiuse: cached snapshot, 2 preamble lines"
echo "like the real one"
echo "{\\"schema_version\\": \\"1.3\\", \\"available\\": [{\\"provider\\": \\"codex\\", \\"headroom_percent\\": $v}], \\"excluded\\": []}"
"""


class AutoResumeBase(Base):
    fake_aiuse: Path = Path()
    aiuse_count: Path = Path()
    healthy_snap: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.fake_aiuse = self.tmp / "fake-aiuse"
        _ = self.fake_aiuse.write_text(FAKE_AIUSE)
        self.fake_aiuse.chmod(0o755)
        self.aiuse_count = self.tmp / "aiuse-count"
        # A measured, healthy pool, as on the real night: the slice is not a checkpoint slice
        # (an unmeasured pool makes every slice one, and a two-line report then classifies
        # `quota-checkpointed`, exit 5, which test_acp_dispatch covers).
        # Weekly must stay above the codex estimate floor (60%) × 1.5, or the near-limit
        # rule forces checkpoint (2026-10-18 dispatch.estimate_floor).
        self.healthy_snap = self.tmp / "healthy.json"
        _ = self.healthy_snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {
            "accounts": [{"provider": "codex", "windows": [
                {"label": "5h", "remaining_percent": 98.0}, {"label": "weekly", "remaining_percent": 95.0}]}]}}))

    @override
    def base_env(self, mode: str = "writes", **extra: str) -> dict[str, str]:
        return super().base_env(mode, **{"AIUSE_SNAPSHOT": str(self.healthy_snap), **extra})

    def record_path(self, name: str = "s1") -> Path:
        return self.out / "jobs" / f"{name}.json"

    def aiuse_calls(self) -> int:
        return int(self.aiuse_count.read_text()) if self.aiuse_count.exists() else 0

    def past_due(self, name: str = "s1") -> None:
        """Pretend the reset has passed: the launchd runner would be past its sleep."""
        rec = self.record(name)
        rec["auto_resume"]["not_before"] = time.time() - 1
        self.record_path(name).write_text(json.dumps(rec))

    def run_auto_resume(self, seq: str, mode: str = "writes", attempt: int = 1,
                        name: str = "s1") -> tuple[int, list[float]]:
        """Run the scheduled runner's work in-process with sleeps recorded, not slept. The
        module loads inside the patched env so module constants (e.g. the D2 max-wait override
        these fixtures need for their 2036 resets) read the same values a subprocess would."""
        sleeps: list[float] = []
        env = self.base_env(mode, ACP_DISPATCH_AIUSE=str(self.fake_aiuse), FAKE_AIUSE_SEQ=seq,
                            FAKE_AIUSE_COUNT=str(self.aiuse_count))
        with patch.dict(os.environ, env), patch("time.sleep", side_effect=sleeps.append):
            mod = runpy.run_path(str(SCRIPT))
            rc = mod["auto_resume_record"](self.record_path(name), attempt)
        return rc, sleeps


class TestSchedule(AutoResumeBase):
    def test_quota_finalize_schedules_exactly_one_resume(self):
        r = self.dispatch(mode="quota_codex_date")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("resume-scheduled\ts1\t"), r.stdout)
        self.assertIn("resumes in place at", r.stdout)
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertEqual((ar["attempt"], ar["max"], ar["reset_source"]), (1, 3, "stderr"))
        # "try again at Oct 18th, 2036 4:41 AM" on the local clock, plus the 5-minute margin (a
        # future year: a reset already past is scheduled from now; 2026 broke this on 2026-10-18)
        want = datetime(2036, 10, 18, 4, 46).astimezone().timestamp()
        self.assertAlmostEqual(ar["not_before"], want, delta=1)
        self.assertEqual(ar["label"], "acp-dispatch.out.s1.resume1")
        calls = self.launchctl()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("submit -l acp-dispatch.out.s1.resume1", calls[0])
        runner = Path(ar["runner"]).read_text()
        self.assertIn(f"auto-resume {rec['record']} --attempt 1", runner)
        self.assertIn("launchctl remove acp-dispatch.out.s1.resume1", runner)
        # the report still ends on its NO-REPORT line; the record stays finished with .done
        lines = Path(rec["report"]).read_text().splitlines()
        self.assertTrue(lines[-1].startswith("NO-REPORT: quota (codex, m1, retry at Oct 18th, 2036 4:41 AM)"), lines[-1])
        self.assertTrue(Path(rec["done"]).exists())
        self.assertEqual(rec["status"], "resume-scheduled")
        # finalize again (a hand re-run): the earlier schedule stands, no second launchd job
        f = run(["finalize", str(self.record_path()), "--exit", "1"], env=self.base_env())
        self.assertEqual(f.returncode, 1, f.stdout + f.stderr)
        self.assertEqual(len(self.launchctl()), 1)
        self.assertEqual(self.record()["auto_resume"]["attempt"], 1)

    def test_non_quota_failures_schedule_nothing(self):
        for mode in ("agent_metrics", "refused", "timeout", "partial", "writes"):
            name = mode.replace("_", "-")
            self.dispatch(mode=mode, name=name)
            self.assertIsNone(self.record(name).get("auto_resume"), mode)
            self.assertNotEqual(self.record(name)["status"], "resume-scheduled", mode)
        self.assertEqual(self.launchctl(), [])

    def test_no_auto_resume_prints_the_manual_command_and_retry_time(self):
        r = self.dispatch("--no-auto-resume", mode="quota_codex_date")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("no-report\t"), r.stdout)
        rec = self.record()
        self.assertEqual((rec["auto_resume"]["state"], rec["auto_resume"]["detail"]), ("off", "--no-auto-resume"))
        self.assertEqual(self.launchctl(), [])
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3)
        self.assertIn(f"resume {rec['record']} --detach --no-wait", c.stdout)
        self.assertIn("after Oct 18th, 2036 4:41 AM", c.stdout)
        self.assertIn("auto-resume off", c.stdout)
        # the opt-out follows the slice through a manual resume
        rr = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env("quota_codex_date"))
        self.assertEqual(rr.returncode, 3, rr.stdout + rr.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "off")
        self.assertEqual(self.launchctl(), [])

    def test_session_wide_opt_out(self):
        r = self.dispatch(mode="quota_codex_date", env={"ACP_DISPATCH_NO_AUTO_RESUME": "1"})
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.record()["auto_resume"]["state"], "off")
        self.assertEqual(self.launchctl(), [])

    def test_closed_record_is_never_scheduled(self):
        # A stop that finalized before this change (plektra-small-issues s1/s2b/s3 on
        # 2026-10-18) has `closed` set and no auto_resume field; a finalize re-run must leave it.
        self.dispatch("--no-auto-resume", mode="quota_codex_date")
        rec = self.record()
        rec.pop("auto_resume")
        rec["closed"] = int(time.time())
        self.record_path().write_text(json.dumps(rec))
        f = run(["finalize", str(self.record_path()), "--exit", "1"], env=self.base_env())
        self.assertEqual(f.returncode, 3, f.stdout)
        self.assertEqual(self.record()["auto_resume"]["state"], "skipped")
        self.assertIn("closed", self.record()["auto_resume"]["detail"])
        self.assertEqual(self.launchctl(), [])
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3)

    def test_no_session_id_or_unsupported_agent_falls_back_to_manual(self):
        for caps, want in (("nosid", "no ACP session id"), ("none", "neither load nor resume")):
            name = f"s-{caps}"
            r = self.dispatch(mode="quota_codex_date", name=name, env={"FAKE_CAPS": caps})
            self.assertEqual(r.returncode, 3, (caps, r.stdout))
            ar = self.record(name)["auto_resume"]
            self.assertEqual(ar["state"], "skipped", caps)
            self.assertIn(want, ar["detail"])
            c = run(["check", str(self.record_path(name))])
            self.assertEqual(c.returncode, 3)
            self.assertIn(" resume ", c.stdout)
        self.assertEqual(self.launchctl(), [])

    def test_reset_time_from_aiuse_snapshot_then_backoff(self):
        resets = (datetime.now().astimezone() + timedelta(hours=2)).replace(microsecond=0)
        snap = self.tmp / "exhausted.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "available_at": resets.isoformat(), "windows": [
                {"label": "5h", "remaining_percent": 0.0, "state": "exhausted", "resets_at": resets.isoformat()},
                {"label": "weekly", "remaining_percent": 40.0, "state": "ok",
                 "resets_at": (resets + timedelta(days=4)).isoformat()}]}]}}))
        r = self.dispatch("--min-headroom", "0", "--est-pct", "0", "--no-preflight", mode="quota",
                          env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["reset_source"], "aiuse")
        self.assertAlmostEqual(ar["not_before"], resets.timestamp() + 300, delta=1)
        # neither stderr nor aiuse: a bounded back-off
        r = self.dispatch(mode="quota", name="s2", env={"AIUSE_SNAPSHOT": str(self.tmp / "missing.json")})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ar = self.record("s2")["auto_resume"]
        self.assertEqual(ar["reset_source"], "backoff")
        self.assertAlmostEqual(ar["not_before"], time.time() + 1800 + 300, delta=30)

    def test_launchctl_refusal_is_recorded_not_fatal(self):
        bad = self.tmp / "bad-launchctl"
        bad.write_text("#!/bin/bash\necho 'nope' >&2\nexit 5\n")
        bad.chmod(0o755)
        r = self.dispatch(mode="quota_codex_date", env={"ACP_DISPATCH_LAUNCHCTL": str(bad)})
        self.assertEqual(r.returncode, 3, r.stdout)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "failed")
        self.assertIn("launchctl submit failed (5): nope", ar["detail"])
        self.assertIn("auto-resume not scheduled", r.stderr)

    def test_manual_resume_supersedes_the_schedule(self):
        self.dispatch(mode="quota_codex_date")
        rr = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(rr.returncode, 0, rr.stdout + rr.stderr)
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["auto_resume"]["state"], "resumed")
        # the launchd runner, firing later, finds it superseded and does nothing
        rc, sleeps = self.run_auto_resume("90")
        self.assertEqual(rc, 0)
        self.assertEqual(sleeps, [])
        self.assertEqual(self.aiuse_calls(), 0)
        self.assertEqual(self.record()["status"], "done")


class TestRunner(AutoResumeBase):
    def test_headroom_gate_resumes_once_the_pool_is_back(self):
        self.dispatch(mode="quota_codex_date")
        self.past_due()
        rc, sleeps = self.run_auto_resume("5,12,65")
        self.assertEqual(rc, 0)
        self.assertEqual(self.aiuse_calls(), 3)               # two short readings, then 65% left
        mod_poll = 10 * 60
        self.assertEqual(sleeps.count(mod_poll), 2, sleeps)
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["resume_count"], 1)
        self.assertIn("--resume fake-session", rec["cmd"])
        ar = rec["auto_resume"]
        self.assertEqual((ar["state"], ar["attempt"]), ("resumed", 1))
        self.assertEqual(ar["history"][-1]["outcome"], "resumed")
        self.assertIn("65.0% left", ar["history"][-1]["headroom"])
        brief = Path(rec["brief"]).read_text()
        self.assertTrue(brief.startswith("The previous turn was stopped by the provider's usage limit"), brief[:120])
        self.assertIn("do not redo", brief)
        self.assertIn("Original brief:\ndo the thing", brief)
        self.assertEqual(brief.count("## Delivery contract"), 1)
        archived = (self.out / "s1-r1-report.md").read_text()
        self.assertIn("NO-REPORT: quota", archived)
        self.assertFalse(Path(rec["report"]).read_text().startswith("NO-REPORT"))
        self.assertEqual(run(["check", str(self.record_path())]).returncode, 0)

    def test_headroom_never_back_gives_up_with_the_manual_command(self):
        self.dispatch(mode="quota_codex_date")
        self.past_due()
        rc, sleeps = self.run_auto_resume("3")
        self.assertEqual(rc, 3)
        self.assertEqual(self.aiuse_calls(), 6)
        self.assertEqual(sleeps.count(10 * 60), 5)
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual(ar["state"], "given-up")
        self.assertIn("3.0% left < 20% (check 6/6)", ar["detail"])
        self.assertEqual(rec["status"], "resume-scheduled")   # finalize's word; check reads the state
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertTrue(c.stdout.startswith("no-report\t"), c.stdout)
        self.assertIn(f"resume {rec['record']} --detach --no-wait", c.stdout)
        self.assertIn("auto-resume given-up", c.stdout)

    def test_unknown_headroom_goes_ahead(self):
        self.dispatch(mode="quota_codex_date")
        self.past_due()
        mod = runpy.run_path(str(SCRIPT))
        with patch.dict(os.environ, self.base_env("writes")), patch("time.sleep"):   # ACP_DISPATCH_AIUSE=off
            rc = mod["auto_resume_record"](self.record_path(), 1)
        self.assertEqual(rc, 0)
        self.assertEqual(self.record()["status"], "done")

    def test_second_quota_stop_schedules_attempt_two_then_gives_up_after_three(self):
        self.dispatch(mode="quota_codex_date")
        self.past_due()
        rc, _ = self.run_auto_resume("80", mode="quota_codex_date")
        self.assertEqual(rc, 1)                                 # resume-scheduled again
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual((ar["state"], ar["attempt"], rec["resume_count"]), ("scheduled", 2, 1))
        self.assertEqual(ar["label"], "acp-dispatch.out.s1.resume2")
        self.assertEqual(len(self.launchctl()), 2)
        self.assertEqual([h["outcome"] for h in ar["history"]], ["resumed"])
        for attempt in (2, 3):
            self.past_due()
            rc, _ = self.run_auto_resume("80", mode="quota_codex_date", attempt=attempt)
        self.assertEqual(rc, 3)
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual((ar["state"], ar["attempt"], rec["resume_count"]), ("given-up", 3, 3))
        self.assertIn("3 automatic resumes", ar["detail"])
        self.assertEqual(len(self.launchctl()), 3)
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3)
        self.assertIn("auto-resume given-up", c.stdout)
        self.assertIn(" resume ", c.stdout)
        for n in (1, 2, 3):
            self.assertTrue((self.out / f"s1-r{n}-report.md").exists(), n)

    def test_runner_for_a_stale_attempt_does_nothing(self):
        self.dispatch(mode="quota_codex_date")
        self.past_due()
        rc, sleeps = self.run_auto_resume("90", attempt=2)
        self.assertEqual((rc, sleeps, self.aiuse_calls()), (0, [], 0))
        self.assertEqual(self.record()["auto_resume"]["state"], "scheduled")
        # a closed record is left alone too
        rec = self.record()
        rec["closed"] = int(time.time())
        self.record_path().write_text(json.dumps(rec))
        rc, sleeps = self.run_auto_resume("90")
        self.assertEqual((rc, sleeps, self.aiuse_calls()), (0, [], 0))
        c = run(["check", str(self.record_path())])
        self.assertEqual(c.returncode, 3)                       # closed: no longer "still running"

    def test_runner_sleeps_until_not_before_and_rereads_the_record(self):
        self.dispatch(mode="quota_codex_date")
        rec = self.record()
        rec["auto_resume"]["not_before"] = time.time() + 150
        self.record_path().write_text(json.dumps(rec))
        mod = runpy.run_path(str(SCRIPT))
        sleeps: list[float] = []
        real_sleep = time.sleep

        def tick(s: float) -> None:
            if sleeps:
                # the reset has arrived and the runner resumed the slice in this process: its wait
                # loop polls with time.sleep too, and must neither be counted nor rewrite the record
                real_sleep(min(s, 0.2))
                return
            sleeps.append(s)
            r = self.record()
            r["auto_resume"]["not_before"] = time.time() - 1   # the reset arrives
            self.record_path().write_text(json.dumps(r))
        with patch.dict(os.environ, self.base_env("writes")), patch("time.sleep", side_effect=tick):
            rc = mod["auto_resume_record"](self.record_path(), 1)
        self.assertEqual(rc, 0)
        self.assertEqual(len(sleeps), 1)
        self.assertLessEqual(sleeps[0], 60)
        self.assertEqual(self.record()["status"], "done")


class TestWaiter(AutoResumeBase):
    def test_wait_keeps_waiting_through_a_scheduled_resume(self):
        self.dispatch(mode="quota_codex_date")
        rec = self.record()
        self.assertTrue(Path(rec["done"]).exists())
        mod = runpy.run_path(str(SCRIPT))
        ticks = [0]

        def tick(_: float) -> None:
            ticks[0] += 1
            if ticks[0] == 2:                                  # the resumed run finished
                r = self.record()
                r["auto_resume"]["state"] = "resumed"
                self.record_path().write_text(json.dumps(r))
        with patch("time.sleep", side_effect=tick):
            self.assertEqual(mod["wait_record"](self.record_path()), 0)
        self.assertEqual(ticks[0], 2)

    def test_wait_is_bounded_when_the_resume_never_starts(self):
        self.dispatch(mode="quota_codex_date")
        rec = self.record()
        rec["auto_resume"]["not_before"] = time.time() - (6 * 600 + 900 + 10)
        self.record_path().write_text(json.dumps(rec))
        mod = runpy.run_path(str(SCRIPT))
        with patch("time.sleep") as sleep:
            self.assertEqual(mod["wait_record"](self.record_path()), 124)
        sleep.assert_not_called()

    def test_wait_returns_at_once_without_a_schedule(self):
        self.dispatch("--no-auto-resume", mode="quota_codex_date")
        mod = runpy.run_path(str(SCRIPT))
        with patch("time.sleep") as sleep:
            self.assertEqual(mod["wait_record"](self.record_path()), 0)
        sleep.assert_not_called()

    def test_rearm_command_text_is_unchanged(self):
        self.dispatch("--no-auto-resume", mode="quota_codex_date")
        rearm = self.record()["rearm"]
        self.assertIn("acp-dispatch-wait", rearm)
        self.assertIn("jobs/s1.json", rearm)
        r = subprocess.run(["bash", "-c", rearm], check=False, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 3, (r.stdout, r.stderr))


class TestResetParsing(unittest.TestCase):
    def test_parse_reset_datetime_formats(self):
        mod = runpy.run_path(str(SCRIPT))
        fc, prd = mod["failure_class"], mod["parse_reset_datetime"]
        now = datetime(2026, 10, 18, 1, 0).astimezone()

        def parse(text: str) -> datetime | None:
            return prd(text, fc(text, 1)[1], now)
        self.assertEqual(parse('FAILED quota: {"message": "try again at Oct 18th, 2026 4:41 AM.", "x": 1}'),
                         datetime(2026, 10, 18, 4, 41).astimezone())
        self.assertEqual(parse("FAILED quota: usage limit; try again at December 1, 2026 12:05 PM."),
                         datetime(2026, 12, 1, 12, 5).astimezone())
        self.assertEqual(parse("FAILED quota: try again at 8:51 PM."), datetime(2026, 10, 18, 20, 51).astimezone())
        self.assertEqual(parse("FAILED quota: try again at 12:30 AM."), datetime(2026, 10, 19, 0, 30).astimezone())
        self.assertEqual(parse("FAILED quota: quota exhausted: retry in 2 hours, 47 minutes"),
                         now + timedelta(hours=2, minutes=47))
        self.assertEqual(parse("FAILED quota: Resets in 2h47m44s. Details: quotaResetTimeStamp:2026-10-11T02:46:28Z"),
                         datetime.fromisoformat("2026-10-11T02:46:28+00:00"))
        self.assertEqual(parse("[1310][Weekly/Monthly Limit Exhausted. Your limit will reset at 2026-10-14 22:56:01]"),
                         datetime(2026, 10, 14, 22, 56, 1).astimezone())
        self.assertIsNone(parse("FAILED quota"))
        self.assertIsNone(parse("FAILED quota: try again at some point"))

    def test_aiuse_note_gets_the_dated_reset_right(self):
        """The clock-time branch read the `18` of `18th` as the hour."""
        mod = runpy.run_path(str(SCRIPT))
        text = 'FAILED quota: {"message": "try again at Oct 18th, 2026 4:41 AM."}'
        flag, val = mod["parse_reset_for_aiuse"](text, mod["failure_class"](text, 1)[1])
        self.assertEqual(flag, "--resets-at")
        self.assertEqual(datetime.fromisoformat(val), datetime(2026, 10, 18, 4, 41).astimezone())


STATEFUL_LAUNCHCTL = """#!/bin/bash
# fake launchctl that remembers what was submitted: `print gui/UID/LABEL` succeeds only for a
# label in $FAKE_LOADED (as a real one does until a reboot), `submit -l LABEL ...` loads it
echo "$@" >> "$FAKE_CALLS"
case "$1" in
  submit) echo "$3" >> "$FAKE_LOADED" ;;
  print) grep -qxF "${2##*/}" "$FAKE_LOADED" 2>/dev/null && { echo "state = running"; exit 0; }; exit 113 ;;
esac
exit 0
"""


class TestRebootResume(AutoResumeBase):
    """2026-10-18: a `launchctl submit` job does not survive a reboot or logout, so a scheduled
    auto-resume was lost with its record still saying `scheduled`. The reap sweep re-submits it."""
    loaded: Path = Path()
    stateful: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.stateful = self.tmp / "stateful-launchctl"
        _ = self.stateful.write_text(STATEFUL_LAUNCHCTL)
        self.stateful.chmod(0o755)
        self.loaded = self.tmp / "loaded"

    def env(self, **extra: str) -> dict[str, str]:
        return {**self.base_env("quota_codex_date", FAKE_LOADED=str(self.loaded), FAKE_CALLS=str(self.launchctl_calls)),
                "ACP_DISPATCH_LAUNCHCTL": str(self.stateful), **extra}

    def scheduled(self) -> dict:
        r = self.dispatch(mode="quota_codex_date", env=self.env())
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "scheduled")
        return self.record()

    def reboot(self) -> None:
        self.loaded.write_text("")

    def reap(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return run(["reap", str(self.record_path()), *extra], env=self.env())

    def submits(self) -> list[str]:
        return [c for c in self.launchctl() if c.startswith("submit ")]

    def test_reboot_loses_the_job_and_the_sweep_resubmits_it_once(self):
        before = self.scheduled()
        ar0 = before["auto_resume"]
        self.assertEqual(len(self.submits()), 1)
        r = self.reap()                                         # still loaded: nothing to do
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(len(self.submits()), 1)
        self.reboot()
        r = self.reap()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        self.assertTrue(lines[0].startswith("resubmitted\ts1\t"), lines[0])
        self.assertIn(ar0["label"], lines[0])
        self.assertIn(f"not_before {ar0['not_before_iso']}", lines[0])
        self.assertEqual(len(self.submits()), 2)
        self.assertIn(f"submit -l {ar0['label']} ", self.submits()[1])
        ar = self.record()["auto_resume"]
        self.assertEqual((ar["state"], ar["attempt"], ar["label"], ar["not_before"]),
                         ("scheduled", 1, ar0["label"], ar0["not_before"]))
        self.assertEqual(len(ar["resubmitted"]), 1)
        self.assertAlmostEqual(ar["resubmitted"][0], time.time(), delta=60)
        # the next sweep finds the label loaded again: exactly once
        r2 = self.reap()
        self.assertEqual((r2.returncode, r2.stdout), (0, ""), r2.stderr)
        self.assertEqual(len(self.submits()), 2)
        # and a second reboot is handled the same way
        self.reboot()
        self.assertTrue(self.reap().stdout.startswith("resubmitted\ts1\t"))
        self.assertEqual(len(self.record()["auto_resume"]["resubmitted"]), 2)

    def test_not_before_already_past_runs_now_and_stays_headroom_gated(self):
        self.scheduled()
        self.past_due()
        self.reboot()
        nb = self.record()["auto_resume"]["not_before"]
        r = self.reap()
        self.assertIn("not_before passed: runs now, headroom-gated", r.stdout)
        self.assertEqual(self.record()["auto_resume"]["not_before"], nb)
        self.assertEqual(len(self.submits()), 2)
        # the resubmitted runner is the same attempt, and the gate still decides
        rc, _ = self.run_auto_resume("5", mode="quota_codex_date")
        self.assertEqual(rc, 3)
        self.assertEqual(self.record()["auto_resume"]["state"], "given-up")

    def test_waiting_headroom_is_resubmitted_and_resuming_is_reopened(self):
        for state, want in (("waiting-headroom", "waiting-headroom"), ("resuming", "scheduled")):
            with self.subTest(state=state):
                self.setUp()
                self.scheduled()
                rec = self.record()
                rec["auto_resume"]["state"] = state
                _ = self.record_path().write_text(json.dumps(rec))
                self.reboot()
                self.assertTrue(self.reap().stdout.startswith("resubmitted\ts1\t"))
                self.assertEqual(self.record()["auto_resume"]["state"], want)
                if state == "resuming":                         # the runner accepts it again
                    self.past_due()
                    rc, _ = self.run_auto_resume("90", mode="writes")
                    self.assertEqual(rc, 0)
                    self.assertEqual(self.record()["status"], "done")

    def test_never_resubmitted_when_closed_superseded_or_finished(self):
        self.scheduled()
        pristine = self.record()
        cases = {
            "closed": lambda r: r.update(closed=True),
            "manual resume": lambda r: r["auto_resume"].update(state="resumed"),
            "reroute": lambda r: r["auto_resume"].update(state="cancelled"),
            "given up": lambda r: r["auto_resume"].update(state="given-up"),
            "failed": lambda r: r["auto_resume"].update(state="failed"),
            "running again": lambda r: r.update(finished=None),
            "never scheduled": lambda r: r.pop("auto_resume"),
        }
        self.reboot()
        for why, mutate in cases.items():
            with self.subTest(why=why):
                rec = json.loads(json.dumps(pristine))
                mutate(rec)
                _ = self.record_path().write_text(json.dumps(rec))
                self.assertEqual(self.reap("--quiet").stdout, "")
                self.assertEqual(len(self.submits()), 1, why)
        # a newer attempt owns a different, still-loaded label; the old attempt's is gone
        rec = json.loads(json.dumps(pristine))
        rec["auto_resume"].update(attempt=2, label="acp-dispatch.out.s1.resume2")
        _ = self.record_path().write_text(json.dumps(rec))
        _ = self.loaded.write_text("acp-dispatch.out.s1.resume2\n")
        self.assertEqual(self.reap("--quiet").stdout, "")
        self.assertEqual(len(self.submits()), 1)

    def test_a_real_manual_resume_after_the_reboot_is_not_undone(self):
        self.scheduled()
        self.reboot()
        rr = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env("writes"))
        self.assertEqual(rr.returncode, 0, rr.stdout + rr.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "resumed")
        self.assertEqual(self.reap("--quiet").stdout, "")
        self.assertEqual(len(self.submits()), 1)

    def test_two_concurrent_sweeps_submit_once(self):
        self.scheduled()
        self.reboot()
        cmd = [sys.executable, str(SCRIPT), "reap", str(self.record_path())]
        env = {**os.environ, **self.env()}
        procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(4)]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 4)
        self.assertEqual(sum(o.count("resubmitted\t") for o in outs), 1, outs)
        self.assertEqual(len(self.submits()), 2)
        self.assertEqual(len(self.record()["auto_resume"]["resubmitted"]), 1)

    def test_launchctl_unavailable_changes_nothing(self):
        self.scheduled()
        self.reboot()
        r = run(["reap", str(self.record_path())], env=self.env(ACP_DISPATCH_LAUNCHCTL=str(self.tmp / "no-such-launchctl")))
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertNotIn("resubmitted", self.record()["auto_resume"])

    def test_a_refused_submit_is_recorded_and_retried_by_the_next_sweep(self):
        self.scheduled()
        self.reboot()
        bad = self.tmp / "refusing-launchctl"
        _ = bad.write_text('#!/bin/bash\n[ "$1" = print ] && exit 113\necho nope >&2; exit 5\n')
        bad.chmod(0o755)
        r = run(["reap", str(self.record_path())], env=self.env(ACP_DISPATCH_LAUNCHCTL=str(bad)))
        self.assertTrue(r.stdout.startswith("resubmit-failed\ts1\t"), r.stdout)
        self.assertIn("launchctl submit failed (5): nope", r.stdout)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertNotIn("resubmitted", ar)
        self.assertIn("nope", ar["resubmit_failed"])
        r = self.reap()
        self.assertTrue(r.stdout.startswith("resubmitted\ts1\t"), r.stdout)
        ar = self.record()["auto_resume"]
        self.assertNotIn("resubmit_failed", ar)
        self.assertEqual(len(ar["resubmitted"]), 1)

    def test_missing_runner_script_is_rewritten(self):
        ar0 = self.scheduled()["auto_resume"]
        Path(ar0["runner"]).unlink()
        self.reboot()
        self.assertTrue(self.reap().stdout.startswith("resubmitted\ts1\t"))
        self.assertIn(f"auto-resume {self.record()['record']} --attempt 1", Path(ar0["runner"]).read_text())

    def test_sweep_over_a_directory_covers_every_record(self):
        self.scheduled()
        self.reboot()
        r = run(["reap", str(self.out)], env=self.env())
        self.assertTrue(r.stdout.startswith("resubmitted\ts1\t"), r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
