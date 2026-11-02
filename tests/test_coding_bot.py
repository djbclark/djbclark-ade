#!/usr/bin/env python3
"""Tests for bin/coding-bot: webhook push, clipboard fallback, reply filing and the blocking `ask`.

A loopback HTTP server stands in for the bot's webhook routine; a fake `clip`/`pbpaste` is the pasteboard.
PATH is cut down so the host's real `sudo-secretspec` (and its real secrets) is never reached.
"""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import override

SCRIPT = Path(__file__).resolve().parent.parent / "bin/coding-bot"
KEY = "k3y-0123456789abcdef-NOT-A-REAL-KEY"


class Hook(http.server.BaseHTTPRequestHandler):
    status = 200
    redirect: str | None = None
    delay = 0.0
    seen: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Hook.seen.append({"auth": self.headers.get("Authorization"), "body": json.loads(body)})
        time.sleep(Hook.delay)
        self.send_response(302 if Hook.redirect else Hook.status)
        if Hook.redirect:
            self.send_header("Location", Hook.redirect)
        self.end_headers()
        self.wfile.write(b'{"success":true,"runUuid":"run-1"}')

    @override
    def log_message(self, *args: object) -> None:
        pass


class Spy(http.server.BaseHTTPRequestHandler):
    """Another host: records every request's Authorization header."""
    seen: list[str | None] = []

    def do_GET(self) -> None:  # noqa: N802
        Spy.seen.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()

    do_POST = do_GET  # noqa: N815

    @override
    def log_message(self, *args: object) -> None:
        pass


class Base(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state, self.pasteboard = root / "state", root / "pasteboard.txt"
        fake = root / "bin"
        fake.mkdir()
        (fake / "clip").write_text(f"#!/bin/sh\ncat > '{self.pasteboard}'\n")
        (fake / "pbpaste").write_text(f"#!/bin/sh\ncat '{self.pasteboard}'\n")
        for f in fake.iterdir():
            f.chmod(0o755)
        self.env = {"PATH": str(fake) + ":/usr/bin:/bin", "CLIP": str(fake / "clip"), "PBPASTE": str(fake / "pbpaste"),
                    "HOME": str(root), "CODING_BOT_STATE": str(self.state)}
        Hook.status, Hook.redirect, Hook.delay, Hook.seen, Spy.seen = 200, None, 0.0, [], []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        self.spy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Spy)
        for srv in (self.server, self.spy):
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/automations/webhook/x"
        self.spy_url = f"http://127.0.0.1:{self.spy.server_port}/stolen"

    def cli(self, *args: str, hook: bool = True, stdin: str | None = None, **extra: str) -> subprocess.CompletedProcess[str]:
        env = dict(self.env)
        if hook:
            env.update(CODING_BOT_WEBHOOK_URL=self.url, CODING_BOT_WEBHOOK_KEY=KEY)
        env.update(extra)
        return subprocess.run([sys.executable, str(SCRIPT), *args], check=False, capture_output=True,
                              text=True, env=env, input=stdin, cwd=self.tmp.name)

    def outbox(self) -> list[dict]:
        return [json.loads(x) for x in (self.state / "outbox.jsonl").read_text().splitlines()]


