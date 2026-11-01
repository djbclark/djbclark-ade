#!/usr/bin/env python3
"""A report that ends `DONE` then one verdict line is finished, not `partial`.

2026-10-30: the scoped delta re-gate for #152 (`adv-e-152-delta`) followed its brief to the letter and
ended its report with `DONE` and then `AC_DONE: adv-e-152-delta APPROVE`, so the lead could grep the
verdict. `classify()` only accepted `DONE` as the *last* line, so a complete APPROVE with both mutation
results in it was reported as `partial — no DONE line yet` and `acp-dispatch check` still exit 1. The
lead has to read the report either way; the status word must not contradict it.

The tolerance is deliberately narrow: exactly `DONE` followed by exactly one `AC_DONE:` line.
Anything else after `DONE` (trailing prose, a second paragraph) is still `partial`, because that shape
is what a truncated or half-written report looks like.
"""
from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "acp-dispatch"


class Classify(unittest.TestCase):
    mod: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = runpy.run_path(str(SCRIPT))

    def report(self, text: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory(prefix="classify-")
        self.addCleanup(tmpdir.cleanup)
        tmp = Path(tmpdir.name)
        path = tmp / "slice-report.md"
        path.write_text(text)
        return path

    def classify(self, text: str) -> tuple[str, str]:
        return self.mod["classify"](self.report(text), finished=True)

    def test_recovery_recognizes_existing_verdict_completion(self):
        self.assertTrue(self.mod["report_finished"](["STATUS: complete", "DONE", "AC_DONE: x APPROVE"]))
        self.assertFalse(self.mod["report_finished"](["DONE", "AC_DONE: x", "still working"]))

    def test_a_plain_done_report_is_done(self):
        self.assertEqual(self.classify("STATUS: working\n\n# Report\n\nsome work\n\nDONE\n")[0], "done")

    def test_a_done_line_followed_by_a_verdict_line_is_done(self):
        status, _detail = self.classify(
            "STATUS: working\n\n# Adversary delta re-gate\n\nAPPROVE — delta-only\n\n"
            "DONE\nAC_DONE: adv-e-152-delta APPROVE\n")
        self.assertEqual(status, "done")

    def test_prose_after_done_is_still_partial(self):
        # The shape a half-written or permission-refused slice leaves behind: the contract's own
        # marker is buried, so the reader must look at it.
        self.assertEqual(
            self.classify("STATUS: working\n\n# Report\n\nDONE\n\nstill checking the last mutant\n")[0],
            "partial")
        self.assertEqual(self.classify("STATUS: working\n\n# Report\n\nDONE\nAC_DONE: x\nmore\n")[0],
                         "partial")

    def test_a_verdict_line_without_done_is_partial(self):
        # `AC_DONE` alone does not satisfy the delivery contract's own `DONE` line.
        self.assertEqual(self.classify("STATUS: working\n\n# Report\n\nAC_DONE: x APPROVE\n")[0],
                         "partial")

    def test_blocked_still_wins(self):
        self.assertEqual(
            self.classify("BLOCKED: which account?\n\nDONE\nAC_DONE: x APPROVE\n")[0], "blocked")


if __name__ == "__main__":
    unittest.main()
