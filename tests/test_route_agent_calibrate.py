#!/usr/bin/env python3
"""calibrate report: grouping, placeholders, suggestions, JSON shape."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r


def _write_job(root: Path, task: str, name: str, body: dict) -> None:
    d = root / task / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(body))


class TestCalibrate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

    def tearDown(self):
        self.tmp.cleanup()

    def _rec(self, **kw):
        base = {
            "agent": "claude",
            "model": "sonnet",
            "kind": "code",
            "status": "done",
            "started": self.now.isoformat(),
            "finished": self.now.isoformat(),
            "cmd": "/Users/djbclark/.local/bin/acp-run claude --model sonnet",
        }
        base.update(kw)
        return base

    def test_groups_skips_placeholders_and_maps_service(self):
        _write_job(self.root, "t1", "a", self._rec())
        _write_job(self.root, "t2", "b", self._rec(
            agent="agy", model="claude-opus-5-5-high", kind="judgment",
            status="no-report",
            failure="NO-REPORT: quota (agy, claude-opus-5-5-high): acp-run exit 1",
        ))
        _write_job(self.root, "t3", "c", self._rec(model="m1", status="done"))
        _write_job(self.root, "t4", "d", self._rec(
            cmd="/var/folders/xx/pytest0/acp-run claude --model sonnet",
            status="done",
        ))
        _write_job(self.root, "t5", "e", self._rec(
            agent="cursor", model="default", kind=None, status="done",
        ))
        # nested layout */*/jobs
        nest = self.root / "wave" / "slice" / "jobs"
        nest.mkdir(parents=True)
        (nest / "f.json").write_text(json.dumps(self._rec(
            agent="codex", model="gpt-6-astra", kind="frontier", status="done",
            measured_usage_pct=2.5,
            measured_usage_windows={"5-hour": 1.0, "weekly": 0.5},
            outcome={"ci": "pass", "review": "fail", "merged": True},
        )))

        report = r.calibrate_report(state_dir=self.root, now=self.now, min_n=99)
        services = {(g["service"], g["model"], g["kind"]) for g in report["groups"]}
        self.assertIn(("claude", "sonnet", "code"), services)
        self.assertIn(("antigravity-claude", "claude-opus-5-5-high", "judgment"),
                      services)
        self.assertIn(("cursor-auto", "default", "?"), services)
        self.assertIn(("codex", "gpt-6-astra", "frontier"), services)
        self.assertNotIn(("claude", "m1", "code"), services)
        # temp-dir fake skipped
        self.assertEqual(
            sum(1 for g in report["groups"]
                if g["service"] == "claude" and g["model"] == "sonnet"),
            1,
        )
        agy = next(g for g in report["groups"]
                   if g["service"] == "antigravity-claude")
        self.assertEqual(agy["no_report"], 1)
        self.assertEqual(agy["quota_stop"], 1)
        codex = next(g for g in report["groups"] if g["service"] == "codex")
        self.assertEqual(codex["median_measured_usage_pct"], 2.5)
        self.assertEqual(codex["outcome"]["ci_pass_rate"], 100.0)
        self.assertEqual(codex["outcome"]["review_pass_rate"], 0.0)
        self.assertEqual(codex["outcome"]["merged_rate"], 100.0)
        self.assertEqual(report["in_flight"], 0)

    def test_epoch_finished_honours_since(self):
        recent = self.now.timestamp()
        old = (self.now - timedelta(days=20)).timestamp()
        _write_job(self.root, "new", "j", self._rec(
            agent="zcode", model="GLM-5.3", kind="code",
            started=recent, finished=recent,
        ))
        _write_job(self.root, "old", "j", self._rec(
            agent="zcode", model="GLM-5.3", kind="code",
            started=old, finished=old,
        ))
        report = r.calibrate_report(
            state_dir=self.root, now=self.now, since_days=7, min_n=99)
        self.assertEqual(len(report["groups"]), 1)
        self.assertEqual(report["groups"][0]["n"], 1)
        self.assertEqual(report["groups"][0]["service"], "zai")

    def test_in_flight_excluded_from_groups(self):
        _write_job(self.root, "done", "j", self._rec(
            agent="zcode", model="GLM-5.3", kind="code", status="done",
        ))
        _write_job(self.root, "run", "j", self._rec(
            agent="zcode", model="GLM-5.3", kind="code",
            status="running", finished=None,
        ))
        _write_job(self.root, "nofin", "j", self._rec(
            agent="cursor", model="default", kind="code",
            status="done", finished=None,
        ))
        report = r.calibrate_report(state_dir=self.root, now=self.now, min_n=99)
        self.assertEqual(report["in_flight"], 2)
        self.assertEqual(sum(g["n"] for g in report["groups"]), 1)

    def test_no_report_class_paren_only(self):
        self.assertEqual(
            r._no_report_class({"failure": "NO-REPORT: (quota)"}),
            "no-report",
        )
        self.assertEqual(
            r._no_report_class({"failure": "NO-REPORT: quota (agy): x"}),
            "quota",
        )

    def test_suggestions_respect_min_and_thresholds(self):
        # Three code-eligible services (min_peers=2 others): zai poor,
        # cursor-auto and cursor good.
        for i in range(6):
            _write_job(self.root, f"bad{i}", "j", self._rec(
                agent="zcode", model="GLM-5.3", kind="code",
                status="no-report" if i < 5 else "done",
                failure="NO-REPORT: exit 1",
            ))
        for i in range(6):
            _write_job(self.root, f"good{i}", "j", self._rec(
                agent="cursor", model="default", kind="code",
                status="done",
            ))
        for i in range(6):
            _write_job(self.root, f"mid{i}", "j", self._rec(
                agent="cursor", model="composer-2.5", kind="code",
                status="done",
            ))
        # Under min: ignored for suggestions
        _write_job(self.root, "tiny", "j", self._rec(
            agent="opencode", model="opencode-go/kimi-k3", kind="code",
            status="done",
        ))

        report = r.calibrate_report(state_dir=self.root, now=self.now, min_n=5)
        sug = {(s["service"], s["suggest_rank_delta"]) for s in report["suggestions"]}
        self.assertIn(("zai", r.CALIBRATE_SUGGEST_WORSE_DELTA), sug)
        self.assertIn(("cursor-auto", -r.CALIBRATE_SUGGEST_BETTER_DELTA), sug)
        self.assertIn(("cursor", -r.CALIBRATE_SUGGEST_BETTER_DELTA), sug)
        self.assertFalse(any(s["service"] == "opencode-go" for s in report["suggestions"]))

        # JSON shape stable keys
        blob = json.dumps(report, sort_keys=True)
        data = json.loads(blob)
        self.assertEqual(set(data),
                         {"generated_at", "since_days", "min_n", "in_flight",
                          "groups", "suggestions"})
        self.assertTrue(data["groups"])
        g0 = data["groups"][0]
        for key in ("service", "model", "kind", "n", "done", "done_rate",
                    "no_report", "quota_stop", "median_measured_usage_pct",
                    "median_measured_usage_windows", "outcome"):
            self.assertIn(key, g0)

    def test_suggestions_exclude_quota_and_unavailable_from_rate(self):
        # Raw table: 6 done + 6 quota = 50% done_rate; suggestion basis = 100%.
        for i in range(6):
            _write_job(self.root, f"ok{i}", "j", self._rec(
                agent="zcode", model="GLM-5.3", kind="code", status="done",
            ))
        for i in range(6):
            _write_job(self.root, f"q{i}", "j", self._rec(
                agent="zcode", model="GLM-5.3", kind="code",
                status="no-report",
                failure="NO-REPORT: quota (zai): exit 1",
            ))
        # Two peers at ~50% so zai's filtered 100% is clearly better.
        for i in range(6):
            _write_job(self.root, f"p1{i}", "j", self._rec(
                agent="cursor", model="default", kind="code",
                status="done" if i < 3 else "no-report",
                failure="NO-REPORT: exit 1",
            ))
        for i in range(6):
            _write_job(self.root, f"p2{i}", "j", self._rec(
                agent="cursor", model="composer-2.5", kind="code",
                status="done" if i < 3 else "no-report",
                failure="NO-REPORT: exit 1",
            ))
        report = r.calibrate_report(state_dir=self.root, now=self.now, min_n=5)
        zai = next(g for g in report["groups"] if g["service"] == "zai")
        self.assertEqual(zai["n"], 12)
        self.assertEqual(zai["done"], 6)
        self.assertEqual(zai["done_rate"], 50.0)
        self.assertEqual(zai["quota_stop"], 6)
        sug = next(s for s in report["suggestions"] if s["service"] == "zai")
        self.assertEqual(sug["done_rate"], 100.0)
        self.assertEqual(sug["n"], 6)
        self.assertEqual(sug["suggest_rank_delta"], -r.CALIBRATE_SUGGEST_BETTER_DELTA)

    def test_suggestions_require_min_peers(self):
        # Only two eligible code services → each has one peer < min_peers=2.
        for i in range(6):
            _write_job(self.root, f"a{i}", "j", self._rec(
                agent="zcode", model="GLM-5.3", kind="code",
                status="no-report" if i < 5 else "done",
                failure="NO-REPORT: exit 1",
            ))
        for i in range(6):
            _write_job(self.root, f"b{i}", "j", self._rec(
                agent="cursor", model="default", kind="code", status="done",
            ))
        report = r.calibrate_report(state_dir=self.root, now=self.now, min_n=5)
        self.assertEqual(report["suggestions"], [])

    def test_cli_json(self):
        _write_job(self.root, "t", "a", self._rec())
        old = r.ACP_DISPATCH_STATE
        try:
            r.ACP_DISPATCH_STATE = self.root
            code = r.main(["calibrate", "--json", "--min", "99"])
        finally:
            r.ACP_DISPATCH_STATE = old
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