class TestSend(Base):
    def test_webhook_post_carries_key_sender_and_increasing_ids(self) -> None:
        a = self.cli("send", "open the page and read the title")
        b = self.cli("--from", "codex", "send", "--re", "coding-1", "now click Next")
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        self.assertEqual([h["auth"] for h in Hook.seen], [f"Bearer {KEY}"] * 2)
        first, second = Hook.seen[0]["body"], Hook.seen[1]["body"]
        self.assertEqual((first["from"], first["id"], first["re"], first["text"]),
                         ("claude-code", "ade-1", None, "open the page and read the title"))
        self.assertEqual((second["from"], second["id"], second["re"]), ("codex", "ade-2", "coding-1"))
        self.assertEqual(first["project"], Path(self.tmp.name).name)
        self.assertIn("runUuid=run-1", a.stdout)
        self.assertNotIn(KEY, a.stdout + a.stderr + (self.state / "outbox.jsonl").read_text())
        results = [r for r in self.outbox() if "result_for" in r]
        self.assertEqual([(r["result_for"], r["ok"]) for r in results], [("ade-1", True), ("ade-2", True)])

    def test_rejected_webhook_is_exit_1_and_never_silently_uses_the_clipboard(self) -> None:
        Hook.status = 401
        r = self.cli("send", "hello")
        self.assertEqual(r.returncode, 1)
        self.assertIn("HTTP 401", r.stderr)
        self.assertNotIn(KEY, r.stdout + r.stderr)
        self.assertFalse([x for x in self.outbox() if "result_for" in x][0]["ok"])
        self.assertFalse(self.pasteboard.exists())

    def test_unconfigured_webhook_falls_back_to_a_self_contained_clipboard_prompt(self) -> None:
        r = self.cli("send", "Read the invoice total on the billing page", hook=False)
        self.assertEqual(r.returncode, 10, r.stderr)
        pasted = self.pasteboard.read_text()
        self.assertIn("Read the invoice total on the billing page", pasted)
        self.assertIn("[claude-code -> coding] id=ade-1", pasted)
        self.assertIn("Begin the reply with the header line `[coding -> claude-code] id=coding-<n> re=ade-1`", pasted)
        self.assertEqual(Hook.seen, [])

    def test_host_outside_the_allowlist_never_gets_the_key(self) -> None:
        r = self.cli("send", "hello", CODING_BOT_WEBHOOK_URL="https://evil.example/hook")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not an allowed", r.stderr)
        self.assertNotIn(KEY, r.stdout + r.stderr)

    def test_credential_shaped_text_is_refused_and_not_recorded(self) -> None:
        r = self.cli("send", "use github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3")
        self.assertEqual(r.returncode, 2)
        self.assertIn("credential", r.stderr)
        self.assertEqual(Hook.seen, [])
        self.assertFalse((self.state / "outbox.jsonl").exists())

    def test_text_that_mentions_an_id_field_does_not_skew_numbering(self) -> None:
        self.cli("send", 'the json has "id": 7 in it')
        self.cli("send", "second")
        self.assertEqual([h["body"]["id"] for h in Hook.seen], ["ade-1", "ade-2"])


