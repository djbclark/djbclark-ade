#!/usr/bin/env python3
"""Tests for the safe-close pieces of session-finder/fleet.py, helm/helm.py and herdr-tidy/tidy.py.

Everything that touches herdr, ps, transcripts or the sleeper journal is stubbed at the module
boundary, so these run without herdr and never read the live journal or ledger.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))
sys.path.insert(0, str(ROOT / "helm"))
sys.path.insert(0, str(ROOT / "herdr-tidy"))

import fleet
import helm
import tidy


class Patched(unittest.TestCase):
    """Swap module attributes for the test and put them back."""

    def setUp(self):
        self._saved = []

    def patch(self, mod, name, value):
        self._saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, value)

    def tearDown(self):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)


class TestResumeForms(unittest.TestCase):
    def test_claude_keeps_only_allowlisted_flags(self):
        argv = ["--dangerously-skip-permissions", "--model", "opus", "-p", "do it", "--fork-session", "--effort=high"]
        self.assertEqual(fleet.replay_flags(argv, "claude"),
                         ["--dangerously-skip-permissions", "--model", "opus", "--effort=high"])

    def test_other_kinds_replay_nothing(self):
        self.assertEqual(fleet.replay_flags(["--yolo"], "cursor"), [])

    def test_forms_match_each_tui_help(self):
        sid, cwd = "abc12345-0000", "/tmp/w d"
        self.assertEqual(fleet.resume_command("claude", sid, cwd, ["--dangerously-skip-permissions"]),
                         "cd '/tmp/w d' && claude --dangerously-skip-permissions --resume abc12345-0000")
        self.assertEqual(fleet.resume_command("opencode", sid, "", None), "opencode -s abc12345-0000")
        self.assertEqual(fleet.resume_command("codex", sid), "codex resume abc12345-0000")
        self.assertEqual(fleet.resume_command("cursor", sid), "cursor-agent --resume abc12345-0000")
        self.assertEqual(fleet.resume_command("copilot", sid), "copilot --resume=abc12345-0000")
        self.assertEqual(fleet.resume_command("muse", sid), "muse resume abc12345-0000")
        self.assertEqual(fleet.resume_command("agy", sid), "agy --conversation abc12345-0000")
        self.assertIsNone(fleet.resume_command("devin", sid))        # unverified kind: no recipe, never a guess
        self.assertIsNone(fleet.resume_command("claude", None))

    def test_sleeper_entry_spells_it_like_manual_command(self):
        e = {"kind": "claude", "uuid": "u-1", "cwd": "/Users/x/src/p", "argv": ["--dangerously-skip-permissions"]}
        self.assertEqual(fleet.sleeper_resume(e), "cd /Users/x/src/p && claude --dangerously-skip-permissions --resume u-1")


class TestBusy(unittest.TestCase):
    TABLE: ClassVar[dict] = {100: (1, "claude --dangerously-skip-permissions"), 101: (100, "node /x/graft mcp"),
             102: (100, "/bin/bash -c sleep 600"), 103: (102, "sleep 600"), 104: (100, "caffeinate -i -t 300"),
             200: (1, "-bash"), 201: (200, "java -classpath /x maestro.cli.AppKt mcp")}

    def test_descendants_walks_the_tree(self):
        self.assertEqual(sorted(fleet.descendants(100, self.TABLE)), [101, 102, 103, 104])

    def test_servers_are_not_work(self):
        work = fleet.background_work(100, self.TABLE)
        self.assertEqual([w.split()[0] for w in work], ["102", "103"])
        self.assertEqual(fleet.background_work(200, self.TABLE), [])
        self.assertIsNone(fleet.background_work(None, self.TABLE))

    def test_mark_busy_turns_idle_into_busy_background(self):
        s = {"status": "idle", "pid": 100}
        fleet.mark_busy(s, self.TABLE)
        self.assertEqual(s["status"], "busy-background")
        self.assertEqual(len(s["busy"]), 2)
        quiet = {"status": "idle", "pid": 200}
        fleet.mark_busy(quiet, self.TABLE)
        self.assertEqual(quiet["status"], "idle")
        working = {"status": "working", "pid": 100}
        fleet.mark_busy(working, self.TABLE)
        self.assertEqual(working["status"], "working")
        acp = {"status": "idle", "pid": 100, "host": "acp"}
        fleet.mark_busy(acp, self.TABLE)
        self.assertEqual(acp["status"], "idle")


class TestPaneDetection(unittest.TestCase):
    def test_tui_from_process_info(self):
        procs = [{"pid": 9, "name": "python3.13", "argv0": "python", "argv": ["/x/bin/python", "/x/bin/token-savior"], "cwd": ""},
                 {"pid": 7, "name": "node", "argv0": "node", "argv": ["node", "/Users/d/.local/bin/zcode", "--mode", "yolo"], "cwd": ""}]
        self.assertEqual(fleet._tui_of(procs)[:2], ("zcode", 7))

    def test_session_id_from_argv(self):
        procs = [{"pid": 5, "name": "node", "argv0": "cursor-agent",
                  "argv": ["/x/cursor-agent", "--yolo", "--resume", "091d8cae-e603-4365-a80e-68f042fac2bb"], "cwd": ""}]
        self.assertEqual(fleet._tui_of(procs), ("cursor", 5, "091d8cae-e603-4365-a80e-68f042fac2bb", procs[0]["argv"]))

    def test_sleeper_stub_is_not_a_tui(self):
        procs = [{"pid": 3, "name": "Python", "argv0": "Python",
                  "argv": ["/x/Python", "/y/herdr-sleeper", "stub", "w22:p2", "uuid", "/state"], "cwd": ""}]
        self.assertEqual(fleet._tui_of(procs), (None, None, None, None))
        self.assertEqual(fleet._tui_of([{"pid": 1, "name": "bash", "argv0": "bash", "argv": ["-bash"], "cwd": ""}])[0], None)


class TestLedger(Patched):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.patch(fleet, "CLOSED", Path(self.tmp.name) / "closed.jsonl")
        self.patch(fleet, "toplevel", lambda p: p)

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()

    def write(self, *rows):
        with fleet.CLOSED.open("a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_missing_ledger_is_empty(self):
        self.assertEqual(fleet.closed_ledger(), [])

    def test_later_lines_update_and_resumed_hides(self):
        now = time.time()
        self.write({"id": "closed:a", "t": now - 10, "agent": "claude", "sid": "s1", "cwd": "/r1", "resume": "claude --resume s1"},
                   {"id": "closed:b", "t": now - 5, "agent": "shell", "cwd": "/r2", "resume": ""},
                   {"id": "closed:a", "resumed": True})
        rows = fleet.closed_ledger()
        self.assertEqual([r["id"] for r in rows], ["closed:b", "closed:a"])
        self.assertTrue(rows[1]["resumed"])
        items = fleet._closed_items(14, live_sids=set(), live_dirs=set(), chain_dirs=set())
        self.assertEqual([i["id"] for i in items], ["closed:b"])
        self.assertIn("no resume recipe", items[0]["action"])

    def test_live_again_or_covered_by_chain_is_hidden(self):
        now = time.time()
        self.write({"id": "closed:c", "t": now, "agent": "claude", "sid": "s9", "cwd": "/r9", "resume": "x", "handoff": "/h"},
                   {"id": "closed:d", "t": now, "agent": "claude", "sid": "s8", "cwd": "/r8", "resume": "y"})
        self.assertEqual([i["id"] for i in fleet._closed_items(14, {"s8"}, set(), set())], ["closed:c"])
        self.assertEqual([i["id"] for i in fleet._closed_items(14, set(), set(), {"/r9"})], ["closed:d"])

    def test_days_cutoff(self):
        self.write({"id": "closed:old", "t": time.time() - 40 * 86400, "cwd": "/r"})
        self.assertEqual(fleet.closed_ledger(14), [])
        self.assertEqual(len(fleet.closed_ledger()), 1)


class TestSleepingGone(Patched):
    JOURNAL: ClassVar[dict] = {
        "w22:p2": {"uuid": "aaaa1111-1", "kind": "claude", "phase": "asleep", "cwd": "/p", "pane_id": "w22:p2",
                   "argv": ["--dangerously-skip-permissions"], "slept_at": "2026-10-08T18:44:10", "title": "live stub", "journal": "/j"},
        "w26:p2": {"uuid": "bbbb2222-2", "kind": "claude", "phase": "asleep", "cwd": "/q", "pane_id": "w26:p2",
                   "argv": [], "slept_at": "2026-10-08T10:00:00", "title": "pane gone", "journal": "/j"},
        "orphan:cccc3333": {"uuid": "cccc3333-3", "kind": "claude", "phase": "orphaned", "cwd": "/r", "pane_id": "w23:p1",
                            "argv": [], "slept_at": "2026-10-07T10:00:00", "title": "orphaned", "journal": "/j"},
        "w24:p1": {"uuid": "dddd4444-4", "kind": "devin", "phase": "asleep", "cwd": "/s", "pane_id": "w24:p1",
                   "argv": [], "slept_at": "2026-10-08T10:00:00", "title": "no recipe", "journal": "/j"},
    }

    def setUp(self):
        super().setUp()
        self.patch(fleet, "sleeper_journal", lambda: dict(self.JOURNAL))
        self.patch(fleet, "herdr_json", lambda *a: {"panes": [{"pane_id": "w22:p2"}]} if a[:2] == ("pane", "list") else {})
        self.patch(fleet, "transcript", lambda sid: None)
        self.patch(time, "time", lambda: time.mktime(time.strptime("2026-10-09T00:00:00", "%Y-%m-%dT%H:%M:%S")))

    def test_only_entries_whose_pane_is_gone(self):
        items = {i["id"]: i for i in fleet._sleeping_items(14, live_sids=set(), ledger_uuids=set())}
        self.assertEqual(set(items), {"sleep:bbbb2222", "sleep:cccc3333", "sleep:dddd4444"})
        self.assertEqual(items["sleep:bbbb2222"]["resume"], "cd /q && claude --resume bbbb2222-2")
        self.assertEqual(items["sleep:cccc3333"]["pane"], "w23:p1")
        self.assertIn("no resume recipe", items["sleep:dddd4444"]["action"])

    def test_ledgered_or_live_entries_are_not_repeated(self):
        items = fleet._sleeping_items(14, live_sids={"bbbb2222-2"}, ledger_uuids={"cccc3333-3"})
        self.assertEqual([i["id"] for i in items], ["sleep:dddd4444"])


class TestEndedOrder(Patched):
    def test_open_work_first_then_closed(self):
        now = time.time()
        self.patch(fleet, "sessions", lambda include_shell=False: [])
        self.patch(fleet, "_chain_logs", lambda days: [{"chain": "c1", "path": "/c1", "dirs": ["/d1"], "updated": now - 100,
                                                        "active": "work", "steps": ["step"]}])
        self.patch(fleet, "toplevel", lambda p: p)
        self.patch(fleet.CLAUDE.__class__, "glob", lambda self, pat: iter(()))
        self.patch(fleet, "_closed_items", lambda *a: [{"kind": "closed", "id": "closed:x", "updated": now, "cwd": "/d2"}])
        self.patch(fleet, "_sleeping_items", lambda *a: [{"kind": "sleeping", "id": "sleep:y", "updated": now, "cwd": "/d3"}])
        kinds = [it["kind"] for it in fleet.ended_open(14)]
        self.assertEqual(kinds, ["handoff", "closed", "sleeping"])


class TestHelm(unittest.TestCase):
    def test_busy_background_is_never_open(self):
        s = {"id": "x", "agent": "zcode", "name": "", "title": "", "where": "herdr", "focus": "", "status": "busy-background",
             "cwd": "/r", "chan": ("herdr", "w1:p1"), "self": False, "busy": ["12 bg just ci"]}
        it = helm.classify(s, {})
        self.assertEqual(it["kind"], "busy-background")
        self.assertFalse(it["open"])
        self.assertIn("BUSY IN THE BACKGROUND", helm.render(it))

    def test_ended_kinds_rank_below_handoffs(self):
        self.assertGreater(helm.ENDED_UNLOCK["handoff"], helm.ENDED_UNLOCK["closed"])
        self.assertGreater(helm.ENDED_UNLOCK["ended-question"], helm.ENDED_UNLOCK["sleeping"])

    def test_render_closed_and_sleeping(self):
        base = {"id": "closed:1", "agent": "claude", "name": "", "title": "t", "where": "ended", "focus": "", "project": "p",
                "unlock": 8, "pane": "w1:p1", "why": "finished with /handoff", "resume": "cd /r && claude --resume s", "mb": 1.2}
        self.assertIn("CLOSED BY herdr-tidy", helm.render({**base, "kind": "closed"}))
        self.assertIn("SLEEPING PANE GONE", helm.render({**base, "kind": "sleeping", "id": "sleep:1"}))


class TestTidyScreens(unittest.TestCase):
    def test_claude_composer_states(self):
        self.assertEqual(tidy.claude_composer(["x", "❯ ", "  ⏵⏵ bypass"]), ("empty", ""))
        self.assertEqual(tidy.claude_composer(["x", "❯ close the two panes", "  ⏵⏵"]), ("draft", "close the two panes"))
        self.assertEqual(tidy.claude_composer(["✻ Churned for 1d", "※ recap: …"]), ("unknown", ""))
        self.assertEqual(tidy.claude_composer(['❯ Try "fix typecheck errors"', "  ⏵⏵"]), ("empty", ""))

    def test_shell_prompt(self):
        self.assertTrue(tidy.SHELL_PROMPT.search("djbclark@mac:~/src/stayturgid$"))
        self.assertTrue(tidy.SHELL_PROMPT.search("djbclark@mac:~$ "))
        self.assertFalse(tidy.SHELL_PROMPT.search("djbclark@mac:~/src/herdr$ claude"))

    def test_tui_waiting(self):
        self.assertTrue(tidy.TUI_WAITING.search("Question 1 of 1"))
        self.assertTrue(tidy.TUI_WAITING.search("Resume? [y/N]"))
        self.assertFalse(tidy.TUI_WAITING.search("done in 3s"))


class TestTidyClassify(Patched):
    """classify() with herdr, ps and the transcript stubbed at the fleet/tidy boundary."""

    def pane(self, pid, **kw):
        return {"pane_id": pid, "tab_id": pid.replace("p", "t"), "workspace_id": pid.split(":")[0], "label": kw.pop("label", ""),
                "focused": kw.pop("focused", False), "agent": kw.pop("agent", None), **kw}

    def setUp(self):
        super().setUp()
        self.procs = {}
        self.screens = {}
        self.tabs = {}
        self.patch(fleet, "pane_procs", lambda pane: self.procs.get(pane, ([], 1)))
        self.patch(fleet, "herdr_label", lambda kind, ident: self.tabs.get(ident, "x-t#1"))
        self.patch(fleet, "background_work", lambda pid, table=None: [])
        self.patch(fleet, "transcript", lambda sid: Path("/tx") if sid else None)
        self.patch(tidy, "screen", lambda pane, lines=60: self.screens.get(pane, []))
        self.patch(tidy, "chain_for", lambda cwd: "/chains/x/SESSION_LOG.md")
        self.tx = {"size": 1200000, "finished": "", "asks": False, "last_text": "done.", "last_prompt": "x"}
        self.patch(fleet, "parse", lambda path: dict(self.tx))

    def classify(self, p, sess=None, journal=None, claims=None):
        return tidy.classify(p, sess or {}, journal or {}, claims or [], {})

    def test_focused_and_protected_panes_are_never_closed(self):
        self.assertEqual(self.classify(self.pane("w1:p1", focused=True))["verdict"], "never")
        self.tabs["w1:t2"] = "helm-relay-t#1"
        it = self.classify(self.pane("w1:p2"))
        self.assertEqual((it["cls"], it["verdict"]), ("orchestrator", "never"))
        self.tabs["w1:t3"] = "coord#4"
        self.assertEqual(self.classify(self.pane("w1:p3"))["verdict"], "never")

    def test_live_claim_protects(self):
        claims = [{"task": "sleeper-restore-flags", "session": "claude f821e18a (herdr w2E:p1 helm-relay)"}]
        it = self.classify(self.pane("w2E:p1"), claims=claims)
        self.assertEqual((it["cls"], it["verdict"]), ("claimed", "never"))

    def test_popup_is_by_process_not_label(self):
        self.procs["w3:p1"] = ([{"pid": 5, "name": "collie", "argv0": "collie", "argv": ["collie"], "cwd": ""}], 1)
        self.assertEqual(self.classify(self.pane("w3:p1"))["cls"], "popup")
        self.procs["w3:p2"] = ([{"pid": 6, "name": "bash", "argv0": "bash", "argv": ["-bash"], "cwd": ""}], 6)
        self.screens["w3:p2"] = ["djbclark@mac:~$"]
        self.assertEqual(self.classify(self.pane("w3:p2", label="collie-doctor-p"))["cls"], "shell")

    def test_sleeping_stub_needs_a_replayable_journal_entry(self):
        stub = [{"pid": 9, "name": "Python", "argv0": "Python", "argv": ["/x/Python", "/y/herdr-sleeper", "stub", "w4:p1", "u", "/s"], "cwd": ""}]
        self.procs["w4:p1"] = (stub, 1)
        self.screens["w4:p1"] = ["💤 slept", "  press Enter to resume (ctrl-c leaves a plain shell)"]
        entry = {"uuid": "u-1", "kind": "claude", "phase": "asleep", "cwd": "/w", "argv": ["--dangerously-skip-permissions"], "title": "T"}
        it = self.classify(self.pane("w4:p1", agent="sleeper"), journal={"w4:p1": entry})
        self.assertEqual((it["cls"], it["verdict"]), ("sleeping", "close"))
        self.assertEqual(it["resume"], "cd /w && claude --dangerously-skip-permissions --resume u-1")
        self.assertEqual(it["journal"], entry)
        self.assertEqual(self.classify(self.pane("w4:p1", agent="sleeper"))["verdict"], "leave")
        self.assertEqual(self.classify(self.pane("w4:p1", agent="sleeper"), journal={"w4:p1": {**entry, "phase": "waking"}})["verdict"], "leave")
        self.assertEqual(self.classify(self.pane("w4:p1", agent="sleeper"), journal={"w4:p1": {**entry, "kind": "devin"}})["verdict"], "leave")

    def claude(self, pid, status="idle", screen_rows=("❯ ", "  ⏵⏵ bypass"), **kw):
        self.screens[pid] = list(screen_rows)
        return {pid: {"agent": "claude", "status": status, "sid": "s-1", "cwd": "/w", "transcript": "/tx", "title": "T",
                      "chan": ("herdr", pid), "argv": ["--dangerously-skip-permissions"], **kw}}

    def test_claude_states(self):
        p = self.pane("w5:p1", agent="claude")
        self.assertEqual(self.classify(p, self.claude("w5:p1"))["verdict"], "handoff-then-close")
        self.assertEqual(self.classify(p, self.claude("w5:p1", status="working"))["verdict"], "leave")
        it = self.classify(p, self.claude("w5:p1", status="busy-background", busy=["12 bash -c sleep"]))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("in flight", it["reason"])
        self.assertEqual(self.classify(p, self.claude("w5:p1", status="blocked"))["verdict"], "leave")
        it = self.classify(p, self.claude("w5:p1", screen_rows=("❯ /quit", "  ⏵⏵")))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("draft", it["reason"])
        it = self.classify(p, self.claude("w5:p1", screen_rows=("✻ Churned", "※ recap")))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("composer", it["reason"])
        self.tx["finished"] = "/handoff"
        it = self.classify(p, self.claude("w5:p1"))
        self.assertEqual((it["cls"], it["verdict"], it["handoff"]), ("claude-finished", "close", "/chains/x/SESSION_LOG.md"))
        self.assertEqual(it["resume"], "cd /w && claude --dangerously-skip-permissions --resume s-1")
        self.tx.update(finished="", asks=True, last_text="Want me to look at the diff?")
        self.assertEqual(self.classify(p, self.claude("w5:p1"))["cls"], "claude-question")
        self.tx.update(asks=False, last_text="", last_prompt="")
        self.assertIn("fresh session", self.classify(p, self.claude("w5:p1"))["reason"])

    def test_other_tuis(self):
        p = self.pane("w6:p1", agent="cursor")
        self.screens["w6:p1"] = ["Question 1 of 1", "  › [ ] (Recommended) refresh"]
        sess = {"w6:p1": {"agent": "cursor", "status": "idle", "sid": "091d", "cwd": "/a", "chan": ("herdr", "w6:p1")}}
        self.assertEqual(self.classify(p, sess)["verdict"], "leave")
        self.screens["w6:p1"] = ["done.", "> "]
        it = self.classify(p, sess)
        self.assertEqual((it["cls"], it["verdict"], it["resume"]), ("cursor", "close", "cd /a && cursor-agent --resume 091d"))
        sess["w6:p1"]["sid"] = None
        self.assertEqual(self.classify(p, sess)["verdict"], "leave")
        sess["w6:p1"].update(sid="x", agent="devin")
        self.assertIn("no verified resume", self.classify(p, sess)["reason"])
        sess["w6:p1"].update(agent="zcode", status="unknown")
        self.assertIn("cannot tell idle", self.classify(p, sess)["reason"])

    def test_shells(self):
        bash = [{"pid": 7, "name": "bash", "argv0": "bash", "argv": ["-bash"], "cwd": ""}]
        self.procs["w7:p1"] = (bash, 7)
        self.screens["w7:p1"] = ["djbclark@mac:~/src/stayturgid$"]
        self.assertEqual(self.classify(self.pane("w7:p1"))["verdict"], "close")
        self.screens["w7:p1"] = ["djbclark@mac:~/src/herdr$ claude"]
        self.assertIn("not a bare prompt", self.classify(self.pane("w7:p1"))["reason"])
        self.screens["w7:p1"] = ["djbclark@mac:~$"]
        self.procs["w7:p1"] = (bash + [{"pid": 8, "name": "vim", "argv0": "vim", "argv": ["vim"], "cwd": ""}], 7)
        self.assertIn("foreground process", self.classify(self.pane("w7:p1"))["reason"])
        self.procs["w7:p1"] = (None, None)
        self.assertIn("could not read", self.classify(self.pane("w7:p1"))["reason"])


class TestLedgerWrite(Patched):
    def test_append_sets_private_modes(self):
        tmp = tempfile.TemporaryDirectory()
        self.patch(fleet, "STATE_DIR", Path(tmp.name) / "sf")
        self.patch(fleet, "CLOSED", Path(tmp.name) / "sf" / "closed.jsonl")
        tidy.ledger_append({"id": "closed:t", "t": time.time()})
        self.assertEqual(oct(os.stat(fleet.STATE_DIR).st_mode & 0o777), "0o700")
        self.assertEqual(oct(os.stat(fleet.CLOSED).st_mode & 0o777), "0o600")
        self.assertEqual(fleet.closed_ledger()[0]["id"], "closed:t")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
