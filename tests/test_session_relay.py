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

ROOT = Path(__file__).resolve().parent.parent
SF = ROOT / "skills" / "session-finder"
sys.path.insert(0, str(SF))

import fleet  # noqa: E402  # pyright: ignore[reportMissingImports]

_spec = importlib.util.spec_from_file_location("relay", SF / "relay.py")
assert _spec and _spec.loader
relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay)


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
                                                 "_proc_scan", "_hermes_gateway", "proc_table", "mark_busy", "ancestors")}
        try:
            fleet.herdr_json = lambda *a: {}
            fleet._launched = lambda used: [fleet._rec(id="L", host="acp", mark="test"), fleet._rec(id="M", host="acp")]
            fleet._claude_sessions = lambda *a, **k: []
            fleet._other_herdr = lambda *a: []
            fleet._pane_only = lambda *a: ([], [])
            fleet._proc_scan = lambda *a: []
            fleet._hermes_gateway = lambda: []
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

    def test_type_line_through_herdr_is_send_text_then_enter(self) -> None:
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
                             ["pane send-text w1:p1 hello there", "agent send-keys w1:p1 enter"])

    def run_main(self, drafts: list[str], scr: str, transcript: Path | None = None) -> tuple[int, list[str]]:
        """main() against one fake working Claude session; DRAFTS are successive input-box reads."""
        enters: list[str] = []
        reads = iter(drafts)
        saved = (relay.fleet.sessions, relay.type_line, relay.draft, relay.press_enter, relay.screen,
                 relay.RETRY_AFTER, sys.argv)
        relay.fleet.sessions = lambda: [sess(transcript=str(transcript) if transcript else None)]
        relay.type_line = lambda chan, text: True
        relay.draft = lambda chan: next(reads, "")
        relay.press_enter = lambda chan: enters.append("enter") or True
        relay.screen = lambda chan, lines=20: scr
        relay.RETRY_AFTER = 0
        sys.argv = ["relay.py", "peer-1", "hello there friend", "--wait", "3"]
        try:
            rc = relay.main()
        finally:
            (relay.fleet.sessions, relay.type_line, relay.draft, relay.press_enter, relay.screen,
             relay.RETRY_AFTER, sys.argv) = saved
        return rc, enters

    def test_text_left_in_the_box_gets_another_enter(self) -> None:
        # first read is the pre-send draft check (empty), then the text sits in the box once, then it is gone
        rc, enters = self.run_main(["", "hello there friend", ""], "Press up to edit queued messages")
        self.assertEqual(rc, 0)
        self.assertEqual(enters, ["enter"])

    def test_queue_hint_is_not_delivery_while_the_text_is_still_in_the_box(self) -> None:
        rc, enters = self.run_main([""] + ["hello there friend"] * 50, "Press up to edit queued messages")
        self.assertEqual(rc, 1)
        self.assertEqual(enters, ["enter"] * relay.ENTER_RETRIES)


if __name__ == "__main__":
    unittest.main()
