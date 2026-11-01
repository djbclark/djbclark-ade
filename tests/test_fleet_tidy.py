#!/usr/bin/env python3
"""Tests for the safe-close pieces of session-finder/fleet.py and helm/helm.py (the herdr-tidy skill was retired from djbclark-ade 2026-10-31; fleet.py still reads its close ledger).

Everything that touches herdr, ps, transcripts or the sleeper journal is stubbed at the module
boundary, so these run without herdr and never read the live journal or ledger.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))
sys.path.insert(0, str(ROOT / "helm"))

import fleet
import helm


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
    def test_cline_cached_tui_is_agent_not_background_work(self):
        wrapper = {"pid": 20, "argv0": "node", "argv": ["node", "/opt/lib/cline/bin/cline", "--tui"]}
        native = {"pid": 21, "argv0": "/opt/lib/cline/bin/.cline", "argv": ["/opt/lib/cline/bin/.cline", "--tui", "--thinking", "low"]}
        agent, pid, _, _ = fleet._tui_of([wrapper, native])
        self.assertEqual((agent, pid), ("cline", 21))
        row = {"pid": pid, "status": "unknown"}
        fleet.mark_busy(row, {20: (1, "node /opt/lib/cline/bin/cline --tui"), 21: (20, "/opt/lib/cline/bin/.cline --tui")})
        self.assertEqual(row["status"], "unknown")
        fleet.mark_busy(row, {21: (20, "/opt/lib/cline/bin/.cline --tui"), 22: (21, "python /tmp/real-work.py")})
        self.assertEqual(row["status"], "busy-background")

    def test_cline_native_service_and_one_shot_are_not_tuis(self):
        for args in [["hub", "start"], ["core", "daemon"], ["--acp"], ["--headless", "task"], ["--zen"], ["--version"], ["--tui", "--acp"]]:
            with self.subTest(args=args):
                proc = {"pid": 21, "argv0": "/opt/lib/cline/bin/.cline", "argv": ["/opt/lib/cline/bin/.cline", *args]}
                self.assertEqual(fleet._tui_of([proc]), (None, None, None, None))

    def test_cline_cache_preference_requires_matching_launcher(self):
        wrapper = {"pid": 20, "argv0": "node", "argv": ["node", "/other/cline/bin/cline", "--tui"]}
        native = {"pid": 21, "argv0": "/opt/lib/cline/bin/.cline", "argv": ["/opt/lib/cline/bin/.cline", "--tui"]}
        self.assertEqual(fleet._tui_of([wrapper, native])[:2], ("cline", 20))

    def test_cline_installed_symlink_still_selects_native_tui(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "lib/cline/bin"
            package.mkdir(parents=True)
            (package / "cline").touch()
            link = root / "cline"
            link.symlink_to(package / "cline")
            wrapper = {"pid": 20, "argv0": "node", "argv": ["node", str(link), "--tui"]}
            binary = str(package / ".cline")
            native = {"pid": 21, "argv0": binary, "argv": [binary, "--tui"]}
            self.assertEqual(fleet._tui_of([wrapper, native])[:2], ("cline", 21))

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


class TestHermesNativeEntry(Patched):
    """The installed Hermes entry shim runs ONE python process, `python -I -c <bootstrap> ARGS`, with no `hermes` in argv; herdr does not
    detect it (2026-10-25). The bootstrap here is a portable stand-in carrying the three marker lines of the real one."""

    BOOT = "\n".join(["import os, re, sys", "sys.path.insert(0, '/opt/example/hermes-agent')", "from hermes_cli.main import main",
                      "sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])", "sys.exit(main())", ""])

    def proc(self, *args: str, boot: str | None = None, argv0: str = "/opt/example/bin/python3") -> list[dict]:
        return [{"pid": 77, "name": "python3.14", "argv0": argv0, "argv": [argv0, "-I", "-c", boot or self.BOOT, *args], "cwd": ""}]

    def test_the_entry_shim_is_a_native_hermes_tui_with_its_session_id(self):
        self.assertEqual(fleet._tui_of(self.proc("--yolo"))[:3], ("hermes", 77, None))
        self.assertEqual(fleet._tui_of(self.proc())[:2], ("hermes", 77))
        self.assertEqual(fleet._tui_of(self.proc("--model", "m1", "chat", "--yolo"))[:2], ("hermes", 77))
        self.assertEqual(fleet._tui_of(self.proc("--yolo", "--resume", "20261025_000000_abc123"))[:3],
                         ("hermes", 77, "20261025_000000_abc123"))

    def test_python_that_merely_mentions_hermes_is_not_a_tui(self):
        mention = "import sys\nprint('hermes_cli.main import main; hermes-agent')\n"
        no_exit = "\n".join(self.BOOT.splitlines()[:3] + [""])    # path and import, never the exit through main
        commented = self.BOOT.replace("from hermes_cli.main import main", "# from hermes_cli.main import main")
        other_path = self.BOOT.replace("/opt/example/hermes-agent", "/opt/example/other-agent")
        for label, procs in {"a print": self.proc(boot=mention), "no exit": self.proc(boot=no_exit), "commented import": self.proc(boot=commented),
                             "another checkout": self.proc(boot=other_path),
                             "no -I": [{**self.proc()[0], "argv": ["/opt/example/bin/python3", "-c", self.BOOT]}],
                             "script argument": [{**self.proc()[0], "argv": ["/opt/example/bin/python3", "/opt/example/hermes-agent/run.py"]}],
                             "not python": [{**self.proc()[0], "argv": ["/bin/sh", "-I", "-c", self.BOOT]}]}.items():
            with self.subTest(label):
                self.assertEqual(fleet._tui_of(procs), (None, None, None, None))

    def test_services_tools_and_single_shot_runs_of_the_shim_are_not_a_tui(self):
        for args in (("gateway", "run"), ("--yolo", "gateway"), ("--model", "m1", "acp"), ("mcp", "serve"), ("cron", "list"), ("-z", "hi"),
                     ("--oneshot=hi",), ("chat", "-q", "hi"), ("--version",), ("--print-runtime-command",), ("--", "gateway")):
            with self.subTest(args):
                self.assertEqual(fleet._tui_of(self.proc(*args)), (None, None, None, None))

    def test_an_undetected_native_hermes_pane_becomes_a_status_unknown_row(self):
        self.patch(fleet, "pane_procs", lambda pane: (self.proc("--yolo"), 70))
        self.patch(fleet, "herdr_label", lambda kind, ident: ident)
        self.patch(fleet, "_where", None)
        pane = {"pane_id": "w1:p1", "cwd": "/x", "tab_id": "w1:t1", "workspace_id": "w1"}
        tuis, shells = fleet._pane_only([pane], set())
        self.assertEqual((len(tuis), shells), (1, []))
        self.assertEqual({k: tuis[0][k] for k in ("id", "agent", "host", "chan", "status", "undetected", "pid")},
                         {"id": "w1:p1", "agent": "hermes", "host": "herdr", "chan": ("herdr", "w1:p1"), "status": "unknown",
                          "undetected": True, "pid": 77})


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


if __name__ == "__main__":
    unittest.main()
