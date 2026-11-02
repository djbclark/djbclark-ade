#!/usr/bin/env python3
"""Tests for bin/coding-bot: webhook push, clipboard fallback, reply filing and the blocking `ask`.

A loopback HTTP server stands in for the bot's webhook routine; a fake `clip`/`pbpaste` is the pasteboard.
PATH is cut down so the host's real `sudo-secretspec` (and its real secrets) is never reached.
"""
from __future__ import annotations

import errno
import http.server
import importlib.machinery
import importlib.util
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
from unittest import mock

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
        reply = self.reply(Hook.seen[0]["body"]["id"], "finished\nDONE")
        self.cli("deliver", stdin=reply)
        out, err = ask.communicate(timeout=20)
        self.assertEqual(ask.returncode, 0, err)
        self.assertEqual(out, reply.strip() + "\n", "ask's stdout must carry the reply and nothing else")
        self.assertIn("ade-1: HTTP 200", err)  # the transport receipt is on stderr

    def test_ask_without_a_webhook_does_not_wait(self) -> None:
        r = self.cli("ask", "--timeout", "30", "task", hook=False)
        self.assertEqual(r.returncode, 10)
        self.assertEqual(r.stdout, "")  # ask's stdout is reserved for the reply
        self.assertIn("no webhook configured", r.stderr)
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

    def test_a_malformed_url_is_never_quoted_in_output_or_the_outbox(self) -> None:
        port = self.server.server_port
        for bad in (f"http://127.0.0.1:{port}/secret path", f"http://127.0.0.1:{port}/secret\x7fpath",
                    "http://127.0.0.1:99999/secret-path", "http://[::1/secret-path", "http://127.0.0.1:1/secret-path"):
            r = self.cli("send", "hello", CODING_BOT_WEBHOOK_URL=bad)
            self.assertEqual(r.returncode, 1, (bad, r.stdout, r.stderr))
            self.assertNotIn("Traceback", r.stderr)
            st = self.cli("status", CODING_BOT_WEBHOOK_URL=bad)
            for out in (r.stdout + r.stderr, st.stdout + st.stderr):
                self.assertNotIn("secret", out, bad)
        self.assertNotIn("secret", (self.state / "outbox.jsonl").read_text())

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

    def test_the_size_limit_applies_to_the_raw_input_not_to_what_is_left_after_stripping(self) -> None:
        pad = " " * 100_000
        r = self.cli("send", "-", stdin=pad + "real task")  # a bounded read would cut this to "r" and accept it
        self.assertEqual((r.returncode, Hook.seen), (2, []), r.stderr)
        self.assertIn("over", r.stderr)
        self.cli("send", "task")
        d = self.cli("deliver", "--re", "ade-1", stdin=pad + "answer\nDONE")
        self.assertEqual(d.returncode, 2)
        self.assertIn("over", d.stderr)
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


