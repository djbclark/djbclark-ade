"""Tests for session-finder/fleet.py's Orca terminal handle resolution.

Orca re-issues terminal handles when its runtime restarts; a process started earlier keeps the old
ORCA_TERMINAL_HANDLE. ORCA_PANE_KEY (tabId:leafId) is stable, so fleet resolves it through one
`orca terminal list` call. `fleet.run` is faked here: no live Orca, ps or herdr is touched.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))

import fleet

TAB, LEAF = "tab-1111", "leaf-2222"
KEY = f"{TAB}:{LEAF}"
LIVE, STALE, OTHER = "term_live", "term_stale", "term_other"


def orca_list(*terms):
    return json.dumps({"ok": True, "result": {"terminals": list(terms), "totalCount": len(terms)}})


LISTING = orca_list(
    {"handle": LIVE, "tabId": TAB, "leafId": LEAF, "orphaned": False, "connected": True},
    {"handle": OTHER, "tabId": "tab-9", "leafId": "leaf-9", "orphaned": False, "connected": True},
    {"handle": "term_orphan", "tabId": "tab-7", "leafId": "leaf-7", "orphaned": True, "connected": False},
)


class FakeWhere:
    def __init__(self, env):
        self.env = env

    def env_of(self, pid):
        return dict(self.env)

    def lookup(self, pid, start):
        return {"where": "Orca · tab", "focus": "orca terminal switch --tab x", "title": "t"}


class OrcaHandle(unittest.TestCase):
    def setUp(self):
        self._saved = []
        self.calls = []
        self.listing = (0, LISTING)
        self.patch(fleet, "_ORCA", None)
        self.patch(fleet, "run", self.fake_run)

    def patch(self, mod, name, value):
        self._saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, value)

    def tearDown(self):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)

    def fake_run(self, *cmd, timeout=10):
        self.calls.append(cmd)
        if cmd[:3] == ("orca", "terminal", "list"):
            return self.listing
        if cmd[0] == "ps":
            return 0, self.ps
        return 127, ""

    ps = ""

    # -- the helper ------------------------------------------------------------------------------

    def test_pane_key_resolves_to_live_handle_when_env_handle_is_stale(self):
        env = {"ORCA_PANE_KEY": KEY, "ORCA_TERMINAL_HANDLE": STALE}
        self.assertEqual(fleet._orca_chan(env), ("orca", LIVE))

    def test_env_handle_used_when_live_and_no_pane_key(self):
        self.assertEqual(fleet._orca_chan({"ORCA_TERMINAL_HANDLE": OTHER}), ("orca", OTHER))

    def test_unknown_pane_key_falls_back_to_live_env_handle(self):
        env = {"ORCA_PANE_KEY": "tab-x:leaf-x", "ORCA_TERMINAL_HANDLE": OTHER}
        self.assertEqual(fleet._orca_chan(env), ("orca", OTHER))

    def test_neither_live_gives_no_channel(self):
        env = {"ORCA_PANE_KEY": "tab-x:leaf-x", "ORCA_TERMINAL_HANDLE": STALE}
        self.assertIsNone(fleet._orca_chan(env))
        self.assertIsNone(fleet._orca_chan({"ORCA_TERMINAL_HANDLE": STALE}))
        self.assertIsNone(fleet._orca_chan({}))

    def test_orphaned_terminal_is_not_live(self):
        self.assertIsNone(fleet._orca_chan({"ORCA_PANE_KEY": "tab-7:leaf-7", "ORCA_TERMINAL_HANDLE": "term_orphan"}))

    def test_orca_missing_or_failing_gives_no_channel_and_no_exception(self):
        env = {"ORCA_PANE_KEY": KEY, "ORCA_TERMINAL_HANDLE": LIVE}
        for listing in ((127, ""), (1, LISTING), (0, "not json"), (0, "{}"), (0, '{"result": {"terminals": [1]}}'),
                        (0, orca_list({"tabId": TAB}))):
            with self.subTest(listing=listing):
                fleet._ORCA = None
                self.listing = listing
                self.assertIsNone(fleet._orca_chan(env))

    def test_list_runs_once_per_process_even_on_failure(self):
        fleet._orca_chan({"ORCA_PANE_KEY": KEY})
        fleet._orca_chan({"ORCA_TERMINAL_HANDLE": OTHER})
        self.assertEqual(len([c for c in self.calls if c[:3] == ("orca", "terminal", "list")]), 1)
        fleet._ORCA = None
        self.listing = (127, "")
        fleet._orca_chan({})
        fleet._orca_chan({})
        self.assertEqual(len([c for c in self.calls if c[:3] == ("orca", "terminal", "list")]), 2)

    def test_list_call_shape(self):
        fleet._orca_terminals()
        self.assertEqual(self.calls[0], ("orca", "terminal", "list", "--json", "--include-visual-layouts"))

    # -- the claude-session site -----------------------------------------------------------------

    def claude_session(self, env):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "sessions").mkdir()
        (Path(tmp.name) / "sessions" / "a.json").write_text(
            json.dumps({"pid": 4242, "sessionId": "abcdef12-0000", "cwd": "/x", "status": "idle"}))
        self.patch(fleet, "CLAUDE", Path(tmp.name))
        self.patch(fleet, "alive", lambda pid: True)
        self.patch(fleet, "transcript", lambda sid: None)
        self.patch(fleet, "_where", FakeWhere(env))
        out = fleet._claude_sessions({}, set(), set())
        self.assertEqual(len(out), 1)
        return out[0]

    def test_claude_site_stale_env_handle_resolved_through_pane_key(self):
        s = self.claude_session({"ORCA_PANE_KEY": KEY, "ORCA_TERMINAL_HANDLE": STALE})
        self.assertEqual((s["host"], s["chan"]), ("orca", ("orca", LIVE)))

    def test_claude_site_dead_handle_gives_no_channel_and_stale_reach(self):
        s = self.claude_session({"ORCA_TERMINAL_HANDLE": STALE})
        self.assertEqual(s["host"], "orca")
        self.assertIsNone(s["chan"])
        self.assertEqual(s["reach"], fleet.ORCA_STALE)
        self.assertIn("stale", s["reach"])

    # -- the process-scan site -------------------------------------------------------------------

    def proc_scan(self, env):
        self.ps = "4343 1 Thu Oct 8 12:00:00 2026 /opt/bin/codex\n"
        self.patch(fleet, "_where", FakeWhere(env))
        out = fleet._proc_scan(set(), set(), set())
        self.assertEqual(len(out), 1)
        return out[0]

    def test_proc_site_stale_env_handle_resolved_through_pane_key(self):
        s = self.proc_scan({"ORCA_PANE_KEY": KEY, "ORCA_TERMINAL_HANDLE": STALE})
        self.assertEqual((s["host"], s["chan"]), ("orca", ("orca", LIVE)))
        self.assertIn("helm.py send", s["reach"])

    def test_proc_site_live_env_handle_without_pane_key(self):
        s = self.proc_scan({"ORCA_TERMINAL_HANDLE": OTHER})
        self.assertEqual(s["chan"], ("orca", OTHER))

    def test_proc_site_dead_handle_gives_no_channel_and_stale_reach(self):
        s = self.proc_scan({"ORCA_PANE_KEY": "tab-x:leaf-x", "ORCA_TERMINAL_HANDLE": STALE})
        self.assertEqual(s["host"], "orca")
        self.assertIsNone(s["chan"])
        self.assertEqual(s["reach"], fleet.ORCA_STALE)

    def test_proc_site_orca_failing_gives_no_channel(self):
        self.listing = (127, "")
        s = self.proc_scan({"ORCA_PANE_KEY": KEY, "ORCA_TERMINAL_HANDLE": LIVE})
        self.assertIsNone(s["chan"])
        self.assertEqual(s["reach"], fleet.ORCA_STALE)

    # -- the ACP-launch site ---------------------------------------------------------------------

    def launched(self, terminal):
        self.patch(fleet, "launches", lambda: [{"id": "l1", "agent": "codex", "host": {"kind": "orca", "terminal": terminal}}])
        self.patch(fleet, "launch_state", lambda d: ("idle", "", None))
        out = fleet._launched(set())
        self.assertEqual(len(out), 1)
        return out[0]

    def test_acp_launch_live_stored_handle_keeps_channel(self):
        s = self.launched(LIVE)
        self.assertEqual(s["chan"], ("orca", LIVE))
        self.assertEqual(s["focus"], f"orca terminal switch --terminal {LIVE}")

    def test_acp_launch_stale_stored_handle_gives_no_channel(self):
        s = self.launched(STALE)
        self.assertIsNone(s["chan"])
        self.assertEqual(s["focus"], "")
        self.assertIn("stale", s["where"])

    def test_acp_launch_missing_handle_or_orca_gives_no_channel(self):
        self.assertIsNone(self.launched(None)["chan"])
        fleet._ORCA = None
        self.listing = (127, "")
        self.assertIsNone(self.launched(LIVE)["chan"])


if __name__ == "__main__":
    unittest.main()
