#!/usr/bin/env python3
"""Re-dispatching a brief file that an earlier dispatch already footed (2026-10-20).

`-f brief.md` where the file is a run's own `<name>-brief.md` carries that run's footer and time
budget. A new --name used to get both contracts, naming different report paths (ime-onstart2).
"""
from __future__ import annotations

import json
import unittest

from test_acp_dispatch import Base, FOOTER, run


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


class TestFooterMatchesTheTemplate(Base):
    """The cut stands only when every footer item is a line of docs/dispatch-footer.md (adversary PR 18
    follow-up A, issue 21): a constraint a lead added to or edited in a pasted footer is not generated."""

    dispatch_file = TestBriefFooter.dispatch_file

    def footed_copy(self, name: str = "copy.md"):
        """A footed brief that is not a record's own file, so the last-footer-heading path (ii) decides."""
        src = self.tmp / "src.md"
        _ = src.write_text("Do the thing.\n")
        self.assertEqual(self.dispatch_file(src, "first").returncode, 0)
        copy = self.tmp / name
        _ = copy.write_text((self.out / "first-brief.md").read_text())
        return copy

    def second(self, copy, name: str = "second"):
        r = self.dispatch_file(copy, name)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r, (self.out / f"{name}-brief.md").read_text()

    def test_a_stock_footer_is_still_stripped(self):
        r, sent = self.second(self.footed_copy())
        self.assertEqual(sent.count("## Delivery contract (shared footer"), 1, sent)
        self.assertIn("second-report.md", sent)
        self.assertNotIn("first-report.md", sent)
        self.assertIn("stripped", r.stderr)

    def test_blank_separators_between_template_items_are_generated(self):
        copy = self.footed_copy()
        text = copy.read_text()
        self.assertIn("\n4. ", text)
        _ = copy.write_text(text.replace("\n4. ", "\n \t\n\n4. ", 1))
        r, sent = self.second(copy)
        self.assertEqual(sent.count("## Delivery contract (shared footer"), 1, sent)
        self.assertNotIn("first-report.md", sent)
        self.assertIn("stripped", r.stderr)

    def test_user_instruction_between_blank_separators_survives(self):
        copy = self.footed_copy()
        text = copy.read_text()
        constraint = "Never push or merge without asking."
        self.assertIn("\n4. ", text)
        _ = copy.write_text(text.replace("\n4. ", "\n\n" + constraint + "\n\n4. ", 1))
        r, sent = self.second(copy)
        self.assertIn(constraint, sent)
        self.assertIn("first-report.md", sent)
        self.assertIn("nothing was stripped", r.stderr)

    def test_an_item_appended_to_the_footer_survives(self):
        copy = self.footed_copy()
        text = copy.read_text()
        at = text.index("\n14. ")
        end = text.index("\n", at + 1)
        _ = copy.write_text(text[:end + 1] + "15. Read-only: never push, never edit /prod.\n" + text[end + 1:])
        r, sent = self.second(copy)
        self.assertIn("15. Read-only: never push, never edit /prod.", sent)
        self.assertIn("nothing was stripped", r.stderr)
        self.assertNotIn("stripped 0", r.stderr)

    def test_an_edited_footer_item_survives(self):
        copy = self.footed_copy()
        text = copy.read_text()
        self.assertIn("Never change anything outside the folders", text)
        _ = copy.write_text(text.replace("Never change anything outside the folders", "Do NOT push or merge. Never change anything outside the folders"))
        r, sent = self.second(copy)
        self.assertIn("Do NOT push or merge.", sent)
        self.assertIn("nothing was stripped", r.stderr)

    def test_a_user_written_list_under_a_footer_heading_survives(self):
        brief = self.tmp / "own.md"
        text = ("Task.\n\n## Delivery contract (shared footer; v2)\n\n1. Push to prod when done.\n"
                "2. Delete old branches.\n")
        _ = brief.write_text(text)
        r, sent = self.second(brief)
        self.assertTrue(sent.startswith(text), sent)
        self.assertIn("nothing was stripped", r.stderr)

    def test_a_footer_with_some_template_items_dropped_is_still_generated(self):
        copy = self.footed_copy()
        lines = [ln for ln in copy.read_text().splitlines(keepends=True) if not ln.startswith(("9. ", "10. "))]
        _ = copy.write_text("".join(lines))
        r, sent = self.second(copy)
        self.assertEqual(sent.count("## Delivery contract (shared footer"), 1, sent)
        self.assertIn("stripped", r.stderr)

    def test_the_footer_without_the_atomic_edit_item_is_still_generated(self):
        # item 20 (2026-11-01) is new: a footer written before it, or a brief that already carries the
        # current one, is cut as generated; an edited copy of it survives.
        self.assertRegex(FOOTER.read_text(), r"(?m)^20\. Never edit in place .*`mv -f`")
        copy = self.footed_copy()
        self.assertIn("\n20. Never edit in place", copy.read_text())
        r, sent = self.second(copy)
        self.assertEqual(sent.count("## Delivery contract (shared footer"), 1, sent)
        self.assertNotIn("nothing was stripped", r.stderr)
        old = self.tmp / "old.md"
        _ = old.write_text("".join(ln for ln in copy.read_text().splitlines(keepends=True) if not ln.startswith("20. ")))
        r, sent = self.second(old, "third")
        self.assertEqual(sent.count("## Delivery contract (shared footer"), 1, sent)
        self.assertNotIn("nothing was stripped", r.stderr)
        edited = self.tmp / "edited.md"
        _ = edited.write_text(copy.read_text().replace("Never edit in place", "Always edit in place"))
        r, sent = self.second(edited, "fourth")
        self.assertIn("Always edit in place", sent)
        self.assertIn("nothing was stripped", r.stderr)

    def test_a_near_miss_footer_is_matched_in_linear_time(self):
        import time
        brief = self.tmp / "big.md"
        item = "1. " + "x" * 200 + "\n"
        _ = brief.write_text("Task.\n\n## Delivery contract (shared footer)\n\n" + item * 20000)
        t0 = time.monotonic()
        r, sent = self.second(brief)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertIn("nothing was stripped", r.stderr)

    def test_items_with_two_placeholders_do_not_backtrack(self):
        # PR 22 review: item 7 has two placeholders; a line repeating the text between them parsed two
        # ways under a lazy wildcard, so 24 such lines plus a near-miss took minutes (2^N).
        import time
        copy = self.footed_copy()
        text = copy.read_text()
        line = next(ln for ln in text.splitlines() if ln.startswith("7. "))
        mid = "` as your very last act. Waiters watch `"
        self.assertIn(mid, line)
        at = line.index(mid)
        crafted = line[:at] + mid + "x" + line[at:] + "\n"
        head = text[:text.index("\n7. ") + 1]
        _ = copy.write_text(head + crafted * 24 + "x\n")
        t0 = time.monotonic()
        r, sent = self.second(copy)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertIn("nothing was stripped", r.stderr)

    def test_a_constraint_in_the_pasted_heading_survives(self):
        copy = self.footed_copy()
        text = copy.read_text()
        heading = next(ln for ln in text.splitlines() if ln.startswith("## Delivery contract (shared footer"))
        _ = copy.write_text(text.replace(heading, "## Delivery contract (shared footer; READ-ONLY, never push)"))
        r, sent = self.second(copy)
        self.assertIn("READ-ONLY, never push", sent)
        self.assertIn("nothing was stripped", r.stderr)


class TestFooterOnlyFile(Base):
    dispatch_file = TestBriefFooter.dispatch_file

    def test_a_file_that_is_only_a_footer_has_no_task_left(self):
        src = self.tmp / "src.md"
        _ = src.write_text("Do the thing.\n")
        self.assertEqual(self.dispatch_file(src, "first").returncode, 0)
        text = (self.out / "first-brief.md").read_text()
        only = self.tmp / "only.md"
        _ = only.write_text(text[text.index("## Delivery contract"):])
        r = self.dispatch_file(only, "second")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("only an earlier dispatch's footer", r.stderr)
        self.assertIn("no task is left", r.stderr)
        self.assertFalse((self.out / "second-brief.md").exists())
        self.assertFalse((self.out / "jobs" / "second.json").exists())


if __name__ == "__main__":
    unittest.main()
