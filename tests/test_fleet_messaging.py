#!/usr/bin/env python3
"""Tests for session-finder/fleet.py's cross-session messaging check (messaging_warning).

Every file it reads (~/.claude.json, settings.json, the Claude binary, the check cache) is a temp file.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "session-finder"))

import fleet


class MessagingWarning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.cj = self.d / "claude.json"
        self.settings = self.d / "settings.json"
        self.binary = self.d / "claude"
        self.cache = self.d / "cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, flag, env=None, binary=b"tengu_harbor_kite CLAUDE_CODE_HARBOR_KITE"):
        feats = {} if flag is None else {fleet.MSG_FLAG: flag}
        self.cj.write_text(json.dumps({"cachedGrowthBookFeatures": feats}))
        self.settings.write_text(json.dumps({"env": {} if env is None else {fleet.MSG_ENV: env}}))
        self.binary.write_bytes(binary)

    def warn(self):
        return fleet.messaging_warning(self.cj, self.settings, str(self.binary), self.cache)

    def test_override_missing_warns_whatever_the_flag(self):
        for flag in (True, False, None):
            self.write(flag)
            self.assertIn("has no env CLAUDE_CODE_HARBOR_KITE=1", self.warn())

    def test_override_set_is_quiet(self):
        self.write(False, env="1", binary=b"tengu_harbor_kite CLAUDE_CODE_HARBOR_KITE")
        self.assertIsNone(self.warn())

    def test_renamed_variable_warns(self):
        self.write(True, env="1", binary=b"tengu_harbor_kite only")
        self.assertIn("no longer reads CLAUDE_CODE_HARBOR_KITE", self.warn())

    def test_gate_gone_is_quiet(self):
        self.write(True, env="1", binary=b"neither name")
        self.assertIsNone(self.warn())

    def test_binary_results_are_cached_per_name(self):
        self.write(True, env="1", binary=b"tengu_harbor_kite only")
        self.warn()
        self.assertEqual(sorted(json.loads(self.cache.read_text()).values()), [False, True])

    def test_missing_settings_warns(self):
        self.assertIn("has no env", self.warn())


if __name__ == "__main__":
    unittest.main()