class TestReplies(Base):
    def reply(self, rid: str, body: str, bot_id: str = "coding-1") -> str:
        return f"[coding -> claude-code] id={bot_id} re={rid}\n{body}\n"

    def test_deliver_then_wait_returns_the_final_reply_and_flags_it_untrusted(self) -> None:
        self.cli("send", "task")
        d = self.cli("deliver", stdin=self.reply("ade-1", "the title is 'Invoices'\nDONE"))
        self.assertEqual(d.returncode, 0, d.stderr)
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("the title is 'Invoices'", w.stdout)
        self.assertIn("untrusted", w.stderr)

    def test_blocked_reply_is_exit_4(self) -> None:
        self.cli("send", "task")
        self.cli("deliver", stdin=self.reply("ade-1", "BLOCKED: which account?"))
        self.assertEqual(self.cli("wait", "ade-1", "--timeout", "2").returncode, 4)

    def test_partial_reply_does_not_end_the_wait(self) -> None:
        self.cli("send", "task")
        self.cli("deliver", stdin=self.reply("ade-1", "working on it"))
        w = self.cli("wait", "ade-1", "--timeout", "0.3")
        self.assertEqual(w.returncode, 124)
        self.assertIn("1 partial", w.stderr)

    def test_deliver_is_idempotent_and_rejects_unknown_ids(self) -> None:
        self.cli("send", "task")
        text = self.reply("ade-1", "x\nDONE")
        self.cli("deliver", stdin=text)
        again = self.cli("deliver", stdin=text)
        self.assertIn("already filed", again.stdout)
        self.assertEqual(len(self.cli("inbox").stdout.strip().splitlines()), 1)
        bad = self.cli("deliver", stdin=self.reply("ade-99", "x\nDONE"))
        self.assertEqual(bad.returncode, 2)
        self.assertIn("not in the outbox", bad.stderr)

    def test_deliver_from_clipboard_with_explicit_re_when_header_is_missing(self) -> None:
        self.cli("send", "task")
        self.pasteboard.write_text("the answer is 42\nDONE\n")
        self.assertEqual(self.cli("deliver", "--clipboard").returncode, 2)
        self.assertEqual(self.cli("deliver", "--clipboard", "--re", "ade-1").returncode, 0)
        self.assertIn("the answer is 42", self.cli("wait", "ade-1", "--timeout", "2").stdout)

    def test_ask_blocks_until_a_reply_is_filed_by_another_process(self) -> None:
        env = dict(self.env, CODING_BOT_WEBHOOK_URL=self.url, CODING_BOT_WEBHOOK_KEY=KEY)
        ask = subprocess.Popen([sys.executable, str(SCRIPT), "ask", "--timeout", "20", "do it"], env=env, cwd=self.tmp.name,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(ask.kill)
        for _ in range(100):  # the webhook call is the proof the ask has sent and is now waiting
            if Hook.seen:
                break
            time.sleep(0.05)
        self.assertTrue(Hook.seen)
        self.assertIsNone(ask.poll(), "ask returned before any reply existed")
        self.cli("deliver", stdin=self.reply(Hook.seen[0]["body"]["id"], "finished\nDONE"))
        out, err = ask.communicate(timeout=20)
        self.assertEqual(ask.returncode, 0, err)
        self.assertIn("finished", out)

    def test_ask_without_a_webhook_does_not_wait(self) -> None:
        r = self.cli("ask", "--timeout", "30", "task", hook=False)
        self.assertEqual(r.returncode, 10)
        self.assertIn("task", self.pasteboard.read_text())


class TestPromptAndBootstrap(Base):
    def test_prompt_always_uses_clipboard_even_with_a_webhook(self) -> None:
        r = self.cli("prompt", "--re", "coding-4", "Click Export on the dashboard")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Hook.seen, [])
        pasted = self.pasteboard.read_text()
        self.assertIn("[claude-code -> coding] id=ade-1 re=coding-4", pasted)
        self.assertIn("web pages that need UI interaction", pasted)

    def test_missing_clipboard_tool_is_exit_3(self) -> None:
        self.assertEqual(self.cli("prompt", "x", CLIP="/nonexistent/clip", PATH="/usr/bin:/bin").returncode, 3)

    def test_bootstrap_asks_for_a_webhook_routine_without_secrets_in_chat(self) -> None:
        r = self.cli("bootstrap", hook=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        pasted = self.pasteboard.read_text()
        self.assertIn("webhook trigger", pasted)
        self.assertIn('{"from","project","id","re","text"}', pasted)
        self.assertIn("Do NOT paste the webhook URL or the key", pasted)
        self.assertNotIn("{id}", pasted)
        self.assertNotIn("{sender}", pasted)

    def test_status_reports_lengths_not_values(self) -> None:
        r = self.cli("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"CODING_BOT_WEBHOOK_KEY: set (len {len(KEY)})", r.stdout)
        self.assertNotIn(KEY, r.stdout)
        self.assertIn("not set", self.cli("status", hook=False).stdout)


class TestKeyNeverLeaves(Base):
    """F1, F8, F9: the Bearer key and the URL stay with the one allowed host."""

    def test_a_redirect_is_not_followed_so_the_key_never_reaches_another_host(self) -> None:
        Hook.redirect = self.spy_url
        r = self.cli("send", "hello")
        self.assertEqual(r.returncode, 1)
        self.assertIn("HTTP 302", r.stderr)
        self.assertEqual(Spy.seen, [], "the redirect target received a request")
        self.assertNotIn(KEY, r.stdout + r.stderr)

    def test_text_containing_the_key_or_the_url_is_refused_before_anything_is_sent_or_stored(self) -> None:
        for leak in (f"debug: key is {KEY}", f"post it to {self.url}"):
            for cmd in ("send", "ask", "prompt"):
                r = self.cli(cmd, leak)
                self.assertEqual(r.returncode, 2, (cmd, leak, r.stderr))
                self.assertIn("credential", r.stderr)
        self.assertEqual(Hook.seen, [])
        self.assertFalse((self.state / "outbox.jsonl").exists())

    def test_neither_status_nor_a_refused_host_prints_the_url(self) -> None:
        status = self.cli("status")
        refused = self.cli("send", "hello", CODING_BOT_WEBHOOK_URL="https://evil.example/hook/secret-path")
        for out in (status.stdout + status.stderr, refused.stdout + refused.stderr):
            self.assertNotIn("127.0.0.1", out)
            self.assertNotIn("evil.example", out)
            self.assertNotIn("secret-path", out)

    def test_a_server_that_never_answers_is_cut_off_at_the_total_deadline(self) -> None:
        Hook.delay = 4.0
        t0 = time.monotonic()
        r = self.cli("send", "hello", CODING_BOT_DEADLINE_S="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no answer in 1s", r.stderr)
        self.assertLess(time.monotonic() - t0, 3.5)


class TestStateFiles(Base):
    """F2, F3: private files, and a damaged or hand-edited log never takes the tool down."""

    def test_state_dir_is_0700_and_logs_are_0600_even_when_they_pre_exist_loose(self) -> None:
        self.state.mkdir(mode=0o755)
        (self.state / "outbox.jsonl").write_text("")
        (self.state / "outbox.jsonl").chmod(0o644)
        self.cli("send", "hello")
        self.cli("deliver", stdin="[coding -> claude-code] id=coding-1 re=ade-1\nx\nDONE")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        for name in ("outbox.jsonl", "inbox.jsonl"):
            self.assertEqual((self.state / name).stat().st_mode & 0o777, 0o600, name)

    def test_a_torn_last_line_is_skipped_and_ids_continue_without_gluing_records(self) -> None:
        self.cli("send", "one")
        with open(self.state / "outbox.jsonl", "a") as f:
            f.write('{"id": "ade-2", "ts": "x", "te')  # a crash mid-write: no newline, not JSON
        r = self.cli("send", "two")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Hook.seen[-1]["body"]["id"], "ade-2", "the torn record's id was not issued, so it is reused")
        self.assertIn("skipped 1 unreadable", r.stderr)
        st = self.cli("status")
        self.assertEqual(st.returncode, 0, st.stderr)
        self.assertIn("outbox: 2 messages", st.stdout)

    def test_records_missing_fields_do_not_crash_inbox_wait_or_status(self) -> None:
        self.cli("send", "task")
        (self.state / "inbox.jsonl").write_text('{"re": "ade-1"}\n{"text": "orphan"}\n[1, 2]\n')
        with open(self.state / "outbox.jsonl", "a") as f:
            f.write('{"result_for": "ade-1"}\n{"id": "ade-9"}\n')
        for args in (("inbox",), ("status",), ("wait", "ade-1", "--timeout", "0.2")):
            r = self.cli(*args)
            self.assertNotIn("Traceback", r.stderr, args)
        self.assertEqual(self.cli("wait", "ade-1", "--timeout", "0.2").returncode, 124)

    def test_unicode_line_separators_in_a_task_or_reply_do_not_split_a_record(self) -> None:
        seps = "a\u2028b\u2029c\x0bd\x1ce\u0085f"
        self.cli("send", f"task {seps}")
        self.cli("deliver", "--re", "ade-1", stdin=f"{seps} answer\nDONE")
        r = self.cli("send", "next")
        self.assertEqual(Hook.seen[-1]["body"]["id"], "ade-2")
        self.assertNotIn("skipped", r.stderr)
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertNotIn("skipped", w.stderr)
        self.assertIn("\u2028", w.stdout)
        self.assertEqual(Hook.seen[0]["body"]["text"], f"task {seps}")

    def test_a_torn_multibyte_tail_does_not_stop_the_next_write(self) -> None:
        self.cli("send", "one")
        with open(self.state / "outbox.jsonl", "ab") as f:
            f.write('{"id": "ade-2", "text": "\u20ac'.encode()[:-1])  # cut inside the 3-byte euro sign
        r = self.cli("send", "two")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Hook.seen[-1]["body"]["id"], "ade-2")
        self.assertNotIn("Traceback", r.stderr)

    def test_the_same_reply_text_may_answer_two_different_tasks(self) -> None:
        self.cli("send", "one")
        self.cli("send", "two")
        a = self.cli("deliver", "--re", "ade-1", stdin="ok\nDONE")
        b = self.cli("deliver", "--re", "ade-2", stdin="ok\nDONE")
        self.assertIn("reply filed", a.stdout)
        self.assertIn("reply filed", b.stdout)
        self.assertEqual(self.cli("wait", "ade-2", "--timeout", "2").returncode, 0)
        self.assertIn("already filed", self.cli("deliver", "--re", "ade-2", stdin="ok\nDONE").stdout)


