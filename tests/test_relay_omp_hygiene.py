#!/usr/bin/env python3
"""omp in relay.py's process walkers (audit A5/A6, 2026-11-03).

A6: `descends_from` (a Hermes caller's identity) and `turn_is_above` (its hop count) read the `ps` tree through fleet.PROC_AGENTS,
which has no omp, so an omp started inside a Hermes turn looked like "no agent" and inherited the turn's identity and hop count.
A5: `named_hits` matched the basename of `argv[:2]`, so `vim omp` counted as the omp TUI of its pane and could pin vim's pid.
"""
from __future__ import annotations

import unittest
import unittest.mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet = fb.relay, fb.fleet

BUN_CLI = "bun /Users/u/.bun/install/global/node_modules/@oh-my-pi/pi-coding-agent/dist/cli.js"
OMPS = ["omp", "/opt/homebrew/Cellar/omp/18.16.0/bin/omp --auto-approve", BUN_CLI, "bun /opt/x/bin/omp", "node /opt/x/bin/omp",
        "omp -p do the thing", "omp --mode rpc", "/opt/homebrew/Cellar/omp/18.16.0/bin/omp __omp_worker_text_predict"]
NOT_OMPS = ["vim omp", "less /tmp/omp", "bun /x/other/cli.js omp", "/usr/bin/grep omp notes.txt"]


def table(middle: str) -> dict[int, tuple[int, str]]:
    """A Hermes turn (pid 100, the relay that started it) with MIDDLE between it and the process under test (pid 102)."""
    return {100: (1, "python3 /x/relay.py hermes hi"), 101: (100, middle), 102: (101, "python3 /x/relay.py claude yo")}


class WalkerTests(unittest.TestCase):
    def test_an_omp_inside_a_turn_is_an_agent_boundary(self) -> None:
        for cmd in OMPS:
            with self.subTest(cmd=cmd):
                self.assertFalse(relay.descends_from(table(cmd), 102, 100), "an omp must not inherit the Hermes identity")
                self.assertFalse(relay.turn_is_above(table(cmd), 102, 100), "an omp must not inherit the hop count")

    def test_a_program_that_only_names_omp_is_not_a_boundary(self) -> None:
        for cmd in NOT_OMPS:
            with self.subTest(cmd=cmd):
                self.assertTrue(relay.descends_from(table(cmd), 102, 100))
                self.assertTrue(relay.turn_is_above(table(cmd), 102, 100))

    def test_other_agents_stay_boundaries_and_hermes_does_not(self) -> None:
        self.assertFalse(relay.descends_from(table("claude --resume abc"), 102, 100))
        self.assertTrue(relay.descends_from(table("python3 /x/bin/hermes -z hi"), 102, 100))


