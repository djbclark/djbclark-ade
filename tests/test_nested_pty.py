#!/usr/bin/env python3
"""Kiro's nested PTY: herdr shows only the outer shim; session-finder must find the inner foreground TUI or fail closed.

Fixtures are private `ps -axo pid=,ppid=,pgid=,tpgid=,tty=,comm=` text; nothing touches herdr, ps or a live process.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))

import fleet
import nested_pty

SHIM = {"pid": 100, "name": "bash (kiro-cli-", "argv": ["bash (kiro-cli-term)"], "argv0": "bash (kiro-cli-term)", "cwd": "/w"}
# outer shim 100 on ttys014; inner bash 200 on ttys017; goose 300 is the inner tty's foreground group
BASE = {
    100: "100 1 100 100 ttys014 bash (kiro-cli-term)",
    200: "200 100 200 300 ttys017 /bin/bash",
    300: "300 200 300 300 ttys017 /opt/homebrew/bin/goose",
}


def ps(**over):
    rows = dict(BASE)
    for k, v in over.items():
        pid = int(k[1:])
        if v is None:
            rows.pop(pid, None)
        else:
            rows[pid] = v
    return nested_pty.parse_ps("\n".join(rows.values()) + "\n")


def found(rows, procs=None, shell_pid=100):
    r = nested_pty.inner_foreground([SHIM] if procs is None else procs, shell_pid, rows)
    return None if r is None else [x["pid"] for x in r]


class TestInnerForeground(unittest.TestCase):
    def test_outer_shim_resolves_to_inner_foreground_group(self):
        self.assertEqual(found(ps()), [300])

    def test_every_member_of_the_foreground_group_is_returned(self):
        rows = ps(p301="301 300 300 300 ttys017 node", p302="302 301 300 300 ttys017 node")
        self.assertEqual(found(rows), [302, 301, 300])

    def test_background_daemon_and_other_tty_children_are_not_taken(self):
        rows = ps(p310="310 300 310 300 ttys017 goosed", p400="400 100 100 100 ttys014 helper")
        self.assertEqual(found(rows), [300])

    def test_shell_only_inner_has_no_foreground_tui(self):
        self.assertIsNone(found(ps(p200="200 100 200 200 ttys017 /bin/bash", p300="300 200 300 200 ttys017 goose")))

    def test_two_nested_ptys_are_ambiguous(self):
        self.assertIsNone(found(ps(p201="201 100 201 201 ttys018 /bin/zsh")))

    def test_non_shell_child_on_a_distinct_tty_is_ambiguous(self):
        self.assertIsNone(found(ps(p201="201 100 201 201 ttys018 python3")))

    def test_inner_without_a_tty(self):
        self.assertIsNone(found(ps(p200="200 100 200 300 ?? /bin/bash")))

    def test_inner_on_the_outer_tty_is_not_nested(self):
        self.assertIsNone(found(ps(p200="200 100 200 300 ttys014 /bin/bash", p300="300 200 300 300 ttys014 goose")))

    def test_stale_foreground_pgid_without_a_live_leader(self):
        self.assertIsNone(found(ps(p300=None)))

    def test_leader_on_another_tty_is_refused(self):
        self.assertIsNone(found(ps(p300="300 200 300 300 ttys099 goose")))

    def test_group_member_outside_the_inner_lineage_is_refused(self):
        self.assertIsNone(found(ps(p500="500 1 300 300 ttys017 intruder")))

    def test_unknown_outer_marker(self):
        self.assertIsNone(found(ps(), procs=[dict(SHIM, argv0="bash", argv=["bash"])]))

    def test_outer_that_is_not_the_only_foreground_process(self):
        self.assertIsNone(found(ps(), procs=[SHIM, dict(SHIM, pid=101)]))

    def test_stale_shell_pid(self):
        self.assertIsNone(found(ps(), shell_pid=999))
        self.assertIsNone(found(ps(p100=None)))

    def test_outer_not_foreground_of_its_own_tty(self):
        self.assertIsNone(found(ps(p100="100 1 100 777 ttys014 bash (kiro-cli-term)")))

    def test_malformed_ps_lines_are_skipped(self):
        rows = nested_pty.parse_ps("garbage\n1 2 3\nx y z w tty comm\n" + "\n".join(BASE.values()))
        self.assertEqual(found(rows), [300])


class TestPaneProcs(unittest.TestCase):
    """fleet.pane_procs end to end with herdr and ps replaced at fleet's own boundary."""

    def setUp(self):
        self._saved = (fleet.herdr_json, fleet.run, fleet._pid_alive, nested_pty.PROC_ROOT)
        nested_pty.PROC_ROOT = "/nonexistent-proc-root"     # fixture pids must never read a real /proc entry

    def tearDown(self):
        fleet.herdr_json, fleet.run, fleet._pid_alive, nested_pty.PROC_ROOT = self._saved

    def drive(self, procs, text, rc=0, argv="/opt/homebrew/bin/goose session", alive=()):
        """ARGV is the `ps -o command=` text for every pid, or {pid: text} ('' = unreadable); ALIVE the pids still alive."""
        fleet.herdr_json = lambda *a: {"process_info": {"shell_pid": 100, "foreground_processes": procs}}
        fleet._pid_alive = lambda pid: pid in alive

        def run(*cmd, timeout=10):
            if cmd[:2] == ("ps", "-axo"):
                return rc, text
            if cmd[:3] == ("ps", "-ww", "-o"):
                t = argv.get(int(cmd[-1]), "") if isinstance(argv, dict) else argv
                return (0, t + "\n") if t else (1, "")
            raise AssertionError(cmd)
        fleet.run = run
        return fleet.pane_procs("w1:p1")

    def test_goose_behind_the_shim_is_a_tui(self):
        procs, shell_pid = self.drive([SHIM], "\n".join(BASE.values()))
        self.assertEqual(shell_pid, 100)
        self.assertEqual({"pid", "name", "argv", "argv0", "cwd"}, set(procs[0]))
        self.assertEqual(fleet._tui_of(procs)[:2], ("goose", 300))

    def test_mastracode_behind_the_shim_is_a_tui(self):
        procs, _ = self.drive([SHIM], "\n".join(BASE.values()), argv="node /x/bin/mastracode --mode auto")
        self.assertEqual(fleet._tui_of(procs)[:2], ("mastra", 300))

    def test_member_that_exited_after_the_snapshot_keeps_the_leader(self):
        text = "\n".join(BASE.values()) + "\n301 300 300 300 ttys017 node"
        procs, _ = self.drive([SHIM], text, argv={300: "/opt/homebrew/bin/goose session"}, alive={300})
        self.assertEqual([p["pid"] for p in procs], [300])
        self.assertEqual(fleet._tui_of(procs)[:2], ("goose", 300))

    def test_leader_that_exited_after_the_snapshot_leaves_herdrs_answer(self):
        procs, _ = self.drive([SHIM], "\n".join(BASE.values()), argv="")
        self.assertEqual(procs, [SHIM])

    def test_unreadable_argv_of_a_live_member_is_unknown(self):
        text = "\n".join(BASE.values()) + "\n301 300 300 300 ttys017 node"
        got = self.drive([SHIM], text, argv={300: "/opt/homebrew/bin/goose session"}, alive={300, 301})
        self.assertEqual(got, (None, 100))
        self.assertEqual(self.drive([SHIM], "\n".join(BASE.values()), argv="", alive={300}), (None, 100))

    def test_ps_failure_timeout_or_empty_success_on_a_shim_is_unknown(self):
        good = "\n".join(BASE.values())
        for text, rc in ((good, 1), (good, 127), ("", 0), ("", 127), ("garbage\n", 0)):
            self.assertEqual(self.drive([SHIM], text, rc=rc), (None, 100))
        self.assertEqual(fleet._tui_of(None), (None, None, None, None))

    def test_absent_or_ambiguous_chain_keeps_herdrs_plain_shell_answer(self):
        for text in ("\n".join(BASE.values()) + "\n201 100 201 201 ttys018 zsh", "100 1 100 100 ttys014 bash (kiro-cli-term)"):
            procs, shell_pid = self.drive([SHIM], text)
            self.assertEqual((procs, shell_pid), ([SHIM], 100))
            self.assertEqual(fleet._tui_of(procs), (None, None, None, None))

    def test_ordinary_pane_does_not_run_ps(self):
        proc = {"pid": 7, "name": "claude", "argv": ["claude"], "argv0": "claude", "cwd": ""}
        procs, _ = self.drive([proc], "")
        self.assertEqual([p["pid"] for p in procs], [7])

    def test_goose_other_subcommands_are_not_the_tui(self):
        for argv in (["goose", "acp"], ["goose", "web"], ["node", "other.js"], ["goose"]):
            self.assertEqual(fleet._tui_of([{"pid": 1, "argv0": argv[0], "argv": argv, "name": "", "cwd": ""}])[0], None)


if __name__ == "__main__":
    unittest.main()