class TestCredentialsViaRun(Base):
    """Credentials come only through `sudo-secretspec run` (never `get`), and nothing else it injects survives."""

    def setUp(self) -> None:
        super().setUp()
        fake = Path(self.tmp.name) / "bin"
        self.log, self.child_env = Path(self.tmp.name) / "ss.log", Path(self.tmp.name) / "clip-env.txt"
        (fake / "sudo-secretspec").write_text(
            "#!/bin/sh\necho \"$@\" >> '" + str(self.log) + "'\n"
            'if [ "$1" = run ]; then\n  shift; while [ "$1" != -- ]; do shift; done; shift\n'
            '  if [ -n "$FAKE_SUPPLY" ]; then export CODING_BOT_WEBHOOK_URL="$FAKE_URL" '
            'CODING_BOT_WEBHOOK_KEY="' + KEY + '" DECOY_SECRET=hunter2-decoy; fi\n  exec "$@"\nfi\nexit 99\n')
        (fake / "clip-env").write_text("#!/bin/sh\nenv > '" + str(self.child_env) + "'\ncat > '" + str(self.pasteboard) + "'\n")
        for f in ("sudo-secretspec", "clip-env"):
            (fake / f).chmod(0o755)
        self.clip_env = str(fake / "clip-env")

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_missing_credentials_come_from_one_run_never_a_get(self) -> None:
        r = self.cli("send", "task", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([h["auth"] for h in Hook.seen], [f"Bearer {KEY}"])
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].startswith("run "), calls)

    def test_no_other_secret_and_neither_credential_reaches_a_child_process(self) -> None:
        r = self.cli("prompt", "task", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url, CLIP=self.clip_env)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = self.child_env.read_text()
        for leaked in ("DECOY_SECRET", "hunter2-decoy", "CODING_BOT_WEBHOOK_KEY", KEY, "CODING_BOT_WEBHOOK_URL"):
            self.assertNotIn(leaked, env)
        self.assertIn("CODING_BOT_STATE=", env)  # its own settings and PATH survive

    def test_proxy_and_ca_overrides_are_dropped_before_the_key_is_used_or_any_child_starts(self) -> None:
        """Codex P1: a caller's proxy must not carry the Bearer key to another machine, nor a CA override re-trust it."""
        proxy = f"http://127.0.0.1:{self.spy.server_port}"
        leaks = dict(HTTP_PROXY=proxy, http_proxy=proxy, HTTPS_PROXY=proxy, https_proxy=proxy, ALL_PROXY=proxy,
                     NO_PROXY="*", no_proxy="*", SOCKS_PROXY=proxy,
                     SSL_CERT_FILE="/tmp/evil-ca.pem", SSL_CERT_DIR="/tmp/evil-ca", REQUESTS_CA_BUNDLE="/tmp/evil-ca.pem",
                     CURL_CA_BUNDLE="/tmp/evil-ca.pem", SSLKEYLOGFILE="/tmp/keys.log", OPENSSL_CONF="/tmp/evil.cnf")
        r = self.cli("send", "task", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url, CLIP=self.clip_env, **leaks)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([h["auth"] for h in Hook.seen], [f"Bearer {KEY}"], "the webhook call did not reach its own host")
        self.assertEqual(Spy.seen, [], "the call went through the caller's proxy")
        p = self.cli("prompt", "task", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url, CLIP=self.clip_env, **leaks)
        self.assertEqual(p.returncode, 0, p.stderr)
        env = self.child_env.read_text()
        for name in leaks:
            self.assertNotRegex(env, rf"(?mi)^{name}=", name)

    def test_openssl_and_tls_overrides_are_gone_before_hashlib_or_ssl_are_first_imported(self) -> None:
        """Codex P1: libcrypto reads OPENSSL_* when it loads, so the scrub must precede the first hashlib/ssl import."""
        prog = (
            "import os, runpy, sys\n"
            "seen = []\n"
            "def hook(event, args):\n"
            "    if event == 'import' and args[0] in ('hashlib', '_hashlib', 'ssl', '_ssl'):\n"
            "        seen.append((args[0], os.environ.get('OPENSSL_CONF'), os.environ.get('SSL_CERT_FILE'),"
            " os.environ.get('HTTPS_PROXY')))\n"
            "sys.addaudithook(hook)\n"
            f"sys.argv = [{str(SCRIPT)!r}, 'inbox']\n"
            f"try:\n    runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n"
            "except SystemExit:\n    pass\n"
            "print(repr(seen), file=sys.stderr)\n")
        env = dict(self.env, OPENSSL_CONF="/tmp/evil.cnf", SSL_CERT_FILE="/tmp/evil-ca.pem", HTTPS_PROXY="http://evil.invalid:1")
        r = subprocess.run([sys.executable, "-I", "-c", prog], check=False, capture_output=True, text=True, env=env,
                           cwd=self.tmp.name)
        seen = eval(r.stderr.strip().splitlines()[-1])  # a list of tuples we just printed ourselves
        self.assertTrue(seen, "hashlib/ssl were never imported, so this test proves nothing")
        for mod, conf, cafile, proxy in seen:
            self.assertEqual((conf, cafile, proxy), (None, None, None), f"{mod} was imported with an override set")

    def test_the_initial_interpreter_is_isolated_when_run_as_a_command(self) -> None:
        """Codex P1: `coding-bot ...` must not import a planted sitecustomize even in its FIRST process, which holds the
        credentials when the caller already ran under `sudo-secretspec run`."""
        root = Path(self.tmp.name)
        (root / "bin/python3").symlink_to(sys.executable)
        plant, marker = root / "plant2", root / "marker2.txt"
        plant.mkdir()
        (plant / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'a').write('planted ran')\n")
        env = dict(self.env, PYTHONPATH=str(plant), CODING_BOT_WEBHOOK_URL=self.url, CODING_BOT_WEBHOOK_KEY=KEY)
        r = subprocess.run([str(SCRIPT), "status"], check=False, capture_output=True, text=True, env=env, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CODING_BOT_WEBHOOK_KEY: set", r.stdout)
        self.assertFalse(marker.exists(), "a planted sitecustomize ran in the first interpreter")

    def test_python_without_dash_i_restarts_isolated_before_it_looks_at_credentials(self) -> None:
        plant, marker = Path(self.tmp.name) / "plant3", Path(self.tmp.name) / "marker3.txt"
        plant.mkdir()
        (plant / "usercustomize.py").write_text("")  # present but harmless: -I must not even look
        (plant / "json.py").write_text(f"open({str(marker)!r}, 'a').write('shadowed json ran')\nraise SystemExit(99)\n")
        r = self.cli("status", hook=True, PYTHONPATH=str(plant))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(marker.exists(), "a planted json.py was imported by the credentialed process")

    def test_the_process_that_holds_the_credentials_ignores_planted_python_hooks(self) -> None:
        plant, marker = Path(self.tmp.name) / "plant", Path(self.tmp.name) / "marker.txt"
        plant.mkdir()
        (plant / "sitecustomize.py").write_text(
            f"import os\nopen({str(marker)!r}, 'a').write('KEY' if os.environ.get('CODING_BOT_WEBHOOK_KEY') else 'nokey')\n")
        r = self.cli("status", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url, PYTHONPATH=str(plant))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("CODING_BOT_WEBHOOK_KEY: set", r.stdout)  # the re-executed process did run, with the credentials
        self.assertEqual(marker.read_text(), "nokey", "a planted sitecustomize ran where the vault credentials were")

    def test_a_run_that_supplies_nothing_is_not_retried_and_the_tool_degrades_to_clipboard(self) -> None:
        st = self.cli("status", hook=False)
        self.assertIn("CODING_BOT_WEBHOOK_KEY: not set", st.stdout)
        self.assertEqual(len(self.calls()), 1, "a loop: run was started more than once")

    def test_commands_that_need_no_credentials_never_start_run(self) -> None:
        self.cli("send", "task", hook=False, FAKE_SUPPLY="1", FAKE_URL=self.url)
        self.log.unlink()
        for args in (("inbox",), ("wait", "ade-1", "--timeout", "0"), ("bootstrap",), ("deliver", "--re", "ade-1")):
            self.cli(*args, hook=False, stdin="x\nDONE")
        self.assertEqual(self.calls(), [])


class TestAtomicState(Base):
    """A crash or a full disk during a write leaves the previous file whole, not a partial record."""

    def load(self):  # the script has no .py suffix: load it by path; importing runs no main
        loader = importlib.machinery.SourceFileLoader("coding_bot_under_test", str(SCRIPT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        with mock.patch.object(sys, "dont_write_bytecode", True):
            loader.exec_module(mod)
        return mod

    def test_a_failed_replace_keeps_the_old_bytes_leaves_no_temp_file_and_the_next_write_works(self) -> None:
        with mock.patch.dict(os.environ, {"CODING_BOT_STATE": str(self.state)}):
            mod = self.load()
            self.assertEqual(mod.append("outbox.jsonl", {"x": 1}, number="ade"), "ade-1")
            before = (self.state / "outbox.jsonl").read_bytes()
            with mock.patch.object(os, "replace", side_effect=OSError(errno.ENOSPC, "No space left on device")):
                with self.assertRaises(OSError):
                    mod.append("outbox.jsonl", {"x": 2}, number="ade")
            self.assertEqual((self.state / "outbox.jsonl").read_bytes(), before)
            self.assertEqual([p.name for p in self.state.iterdir() if p.name.endswith(".tmp")], [])
            self.assertEqual(mod.append("outbox.jsonl", {"x": 3}, number="ade"), "ade-2")

    def test_a_failed_write_while_building_the_temp_file_also_keeps_the_old_file(self) -> None:
        with mock.patch.dict(os.environ, {"CODING_BOT_STATE": str(self.state)}):
            mod = self.load()
            mod.append("inbox.jsonl", {"re": "ade-1"})
            before = (self.state / "inbox.jsonl").read_bytes()
            with mock.patch.object(os, "fsync", side_effect=OSError(errno.EIO, "I/O error")):
                with self.assertRaises(OSError):
                    mod.append("inbox.jsonl", {"re": "ade-2"})
            self.assertEqual((self.state / "inbox.jsonl").read_bytes(), before)
            self.assertEqual([p.name for p in self.state.iterdir() if p.name.endswith(".tmp")], [])


class TransportBase(Base):
    """An ssh drop (a fake `ssh` that runs the remote command locally, with a down switch and a call log) and a git
    mailbox (a real local bare repo, a clone for us and a clone for the 'bot')."""

    def setUp(self) -> None:
        super().setUp()
        root = Path(self.tmp.name)
        self.to_dir, self.from_dir = root / "drop/to-coding", root / "drop/from-coding"
        self.to_dir.mkdir(parents=True)
        self.from_dir.mkdir()
        self.ssh_log, self.ssh_down, self.ssh_hang = root / "ssh.log", root / "ssh.down", root / "ssh.hang"
        fake_ssh = root / "bin/ssh"
        fake_ssh.write_text(
            f"#!/bin/sh\necho call >> '{self.ssh_log}'\n"
            f"[ -e '{self.ssh_down}' ] && {{ echo 'ssh: connect failed' >&2; exit 255; }}\n"
            f"[ -e '{self.ssh_hang}' ] && exec sleep 30\n"
            'for last; do :; done\nexec sh -c "$last"\n')
        fake_ssh.chmod(0o755)
        self.origin, self.mailbox, self.bot = root / "origin.git", root / "mailbox", root / "bot-clone"
        self.git(root, "init", "--bare", "-q", "-b", "main", str(self.origin))
        self.git(root, "clone", "-q", str(self.origin), str(self.mailbox))
        (self.mailbox / "README.md").write_text("mailbox\n")
        self.git(self.mailbox, "add", "README.md")
        self.git(self.mailbox, "commit", "-q", "-m", "init")
        self.git(self.mailbox, "push", "-q", "origin", "HEAD:main")
        self.git(root, "clone", "-q", str(self.origin), str(self.bot))
        self.cfg = {"ssh": {"host": "h", "user": "u", "key": "k", "known_hosts": "kh", "port": 2222,
                            "to_dir": str(self.to_dir), "from_dir": str(self.from_dir)},
                    "git": {"path": str(self.mailbox), "remote": "origin", "branch": "main"}}
        self.write_cfg()
        self.env.update(CODING_BOT_TRANSPORTS=str(root / "transports.json"), CODING_BOT_POLL_S="0.2")
        # A local git push is far quicker than a real one; pin git's measured cost to a realistic few seconds so the
        # tests exercise the preference (ssh prior 1 s) and not this machine's speed.
        self.set_health("git", ewma_s=3.0, last_ok=time.time(), fails=0, down_until=0)

    def write_cfg(self) -> None:
        (Path(self.tmp.name) / "transports.json").write_text(json.dumps(self.cfg))

    @staticmethod
    def git(cwd: Path, *args: str) -> str:
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-C", str(cwd), *args],
                              check=True, capture_output=True, text=True).stdout

    def in_origin(self, rel: str) -> bool:
        r = subprocess.run(["git", "-C", str(self.origin), "cat-file", "-e", f"main:{rel}"], capture_output=True)
        return r.returncode == 0

    def ssh_calls(self) -> int:
        return len(self.ssh_log.read_text().splitlines()) if self.ssh_log.exists() else 0

    def health(self) -> dict:
        return json.loads((self.state / "health.json").read_text())

    def set_health(self, name: str, **fields: object) -> None:
        h = self.health() if (self.state / "health.json").exists() else {}
        h.setdefault(name, {}).update(fields)
        self.state.mkdir(exist_ok=True)
        (self.state / "health.json").write_text(json.dumps(h))

    def bot_reply_ssh(self, mid: str, body: str, n: int = 1) -> None:
        (self.from_dir / f"{mid}--coding-{n}.md").write_text(f"[coding -> claude-code] id=coding-{n} re={mid}\n{body}\n")

    def bot_reply_git(self, mid: str, body: str, n: int = 1) -> None:
        self.git(self.bot, "pull", "-q", "origin", "main")
        (self.bot / "from-coding").mkdir(exist_ok=True)
        (self.bot / f"from-coding/{mid}--coding-{n}.md").write_text(f"[coding -> claude-code] id=coding-{n} re={mid}\n{body}\n")
        self.git(self.bot, "add", "-A")
        self.git(self.bot, "commit", "-q", "-m", "reply")
        self.git(self.bot, "push", "-q", "origin", "HEAD:main")


class TestTransportSend(TransportBase):
    def test_the_cheaper_transport_carries_the_message_and_the_doorbell_is_short(self) -> None:
        r = self.cli("send", "the long task text")
        self.assertEqual(r.returncode, 0, r.stderr)
        msg = (self.to_dir / "ade-1.md").read_text()
        self.assertTrue(msg.startswith("[claude-code -> coding] id=ade-1\nproject: "), msg)
        self.assertIn("the long task text", msg)
        self.assertEqual([p.name for p in self.to_dir.iterdir()], ["ade-1.md"], "a temp file was left behind")
        self.assertFalse(self.in_origin("to-coding/ade-1.md"))
        body = Hook.seen[0]["body"]
        self.assertNotIn("the long task text", body["text"])
        self.assertIn("ade-1.md", body["text"])
        self.assertEqual(body["paths"], ["ssh"])
        self.assertIn("via ssh", r.stdout)
        self.assertEqual(self.health()["ssh"]["fails"], 0)

    def test_falls_back_to_git_when_ssh_is_down_then_skips_ssh_while_it_is_in_backoff(self) -> None:
        self.ssh_down.write_text("")
        r = self.cli("send", "task one")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("transport ssh:", r.stderr)
        self.assertTrue(self.in_origin("to-coding/ade-1.md"))
        self.assertEqual(Hook.seen[0]["body"]["paths"], ["git"])
        h = self.health()["ssh"]
        self.assertEqual(h["fails"], 1)
        self.assertTrue(5 < h["down_until"] - time.time() < 20, h)  # 15 s, jittered 0.75-1.25x, minus the send's own time
        self.assertEqual(self.ssh_calls(), 1)
        self.cli("send", "task two")
        self.assertEqual(self.ssh_calls(), 1, "ssh was tried again while it was in backoff")
        self.assertTrue(self.in_origin("to-coding/ade-2.md"))

    def test_traffic_switches_back_to_the_faster_transport_once_its_backoff_ends(self) -> None:
        self.ssh_down.write_text("")
        self.cli("send", "while ssh is down")
        self.ssh_down.unlink()
        self.set_health("ssh", down_until=time.time() - 1)  # the backoff has ended
        r = self.cli("send", "after it is back")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.to_dir / "ade-2.md").exists(), "did not return to ssh")
        self.assertFalse(self.in_origin("to-coding/ade-2.md"))
        self.assertEqual(self.health()["ssh"]["fails"], 0)

    def test_a_failed_probe_after_backoff_lengthens_the_next_backoff(self) -> None:
        self.ssh_down.write_text("")
        self.cli("send", "one")
        self.set_health("ssh", down_until=time.time() - 1)  # due again, still down
        self.cli("send", "two")
        h = self.health()["ssh"]
        self.assertEqual(h["fails"], 2)
        self.assertTrue(15 < h["down_until"] - time.time() < 40, h)  # 30 s, jittered, minus the send's own time

    def test_a_measured_slow_transport_loses_to_a_measured_fast_one_and_staleness_decays_to_the_prior(self) -> None:
        now = time.time()
        self.set_health("ssh", ewma_s=9.0, last_ok=now, fails=0, down_until=0)
        self.set_health("git", ewma_s=0.1, last_ok=now, fails=0, down_until=0)
        self.cli("send", "x")
        self.assertTrue(self.in_origin("to-coding/ade-1.md"))
        mod = TestAtomicState.load(self)
        self.assertEqual(mod.cost("ssh", {"ewma_s": 9.0, "last_ok": now}, now), 9.0)
        self.assertEqual(mod.cost("ssh", {"ewma_s": 9.0, "last_ok": now - 7200}, now), 1.0)  # stale: back to the prior
        self.assertEqual(mod.cost("git", {}, now), 4.0)

    def test_when_every_transport_fails_the_doorbell_carries_the_text(self) -> None:
        self.ssh_down.write_text("")
        self.cfg["git"]["remote"] = "no-such-remote"
        self.write_cfg()
        r = self.cli("send", "the whole task")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Hook.seen[0]["body"]["text"], "the whole task")
        self.assertNotIn("paths", Hook.seen[0]["body"])
        self.assertIn("transport ssh:", r.stderr)
        self.assertIn("transport git:", r.stderr)

    def test_backoff_grows_doubles_and_is_capped(self) -> None:
        mod = TestAtomicState.load(self)
        mid = [mod.backoff_s(n, rand=lambda: 0.5) for n in range(1, 11)]
        self.assertEqual(mid[:5], [15.0, 30.0, 60.0, 120.0, 240.0])
        self.assertEqual(mid[-1], 900.0)
        self.assertEqual((mod.backoff_s(1, rand=lambda: 0.0), mod.backoff_s(1, rand=lambda: 1.0)), (11.25, 18.75))

    def test_status_shows_the_backoff(self) -> None:
        self.ssh_down.write_text("")
        self.cli("send", "x")
        st = self.cli("status")
        self.assertIn("IN BACKOFF", st.stdout)
        self.assertRegex(st.stdout, r"git: cost .*\n.*ssh: cost .*IN BACKOFF")  # the usable one is listed first


