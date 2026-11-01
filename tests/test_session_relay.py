#!/usr/bin/env python3
"""session-finder's reach to running Claude sessions (2026-10-11).

  * fleet.claude_reach names SendMessage only when the session has a messaging socket, and always names
    relay.py as the fallback: a workflow sub-agent's ListAgents may not list cross-session peers
    (q-shizuku relay: "No agent named 'shizukutendcf-e7' is reachable").
  * relay.py refuses the sessions keys must not reach, and types text + Enter through herdr.
  * fleet matches the Claude Code inside an ACP launch by session id, so a detached (--host none) launch
    is one session, not two.
  * fleet.sessions(include_marked=False) leaves --mark'ed launches out (for helm, hcom trial 6g).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SF = ROOT / "skills" / "session-finder"
sys.path.insert(0, str(SF))

import fleet  # noqa: E402  # pyright: ignore[reportMissingImports]

_spec = importlib.util.spec_from_file_location("relay", SF / "relay.py")
assert _spec and _spec.loader
relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay)
# main() records unsent messages; keep the tests' records out of the real ledger
relay.UNSENT = Path(tempfile.mkdtemp(prefix="relay-test-")) / "relay-unsent.json"


MSG = "[relay from tester] hello there friend"    # what relay types: the sender header, then the text (A1, 2026-10-25)


def sess(**kw: Any) -> dict[str, Any]:
    return fleet._rec(**{"id": "abcd1234", "agent": "claude", "name": "peer-1", "sid": "abcd1234-0000", "status": "working",
                         "chan": ("herdr", "w1:p1"), **kw})


class TestReach(unittest.TestCase):
    def test_sendmessage_only_with_a_live_socket_and_relay_always(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            sock = Path(t) / "1.sock"
            sock.touch()
            r = fleet.claude_reach({"name": "peer-1", "messagingSocketPath": str(sock)}, "abcd1234-ffff")
            self.assertTrue(r.startswith("SendMessage to peer-1"))
            self.assertIn("relay.py abcd1234", r)
            r = fleet.claude_reach({"name": "peer-1", "messagingSocketPath": str(Path(t) / "gone.sock")}, "abcd1234-ffff")
            self.assertNotIn("SendMessage to", r)
            self.assertIn("relay.py abcd1234", r)
            self.assertIn("no messaging socket", fleet.claude_reach({"name": "x"}, "abcd1234-ffff"))


class TestInnerClaudeBySid(unittest.TestCase):
    def test_registry_entry_with_a_launch_session_id_merges_into_the_launch(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "sessions").mkdir()
            sid = "11111111-2222-3333-4444-555555555555"
            _ = (Path(t) / "sessions" / f"{os.getpid()}.json").write_text(
                json.dumps({"pid": os.getpid(), "sessionId": sid, "name": "inner", "status": "waiting", "cwd": t}))
            launch = fleet._rec(id="L1", host="acp", status="working", sid=sid)
            old = fleet.CLAUDE
            fleet.CLAUDE = Path(t)
            try:
                out = fleet._claude_sessions({}, set(), set(), {}, {sid: launch})
            finally:
                fleet.CLAUDE = old
            self.assertEqual(out, [], "the inner Claude was listed as a second session")
            self.assertEqual(launch["pid"], os.getpid())
            self.assertEqual(launch["underlying"]["name"], "inner")
            self.assertEqual(launch["status"], "blocked")    # its AskUserQuestion shows on the launch


class TestMarkedHidden(unittest.TestCase):
    def test_include_marked_false_drops_marked_launches(self) -> None:
        saved = {k: getattr(fleet, k) for k in ("herdr_json", "_launched", "_claude_sessions", "_other_herdr", "_pane_only",
                                                 "_proc_scan", "_hermes_gateway", "_paseo_rows", "proc_table", "mark_busy", "ancestors")}
        try:
            fleet.herdr_json = lambda *a: {}
            fleet._launched = lambda used: [fleet._rec(id="L", host="acp", mark="test"), fleet._rec(id="M", host="acp")]
            fleet._claude_sessions = lambda *a, **k: []
            fleet._other_herdr = lambda *a: []
            fleet._pane_only = lambda *a: ([], [])
            fleet._proc_scan = lambda *a: []
            fleet._hermes_gateway = lambda: []
            fleet._paseo_rows = lambda *a: []
            fleet.proc_table = lambda: {}
            fleet.mark_busy = lambda *a: None
            fleet.ancestors = lambda: set()
            self.assertEqual([s["id"] for s in fleet.sessions()], ["L", "M"])
            self.assertEqual([s["id"] for s in fleet.sessions(include_marked=False)], ["M"])
        finally:
            for k, v in saved.items():
                setattr(fleet, k, v)


class TestRelayRules(unittest.TestCase):
    def test_refusals(self) -> None:
        cases = {"this session": sess(self=True), "launch.py reply": sess(host="acp"), "finished": sess(finished="/handoff"),
                 "no terminal channel": sess(chan=None, where="Ghostty"), "blocked": sess(status="blocked"),
                 "only idle ones": sess(agent="codex", status="working")}
        for want, s in cases.items():
            why = relay.refusal(s)
            self.assertIsNotNone(why, want)
            self.assertIn(want, why or "", want)

    def test_working_claude_and_idle_codex_are_allowed(self) -> None:
        self.assertIsNone(relay.refusal(sess()))       # Claude Code queues it
        self.assertIsNone(relay.refusal(sess(status="busy-background")))
        self.assertIsNone(relay.refusal(sess(agent="codex", status="idle")))

    def test_find_by_id_name_or_sid_prefix(self) -> None:
        ss = [sess(), sess(id="ffff0000", name="other", sid="ffff0000-9999")]
        self.assertEqual([s["id"] for s in relay.find("peer-1", ss)], ["abcd1234"])
        self.assertEqual([s["id"] for s in relay.find("ffff0000-99", ss)], ["ffff0000"])
        self.assertEqual(relay.find("nope", ss), [])

    PID = "d08a31c6-a58b-418d-b66c-ca765e0d2e68"
    SID = "c795c830-5d18-4251-acce-971e1d34dd82"

    def twice(self) -> list[dict[str, Any]]:
        """One Paseo session listed twice (2026-11-01: two live claude processes of one resumed session), beside two other sessions."""
        row = dict(id="c795c830", name="history", sid=self.SID, host="paseo", chan=("paseo", self.PID), paseo=self.PID, status="idle")
        return [sess(**row, pid=68029), sess(id="aaaa1111", name="a", sid="aaaa1111-0001", paseo="aaaa1111-1111-4111-8111-111111111111",
                                             host="paseo", chan=("paseo", "aaaa1111-1111-4111-8111-111111111111")),
                sess(**row, pid=95867)]

    def test_find_full_paseo_id_or_sid_of_a_listed_twice_session_is_one_recipient(self) -> None:
        for ident in (self.PID, self.SID, "c795c830", self.PID[:8], self.SID[:12]):
            got = relay.find(ident, self.twice())
            self.assertEqual([(s["id"], s["pid"]) for s in got], [("c795c830", 68029)], ident)

    def test_find_same_session_collapses_to_the_row_with_a_channel_and_keeps_self(self) -> None:
        bare = sess(id="c795c830", name="h", sid=self.SID, paseo=self.PID, chan=None, host="paseo")
        good = sess(id="c795c830", name="h", sid=self.SID, paseo=self.PID, chan=("paseo", self.PID), host="paseo")
        self.assertIs(relay.find(self.PID, [bare, good])[0], good)
        me = dict(good, self=True)
        self.assertIs(relay.find(self.SID, [good, me])[0], me)    # still refused later by hard_stop: never sent to this very session

    def test_find_short_prefix_of_two_different_sessions_is_still_ambiguous(self) -> None:
        p1, p2 = "d08a31c6-a58b-418d-b66c-ca765e0d2e68", "d08a31c6-ffff-4fff-8fff-ffffffffffff"
        ss = [sess(id="c795c830", sid=self.SID, paseo=p1, chan=("paseo", p1), host="paseo"),
              sess(id="c795c830", sid=self.SID, paseo=p1, chan=("paseo", p1), host="paseo"),
              sess(id="bbbb2222", name="b", sid="bbbb2222-0002", paseo=p2, chan=("paseo", p2), host="paseo")]
        self.assertEqual(sorted(s["id"] for s in relay.find("d08a31c6", ss)), ["bbbb2222", "c795c830"])

    def test_find_row_bridging_a_sid_and_a_paseo_id_joins_both_into_one_session(self) -> None:
        a = sess(id="c795c830", sid=self.SID, paseo=None, chan=None, host="terminal")
        b = sess(id="c795c830", sid=None, paseo=self.PID, chan=("paseo", self.PID), host="paseo")
        c = sess(id="c795c830", sid=self.SID, paseo=self.PID, chan=("paseo", self.PID), host="paseo")
        self.assertEqual(len(relay.find("c795c830", [a, b, c])), 1)

    def test_claude_registry_with_two_live_processes_of_one_session_gives_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "sessions").mkdir()
            for pid, upd in ((68029, 100), (95867, 200)):
                _ = (Path(t) / "sessions" / f"{pid}.json").write_text(
                    json.dumps({"pid": pid, "sessionId": self.SID, "name": "h", "status": "idle", "cwd": t, "updatedAt": upd}))
            _ = (Path(t) / "sessions" / "7.json").write_text(
                json.dumps({"pid": 7, "sessionId": "eeeeeeee-0000", "name": "other", "status": "idle", "cwd": t}))
            saved = {k: getattr(fleet, k) for k in ("CLAUDE", "alive", "transcript", "_where")}
            try:
                fleet.CLAUDE, fleet.alive, fleet.transcript, fleet._where = Path(t), (lambda pid: True), (lambda sid: None), None
                out = fleet._claude_sessions({}, set(), {68029})    # the OLD process is this one's ancestor
            finally:
                for k, v in saved.items():
                    setattr(fleet, k, v)
            self.assertEqual([(s["sid"], s["pid"]) for s in out], [(self.SID, 95867), ("eeeeeeee-0000", 7)])    # the newest entry wins
            self.assertTrue(out[0]["self"])    # any process of the session being an ancestor makes it this session
            self.assertFalse(out[1]["self"])

    def test_find_by_herdr_pane_reaches_a_launch_row_and_prefers_the_unfinished_one(self) -> None:
        # a launch row has its pane only in chan; a reused pane lists the finished first launch too (2026-10-25)
        launch1 = sess(id="2026-a", name="baton", sid="2026-a", host="acp", chan=("herdr", "w2N:p14"), finished="done")
        launch2 = sess(id="2026-b", name="baton", sid="2026-b", host="acp", chan=("herdr", "w2N:p14"))
        tui = sess(id="tui00001", name="tui", pane="w2N:p9", chan=("herdr", "w2N:p9"))
        ss = [launch1, launch2, tui]
        self.assertEqual([s["id"] for s in relay.find("w2N:p14", ss)], ["2026-b"])
        self.assertEqual([s["id"] for s in relay.find("w2N:p9", ss)], ["tui00001"])
        self.assertEqual([s["id"] for s in relay.find("2026-a", ss)], ["2026-a"])    # an exact id still finds a finished one
        self.assertEqual([s["id"] for s in relay.find("w2N:p14", [launch1])], ["2026-a"])    # nothing else: still reported

    def test_find_by_herdr_agent_name_goes_through_herdr(self) -> None:
        ss = [sess(id="2026-b", chan=("herdr", "w2N:p14")), sess(id="other", name="x", chan=("herdr", "w2N:p9"))]
        calls: list[tuple[str, ...]] = []

        def fake_herdr_json(*args: str) -> dict[str, Any]:
            calls.append(args)
            return {"agent": {"pane_id": "w2N:p14"}} if args == ("agent", "get", "sf-succ-1") else {}

        real = relay.fleet.herdr_json
        relay.fleet.herdr_json = fake_herdr_json
        try:
            self.assertEqual([s["id"] for s in relay.find_herdr_agent("sf-succ-1", ss)], ["2026-b"])
            self.assertEqual(relay.find_herdr_agent("no-such-agent", ss), [])
        finally:
            relay.fleet.herdr_json = real
        self.assertEqual(calls[0], ("agent", "get", "sf-succ-1"))

    def test_type_line_through_herdr_submits_one_atomic_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            calls = Path(t) / "calls"
            fake = Path(t) / "herdr"
            _ = fake.write_text(f"#!/bin/bash\nprintf '%s\\n' \"$*\" >> {calls}\n")
            fake.chmod(0o755)
            old = relay.HERDR
            relay.HERDR = str(fake)
            try:
                self.assertTrue(relay.type_line(("herdr", "w1:p1"), "hello there"))
            finally:
                relay.HERDR = old
            self.assertEqual(calls.read_text().splitlines(),
                             ["agent prompt w1:p1 hello there"])

    def run_main(self, drafts: list[str], scr: str, transcript: Path | None = None) -> tuple[int, list[str]]:
        """main() against one fake working Claude session; DRAFTS are successive input-box reads."""
        enters: list[str] = []
        relay.UNSENT.unlink(missing_ok=True)    # an earlier test's leftover would make this a retry of it
        reads = iter(drafts)
        saved = (relay.fleet.sessions, relay.type_line, relay.draft, relay.press_enter, relay.screen,
                 relay.RETRY_AFTER, sys.argv)
        relay.fleet.sessions = lambda: [sess(transcript=str(transcript) if transcript else None)]
        relay.type_line = lambda chan, text: True
        relay.draft = lambda chan: next(reads, "")
        saved_rows, relay.rows_below = relay.rows_below, lambda chan: ""
        saved_box, relay.box_read = relay.box_read, screen_of_hooks()
        relay.press_enter = lambda chan: enters.append("enter") or True
        relay.screen = lambda chan, lines=20: scr
        relay.RETRY_AFTER = 0
        sys.argv = ["relay.py", "peer-1", "hello there friend", "--wait", "3"]
        try:
            # the header names the sender: any real session identity outranks a declared RELAY_SENDER_NAME (sender_name), so the
            # runner's own (a Hermes or Paseo session, 2026-10-25: header `hermes xxxx`, the typed text never matched MSG) is cut off
            with mock.patch.dict(os.environ, {"RELAY_SENDER_NAME": "tester"}), mock.patch.object(relay, "own_paseo_id", lambda: ""):
                for k in ("PASEO_AGENT_ID", "HERDR_PANE_ID", "CLAUDE_CODE_SESSION_ID", "HERMES_SESSION_ID", "RELAY_SENDER"):
                    os.environ.pop(k, None)
                rc = relay.main()
        finally:
            (relay.fleet.sessions, relay.type_line, relay.draft, relay.press_enter, relay.screen,
             relay.RETRY_AFTER, sys.argv) = saved
            relay.rows_below = saved_rows
            relay.box_read = saved_box
        return rc, enters

    def test_text_left_in_the_box_gets_another_enter(self) -> None:
        # first read is the pre-send draft check (empty), then the text sits in the box once, then it is gone
        rc, enters = self.run_main(["", MSG, ""], "Press up to edit queued messages")
        self.assertEqual(rc, 0)
        self.assertEqual(enters, ["enter"])

    def test_queue_hint_is_not_delivery_while_the_text_is_still_in_the_box(self) -> None:
        rc, enters = self.run_main([""] + [MSG] * 50, "Press up to edit queued messages")
        self.assertEqual(rc, 1)
        self.assertEqual(enters, ["enter"] * relay.ENTER_RETRIES)


def screen_of_hooks():
    """A box_read that draws the screen the tests' relay.draft / relay.rows_below hooks describe (box_text reads once)."""
    def read(chan):
        rows = relay.rows_below(chan)
        return "\n".join(["\u2500" * 40, "\u276f " + relay.draft(chan), *([f"  {rows}"] if rows else []),
                         "\u2500" * 40, "  ? for shortcuts"])
    return read


