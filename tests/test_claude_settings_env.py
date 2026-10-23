#!/usr/bin/env python3
"""Tests for bin/claude-settings-env (2026-10-16): enforces GRAFT_NO_GITIGNORE and (2026-10-23) adds the
CLAUDE_CODE_SUBAGENT_MODEL default only when absent, idempotently, keeping other keys, key order, mode and a
symlinked target."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "claude-settings-env"


def run(settings: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--settings", str(settings), *extra],
        capture_output=True, text=True, check=False,
    )


class ClaudeSettingsEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp))
        self.settings = self.tmp / "settings.json"
        self.settings.write_text(json.dumps({"env": {"A": "1"}, "model": "x"}, indent=2) + "\n")
        self.settings.chmod(0o644)

    def test_check_then_set_then_idempotent(self) -> None:
        self.assertEqual(run(self.settings, "--check").returncode, 1)
        self.assertEqual(run(self.settings).returncode, 0)
        data = json.loads(self.settings.read_text())
        self.assertEqual(data["env"], {"A": "1", "GRAFT_NO_GITIGNORE": "1", "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"})
        self.assertEqual(list(data), ["env", "model"])
        before = self.settings.read_text()
        self.assertEqual(run(self.settings, "--check").returncode, 0)
        self.assertEqual(run(self.settings).returncode, 0)
        self.assertEqual(self.settings.read_text(), before)
        self.assertEqual(self.settings.stat().st_mode & 0o777, 0o644)

    def test_wrong_value_is_corrected_and_no_env_block_is_created(self) -> None:
        self.settings.write_text(json.dumps({"env": {"GRAFT_NO_GITIGNORE": "0"}}) + "\n")
        self.assertEqual(run(self.settings).returncode, 0)
        self.assertEqual(json.loads(self.settings.read_text())["env"]["GRAFT_NO_GITIGNORE"], "1")
        self.settings.write_text("{}\n")
        self.assertEqual(run(self.settings).returncode, 0)
        self.assertEqual(json.loads(self.settings.read_text()),
                         {"env": {"GRAFT_NO_GITIGNORE": "1", "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}})

    def test_a_deliberate_default_value_is_left_alone(self) -> None:
        self.settings.write_text(json.dumps({"env": {"GRAFT_NO_GITIGNORE": "1", "CLAUDE_CODE_SUBAGENT_MODEL": "opus"}}) + "\n")
        before = self.settings.read_text()
        p = run(self.settings, "--check")
        self.assertEqual(p.returncode, 0)
        self.assertIn("left alone", p.stdout)
        self.assertEqual(run(self.settings).returncode, 0)
        self.assertEqual(self.settings.read_text(), before)

    def test_symlink_is_kept(self) -> None:
        link = self.tmp / "link.json"
        os.symlink(self.settings, link)
        self.assertEqual(run(link).returncode, 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(self.settings.read_text())["env"]["GRAFT_NO_GITIGNORE"], "1")


if __name__ == "__main__":
    unittest.main()
