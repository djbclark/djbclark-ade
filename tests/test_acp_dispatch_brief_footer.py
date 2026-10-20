#!/usr/bin/env python3
"""Re-dispatching a brief file that an earlier dispatch already footed (2026-10-20).

`-f brief.md` where the file is a run's own `<name>-brief.md` carries that run's footer and time
budget. A new --name used to get both contracts, naming different report paths (ime-onstart2).
"""
from __future__ import annotations

import unittest

from test_acp_dispatch import Base, run


class TestBriefFooter(Base):
    def dispatch_file(self, brief, name: str):
        return run(["codex", "--model", "m1", "--name", name, "-f", str(brief), "-C", str(self.repo),
                    "--out", str(self.out), "--acp-run", str(self.fake), "--kind", "frontier"],
                   env=self.base_env())

    def test_one_contract_with_the_new_name(self):
        brief = self.tmp / "src-brief.md"
        _ = brief.write_text("Do the thing.\n")
        r1 = self.dispatch_file(brief, "first")
        self.assertEqual(r1.returncode, 0, r1.stderr)
        first = (self.out / "first-brief.md").read_text()
        self.assertEqual(first.count("## Delivery contract (shared footer"), 1)
        self.assertEqual(brief.read_text(), "Do the thing.\n")          # the caller's file is untouched
        r2 = self.dispatch_file(self.out / "first-brief.md", "second")  # the footed brief, new name
        self.assertEqual(r2.returncode, 0, r2.stderr)
        second = (self.out / "second-brief.md").read_text()
        self.assertEqual(second.count("## Delivery contract (shared footer"), 1, second)
        self.assertEqual(second.count("## Time budget (acp-dispatch)"), 1, second)
        self.assertIn("second-report.md", second)
        self.assertNotIn("first-report.md", second)
        self.assertTrue(second.startswith("Do the thing."))


if __name__ == "__main__":
    unittest.main()
