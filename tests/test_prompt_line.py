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


if __name__ == "__main__":
    unittest.main()