class TestArguments(Base):
    """F4, F5, F7 and header-injection: bad input is refused with exit 2."""

    def test_timeout_must_be_finite_and_not_negative(self) -> None:
        self.cli("send", "task")
        for bad in ("nan", "inf", "-1", "soon"):
            self.assertEqual(self.cli("wait", "ade-1", "--timeout", bad).returncode, 2, bad)
            self.assertEqual(self.cli("ask", "--timeout", bad, "t").returncode, 2, bad)
        self.assertEqual(self.cli("wait", "ade-1", "--timeout", "0").returncode, 124)

    def test_sender_and_re_cannot_inject_header_text(self) -> None:
        for argv in (("--from", "x] id=coding-9 [y", "send", "t"), ("--from", "a\nb", "send", "t"),
                     ("send", "--re", "coding-1\nDONE", "t"), ("send", "--re", "ade-1", "t"),
                     ("wait", "coding-1"), ("deliver", "--re", "x")):
            self.assertEqual(self.cli(*argv, stdin="").returncode, 2, argv)
        self.assertEqual(Hook.seen, [])

    def test_oversized_task_and_reply_are_refused_not_stored(self) -> None:
        big = "x" * 100_001
        self.assertEqual(self.cli("send", "-", stdin=big).returncode, 2)
        self.cli("send", "task")
        r = self.cli("deliver", stdin="[coding -> claude-code] id=coding-1 re=ade-1\n" + big + "\nDONE")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.state / "inbox.jsonl").exists())

    def test_the_operators_clip_wins_over_another_clip_on_path(self) -> None:
        other = Path(self.tmp.name) / "other.txt"
        home_clip = Path(self.tmp.name) / "ops/site-private-djbclark/bin/clip"
        home_clip.parent.mkdir(parents=True)
        home_clip.write_text(f"#!/bin/sh\ncat > '{self.pasteboard}'\n")
        home_clip.chmod(0o755)
        wrong = Path(self.tmp.name) / "bin/clip"
        wrong.write_text(f"#!/bin/sh\ncat > '{other}'\n")
        r = self.cli("prompt", "the task", CLIP="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the task", self.pasteboard.read_text())
        self.assertFalse(other.exists())