class TestTransportReplies(TransportBase):
    FINAL = "finished\nDONE"

    def test_a_reply_on_both_transports_is_filed_once_and_not_refiled(self) -> None:
        self.cli("send", "task")
        self.bot_reply_ssh("ade-1", self.FINAL)
        self.bot_reply_git("ade-1", self.FINAL)
        s = self.cli("sync")
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertEqual(len(self.cli("inbox").stdout.strip().splitlines()), 1)
        self.assertIn("0 new", self.cli("sync").stdout)
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("finished", w.stdout)

    def test_a_reply_that_only_one_transport_has_is_found(self) -> None:
        self.cli("send", "task")
        self.bot_reply_git("ade-1", self.FINAL)
        self.assertIn("finished", self.cli("wait", "ade-1", "--timeout", "10").stdout)

    def test_drop_replies_are_checked_like_any_reply_and_a_refused_one_is_not_retried(self) -> None:
        self.cli("send", "task one")
        self.cli("send", "task two")
        (self.from_dir / "ade-1--coding-1.md").write_text("[coding -> claude-code] id=coding-1 re=ade-2\nx\nDONE\n")
        (self.from_dir / "ade-99--coding-1.md").write_text("[coding -> claude-code] id=coding-1 re=ade-99\nx\nDONE\n")
        (self.from_dir / "evil.md").write_text("[coding -> claude-code] id=coding-1 re=ade-1\nx\nDONE\n")
        (self.from_dir / "ade-1--coding-2.md.tmp").write_text("partial")
        s = self.cli("sync")
        self.assertIn("header says re=ade-2", s.stderr)
        self.assertIn("not in the outbox", s.stderr)
        self.assertEqual(self.cli("inbox").stdout, "")
        again = self.cli("sync")
        self.assertNotIn("header says", again.stderr, "a refused reply file was retried")

    def test_ask_returns_a_reply_that_arrives_by_drop(self) -> None:
        env = dict(self.env, CODING_BOT_WEBHOOK_URL=self.url, CODING_BOT_WEBHOOK_KEY=KEY)
        ask = subprocess.Popen([sys.executable, str(SCRIPT), "ask", "--timeout", "20", "do it"], env=env,
                               cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(ask.kill)
        for _ in range(100):
            if Hook.seen:
                break
            time.sleep(0.05)
        self.assertTrue(Hook.seen)
        self.assertIsNone(ask.poll())
        self.bot_reply_ssh("ade-1", "from the drop\nDONE")
        out, err = ask.communicate(timeout=20)
        self.assertEqual(ask.returncode, 0, err)
        self.assertEqual(out, "[coding -> claude-code] id=coding-1 re=ade-1\nfrom the drop\nDONE\n")

    def test_polling_never_changes_the_cost_used_to_rank_transports_for_sending(self) -> None:
        self.cli("sync")
        h = self.health()
        self.assertEqual(h["git"]["ewma_s"], 3.0, "a fetch made git look cheap to send with")
        self.assertIn("poll_s", h["git"])
        self.assertIn("poll_s", h["ssh"])
        self.assertNotIn("ewma_s", h["ssh"])

    def test_a_transport_in_backoff_is_not_polled_unless_forced(self) -> None:
        self.ssh_down.write_text("")
        self.cli("send", "x")  # ssh fails once, git carries it
        before = self.ssh_calls()
        self.cli("sync")
        self.assertEqual(self.ssh_calls(), before, "sync polled a transport in backoff")
        self.cli("sync", "--force")
        self.assertEqual(self.ssh_calls(), before + 1)


class TestTransportRobustness(TransportBase):
    """Local review of PR 245: backoff on send, a wedged git clone, replies caught mid-write, wait's time budget."""

    def test_a_send_never_tries_a_transport_in_backoff_and_falls_back_to_the_webhook_at_once(self) -> None:
        far = time.time() + 600
        self.set_health("ssh", fails=3, down_until=far)
        self.set_health("git", fails=3, down_until=far)
        before = (self.ssh_calls(), self.git(self.origin, "rev-parse", "main"))
        t0 = time.monotonic()
        r = self.cli("send", "the whole task")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.monotonic() - t0, 5)
        self.assertEqual((self.ssh_calls(), self.git(self.origin, "rev-parse", "main")), before, "a backed-off transport was tried")
        self.assertEqual(Hook.seen[0]["body"]["text"], "the whole task")
        self.assertIn("skipped, in backoff", r.stderr)
        self.assertEqual(self.health()["ssh"]["fails"], 3, "a skipped transport's backoff was extended")

    def test_an_unpublished_local_commit_does_not_wedge_the_git_transport(self) -> None:
        self.ssh_down.write_text("")
        (self.mailbox / "to-coding").mkdir(exist_ok=True)
        (self.mailbox / "to-coding/ade-0.md").write_text("an earlier send whose push failed\n")
        self.git(self.mailbox, "add", "-A")
        self.git(self.mailbox, "commit", "-q", "-m", "unpublished")
        self.bot_reply_git("ade-9", "an unrelated reply\nDONE")  # the remote moves on: histories diverge
        r = self.cli("send", "after the failed push")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.in_origin("to-coding/ade-1.md"), r.stderr)
        self.assertTrue(self.in_origin("to-coding/ade-0.md"), "the unpublished commit was not recovered")
        self.assertEqual(Hook.seen[0]["body"]["paths"], ["git"])

    def test_a_reply_caught_mid_write_is_read_again_until_it_is_final(self) -> None:
        self.cli("send", "task")
        target = self.from_dir / "ade-1--coding-1.md"
        target.write_text("")
        self.cli("sync")
        target.write_text("[coding -> claude-code] id=coding-1 re=ade-1\nhalf of the ans")
        self.cli("sync")
        target.write_text("[coding -> claude-code] id=coding-1 re=ade-1\nhalf of the answer, then the rest\nDONE\n")
        self.cli("sync")
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("then the rest", w.stdout)

    def test_wait_answers_a_filed_reply_without_touching_the_network(self) -> None:
        self.cli("send", "task")
        self.cli("deliver", stdin="[coding -> claude-code] id=coding-1 re=ade-1\nok\nDONE")
        self.ssh_hang.write_text("")
        before = self.ssh_calls()
        t0 = time.monotonic()
        w = self.cli("wait", "ade-1", "--timeout", "20")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(self.ssh_calls(), before)

    def test_a_hung_transport_cannot_hold_wait_past_its_timeout_nor_earn_a_backoff(self) -> None:
        self.cli("send", "task")  # ssh carries it and is healthy
        self.ssh_hang.write_text("")
        t0 = time.monotonic()
        w = self.cli("wait", "ade-1", "--timeout", "1.5")
        self.assertEqual(w.returncode, 124, w.stderr)
        self.assertLess(time.monotonic() - t0, 6)
        self.assertEqual(self.health()["ssh"].get("fails", 0), 0, "our own deadline was counted as a transport failure")


