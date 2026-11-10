#!/usr/bin/env python3
"""macOS-only guards revived from closed PR 292 (#279): explanatory exit 69 (EX_UNAVAILABLE).

coding-bot / codium-ai / app-tamer-ab and the acp-dispatch launchctl guards from that PR are not
revived here: those tools were retired by the 2026-11-06/07 slim-down (or are queued for Wave 6
removal). What remains is paseo-set-model's missing-helper guard.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"


class PaseoSetModelGuard(unittest.TestCase):
    def test_missing_helper_exits_69_naming_path_and_override(self):
        env = dict(os.environ, PASEO_SET_MODEL_HELPER="/nonexistent/Paseo Helper")
        r = subprocess.run([sys.executable, "-I", str(BIN / "paseo-set-model"), "list", "--json"],
                           check=False, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 69, r.stderr)
        self.assertIn("/nonexistent/Paseo Helper", r.stderr)
        self.assertIn("PASEO_SET_MODEL_HELPER", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