class TestReplyHandling(Base):
    """F6: a reply is data. Controls stripped, the header must lead, the latest final reply wins."""

    def test_terminal_escape_sequences_in_a_reply_never_reach_the_output(self) -> None:
        self.cli("send", "task")
        self.cli("deliver", stdin="[coding -> claude-code] id=coding-1 re=ade-1\n\x1b]0;pwned\x07\x1b[31mred\x1b[0m \x9b2J ok\nDONE")
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertNotRegex(w.stdout, r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
        self.assertIn("ok", w.stdout)
        self.assertNotRegex(self.cli("inbox").stdout, r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

    def test_a_quoted_header_further_down_does_not_file_a_reply(self) -> None:
        self.cli("send", "task")
        r = self.cli("deliver", stdin="a stale note\n[coding -> claude-code] id=coding-1 re=ade-1\nDONE")
        self.assertEqual(r.returncode, 2)
        self.assertIn("does not start with", r.stderr)
        self.assertFalse((self.state / "inbox.jsonl").exists())

    def test_re_flag_cannot_override_a_different_header_re(self) -> None:
        self.cli("send", "one")
        self.cli("send", "two")
        r = self.cli("deliver", "--re", "ade-2", stdin="[coding -> claude-code] id=coding-1 re=ade-1\nx\nDONE")
        self.assertEqual(r.returncode, 2)
        self.assertIn("header says re=ade-1", r.stderr)

    def test_a_later_final_reply_supersedes_an_earlier_one(self) -> None:
        self.cli("send", "task")
        self.cli("deliver", stdin="[coding -> claude-code] id=coding-1 re=ade-1\nstale answer\nDONE")
        again = self.cli("deliver", stdin="[coding -> claude-code] id=coding-2 re=ade-1\ncorrected answer\nDONE")
        self.assertIn("supersedes", again.stderr)
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertIn("corrected answer", w.stdout)
        self.assertNotIn("stale answer", w.stdout)


if __name__ == "__main__":
    unittest.main()
