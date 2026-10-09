#!/usr/bin/env python3
"""fleet.launch_state understands acp-dispatch's report contract for headless launches.

A headless launch (launch.py one-turn path, dispatched through acp-dispatch) records
`dispatch: true` and a `report` path. When the agent wrote `BLOCKED: <question>` as the
report's first line (acp-dispatch exit 4) the launch is a `blocked` session whose final text is
that line, so helm shows it as a `reply` item the operator answers with `launch.py reply`.
When it finished with no report (exit 3) it is a delivery failure named by launch id, not a
reply item.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))
sys.path.insert(0, str(ROOT / "helm"))

import fleet  # noqa: E402  # pyright: ignore[reportMissingImports]
import helm  # noqa: E402  # pyright: ignore[reportMissingImports]


class TestDispatchLaunchState(unittest.TestCase):
    tmp: Path = Path()

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="fls-"))

    def launch(self, exit_code: int | None, report_text: str | None, **extra: Any) -> dict[str, Any]:
        report = self.tmp / "L1-report.md"
        if report_text is not None:
            _ = report.write_text(report_text)
        d: dict[str, Any] = {"id": "L1", "agent": "codex", "cwd": str(self.tmp), "dispatch": True,
                             "report": str(report), "done": str(report) + ".done", "log": str(self.tmp / "L1.jsonl"),
                             "interactive": False}
        if exit_code is not None:
            d["exit"] = exit_code
            (self.tmp / "L1-report.md.done").touch()
        d.update(extra)
        return d

    def test_exit_4_with_blocked_report_is_a_blocked_session_carrying_the_question(self) -> None:
        d = self.launch(4, "BLOCKED: do I own ~/opt/cfengine-dev?\nmore context\n")
        status, final, result = fleet.launch_state(d)
        self.assertEqual(status, "blocked")
        self.assertEqual(final, "BLOCKED: do I own ~/opt/cfengine-dev?")
        self.assertEqual((result or {}).get("exit"), 4)

    def test_blocked_report_wins_even_when_the_acp_run_log_is_missing_the_exit(self) -> None:
        d = self.launch(None, "BLOCKED: which branch?\n")
        (self.tmp / "L1-report.md.done").touch()     # acp-dispatch finished; runner exit line not yet appended
        status, final, _ = fleet.launch_state(d)
        self.assertEqual((status, final), ("blocked", "BLOCKED: which branch?"))

    def test_exit_3_without_report_is_a_delivery_failure_not_a_reply(self) -> None:
        d = self.launch(3, None)
        status, final, result = fleet.launch_state(d)
        self.assertEqual(status, "idle")
        self.assertIn("DELIVERY FAILURE", final)
        self.assertIn("L1", final)
        self.assertIn("no report", final)
        self.assertEqual((result or {}).get("exit"), 3)

    def test_exit_0_with_done_report_is_idle_with_the_report_head(self) -> None:
        d = self.launch(0, "STATUS: working\nall tests pass\nDONE\n")
        status, final, result = fleet.launch_state(d)
        self.assertEqual(status, "idle")
        self.assertIn("all tests pass", final)
        self.assertEqual((result or {}).get("exit"), 0)

    def test_still_running_dispatch_launch_is_working(self) -> None:
        d = self.launch(None, "STATUS: working\n")
        status, _, result = fleet.launch_state(d)
        self.assertEqual(status, "working")
        self.assertIsNone(result)

    def test_helm_classifies_the_blocked_launch_as_a_reply_item_and_renders_the_question(self) -> None:
        d = self.launch(4, "BLOCKED: do I own ~/opt/cfengine-dev?\n")
        status, final, result = fleet.launch_state(d)
        s: dict[str, Any] = {"id": "L1", "agent": "codex", "name": "n", "title": "t", "where": "", "focus": "",
                             "status": status, "cwd": str(self.tmp), "host": "acp", "sid": "L1", "chan": None, "self": False,
                             "launch": {**d, "final": final, "result": result, "alive": False}}
        it = helm.classify(s, {})
        self.assertEqual(it["kind"], "reply")
        self.assertEqual(it["detail"], "BLOCKED: do I own ~/opt/cfengine-dev?")
        text = helm.render(it)
        self.assertIn("BLOCKED: do I own", text)
        self.assertIn("launch.py reply L1", text)

    def test_helm_classifies_the_no_report_launch_as_done_with_the_failure_text(self) -> None:
        d = self.launch(3, None)
        status, final, result = fleet.launch_state(d)
        s: dict[str, Any] = {"id": "L1", "agent": "codex", "name": "n", "title": "t", "where": "", "focus": "",
                             "status": status, "cwd": str(self.tmp), "host": "acp", "sid": "L1", "chan": None, "self": False,
                             "launch": {**d, "final": final, "result": result, "alive": False}}
        it = helm.classify(s, {})
        self.assertEqual(it["kind"], "done")
        self.assertEqual(it["exit"], 3)
        self.assertIn("DELIVERY FAILURE", helm.render(it))


if __name__ == "__main__":
    unittest.main()
