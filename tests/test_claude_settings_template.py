#!/usr/bin/env python3
"""agents/claude/settings.json.tmpl (queue Carried 40, 2026-11-15): the template registers the ADE-owned
hooks and carries the portable graft footer-link regex, and uses the canonical ops repo names."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

TMPL = Path(__file__).resolve().parent.parent / "agents" / "claude" / "settings.json.tmpl"


class SettingsTemplateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.text = TMPL.read_text()
        self.data = json.loads(self.text)

    def test_footer_links_regex_for_graft_cards(self) -> None:
        self.assertEqual(self.data["footerLinksRegexes"], ["graft/[\\w./-]+\\.md"])

    def test_no_stale_ops_repo_names(self) -> None:
        self.assertNotIn("ops/site-private/", self.text)
        self.assertNotIn("ops/site-djbclark/", self.text)

    def test_context_size_nudge_registered(self) -> None:
        for event in ("PostToolUse", "UserPromptSubmit"):
            cmds = [h["command"] for g in self.data["hooks"][event] for h in g["hooks"]]
            self.assertTrue(any("context_size_nudge.py" in c for c in cmds), event)


if __name__ == "__main__":
    unittest.main()
