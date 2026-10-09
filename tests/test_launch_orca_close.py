"""Tests for launch.py close on an Orca-hosted launch: the terminal is closed with `orca terminal close`,
except the caller's own terminal and handles Orca no longer lists. `fleet.run` is faked: no live Orca is touched."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))

import fleet
import launch

TAB, LEAF = "tab-1", "leaf-1"
OWN, TARGET, GONE = "term_own", "term_target", "term_gone"
LISTING = json.dumps({"ok": True, "result": {"terminals": [
    {"handle": OWN, "tabId": TAB, "leafId": LEAF, "orphaned": False},
    {"handle": TARGET, "tabId": "tab-2", "leafId": "leaf-2", "orphaned": False},
]}})


class OrcaClose(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.close_rc = 0
        self.tmp = tempfile.mkdtemp(prefix="orcaclose-")
        for p in (mock.patch.object(fleet, "_ORCA", None), mock.patch.object(fleet, "run", self.fake_run),
                  mock.patch.object(launch, "STATE", Path(self.tmp)),
                  mock.patch.dict(os.environ, {"ORCA_TERMINAL_HANDLE": OWN, "ORCA_PANE_KEY": f"{TAB}:{LEAF}"})):
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, *cmd, timeout=10):
        self.calls.append(cmd)
        if cmd[:3] == ("orca", "terminal", "list"):
            return 0, LISTING
        if cmd[:3] == ("orca", "terminal", "close"):
            return self.close_rc, ""
        return 127, ""

    def closes(self):
        return [c for c in self.calls if c[:3] == ("orca", "terminal", "close")]

    def test_closes_a_live_foreign_terminal(self):
        msg = launch.close_orca_terminal(TARGET)
        self.assertEqual(self.closes(), [("orca", "terminal", "close", "--terminal", TARGET, "--json")])
        self.assertIn("closed", msg)

    def test_never_closes_the_callers_own_terminal(self):
        self.assertIn("own terminal", launch.close_orca_terminal(OWN))
        self.assertEqual(self.closes(), [])

    def test_own_terminal_found_by_pane_key_when_env_handle_is_stale(self):
        with mock.patch.dict(os.environ, {"ORCA_TERMINAL_HANDLE": "term_stale"}):
            self.assertIn("own terminal", launch.close_orca_terminal(OWN))
        self.assertEqual(self.closes(), [])

    def test_unlisted_handle_is_skipped(self):
        self.assertIn("already gone", launch.close_orca_terminal(GONE))
        self.assertEqual(self.closes(), [])

    def test_close_failure_is_reported_not_raised(self):
        self.close_rc = 1
        self.assertIn("failed", launch.close_orca_terminal(TARGET))

    def run_close(self, host, keep_pane=False):
        rec = {"id": "L1", "host": host, "interactive": False, "exit": 0}
        args = argparse.Namespace(id="L1", force=False, keep_pane=keep_pane)
        out = io.StringIO()
        with mock.patch.object(fleet, "launches", return_value=[rec]), \
                mock.patch.object(fleet, "launch_state", return_value=("done", None, "ok")), \
                contextlib.redirect_stdout(out):
            rc = launch.cmd_close(args)
        return rc, out.getvalue()

    def test_cmd_close_closes_the_orca_terminal(self):
        rc, out = self.run_close({"kind": "orca", "terminal": TARGET})
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.closes()), 1)
        self.assertIn("closed L1", out)

    def test_cmd_close_keep_pane_leaves_it(self):
        rc, _ = self.run_close({"kind": "orca", "terminal": TARGET}, keep_pane=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.closes(), [])

    def test_cmd_close_without_a_terminal_handle_does_nothing_extra(self):
        rc, out = self.run_close({"kind": "orca"})
        self.assertEqual(rc, 0)
        self.assertEqual(self.closes(), [])


if __name__ == "__main__":
    unittest.main()
