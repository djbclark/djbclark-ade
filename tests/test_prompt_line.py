#!/usr/bin/env python3
"""prompt_line: only unstyled text on the ❯ line is a draft (2026-10-16).

relay.py refused w34:p3 because its ❯ line held Claude Code's dim suggested prompt
("install the new build on the phone"), which anything typed replaces.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "session-finder"))
import prompt_line  # noqa: E402

E = "\x1b["


class PromptLineTest(unittest.TestCase):
    def test_dim_suggestion_is_empty(self) -> None:
        # The live line from 2026-10-16, ❯ then NBSP, dim suggestion, CR.
        line = f"❯\xa0{E}0m{E}2minstall the new build on the phone{E}0m\r"
        self.assertEqual(prompt_line.classify(line), "")

    def test_grey_rgb_and_reverse_video_are_not_drafts(self) -> None:
        self.assertEqual(prompt_line.classify(f"❯ {E}38;2;153;153;153mdid it fire?{E}0m"), "")
        self.assertEqual(prompt_line.classify(f"❯ {E}7mP{E}27m{E}2mlan, search{E}0m"), "")

    def test_typed_text_is_a_draft(self) -> None:
        self.assertEqual(prompt_line.classify(f"❯\xa0{E}0mhalf a sentence"), "half a sentence")
        # An RGB background's "2" is not dim.
        self.assertEqual(prompt_line.classify(f"❯ {E}48;2;30;30;30mtyped{E}0m"), "typed")

    def test_plain_hint_text_and_no_prompt(self) -> None:
        self.assertEqual(prompt_line.classify("❯ Press up to edit queued messages"), "")
        self.assertIsNone(prompt_line.classify("no prompt here"))

    def test_omp_input_row(self) -> None:
        # Rows captured from `herdr agent read --format ansi` on 2026-10-24: omp has no ❯; its input is the box's last
        # row. The `⇧⇥ to change thinking effort` hint and the ` ─╯` border are not the operator's text.
        edge, text, hint = f"{E}0m{E}38;2;0;180;255m", f"{E}0m{E}38;2;229;229;231m", f"{E}0m{E}3m{E}38;2;107;114;128m"
        empty = f"{edge}╰─ {text}{' ' * 40}{edge}⇧⇥{text} {hint}to change thinking effort{edge} ─╯{E}0m"
        draft = f"{edge}╰─ {text}hello draft{' ' * 40}{edge} ─╯{E}0m"
        box_bottom = f"{edge}╰{'─' * 60}╯{E}0m"  # a tool box's closing row has no space after ╰─
        self.assertEqual(prompt_line.classify(f"{box_bottom}\n{empty}", prompt_line.OMP_MARK), "")
        self.assertEqual(prompt_line.classify(f"{box_bottom}\n{draft}", prompt_line.OMP_MARK), "hello draft")
        self.assertIsNone(prompt_line.classify(box_bottom, prompt_line.OMP_MARK))

    def test_agy_input_row(self) -> None:
        # agy uses `>` as its prompt marker (2026-10-28).
        empty = f"{E}0m{E}38;5;12m>{E}0m"
        draft = f"{E}0m{E}38;5;12m>{E}0m hello draft"
        self.assertEqual(prompt_line.classify(empty, ">"), "")
        self.assertEqual(prompt_line.classify(draft, ">"), "hello draft")
        self.assertIsNone(prompt_line.classify("no prompt here", ">"))


BG = f"{E}48;2;65;69;76m"
OFF = f"{E}0m"
FOOTER = "GPT-6.1-Sol high · ~/src/example"


def shaded(*rows: str) -> str:
    """A Codex composer: every row in one background, then the unshaded footer."""
    return "".join(f"{BG}{row}{OFF}\n" for row in rows) + FOOTER + "\n"


class CodexComposerRegionTest(unittest.TestCase):
    def classify(self, screen: str) -> str | None:
        return prompt_line.classify(screen, "›")

    def test_a_marker_looking_row_inside_the_shaded_region_is_draft_content(self) -> None:
        for last in ("›", "› "):
            with self.subTest(last=last):
                self.assertEqual(self.classify(shaded("› keep this operator draft", last)),
                                 "keep this operator draft\n›")

    def test_leading_empty_prompt_then_typed_text_then_a_marker_looking_row(self) -> None:
        self.assertEqual(self.classify(shaded("› ", "typed continuation", "›")), "typed continuation\n›")

    def test_several_marker_looking_continuations_keep_every_row(self) -> None:
        self.assertEqual(self.classify(shaded("› first", "› second", "›", "› third")), "first\n› second\n›\n› third")

    def test_only_marker_looking_rows_are_still_a_draft(self) -> None:
        self.assertEqual(self.classify(shaded("› ", "›")), "›")

    def test_an_unshaded_transcript_quote_is_not_a_composer(self) -> None:
        self.assertIsNone(self.classify("› quoted transcript\nordinary output\n"))
        self.assertIsNone(self.classify("› quoted transcript\n" + shaded("typed text, no marker row")))
        # an unstyled quote below a styled draft is no composer boundary either: fail closed
        self.assertIsNone(self.classify(shaded("› draft") + "› quote after it\n"))

    def test_a_prior_shaded_block_apart_from_the_composer_is_not_the_draft(self) -> None:
        old = shaded("› an earlier message the operator already sent", "its second line")
        old = old.replace(FOOTER + "\n", "assistant answer\n")
        self.assertEqual(self.classify(old + shaded(f"› {E}2mAsk Codex to do anything{OFF}", "")), "")
        self.assertEqual(self.classify(old + shaded("› unsent draft", "›")), "unsent draft\n›")

    def test_a_current_empty_composer_does_not_hide_behind_an_older_drafted_block(self) -> None:
        old = shaded("› older", "text").replace(FOOTER + "\n", "assistant answer\n")
        self.assertEqual(self.classify(old + shaded("› ", "")), "")

    def test_text_above_the_first_visible_marker_in_the_region_counts(self) -> None:
        # the screen window can cut a long draft: the shaded rows above the first visible marker are still draft text
        self.assertEqual(self.classify(shaded("scrolled-off tail of a draft", "›")), "scrolled-off tail of a draft")


class CliMainTest(unittest.TestCase):
    def test_cli_handles_mark_not_in_screen_without_index_error(self) -> None:
        import subprocess
        # zcode or custom classifiers may return a non-None classification even if mark is not in screen lines
        res = subprocess.run(
            [sys.executable, str(Path(prompt_line.__file__).resolve()), prompt_line.ZCODE_MARK],
            input="─" * 40 + "\n" + "─" * 40 + "\n",
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(res.stdout.strip(), "EMPTY")
        self.assertIn("RAW (no mark in screen", res.stderr)


if __name__ == "__main__":
    unittest.main()
