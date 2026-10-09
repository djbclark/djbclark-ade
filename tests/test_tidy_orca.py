#!/usr/bin/env python3
"""Tests for herdr-tidy's Orca host mode (skills/herdr-tidy/tidy.py, `--host orca`, `/orca-tidy`).

No live Orca, ps or herdr: `run` is replaced by a dispatcher keyed on the argv shapes tidy.py uses
(`orca terminal list|show|read|send|close`, `orca worktree ps`, `ps eww -ax`), the hook ledger points at
a temp file, and fleet's session/process/transcript readers are stubbed at the module boundary.
Fixture JSON mirrors the shapes verified live on Orca 1.4.219 (2026-10-08).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(ROOT / "session-finder"))
sys.path.insert(0, str(ROOT / "herdr-tidy"))

import fleet
import tidy

H1 = "term_aaaaaaaa11111111222222223333333344444444"   # tabA:leaf1, claude, focused in the fixture
H2 = "term_bbbbbbbb11111111222222223333333344444444"   # tabB:leaf1, plain shell
H3 = "term_cccccccc11111111222222223333333344444444"   # orphaned: never listed
H4 = "term_dddddddd11111111222222223333333344444444"   # tabC:leafX, codex, in a worktree that is not active
H5 = "term_aaaaaaaa99999999222222223333333344444444"   # shares H1's 13-char prefix: ambiguity fixture
ENV_KEYS = ("TIDY_HOST", "ORCA_PANE_KEY", "TERM_PROGRAM", "HERDR_PANE_ID")


def ok(result):
    return 0, json.dumps({"ok": True, "result": result})


def err(code, message="", rc=1):
    return rc, json.dumps({"ok": False, "error": {"code": code, "message": message}})


def terminal(handle, tab, leaf, wt, title, path="/w", orphaned=False):
    return {"handle": handle, "tabId": tab, "leafId": leaf, "worktreeId": wt, "worktreePath": path, "title": title,
            "orphaned": orphaned, "connected": not orphaned, "preview": ""}


def leaf(handle, tab, leaf_id, active=False):
    return {"type": "terminal", "handle": handle, "tabId": tab, "leafId": leaf_id, "active": active}


class OrcaBase(unittest.TestCase):
    """HOST=orca, every outside call dispatched to in-memory fixtures; module attributes and env restored."""

    def setUp(self):
        self._saved, self._env = [], {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.patch(tidy, "HOST", "orca")
        self.patch(tidy, "ORCA_LAST_STATUS", Path(self.tmp.name) / "last-status.json")
        self.patch(fleet, "STATE_DIR", Path(self.tmp.name) / "sf")
        self.patch(fleet, "CLOSED", Path(self.tmp.name) / "sf" / "closed.jsonl")
        self.patch(fleet, "run", self.fake_run)
        self.patch(tidy, "run", self.fake_run)              # tidy binds fleet.run at import: patch both names
        self.patch(fleet, "sessions", lambda include_shell=False: list(self.sessions))
        self.patch(fleet, "proc_table", lambda: dict(self.table))
        self.patch(fleet, "claims", lambda: list(self.claims))
        self.patch(fleet, "parse", lambda path: dict(self.tx))
        self.patch(fleet, "transcript", lambda sid: Path("/tx") if sid else None)
        self.patch(fleet, "alive", lambda pid: self.alive_seq.pop(0) if self.alive_seq else False)
        self.patch(fleet, "background_work", lambda pid, table=None: list(self.kids))
        self.patch(tidy, "chain_for", lambda cwd: "/chains/x/SESSION_LOG.md")
        self.patch(time, "sleep", lambda s: None)
        # fixtures: the live shapes of 2026-10-08
        self.terminals = [terminal(H1, "tabA", "leaf1", "wt1", "✳ Fable 5.1 codebase"),
                          terminal(H2, "tabB", "leaf1", "wt1", "Terminal 1"),
                          terminal(H3, "tabX", "leaf9", "wt1", "gone", orphaned=True),
                          terminal(H4, "tabC", "leafX", "wt2", "◐ Battery locate sound", path="/q")]
        self.layouts = [
            {"worktreeId": "wt1", "root": {"type": "group", "activeTabId": "tabA", "tabs": [
                {"tabId": "tabA", "title": "✳ Fable 5.1 codebase", "activeLeafId": "leaf1",
                 "panes": {"type": "split", "direction": "row", "children": [
                     leaf(H1, "tabA", "leaf1", True),
                     {"type": "split", "direction": "column", "children": [leaf("term_x1", "tabA", "leaf2"), leaf("term_x2", "tabA", "leaf3")]}]}},
                {"tabId": "tabB", "title": "Terminal 1", "activeLeafId": "leaf1", "panes": leaf(H2, "tabB", "leaf1", True)}]}},
            {"worktreeId": "wt2", "root": {"type": "group", "activeTabId": "tabC", "tabs": [
                {"tabId": "tabC", "title": "◐ Battery locate sound", "activeLeafId": "leafX", "panes": leaf(H4, "tabC", "leafX", True)}]}}]
        self.worktrees = [
            {"worktreeId": "wt1", "path": "/w", "isActive": True, "liveTerminalCount": 2,
             "agents": [{"paneKey": "tabA:leaf1", "state": "working", "agentType": "claude", "lastAssistantMessage": "…"}]},
            {"worktreeId": "wt2", "path": "/q", "isActive": False, "liveTerminalCount": 1,
             "agents": [{"paneKey": "tabC:leafX", "state": "done", "agentType": "codex", "lastAssistantMessage": "done"}]},
            {"worktreeId": "wt3", "path": "/hibernated", "isActive": False, "liveTerminalCount": 0,
             "agents": [{"paneKey": "tabZ:leafZ", "state": "done", "agentType": "claude", "lastAssistantMessage": "stale"}]}]
        self.last_status = {"version": 1, "authorityCommitments": {}, "entries": {
            "tabA:leaf1": {"source": "hook", "providerSession": {"id": "sid-1", "transcriptPath": "/tx1"}, "payload": {"state": "working"}},
            "tabB:leaf1": {"source": "hook", "providerSession": {"id": "sid-stale", "transcriptPath": "/tx-stale"}, "payload": {"state": "done"}}}}
        self.ps_text = ("  100 bash --rcfile /x/rc ORCA_PANE_KEY=tabA:leaf1 TERM=xterm-256color\n"
                        "  101 claude --dangerously-skip-permissions ORCA_PANE_KEY=tabA:leaf1 HOME=/Users/d\n"
                        "  300 bash --rcfile /x/rc ORCA_PANE_KEY=tabB:leaf1\n"
                        "  400 bash --rcfile /x/rc ORCA_PANE_KEY=tabC:leafX\n"
                        "  401 codex ORCA_PANE_KEY=tabC:leafX\n"
                        "  500 /usr/libexec/other-daemon TERM=dumb\n"
                        "garbage line without a pid\n")
        self.table = {100: (1, "bash --rcfile /x/rc"), 101: (100, "claude --dangerously-skip-permissions"),
                      300: (1, "bash --rcfile /x/rc"), 400: (1, "bash --rcfile /x/rc"), 401: (400, "codex")}
        self.sessions, self.claims, self.kids, self.alive_seq = [], [], [], []
        self.tx = {"size": 1200000, "finished": "", "asks": False, "last_text": "done.", "last_prompt": "x"}
        self.reads, self.waits, self.show_fail = {}, {}, set()
        self.list_fail = self.ps_fail = self.wps_fail = self.close_survives = False
        self.send_accept = True
        self.calls, self.sent, self.closed = [], [], []

    def tearDown(self):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def patch(self, mod, name, value):
        self._saved.append((mod, name, getattr(mod, name)))
        setattr(mod, name, value)

    def write_status(self):
        tidy.ORCA_LAST_STATUS.write_text(json.dumps(self.last_status))

    @staticmethod
    def _opt(args, flag):
        return args[args.index(flag) + 1] if flag in args else None

    def fake_run(self, *cmd, timeout=10):
        self.calls.append(cmd)
        if cmd[0] == "ps":
            self.assertEqual(cmd[1:4], ("eww", "-ax", "-o"), "only `ps eww -ax` prints other processes' environments")
            return (127, "") if self.ps_fail else (0, self.ps_text)
        if cmd[0] != "orca":
            return 127, ""
        self.assertIn("--json", cmd)
        args = [c for c in cmd[1:] if c != "--json"]
        if args[:2] == ["terminal", "list"]:
            if self.list_fail:
                return err("runtime_unavailable", "orca runtime is not running")
            r = {"terminals": list(self.terminals)}
            if "--include-visual-layouts" in args:
                r["visualLayouts"] = self.layouts
            return ok(r)
        if args[:2] == ["worktree", "ps"]:
            return err("runtime_unavailable") if self.wps_fail else ok({"worktrees": self.worktrees})
        h = self._opt(args, "--terminal")
        if args[:2] == ["terminal", "show"]:
            if h in self.show_fail:
                return err("terminal_not_found")
            return ok({"terminal": {"handle": h, "agentWait": self.waits.get(h), "agentIdentity": {}}})
        if args[:2] == ["terminal", "read"]:
            self.assertIn("--screen", args)
            if h not in self.reads:
                return ok({"terminal": {"handle": h, "tail": [], "source": "screen-unavailable"}})
            tail, draft = self.reads[h]
            t = {"handle": h, "tail": list(tail), "source": "screen"}
            if draft is not None:
                t["draft"] = draft
            return ok({"terminal": t})
        if args[:2] == ["terminal", "send"]:
            self.sent.append((h, self._opt(args, "--text"), self._opt(args, "--wait-submit")))
            self.assertIn("--enter", args)
            send = {"accepted": self.send_accept, "prompt": {"stages": ["input_accepted", "turn_started"] if self.send_accept else []}}
            rc, out = ok({"send": send})
            return (0 if self.send_accept else 1), out
        if args[:2] == ["terminal", "close"]:
            self.closed.append(tuple(args[2:]))
            if not self.close_survives:
                self.terminals = [t for t in self.terminals if t["handle"] != h]
            return ok({"closed": True})
        raise AssertionError(f"unexpected orca call {args}")

    # pane records shaped like orca_terminals() output
    def pane(self, handle=H1, key="tabA:leaf1", **kw):
        p = {"pane_id": handle, "tab_id": key.split(":")[0], "leaf_id": key.split(":")[1], "pane_key": key, "workspace_id": "wt1",
             "cwd": "/w", "label": "", "tab_label": "Some tab", "terminal_title_stripped": "Some tab", "focused": False,
             "tab_panes": 1, "agent": None, "agent_status": None, "agent_session": None, "transcript": None, "self": False,
             "pids": [], "host": "orca"}
        p.update(kw)
        return p

    def sess(self, handle=H1, agent="claude", status="idle", **kw):
        s = {"id": "x", "agent": agent, "status": status, "sid": "s-1", "cwd": "/w", "transcript": "/tx", "title": "T",
             "chan": ("orca", handle), "argv": ["--dangerously-skip-permissions"], "pid": 101, "host": "orca", "name": ""}
        s.update(kw)
        return {handle: s}

    def classify(self, p, sess=None, claims=None):
        return tidy.classify(p, sess or {}, {}, claims if claims is not None else self.claims, self.table)


class TestDetectHost(OrcaBase):
    def test_explicit_wins(self):
        os.environ["ORCA_PANE_KEY"] = "t:l"
        self.assertEqual(tidy.detect_host("herdr"), "herdr")
        self.assertEqual(tidy.detect_host("orca"), "orca")

    def test_env_override_then_orca_markers_then_herdr(self):
        self.assertEqual(tidy.detect_host("auto"), "herdr")
        os.environ["TERM_PROGRAM"] = "Orca"
        self.assertEqual(tidy.detect_host(), "orca")
        os.environ.pop("TERM_PROGRAM")
        os.environ["ORCA_PANE_KEY"] = "tabA:leaf1"
        self.assertEqual(tidy.detect_host(), "orca")
        os.environ["TIDY_HOST"] = "herdr"
        self.assertEqual(tidy.detect_host(), "herdr")
        os.environ["TIDY_HOST"] = "bogus"
        self.assertEqual(tidy.detect_host(), "orca")


class TestOrcaTabs(OrcaBase):
    def test_leaf_count_over_nested_splits_and_active_flags(self):
        tabs = tidy._orca_tabs(self.layouts)
        self.assertEqual(set(tabs), {"tabA", "tabB", "tabC"})
        self.assertEqual(tabs["tabA"]["n"], 3)
        self.assertEqual(tabs["tabB"]["n"], 1)
        self.assertTrue(tabs["tabA"]["is_active_tab"])
        self.assertFalse(tabs["tabB"]["is_active_tab"])
        self.assertTrue(tabs["tabC"]["is_active_tab"])        # active in its own (inactive) worktree
        self.assertEqual(tabs["tabA"]["active_leaf"], "leaf1")
        self.assertEqual((tabs["tabA"]["worktree"], tabs["tabC"]["worktree"]), ("wt1", "wt2"))
        self.assertEqual(tabs["tabA"]["title"], "✳ Fable 5.1 codebase")   # raw: the caller strips the glyph

    def test_empty_or_missing_layouts(self):
        self.assertEqual(tidy._orca_tabs(None), {})
        self.assertEqual(tidy._orca_tabs([]), {})


class TestOrcaEnvMap(OrcaBase):
    def test_pane_key_to_pids(self):
        m = tidy.orca_env_map()
        self.assertEqual(m, {"tabA:leaf1": [100, 101], "tabB:leaf1": [300], "tabC:leafX": [400, 401]})

    def test_ps_failure_is_empty(self):
        self.ps_fail = True
        self.assertEqual(tidy.orca_env_map(), {})


class TestOrcaRead(OrcaBase):
    def test_rows_and_draft(self):
        self.reads[H1] = (["done.   ", "❯ close it", "  ⏵⏵ bypass "], "close it")
        self.assertEqual(tidy.orca_read(H1), (["done.", "❯ close it", "  ⏵⏵ bypass"], "close it"))
        self.reads[H1] = (["❯ "], None)
        self.assertEqual(tidy.orca_read(H1), (["❯"], None))

    def test_unavailable_or_failed_is_none_none(self):
        self.assertEqual(tidy.orca_read(H2), (None, None))              # source: screen-unavailable
        self.list_fail = True
        self.patch(tidy, "run", lambda *a, **k: (1, "not json"))
        self.assertEqual(tidy.orca_read(H1), (None, None))


class TestOrcaStatusMerge(OrcaBase):
    def merge(self, a, b):
        return tidy.orca_status_merge({"agent_status": a}, {"status": b})

    def test_working_and_blocked_win(self):
        self.assertEqual(self.merge("working", "idle"), "working")
        self.assertEqual(self.merge("idle", "working"), "working")
        self.assertEqual(self.merge("idle", "blocked"), "blocked")
        self.assertEqual(self.merge("blocked", "idle"), "blocked")
        self.assertEqual(self.merge("idle", "busy-background"), "busy-background")

    def test_idle_needs_agreement_or_silence(self):
        self.assertEqual(self.merge("idle", "idle"), "idle")
        self.assertEqual(self.merge("idle", "unknown"), "idle")
        self.assertEqual(self.merge("unknown", "idle"), "idle")
        self.assertEqual(self.merge(None, "idle"), "idle")
        self.assertEqual(self.merge("unknown", "unknown"), "unknown")
        self.assertEqual(self.merge(None, None), "unknown")
        self.assertEqual(self.merge("idle", "shell"), "shell")


class TestOrcaTerminals(OrcaBase):
    def test_join(self):
        self.write_status()
        os.environ["ORCA_PANE_KEY"] = "tabB:leaf1"
        terms = tidy.orca_terminals()
        self.assertEqual(set(terms), {H1, H2, H4})                     # the orphaned H3 is skipped
        t1, t2, t4 = terms[H1], terms[H2], terms[H4]
        self.assertTrue(t1["focused"])                                 # active leaf of the active tab of an isActive worktree
        self.assertFalse(t2["focused"])                                # not the active tab
        self.assertFalse(t4["focused"])                                # active leaf, but its worktree is not active
        self.assertEqual((t1["pane_key"], t1["tab_panes"], t1["tab_label"]), ("tabA:leaf1", 3, "Fable 5.1 codebase"))
        self.assertEqual(t4["tab_label"], "Battery locate sound")
        self.assertEqual((t1["agent"], t1["agent_status"], t1["agent_session"], t1["transcript"]),
                         ("claude", "working", {"value": "sid-1"}, "/tx1"))
        self.assertEqual((t4["agent"], t4["agent_status"]), ("codex", "idle"))
        self.assertEqual((t2["agent"], t2["agent_status"], t2["agent_session"], t2["transcript"]), (None, None, None, None))
        self.assertTrue(t2["self"])
        self.assertFalse(t1["self"])
        self.assertEqual((t1["pids"], t2["pids"], t4["pids"]), ([100, 101], [300], [400, 401]))
        self.assertEqual((t1["host"], t1["cwd"], t1["workspace_id"], t4["cwd"]), ("orca", "/w", "wt1", "/q"))

    def test_focus_is_unknown_without_one_active_worktree_or_the_tab(self):
        self.worktrees[1]["isActive"] = True                          # two active worktrees
        self.assertEqual({h: t["focused"] for h, t in tidy.orca_terminals().items()}, {H1: None, H2: None, H4: None})
        self.worktrees[1]["isActive"] = False
        self.wps_fail = True                                           # worktree ps failed
        terms = tidy.orca_terminals()
        self.assertEqual({t["focused"] for t in terms.values()}, {None})
        self.assertEqual((terms[H1]["agent"], terms[H1]["agent_status"]), (None, None))
        self.wps_fail = False
        self.layouts[0]["root"]["tabs"].pop(1)                         # tabB missing from the layouts
        terms = tidy.orca_terminals()
        self.assertEqual((terms[H1]["focused"], terms[H2]["focused"], terms[H4]["focused"]), (True, None, False))

    def test_tab_panes_needs_layout_and_list_to_agree_on_one(self):
        self.terminals.append(terminal(H5, "tabB", "leaf2", "wt1", "Terminal 2"))   # listed, not in the layout
        terms = tidy.orca_terminals()
        self.assertEqual((terms[H1]["tab_panes"], terms[H2]["tab_panes"], terms[H5]["tab_panes"], terms[H4]["tab_panes"]),
                         (3, 2, 2, 1))

    def test_list_failure_is_none(self):
        self.list_fail = True
        self.assertIsNone(tidy.orca_terminals())
        self.assertIsNone(tidy.orca_live_handles())

    def test_ps_failure_and_missing_ledger_fail_soft(self):
        self.ps_fail = True                                            # no ledger file written either
        terms = tidy.orca_terminals()
        self.assertEqual(terms[H1]["pids"], [])
        self.assertIsNone(terms[H1]["agent_session"])
        self.assertEqual(terms[H1]["agent"], "claude")

    def test_live_handles_keep_orphans(self):
        # an orphaned terminal still exists to Orca (hazard #14719: a close may leave the TUI behind), so the
        # post-close existence check counts it; only the inventory skips orphans
        self.assertEqual(tidy.orca_live_handles(), {H1, H2, H3, H4})
        self.assertTrue(tidy.pane_exists(H3))
        self.assertFalse(tidy.pane_exists("term_nope"))
        self.list_fail = True
        self.assertTrue(tidy.pane_exists("term_nope"))                 # cannot list → assume it is still there


class TestClassifyOrca(OrcaBase):
    def test_self_focused_protected(self):
        it = self.classify({**self.pane(), "self": True})
        self.assertEqual((it["cls"], it["verdict"], it["host"], it["pane_key"]), ("self", "never", "orca", "tabA:leaf1"))
        it = self.classify(self.pane(focused=True))
        self.assertEqual((it["cls"], it["verdict"]), ("focused", "never"))
        os.environ["HERDR_PANE_ID"] = H1                               # herdr's own self marker means nothing here
        self.assertNotEqual(self.classify(self.pane(agent=None, pids=[]))["cls"], "self")

    def test_focus_unknown_is_never(self):
        it = self.classify(self.pane(focused=None, pids=[100, 101]), self.sess())
        self.assertEqual((it["cls"], it["verdict"]), ("focused", "never"))
        self.assertIn("cannot tell which terminal the operator is in", it["reason"])
        tidy.HOST = "herdr"                                             # herdr panes always carry the flag
        self.assertNotEqual(self.classify(self.pane(focused=None, pids=[]))["cls"], "focused")

    def test_orca_agent_without_a_fleet_session_is_left(self):
        p = self.pane(H4, "tabC:leafX", agent="codex", agent_status="idle", pids=[400, 401])
        self.reads[H4] = (["done.", "› "], None)
        it = self.classify(p)
        self.assertEqual((it["cls"], it["agent"], it["verdict"]), ("codex", "codex", "leave"))
        self.assertIn("matched no session", it["reason"])

    def test_protected_tab_title_glyph_stripped_end_to_end(self):
        self.terminals[0]["title"] = "◐ helm-relay"
        self.layouts[0]["root"]["tabs"][0]["title"] = "◐ helm-relay"
        self.layouts[0]["root"]["activeTabId"] = "tabB"                # so H1 is not the focused pane
        p = tidy.orca_terminals()[H1]
        self.assertEqual(p["tab_label"], "helm-relay")
        it = self.classify(p, self.sess())
        self.assertEqual((it["cls"], it["verdict"]), ("orchestrator", "never"))
        self.assertEqual(self.classify(self.pane(tab_label="coord"))["verdict"], "never")

    def test_claim_by_pane_key(self):
        claims = [{"task": "slice-3", "session": "codex (orca tabA:leaf1)"}]
        it = self.classify(self.pane(pids=[100, 101]), self.sess(), claims)
        self.assertEqual((it["cls"], it["verdict"]), ("claimed", "never"))

    def test_claude_working_by_orca_hook_state(self):
        p = self.pane(agent="claude", agent_status="working", pids=[100, 101])
        it = self.classify(p, self.sess(status="idle"))                 # fleet says idle, Orca says working: working wins
        self.assertEqual((it["cls"], it["verdict"], it["reason"], it["status"]), ("claude", "leave", "working", "working"))

    def test_claude_idle_orca_draft(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101])
        self.reads[H1] = (["❯ close the two panes", "  ⏵⏵"], "close the two panes")
        it = self.classify(p, self.sess())
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("Orca draft", it["reason"])
        self.reads[H1] = (['❯ Try "fix typecheck errors"', "  ⏵⏵"], 'Try "fix typecheck errors"')
        self.assertEqual(self.classify(p, self.sess())["verdict"], "handoff-then-close")   # placeholder is not a draft

    def test_claude_idle_agent_wait(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101])
        self.reads[H1] = (["❯ ", "  ⏵⏵"], None)
        self.waits[H1] = {"kind": "permission", "prompt": "Allow Bash?"}
        it = self.classify(p, self.sess())
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("agentWait", it["reason"])
        del self.waits[H1]
        self.show_fail.add(H1)
        it = self.classify(p, self.sess())
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("terminal show failed", it["reason"])

    def test_claude_idle_screen_unavailable(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101])
        it = self.classify(p, self.sess())                              # no reads[H1]: screen-unavailable
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("screen-unavailable", it["reason"])

    def test_claude_idle_finished_closes_with_resume(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101], tab_panes=2)
        self.reads[H1] = (["❯ ", "  ⏵⏵ bypass"], None)
        self.tx["finished"] = "/handoff"
        it = self.classify(p, self.sess())
        self.assertEqual((it["cls"], it["verdict"], it["handoff"]), ("claude-finished", "close", "/chains/x/SESSION_LOG.md"))
        self.assertEqual(it["resume"], "cd /w && claude --dangerously-skip-permissions --resume s-1")
        self.assertEqual((it["host"], it["pane_key"], it["tab_panes"], it["pid"]), ("orca", "tabA:leaf1", 2, 101))
        self.tx.update(finished="", asks=True, last_text="Shall I continue?")
        self.assertEqual(self.classify(p, self.sess())["cls"], "claude-question")

    def test_claude_idle_no_finish_is_handoff_then_close(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101])
        self.reads[H1] = (["❯ ", "  ⏵⏵ bypass"], None)
        it = self.classify(p, self.sess())
        self.assertEqual((it["cls"], it["verdict"]), ("claude-idle", "handoff-then-close"))
        self.reads[H1] = (["✻ Churned", "※ recap"], None)              # composer not on screen
        it = self.classify(p, self.sess())
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("orca terminal switch --terminal " + H1, it["reason"])

    def test_claude_transcript_from_orca_ledger_when_fleet_has_none(self):
        p = self.pane(agent="claude", agent_status="idle", pids=[100, 101], transcript="/tx1", agent_session={"value": "sid-1"})
        self.reads[H1] = (["❯ "], None)
        self.tx["finished"] = "/quit"
        it = self.classify(p, self.sess(transcript=None, sid=None))
        self.assertEqual((it["cls"], it["sid"]), ("claude-finished", "sid-1"))

    def test_codex_with_app_server_child_is_left(self):
        self.table[402] = (401, "codex app-server --listen /tmp/sock")
        p = self.pane(H4, "tabC:leafX", agent="codex", agent_status="idle", pids=[400, 401, 402], cwd="/q")
        self.reads[H4] = (["done.", "› "], None)
        it = self.classify(p, self.sess(H4, agent="codex", sid="c-1", cwd="/q", pid=401, argv=[]))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("23833", it["reason"])
        del self.table[402]
        it = self.classify(p, self.sess(H4, agent="codex", sid="c-1", cwd="/q", pid=401, argv=[]))
        self.assertEqual((it["cls"], it["verdict"], it["resume"]), ("codex", "close", "cd /q && codex resume c-1"))

    def test_cursor_idle_with_prompt_line_closes_with_resume(self):
        self.table[401] = (400, "cursor-agent --yolo")
        p = self.pane(H4, "tabC:leafX", agent="cursor", agent_status="idle", pids=[400, 401], cwd="/a")
        self.reads[H4] = (["done.", "› "], None)
        it = self.classify(p, self.sess(H4, agent="cursor", sid="091d", cwd="/a", pid=401, argv=[]))
        self.assertEqual((it["cls"], it["verdict"], it["resume"]), ("cursor", "close", "cd /a && cursor-agent --resume 091d"))
        self.assertIn("Orca reported no draft", it["reason"])
        self.reads[H4] = (["Question 1 of 1", "› [ ] refresh"], None)
        self.assertIn("waiting on an answer", self.classify(p, self.sess(H4, agent="cursor", sid="091d", cwd="/a", pid=401))["reason"])
        self.reads[H4] = (["done.", "› "], "y")                        # Orca read an unsent draft
        self.assertIn("Orca draft", self.classify(p, self.sess(H4, agent="cursor", sid="091d", cwd="/a", pid=401))["reason"])
        self.reads[H4] = (["done.", "› "], None)
        self.assertIn("session id unknown", self.classify(p, self.sess(H4, agent="cursor", sid=None, cwd="/a", pid=401))["reason"])

    def test_grok_idle_is_left_no_resume_form(self):
        self.table[401] = (400, "grok")
        p = self.pane(H4, "tabC:leafX", agent="grok", agent_status="idle", pids=[400, 401])
        self.reads[H4] = (["❯ "], None)
        it = self.classify(p, self.sess(H4, agent="grok", sid="g-1", pid=401))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("no verified resume form for grok", it["reason"])

    def test_tui_without_prompt_glyph_is_left(self):
        p = self.pane(H4, "tabC:leafX", agent="codex", agent_status="idle", pids=[400, 401])
        self.reads[H4] = (["done.", "> "], None)
        it = self.classify(p, self.sess(H4, agent="codex", sid="c-1", pid=401))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("no ❯ › » prompt line", it["reason"])

    def test_tui_status_unknown_is_left(self):
        p = self.pane(H4, "tabC:leafX", agent="zcode", agent_status=None, pids=[400, 401])
        it = self.classify(p, self.sess(H4, agent="zcode", status="unknown", sid="z", pid=401))
        self.assertIn("Orca cannot tell idle from working", it["reason"])

    def test_shells(self):
        p = self.pane(H2, "tabB:leaf1", pids=[300])
        self.reads[H2] = (["djbclark@mac:~/src/core-simjson$"], None)
        it = self.classify(p)
        self.assertEqual((it["cls"], it["verdict"], it["agent"]), ("shell", "close", "shell"))
        self.reads[H2] = (["djbclark@mac:~$ claude"], None)
        self.assertIn("not a bare prompt", self.classify(p)["reason"])
        self.reads[H2] = (["djbclark@mac:~$"], None)
        self.kids = ["301 sleep 600"]
        self.assertIn("child processes", self.classify(p)["reason"])
        self.kids = []
        self.table[301] = (300, "vim notes.md")
        it = self.classify(self.pane(H2, "tabB:leaf1", pids=[300, 301]))
        self.assertIn("foreground process", it["reason"])
        self.assertIn("vim", it["reason"])

    def test_no_pids_for_the_pane_key_is_left(self):
        it = self.classify(self.pane(H2, "tabB:leaf1", pids=[]))
        self.assertEqual(it["verdict"], "leave")
        self.assertIn("ps shows no process carrying this pane key", it["reason"])
        it = self.classify(self.pane(H2, "tabB:leaf1", pids=[999]))    # pid gone from the table since the env scan
        self.assertIn("no process carrying", it["reason"])

    def test_acp_launch_in_orca_is_left(self):
        s = {"host": "acp", "status": "idle", "id": "L1", "agent": "claude", "chan": ("orca", H1), "title": "acp"}
        it = self.classify(self.pane(pids=[100, 101]), {H1: s})
        self.assertEqual((it["cls"], it["verdict"]), ("acp", "leave"))
        self.assertIn("launch.py close L1", it["reason"])
        self.assertIn("orca terminal close --terminal " + H1, it["reason"])
        self.assertNotIn("close_cmd", it)
        s["status"] = "working"
        self.assertEqual(self.classify(self.pane(pids=[100, 101]), {H1: s})["reason"], "ACP launch L1 is working")

    def test_no_sleeper_or_popup_classes_from_orca_titles(self):
        p = self.pane(H2, "tabB:leaf1", pids=[300], tab_label="💤 old session", terminal_title_stripped="collie-doctor")
        self.reads[H2] = (["djbclark@mac:~$"], None)
        self.assertEqual(self.classify(p)["cls"], "shell")


class TestResolve(OrcaBase):
    def setUp(self):
        super().setUp()
        self.panes = [self.pane(H1, "tabA:leaf1"), self.pane(H2, "tabB:leaf1"), self.pane(H5, "tabD:leaf1")]

    def test_full_handle_pane_key_prefix(self):
        self.assertIs(tidy.resolve(H1, self.panes), self.panes[0])
        self.assertIs(tidy.resolve("tabB:leaf1", self.panes), self.panes[1])
        self.assertIs(tidy.resolve("term_bbbb", self.panes), self.panes[1])
        self.assertIs(tidy.resolve(H5[:16], self.panes), self.panes[2])
        self.assertIsNone(tidy.resolve("term_zzzz", self.panes))
        self.assertIsNone(tidy.resolve("term_", self.panes))            # shorter than 6 chars never prefix-matches

    def test_ambiguous_prefix_exits(self):
        with self.assertRaises(SystemExit) as cm:
            tidy.resolve("term_aaaaaaaa", self.panes)
        self.assertIn("matches 2 terminals", str(cm.exception))

    def test_herdr_mode_is_exact_only(self):
        tidy.HOST = "herdr"
        self.assertIsNone(tidy.resolve("term_bbbb", self.panes))
        self.assertIs(tidy.resolve(H1, self.panes), self.panes[0])


class TestInventoryOrca(OrcaBase):
    def test_sessions_join_by_channel_or_stable_pane_key(self):
        self.write_status()
        by_chan = {"id": "a", "agent": "claude", "status": "working", "chan": ("orca", H1), "pid": 101, "host": "orca"}
        stale = {"id": "b", "agent": "codex", "status": "idle", "chan": None, "pid": 401, "host": "orca"}   # dead handle in its env
        elsewhere = {"id": "c", "agent": "claude", "status": "idle", "chan": ("herdr", "w1:p1"), "pid": 777, "host": "herdr"}
        self.sessions = [by_chan, stale, elsewhere]
        panes, sess, journal, claims, table = tidy.inventory()
        self.assertEqual({p["pane_id"] for p in panes}, {H1, H2, H4})
        self.assertEqual(set(sess), {H1, H4})
        self.assertIs(sess[H4], stale)
        self.assertEqual(journal, {})                                  # no sleeper journal in Orca
        self.assertIs(table[101][0], 100)

    def test_list_failure_exits(self):
        self.list_fail = True
        with self.assertRaises(SystemExit) as cm:
            tidy.inventory()
        self.assertIn("orca terminal list failed", str(cm.exception))


class TestClosePaneOrca(OrcaBase):
    def setUp(self):
        super().setUp()
        self.exits = []
        self.patch(tidy, "orca_send", self.fake_send)
        self.it = {"pane": H1, "tab": "tabA", "cls": "claude-finished", "pid": 101, "pane_key": "tabA:leaf1"}

    def fake_send(self, handle, text, wait=15):
        self.exits.append((handle, text, wait))
        return (self.send_accept, {} if self.send_accept else {"code": "input_not_accepted"})

    def test_exit_then_close_tab_when_only_pane(self):
        self.alive_seq = [True, True, False]
        rc, msg = tidy.close_pane(self.it, only_pane=True, tab_panes=1)
        self.assertEqual((rc, msg), (0, "tab closed"))
        self.assertEqual(self.exits, [(H1, "/exit", 5)])
        self.assertEqual(self.closed, [("--terminal", H1, "--tab")])

    def test_close_terminal_only_when_tab_has_other_panes(self):
        self.alive_seq = [False]
        rc, msg = tidy.close_pane(self.it, only_pane=False, tab_panes=3)
        self.assertEqual((rc, msg), (0, "terminal closed"))
        self.assertEqual(self.closed, [("--terminal", H1)])

    def test_exit_not_accepted_leaves_terminal_open(self):
        self.send_accept = False
        rc, msg = tidy.close_pane(self.it, True, 1)
        self.assertEqual(rc, 1)
        self.assertIn("not accepted", msg)
        self.assertIn("input_not_accepted", msg)
        self.assertEqual(self.closed, [])

    def test_pid_still_alive_leaves_terminal_open(self):
        self.patch(fleet, "alive", lambda pid: True)
        rc, msg = tidy.close_pane(self.it, True, 1)
        self.assertEqual(rc, 1)
        self.assertIn("still alive", msg)
        self.assertEqual(self.closed, [])

    def test_question_class_also_exits_first_and_shell_does_not(self):
        self.alive_seq = [False]
        tidy.close_pane({**self.it, "cls": "claude-question"}, True, 1)
        self.assertEqual(len(self.exits), 1)
        tidy.close_pane({"pane": H2, "tab": "tabB", "cls": "shell", "pid": None}, True, 1)
        self.assertEqual(len(self.exits), 1)
        self.assertEqual(self.closed[-1], ("--terminal", H2, "--tab"))

    def test_close_error_is_reported(self):
        self.alive_seq = [False]
        self.patch(tidy, "orca_call", lambda *a, **k: (False, {"code": "terminal_not_found", "message": "gone"}))
        rc, msg = tidy.close_pane(self.it, True, 1)
        self.assertEqual((rc, msg), (1, "terminal_not_found: gone"))

    def test_send_prompt_and_agent_idle_now_dispatch_to_orca(self):
        self.assertTrue(tidy.send_prompt({"pane": H1}, "/handoff"))
        self.assertEqual(self.exits[-1], (H1, "/handoff", 15))
        self.assertFalse(tidy.agent_idle_now({"pane_key": "tabA:leaf1"}))   # worktree ps says working
        self.assertTrue(tidy.agent_idle_now({"pane_key": "tabC:leafX"}))    # done → idle
        self.assertFalse(tidy.agent_idle_now({"pane_key": "tabZ:none"}))    # no agent row → None → not idle


class TestCmdCloseDryRun(OrcaBase):
    def setUp(self):
        super().setUp()
        self.layouts[0]["root"]["activeTabId"] = "tabA"                # H2 (tabB) is not the focused pane
        self.reads[H2] = (["$ ls", "SKILL.md tidy.py", "djbclark@mac:~/src/core-simjson$"], None)

    def dry_run(self, pane):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tidy.cmd_close(argparse.Namespace(pane=pane, why="idle shell", resume="", dry_run=True))
        lines = buf.getvalue().splitlines()
        return rc, json.loads(lines[0]), lines[1]

    def test_entry_has_host_and_pane_key(self):
        rc, entry, tail = self.dry_run(H2)
        self.assertEqual(rc, 0)
        self.assertEqual((entry["host"], entry["pane_key"], entry["pane"], entry["tab"], entry["cls"]),
                         ("orca", "tabB:leaf1", H2, "tabB", "shell"))
        self.assertTrue(entry["id"].startswith("closed:"))
        self.assertTrue(entry["id"].endswith("-" + H2[:18]))           # id uses the handle's first 18 chars
        self.assertEqual(entry["tab_label"], "Terminal 1")
        self.assertEqual(entry["why"], "idle shell; bare prompt, no process; the ledger keeps the screen tail")
        self.assertIn("orca pane", entry["by"])
        self.assertNotIn("screen", entry)
        self.assertEqual(tail, "dry run: would close tab tabB")
        self.assertEqual(self.closed, [])
        self.assertFalse(fleet.CLOSED.exists())

    def test_pane_key_argument_resolves(self):
        rc, entry, _tail = self.dry_run("tabB:leaf1")
        self.assertEqual(entry["pane"], H2)

    def test_refuses_non_close_verdicts(self):
        self.reads[H2] = (["djbclark@mac:~$ claude"], None)
        with self.assertRaises(SystemExit) as cm:
            self.dry_run(H2)
        self.assertIn("refused", str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            self.dry_run(H1)                                           # the focused pane
        self.assertIn("focused", str(cm.exception))
        self.worktrees[1]["isActive"] = True                           # focus unknown everywhere → refused too
        with self.assertRaises(SystemExit) as cm:
            self.dry_run(H2)
        self.assertIn("cannot tell", str(cm.exception))

    def test_claude_finished_dry_run_says_after_exit(self):
        self.layouts[0]["root"]["activeTabId"] = "tabB"
        self.worktrees[0]["agents"][0]["state"] = "done"
        self.write_status()
        self.sessions = [self.sess()[H1]]
        self.reads[H1] = (["❯ ", "  ⏵⏵ bypass"], None)
        self.tx["finished"] = "/handoff"
        rc, entry, tail = self.dry_run(H1)
        self.assertEqual((entry["cls"], entry["resume"]), ("claude-finished", "cd /w && claude --dangerously-skip-permissions --resume s-1"))
        self.assertEqual(entry["id"], f"{entry['id'].rsplit('-', 1)[0]}-{H1[:18]}")
        self.assertEqual(tail, f"dry run: would close pane {H1} (after /exit)")   # tabA has 3 panes
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