class TestMailboxSafety(TransportBase):
    """Local review of PR 245, round 2: a bot-writable repo cannot steer our writes, crash leftovers, ordering, caps."""

    def setUp(self) -> None:
        super().setUp()
        self.ssh_down.write_text("")  # git only

    def bot_commits(self, fn) -> None:
        self.git(self.bot, "pull", "-q", "origin", "main")
        fn(self.bot)
        self.git(self.bot, "add", "-A")
        self.git(self.bot, "commit", "-q", "-m", "bot change")
        self.git(self.bot, "push", "-q", "origin", "HEAD:main")

    def test_a_symlink_planted_in_the_mailbox_is_never_followed(self) -> None:
        outside = Path(self.tmp.name) / "outside-target.md"
        self.bot_commits(lambda d: ((d / "to-coding").mkdir(exist_ok=True), (d / "to-coding/ade-1.md").symlink_to(outside)))
        r = self.cli("send", "task")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(outside.exists(), "the write followed a symlink out of the mailbox")
        self.assertEqual(Hook.seen[0]["body"]["text"], "task")  # git refused, the doorbell carried the text

    def test_a_symlinked_to_coding_folder_is_refused(self) -> None:
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        self.bot_commits(lambda d: (d / "to-coding").symlink_to(elsewhere))
        self.cli("send", "task")
        self.assertEqual(list(elsewhere.iterdir()), [], "the write escaped through a symlinked folder")

    def test_a_staged_but_uncommitted_message_left_by_a_crash_does_not_wedge_git(self) -> None:
        (self.mailbox / "to-coding").mkdir(exist_ok=True)
        (self.mailbox / "to-coding/ade-0.md").write_text("half a transaction\n")
        self.git(self.mailbox, "add", "to-coding/ade-0.md")
        self.bot_reply_git("ade-9", "remote moves on\nDONE")
        r = self.cli("send", "after the crash")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.in_origin("to-coding/ade-1.md"), r.stderr)

    def test_concurrent_sends_share_the_clone_without_failing(self) -> None:
        env = dict(self.env, CODING_BOT_WEBHOOK_URL=self.url, CODING_BOT_WEBHOOK_KEY=KEY)
        procs = [subprocess.Popen([sys.executable, str(SCRIPT), "send", f"task {i}"], env=env, cwd=self.tmp.name,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        outs = [p.communicate(timeout=120) for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * 4, [o[1] for o in outs])
        for i in range(1, 5):
            self.assertTrue(self.in_origin(f"to-coding/ade-{i}.md"), f"ade-{i} missing; {[o[1] for o in outs]}")
        self.assertEqual(sorted(h["body"]["paths"][0] for h in Hook.seen), ["git"] * 4)

    def test_replies_are_imported_in_numeric_order_and_an_older_revision_never_wins(self) -> None:
        self.cli("send", "task")
        self.bot_reply_git("ade-1", "the newest answer\nDONE", n=10)
        self.bot_reply_git("ade-1", "an older answer\nDONE", n=9)
        self.cli("sync")
        w = self.cli("wait", "ade-1", "--timeout", "2")
        self.assertIn("the newest answer", w.stdout)
        self.assertNotIn("an older answer", w.stdout)

    def test_an_oversized_git_reply_is_refused_without_being_read_and_not_retried(self) -> None:
        self.cli("send", "task")
        self.bot_reply_git("ade-1", "x" * 500_000 + "\nDONE")
        s = self.cli("sync")
        self.assertIn("over the reply cap", s.stderr)
        self.assertEqual(self.cli("inbox").stdout, "")
        self.assertNotIn("over the reply cap", self.cli("sync").stderr, "a refused oversized reply was read again")

    def test_a_huge_failure_count_still_gives_a_capped_backoff(self) -> None:
        mod = TestAtomicState.load(self)
        self.assertEqual(mod.backoff_s(5000, rand=lambda: 0.5), 900.0)


class TestWaitPollsOneTransportAtATime(TransportBase):
    def test_a_reply_ssh_just_filed_is_returned_while_git_would_hang(self) -> None:
        self.cli("send", "task")  # via ssh
        self.bot_reply_ssh("ade-1", "fast answer\nDONE")
        hang = Path(self.tmp.name) / "bin/git"
        hang.write_text("#!/bin/sh\nexec sleep 30\n")
        hang.chmod(0o755)
        t0 = time.monotonic()
        w = self.cli("wait", "ade-1", "--timeout", "20")
        self.assertEqual(w.returncode, 0, w.stderr)
        self.assertIn("fast answer", w.stdout)
        self.assertLess(time.monotonic() - t0, 8, "a ready reply waited behind a hung git")


if __name__ == "__main__":
    unittest.main()