class NamedHitsTests(unittest.TestCase):
    ROW = {"agent": "omp", "id": "w2N:pZ", "chan": ("herdr", "w2N:pZ")}

    @staticmethod
    def proc(pid: int, name: str, *argv: str) -> dict:
        return {"pid": pid, "name": name, "argv0": argv[0] if argv else name, "argv": list(argv) or [name]}

    def test_a_program_with_omp_as_an_argument_is_not_the_tui(self) -> None:
        tui = self.proc(100, "bun", *BUN_CLI.split())
        for other in (self.proc(200, "vim", "vim", "omp"), self.proc(201, "less", "less", "omp"),
                      self.proc(202, "omp-bar", "bash", "-c", "omp"), self.proc(203, "node", "node", "/x/omp-helper.js", "omp")):
            with self.subTest(other=other["argv"]):
                self.assertEqual(relay.named_hits(self.ROW, [other, tui]), [tui])
                self.assertEqual(relay.named_hits(self.ROW, [other]), [])

    def test_the_tui_in_each_launch_form_is_a_hit(self) -> None:
        for argv in (("omp", "--auto-approve"), ("/opt/homebrew/bin/omp",), ("bun", "/x/bin/omp"), ("node", "/x/bin/omp"),
                     tuple(BUN_CLI.split())):
            with self.subTest(argv=argv):
                pr = self.proc(300, argv[0].rsplit("/", 1)[-1], *argv)
                self.assertEqual(relay.named_hits(self.ROW, [pr]), [pr])

    def test_agent_pid_pins_the_tui_not_a_vim_child_so_pid_check_stays_same(self) -> None:
        tui, vim = self.proc(100, "bun", *BUN_CLI.split()), self.proc(200, "vim", "vim", "omp")
        row = {**self.ROW, "pid": None, "sid": None}
        calls = {"procs": [vim, tui]}
        with unittest.mock.patch.object(relay, "herdr_pane_procs", lambda s: calls["procs"]):
            self.assertEqual(relay.agent_pid(row), 100)
            self.assertEqual(relay.pid_check(row, 100), "same")
            calls["procs"] = [tui]    # the editor exited
            self.assertEqual(relay.pid_check(row, 100), "same")

    def test_pi_is_an_exact_row_too(self) -> None:
        row = {"agent": "pi"}
        tui = self.proc(1, "pi", "pi", "--session", "x")
        via_node = self.proc(2, "node", "node", "/usr/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js")
        self.assertEqual(relay.named_hits(row, [tui, via_node, self.proc(3, "vim", "vim", "pi")]), [tui, via_node])
        self.assertFalse(relay.descends_from(table("pi --session x"), 102, 100))
        self.assertTrue(relay.descends_from(table("vim pi"), 102, 100))

    def test_an_omp_child_of_a_pi_pane_is_never_a_pi_hit_even_if_pis_own_test_accepts_it(self) -> None:
        """omp's package is `@oh-my-pi/pi-coding-agent`, named like Pi's: one label per process, omp tested first, whatever
        fleet._pi_executable accepts (another branch tightens it separately)."""
        pi_tui = self.proc(1, "pi", "pi", "--session", "x")
        omp_child = self.proc(2, "bun", *BUN_CLI.split())
        with unittest.mock.patch.object(fleet, "_pi_executable", lambda argv0, argv: True):    # a Pi test that cannot tell them apart
            self.assertEqual(relay.named_hits({"agent": "pi"}, [pi_tui, omp_child]), [pi_tui])
            self.assertEqual(relay.named_hits(self.ROW, [pi_tui, omp_child]), [omp_child])
            pi_row = {"agent": "pi", "id": "w2N:pZ", "chan": ("herdr", "w2N:pZ"), "pid": None, "sid": None}
            with unittest.mock.patch.object(relay, "herdr_pane_procs", lambda s: [omp_child, pi_tui]):
                self.assertEqual(relay.agent_pid(pi_row), 1)    # not 0 ("several match")

    def test_an_unreviewed_agent_keeps_the_older_argv_word_rule_until_its_row_is_added(self) -> None:
        """cursor has no row in fleet.EXACT_EXECUTABLES: its binary, a node-run script and (the known weakness a later PR flips by adding
        a row) a program with its name as the first or second word all still count. Adding the row must change this test, on purpose."""
        row = {"agent": "cursor"}
        direct = self.proc(1, "cursor-agent", "/Users/u/.local/bin/cursor-agent", "--yolo")
        via_node = self.proc(2, "node", "node", "/x/cursor-agent")
        vim = self.proc(3, "vim", "vim", "cursor-agent")
        self.assertNotIn("cursor", fleet.EXACT_EXECUTABLES)
        self.assertEqual(relay.named_hits(row, [direct, via_node, vim, self.proc(4, "bash", "bash", "-c", "x cursor-agent")]), [direct, via_node, vim])
        self.assertFalse(relay.descends_from(table("claude --resume abc"), 102, 100))


class TableTests(unittest.TestCase):
    def test_exact_agent_and_legacy_agents_split_the_table(self) -> None:
        self.assertEqual(sorted(fleet.EXACT_EXECUTABLES), ["omp", "pi"])
        self.assertEqual(fleet.exact_agent("", ["bun", "/x/bin/omp"]), "omp")
        self.assertIsNone(fleet.exact_agent("", ["vim", "omp"]))
        self.assertEqual(fleet.legacy_agents(["vim", "/x/claude"]), ["claude"])
        self.assertEqual(fleet.legacy_agents(["omp", "pi", "vim"]), [])  # exact rows are never read by the older word rule


if __name__ == "__main__":
    unittest.main()
