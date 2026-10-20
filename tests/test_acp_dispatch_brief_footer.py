#!/usr/bin/env python3
"""Re-dispatching a brief file that an earlier dispatch already footed (2026-10-20).

`-f brief.md` where the file is a run's own `<name>-brief.md` carries that run's footer and time
budget. A new --name used to get both contracts, naming different report paths (ime-onstart2).
"""
from __future__ import annotations

import json
import unittest

from test_acp_dispatch import Base, run


class TestBriefFooter(Base):
    def dispatch_file(self, brief, name: str, *extra: str, approve: str = ""):
        env = self.base_env(**({"ACP_OPERATOR_APPROVED": approve} if approve else {}))
        return run(["codex", "--model", "m1", "--name", name, "-f", str(brief), "-C", str(self.repo),
                    "--out", str(self.out), "--acp-run", str(self.fake), "--kind", "frontier", *extra],
                   env=env)

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
        self.assertIn("stripped", r2.stderr)                            # a cut is always announced
        self.assertIn("earlier dispatch's footer", r2.stderr)

    def test_a_footer_pasted_mid_document_loses_nothing(self):
        brief = self.tmp / "paste.md"
        text = ("Task.\n\nPaste this footer into the doc:\n\n## Delivery contract (shared footer; new wording)\n\n"
                "1. x\n\n## Step 2\nImportant later instructions: do not push.\n")
        _ = brief.write_text(text)
        r = self.dispatch_file(brief, "mid")
        self.assertEqual(r.returncode, 0, r.stderr)
        sent = (self.out / "mid-brief.md").read_text()
        self.assertTrue(sent.startswith(text), sent)                    # all of it survives, then the real footer
        self.assertIn("Important later instructions: do not push.", sent)
        self.assertIn("nothing was stripped", r.stderr)

    def test_content_after_the_footer_survives(self):
        brief = self.tmp / "src.md"
        _ = brief.write_text("Do the thing.\n")
        self.assertEqual(self.dispatch_file(brief, "first").returncode, 0)
        footed = self.tmp / "footed.md"                                  # not a record's own brief
        _ = footed.write_text((self.out / "first-brief.md").read_text() + "\n## Addendum\nkeep me\n")
        r = self.dispatch_file(footed, "second")
        self.assertEqual(r.returncode, 0, r.stderr)
        second = (self.out / "second-brief.md").read_text()
        self.assertIn("keep me", second)
        self.assertIn("first-report.md", second)                         # left whole, so the old contract stays
        self.assertIn("nothing was stripped", r.stderr)

    def test_a_record_brief_that_was_edited_after_the_footer_is_left_whole(self):
        brief = self.tmp / "src.md"
        _ = brief.write_text("Do the thing.\n")
        self.assertEqual(self.dispatch_file(brief, "first").returncode, 0)
        edited = self.out / "first-brief.md"
        _ = edited.write_text(edited.read_text() + "\nAlso: never touch prod.\n")
        r = self.dispatch_file(edited, "second")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("never touch prod.", (self.out / "second-brief.md").read_text())

    def test_a_record_brief_is_rebuilt_from_its_stored_prompt(self):
        brief = self.tmp / "src.md"
        _ = brief.write_text("Pasted footer example:\n\n## Delivery contract (shared footer in a quote)\n\n1. q\n\nThen do the thing.\n")
        self.assertEqual(self.dispatch_file(brief, "first").returncode, 0)
        rec = json.loads((self.out / "jobs" / "first.json").read_text())
        self.assertIn("Pasted footer example", rec["prompt"])
        r = self.dispatch_file(self.out / "first-brief.md", "second")
        self.assertEqual(r.returncode, 0, r.stderr)
        second = (self.out / "second-brief.md").read_text()
        self.assertEqual(json.loads((self.out / "jobs" / "second.json").read_text())["prompt"], rec["prompt"])
        self.assertIn("second-report.md", second)
        self.assertNotIn("first-report.md", second)
        self.assertIn("(shared footer in a quote)", second)             # the caller's own text stays
        self.assertIn("Then do the thing.", second)

    def test_the_advisor_section_is_not_duplicated_and_a_role_change_drops_it(self):
        brief = self.tmp / "src.md"
        _ = brief.write_text("Review it.\n")
        advise = ["--role", "advise"]
        self.assertEqual(self.dispatch_file(brief, "first", *advise).returncode, 0)
        first = (self.out / "first-brief.md").read_text()
        self.assertEqual(first.count("## Advisor role"), 1)
        copy = self.tmp / "advised.md"                                  # not the record's own file: path (2)
        _ = copy.write_text(first)
        self.assertEqual(self.dispatch_file(copy, "second", *advise).returncode, 0)
        second = (self.out / "second-brief.md").read_text()
        self.assertEqual(second.count("## Advisor role"), 1, second)
        self.assertEqual(second.count("## Delivery contract (shared footer"), 1, second)
        self.assertEqual(self.dispatch_file(self.out / "first-brief.md", "third", "--role", "exec",
                                            approve="frontier-exec").returncode, 0)
        self.assertNotIn("## Advisor role", (self.out / "third-brief.md").read_text())


if __name__ == "__main__":
    unittest.main()
