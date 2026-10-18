#!/usr/bin/env python3
"""Tests for `acp-dispatch tell`: lead messages into a running slice.

The inbox file beside the record is the source of truth; the Claude live-session
delivery rides on top of it and must never fail a tell. `check` reports the
message state, and `resume` carries unanswered messages into the next prompt.

Uses test_acp_dispatch's fake acp-run and fixtures.
"""
from __future__ import annotations

import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import SCRIPT, Base, run


def run_stdin(args: list[str], env: dict[str, str], text: str) -> subprocess.CompletedProcess[str]:
    e = dict(os.environ)
    e.update(env)
    return subprocess.run([sys.executable, str(SCRIPT), *args], check=False, capture_output=True,
                          text=True, env=e, input=text)


def sink(sock_path: Path) -> tuple[socketserver.UnixStreamServer, list[bytes]]:
    """A unix-socket server recording everything one client sends before it shuts down its
    write side (what claude_socket_send does)."""
    received: list[bytes] = []

    class Handler(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            buf = b""
            while chunk := self.request.recv(4096):
                buf += chunk
            received.append(buf)

    server = socketserver.UnixStreamServer(str(sock_path), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


class TellBase(Base):
    record_path: Path
    inbox: Path
    replies: Path

    @override
    def setUp(self) -> None:
        super().setUp()
        self.record_path = self.out / "jobs" / "s1.json"
        self.inbox = self.out / "jobs" / "s1.inbox.md"
        self.replies = self.out / "jobs" / "s1.replies.md"

    def dispatch_running(self, agent: str = "codex") -> dict:
        """A finished dispatch rewound to running: .done gone, finished cleared (the same
        dance test_acp_dispatch's extend tests use)."""
        self.assertEqual(self.dispatch_agent(agent, "m1").returncode, 0)
        rec = self.record()
        Path(rec["done"]).unlink()
        rec.update(finished=None, status="running", exit=None)
        self.record_path.write_text(json.dumps(rec))
        return rec

    def finish_again(self) -> None:
        rec = self.record()
        rec.update(finished=(rec.get("started") or 0) + 1, status="done", exit=0)
        Path(rec["done"]).touch(exist_ok=True)
        self.record_path.write_text(json.dumps(rec))


class TestTell(TellBase):
    def test_tell_appends_msg_1_then_msg_2(self):
        self.dispatch_running()
        for text in ("use the other file", "stop after step 3"):
            r = run(["tell", str(self.record_path), text])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "delivered: inbox")
        inbox = self.inbox.read_text()
        headers = [ln for ln in inbox.splitlines() if ln.startswith("## MSG ")]
        self.assertEqual(len(headers), 2, inbox)
        for n, header in enumerate(headers, start=1):
            self.assertRegex(header, rf"^## MSG {n} · \d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}} · from lead$")
        self.assertIn("use the other file", inbox)
        self.assertIn("stop after step 3", inbox)

    def test_tell_refuses_a_finished_record(self):
        self.dispatch_agent("codex", "m1")
        r = run(["tell", str(self.record_path), "one more thing"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("resume", r.stderr)
        self.assertFalse(self.inbox.exists(), "a refused tell writes nothing")

    def test_tell_accepts_a_finished_record_with_a_resume_scheduled(self):
        self.dispatch_agent("codex", "m1")
        rec = self.record()
        rec["auto_resume"] = {"state": "scheduled", "attempt": 1, "not_before": 0}
        self.record_path.write_text(json.dumps(rec))
        r = run(["tell", str(self.record_path), "after the reset, skip step 2"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skip step 2", self.inbox.read_text())

    def test_tell_reads_stdin_and_names_the_sender(self):
        self.dispatch_running()
        r = run_stdin(["tell", str(self.record_path), "-", "--from", "operator"], {}, "via stdin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(self.inbox.read_text(), r"(?m)^## MSG 1 · \S+ · from operator$")
        self.assertIn("via stdin", self.inbox.read_text())

    def test_tell_accepts_a_bare_report_path(self):
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        report = scratch / "fix-report.md"
        report.write_text("STATUS: working\n")
        r = run(["tell", str(report), "new constraint: no schema change"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "delivered: inbox")
        inbox = (scratch / "fix-report.md.inbox.md").read_text()
        self.assertIn("## MSG 1", inbox)
        self.assertIn("no schema change", inbox)

    def test_claude_live_delivery_sends_the_verified_frame(self):
        self.dispatch_running(agent="claude")
        sock = self.tmp / "live.sock"
        server, received = sink(sock)
        try:
            reg = self.tmp / "sessions"
            reg.mkdir()
            (reg / f"{os.getpid()}.json").write_text(json.dumps({
                "pid": os.getpid(), "sessionId": "fake-session",
                "messagingSocketPath": str(sock), "kind": "claude-code"}))
            r = run(["tell", str(self.record_path), "stop after step 3"],
                    env={"ACP_DISPATCH_CLAUDE_SESSIONS": str(reg)})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), f"delivered: inbox + live session {os.getpid()}")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].endswith(b"\n"))
        self.assertNotIn(b"\n", received[0][:-1], "one JSON line")
        frame = json.loads(received[0].decode())
        self.assertEqual(frame["msgV"], 1)
        self.assertEqual(frame["type"], "user")
        self.assertEqual(frame["priority"], "next")
        self.assertEqual(frame["message"]["role"], "user")
        # the `from` value must match ^[A-Za-z0-9%:_/.-]+$ or the receiver drops the frame
        self.assertRegex(frame["from"], r"^[A-Za-z0-9%:_/.-]+$")
        self.assertEqual(frame["from"], "acp-dispatch")
        wrap = frame["message"]["content"]
        self.assertTrue(wrap.startswith('<cross-session-message from="acp-dispatch" '
                                         'from-name="acp-dispatch tell (lead)" from-mode="bypass">\n'))
        self.assertIn("\nstop after step 3\n", wrap)
        self.assertIn("MSG 1 from lead", wrap)
        self.assertIn(f"REPLY 1: <one line>` appended to {self.replies.resolve()}", wrap)
        self.assertTrue(wrap.endswith("</cross-session-message>"))
        # the inbox entry is written all the same
        self.assertIn("stop after step 3", self.inbox.read_text())

    def test_dead_or_missing_socket_still_delivers_the_inbox(self):
        self.dispatch_running(agent="claude")
        reg = self.tmp / "sessions"
        reg.mkdir()
        (reg / "99999999.json").write_text(json.dumps({
            "pid": 99999999, "sessionId": "fake-session",          # dead pid: skipped
            "messagingSocketPath": str(self.tmp / "nope.sock")}))
        (reg / f"{os.getpid()}.json").write_text(json.dumps({
            "pid": os.getpid(), "sessionId": "fake-session",       # live pid, missing socket
            "messagingSocketPath": str(self.tmp / "missing.sock")}))
        r = run(["tell", str(self.record_path), "hello"],
                env={"ACP_DISPATCH_CLAUDE_SESSIONS": str(reg)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "delivered: inbox")
        self.assertIn("## MSG 1", self.inbox.read_text())

    def test_check_shows_inbox_sent_and_answered(self):
        self.dispatch_running()
        run(["tell", str(self.record_path), "first note"])
        run(["tell", str(self.record_path), "second note"])
        c = run(["check", str(self.record_path)])
        self.assertIn("inbox: 2 sent, 0 answered", c.stdout)
        self.assertNotIn("last reply", c.stdout)
        self.replies.write_text("REPLY 1: done, stopped after step 3\n")
        c = run(["check", str(self.record_path)])
        self.assertIn("inbox: 2 sent, 1 answered, last reply: done, stopped after step 3", c.stdout)

    def test_resume_carries_unanswered_messages(self):
        self.dispatch_running()
        run(["tell", str(self.record_path), "stop after step 3"])
        self.finish_again()
        r = run(["resume", str(self.record_path), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = Path(self.record()["brief"]).read_text()
        self.assertIn("Messages from the lead you have not answered yet (answer each with REPLY N in "
                      f"{self.replies.resolve()}):", brief)
        self.assertIn("stop after step 3", brief)
        self.assertLess(brief.index("Messages from the lead"), brief.index("## Delivery contract"))
        # once answered, the next resume does not carry it again
        self.replies.write_text("REPLY 1: stopped as asked\n")
        r = run(["resume", str(self.record_path), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = Path(self.record()["brief"]).read_text()
        self.assertNotIn("stop after step 3", brief)
        self.assertNotIn("Messages from the lead you have not answered yet", brief,
                         "the footer's item 14 talks about messages; only the resume block has this heading")

    def test_dispatch_footer_names_the_inbox_beside_the_record(self):
        self.dispatch_agent("codex", "m1")
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("jobs/s1.inbox.md", brief)
        self.assertIn("jobs/s1.replies.md", brief)
        self.assertNotIn("{inbox}", brief)
        self.assertNotIn("{replies}", brief)


class TestFooterInbox(unittest.TestCase):
    def test_footer_renders_inbox_and_replies_beside_the_report(self):
        r = run(["footer", "--report", "/abs/x-report.md"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/abs/x-report.md.inbox.md", r.stdout)
        self.assertIn("/abs/x-report.md.replies.md", r.stdout)
        self.assertIn("## MSG N", r.stdout)
        self.assertIn("REPLY N:", r.stdout)
        self.assertIn("overrides the brief", r.stdout)
        self.assertNotIn("{inbox}", r.stdout)
        self.assertNotIn("{replies}", r.stdout)


if __name__ == "__main__":
    unittest.main()
