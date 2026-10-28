#!/usr/bin/env python3
"""bin/pytest installs the same test dependencies as CI's pytest job, so the two cannot drift."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "bin" / "pytest"
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"


class BinPytestTests(unittest.TestCase):
    def test_print_matches_the_ci_command(self) -> None:
        ci = re.search(r"run: (uv run --with .* python -m pytest tests/ -q)", WORKFLOW.read_text())
        self.assertIsNotNone(ci, "CI no longer runs `uv run --with ... python -m pytest tests/ -q`")
        mine = subprocess.run([sys.executable, str(WRAPPER), "--print"], capture_output=True, text=True,
                              check=True).stdout.strip()
        norm = lambda s: s.replace("'", "")
        self.assertEqual(norm(mine), norm(ci.group(1)))


if __name__ == "__main__":
    unittest.main()
