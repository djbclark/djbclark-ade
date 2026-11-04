#!/usr/bin/env python3
"""Tests for the "macOS only" guards (issue #279): each tool exits 69 (EX_UNAVAILABLE) with a clear message
where its macOS pieces are missing. codium-ai and app-tamer-ab check `uname -s` and are only tested on
non-Darwin hosts; paseo-set-model and acp-dispatch are tested through their overrides."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from test_acp_dispatch import Base, run

BIN = Path(__file__).resolve().parent.parent / "bin"


@unittest.skipIf(sys.platform == "darwin", "the guard only fires off macOS")
class UnameGuards(unittest.TestCase):
    def test_codium_ai_and_app_tamer_ab_exit_69(self):
        for tool in ("codium-ai", "app-tamer-ab"):
            r = subprocess.run([str(BIN / tool), "run"], check=False, capture_output=True, text=True)
            self.assertEqual(r.returncode, 69, r.stderr)
            self.assertIn(f"{tool}: macOS only:", r.stderr)


class PaseoSetModelGuard(unittest.TestCase):
    def test_missing_helper_exits_69_naming_path_and_override(self):
        env = dict(os.environ, PASEO_SET_MODEL_HELPER="/nonexistent/Paseo Helper")
        r = subprocess.run([sys.executable, str(BIN / "paseo-set-model"), "list", "--json"],
                           check=False, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 69, r.stderr)
        self.assertIn("/nonexistent/Paseo Helper", r.stderr)
        self.assertIn("PASEO_SET_MODEL_HELPER", r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class AcpDispatchLaunchctlGuard(Base):
    MSG = "launchd paths are macOS only; on Linux use `paseo run`"

    def test_reap_install_without_launchctl_exits_69_and_writes_nothing(self):
        agents = self.tmp / "LaunchAgents"
        r = run(["reap", "--install"], env={"ACP_DISPATCH_LAUNCHCTL": str(self.tmp / "no-launchctl"),
                                           "ACP_DISPATCH_LAUNCH_AGENTS": str(agents)})
        self.assertEqual(r.returncode, 69, r.stderr)
        self.assertIn(self.MSG, r.stderr)
        self.assertFalse(agents.exists())

    def test_detach_without_launchctl_exits_69(self):
        r = self.dispatch("--detach", "--no-wait", env={"ACP_DISPATCH_LAUNCHCTL": str(self.tmp / "no-launchctl")})
        self.assertEqual(r.returncode, 69, r.stdout + r.stderr)
        self.assertIn(self.MSG, r.stderr)
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
