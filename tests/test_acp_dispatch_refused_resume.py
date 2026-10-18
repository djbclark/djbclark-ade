#!/usr/bin/env python3
"""A refused resume must leave the job record alone.

2026-10-18 05:37: `acp-dispatch resume RECORD` on finished codex records, with the pool at 0%
headroom, was refused at preflight (exit 5) and overwrote each record with a bare `unavailable`
one, losing log, session_id, cmd, brief, prompt and auto_resume; the next resume then died with
`KeyError: 'log'`. Now the refusal is appended to `refusals` and everything else stays.

Uses test_acp_dispatch's fake acp-run and launchctl; the pool reading comes from fake aiuse
snapshots (AIUSE_SNAPSHOT), never real quota or live records.
"""
from __future__ import annotations

import json
import runpy
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import SCRIPT, Base, run


def snapshot(path: Path, remaining: float) -> Path:
    _ = path.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {
        "accounts": [{"provider": "codex", "windows": [
            {"label": "5h", "remaining_percent": remaining},
            {"label": "weekly", "remaining_percent": remaining}]}]}}))
    return path


class RefusedResume(Base):
    healthy: Path = Path()
    empty: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.healthy = snapshot(self.tmp / "healthy.json", 98.0)
        self.empty = snapshot(self.tmp / "empty.json", 0.0)

    def record_path(self, name: str = "s1") -> Path:
        return self.out / "jobs" / f"{name}.json"

    def finished_record(self) -> dict:
        r = self.dispatch(env={"AIUSE_SNAPSHOT": str(self.healthy)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        for key in ("log", "cmd", "brief", "prompt", "session_id"):
            self.assertTrue(rec.get(key), key)
        return rec

    def resume(self, snap: Path):
        return run(["resume", str(self.record_path()), "--timeout", "0"],
                   env=self.base_env(AIUSE_SNAPSHOT=str(snap)))

    def test_refused_resume_keeps_every_key_and_appends_one_refusal(self):
        before = self.finished_record()
        r = self.resume(self.empty)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"^unavailable\ts1\tclass=headroom agent=codex model=m1 headroom 0\.0% < minimum 10\.0%")
        after = self.record()
        refusals = after.pop("refusals")
        self.assertEqual(after, before)
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["class"], "headroom")
        self.assertIn("headroom 0.0% < minimum 10.0%", refusals[0]["detail"])
        self.assertIsInstance(refusals[0]["at"], float)

    def test_two_refusals_append_two_and_a_later_resume_still_works(self):
        before = self.finished_record()
        for _ in range(2):
            self.assertEqual(self.resume(self.empty).returncode, 5)
        refusals = self.record()["refusals"]
        self.assertEqual([x["class"] for x in refusals], ["headroom", "headroom"])
        self.assertLessEqual(refusals[0]["at"], refusals[1]["at"])
        # the record is still resumable once the pool is back
        r = self.resume(self.healthy)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual(rec["session_id"], before["session_id"])
        self.assertEqual(rec["resume_count"], 1)

    def test_wont_fit_refusal_also_keeps_the_record(self):
        # 40% estimated against 11% left: refused as wont-fit (headroom 11% passes the 10% minimum)
        rec = self.finished_record()
        _ = self.record_path().write_text(json.dumps({**rec, "estimated_usage_pct": 40.0}))
        before = self.record()
        r = self.resume(snapshot(self.tmp / "low.json", 11.0))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("class=wont-fit", r.stdout)
        after = self.record()
        self.assertEqual(after.pop("refusals")[0]["class"], "wont-fit")
        self.assertEqual(after, before)

    def test_fresh_dispatch_refusal_still_writes_the_unavailable_record(self):
        r = self.dispatch(env={"AIUSE_SNAPSHOT": str(self.empty)})
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"^unavailable\ts1\tclass=headroom agent=codex model=m1 headroom 0\.0% < minimum 10\.0%")
        rec = self.record()
        self.assertEqual(rec["status"], "unavailable")
        self.assertEqual(rec["unavailable_class"], "headroom")
        self.assertEqual(rec["exit"], 5)
        self.assertNotIn("refusals", rec)

    def test_fresh_dispatch_over_an_old_record_still_replaces_it(self):
        _ = self.finished_record()
        r = self.dispatch("--force", env={"AIUSE_SNAPSHOT": str(self.empty)})
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual(rec["status"], "unavailable")
        self.assertNotIn("refusals", rec)
        self.assertNotIn("log", rec)

    def test_resume_of_a_bare_unavailable_record_gives_a_message_not_a_traceback(self):
        _ = self.dispatch(env={"AIUSE_SNAPSHOT": str(self.empty)})        # the clobbered shape
        r = self.resume(self.healthy)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("has no log or cmd", r.stderr)
        self.assertIn("acp-run --resume SESSION_ID", r.stderr)

    def test_session_info_without_a_log(self):
        mod = runpy.run_path(str(SCRIPT))
        self.assertEqual(mod["session_info"]({"session_id": "abc"}), ("abc", None))
        self.assertEqual(mod["session_info"]({}), (None, None))
        self.assertEqual(mod["session_info"]({"log": str(self.tmp / "missing.jsonl")}), (None, None))


if __name__ == "__main__":
    unittest.main()