class TestStuckInBox(unittest.TestCase):
    def check(self, box: str, text: str) -> bool:
        orig = relay.draft, relay.rows_below, relay.box_read
        relay.draft, relay.rows_below = (lambda chan: box), (lambda chan: "")
        relay.box_read = screen_of_hooks()
        try:
            return relay.stuck_in_box(("herdr", "w1:p1"), text)
        finally:
            relay.draft, relay.rows_below, relay.box_read = orig

    def test_own_text_still_in_box(self) -> None:
        self.assertTrue(self.check("From the Paseo session: hello  there", "From the Paseo session: hello there"))

    def test_collapsed_paste_placeholder_is_ours(self) -> None:
        self.assertTrue(self.check("[Pasted text #1]", "a long relayed message " * 40))

    def test_multi_line_paste_placeholder_is_never_ours(self) -> None:
        self.assertFalse(self.check("[Pasted text #1 +3 lines]", "a long relayed message " * 40))

    def test_placeholder_beside_a_short_text_is_the_operators_own_paste(self) -> None:
        self.assertFalse(self.check("[Pasted text #1 +3 lines]", "hello"))
        self.assertFalse(self.check("[Pasted text #1 +3 lines] and more", "a long relayed message " * 40))

    def test_empty_or_other_box_is_not_stuck(self) -> None:
        self.assertFalse(self.check("", "hello"))
        self.assertFalse(self.check("something else entirely", "hello"))


if __name__ == "__main__":
    unittest.main()


class TestOwnLeftover(unittest.TestCase):
    def test_draft_matching_our_unsent_text(self) -> None:
        sent = "From djbclark-ade: a long proposal that ends with say which of 1-5 you want."
        self.assertTrue(relay.ours(sent, sent))
        self.assertTrue(relay.ours("…a long proposal that ends with say which of 1-5 you want.", sent))
        self.assertFalse(relay.ours("someone typing their own words here, not ours at all", sent))
        self.assertFalse(relay.ours("anything", None))

    def test_unsent_ledger_round_trip(self) -> None:
        import tempfile
        orig = relay.UNSENT
        with tempfile.TemporaryDirectory() as d:
            relay.UNSENT = relay.Path(d) / "u.json"
            try:
                relay.note_unsent("abc", "hello")
                self.assertEqual(relay._unsent()["abc"]["text"], "hello")
                self.assertEqual(relay.leftover("abc")["text"], "hello")
                relay.note_unsent("abc", None)
                self.assertEqual(relay._unsent(), {})
            finally:
                relay.UNSENT = orig
