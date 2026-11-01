#!/usr/bin/env python3
"""`relay.py --message-file PATH|-` (2026-11-01).

Why: relay took the message only as a positional argv string, so every agent built a shell command line, and a message holding backticks or `$( )`
inside double quotes was EXECUTED by the caller's shell, silently losing text (a lead's message lost `stages: [pre-push]` and
`pass_filenames: true`; an earlier one ran a command). The file or stdin carries the text without any shell step. Every id here is fake.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay = fb.relay
TRICKY = "run `touch /tmp/never` and $(echo gone) with \"quotes\", $HOME, 'single', stages: [pre-push], pass_filenames: true"


class Base(fb.Harness):
    def setUp(self) -> None:
        super().setUp()
        self.typed: list[str] = []
        relay.type_line = lambda chan, text: self.typed.append(text) or True

    def send(self, *argv: str, stdin: bytes | None = None) -> tuple[int, str, str]:
        relay.fleet.sessions = lambda: [fb.sess()]
        out, err = io.StringIO(), io.StringIO()
        stack: list[Any] = [contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)]
        if stdin is not None:
            stack.append(mock.patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")))
        with contextlib.ExitStack() as es:
            for cm in stack:
                es.enter_context(cm)
            rc = relay.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def file(self, content: bytes) -> str:
        p = Path(self.tmp) / "msg.txt"
        p.write_bytes(content)
        return str(p)


class TestMessageFile(Base):
    def test_a_file_is_delivered_verbatim_with_backticks_and_command_substitution(self) -> None:
        rc, _, err = self.send("peer-fb", "--message-file", self.file(TRICKY.encode() + b"\n"), "--wait", "2", "--via", "pane")
        self.assertEqual((rc, self.typed), (0, [TRICKY]), err)

    def test_stdin_is_delivered_verbatim_and_only_one_trailing_newline_is_dropped(self) -> None:
        rc, _, err = self.send("peer-fb", "--message-file", "-", "--wait", "2", "--via", "pane", stdin=TRICKY.encode() + b"\n")
        self.assertEqual((rc, self.typed), (0, [TRICKY]), err)

    def test_utf8_survives(self) -> None:
        text = "naïve café — ✓ `x`"
        rc, _, err = self.send("peer-fb", "--message-file", self.file(text.encode()), "--wait", "2", "--via", "pane")
        self.assertEqual((rc, self.typed), (0, [text]), err)

    def test_both_the_positional_text_and_a_file_is_a_usage_error_and_sends_nothing(self) -> None:
        rc, _, err = self.send("peer-fb", "hello there friend", "--message-file", self.file(b"from a file"), "--wait", "2")
        self.assertEqual((rc, self.typed), (2, []))
        self.assertIn("not both", err)

    def test_neither_is_a_usage_error_and_sends_nothing(self) -> None:
        rc, _, err = self.send("peer-fb", "--wait", "2")
        self.assertEqual((rc, self.typed), (2, []))
        self.assertIn("--message-file", err)    # the usage line names the file form

    def test_an_empty_file_or_empty_stdin_is_a_usage_error_and_sends_nothing(self) -> None:
        for content in (b"", b"\n", b"\r\n"):
            rc, _, err = self.send("peer-fb", "--message-file", self.file(content), "--wait", "2")
            self.assertEqual((rc, self.typed), (2, []), content)
            self.assertIn("is empty", err)
        rc, _, err = self.send("peer-fb", "--message-file", "-", "--wait", "2", stdin=b"")
        self.assertEqual((rc, self.typed), (2, []))
        self.assertIn("is empty", err)

    def test_a_missing_or_non_utf8_file_is_a_usage_error_and_sends_nothing(self) -> None:
        rc, _, err = self.send("peer-fb", "--message-file", str(Path(self.tmp) / "absent.txt"), "--wait", "2")
        self.assertEqual((rc, self.typed), (2, []))
        self.assertIn("cannot read", err)
        rc, _, err = self.send("peer-fb", "--message-file", self.file(b"\xff\xfe bad"), "--wait", "2")
        self.assertEqual((rc, self.typed), (2, []))
        self.assertIn("cannot read", err)

    def test_a_file_with_a_command_that_is_not_a_send_is_refused(self) -> None:
        for argv in (["--pending"], ["--sweep"], ["--cancel", "x"], ["--retire", "x", "--reason", "r"], ["--why"]):
            rc, _, err = self.send("peer-fb", "--message-file", self.file(b"hi"), *argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn("--message-file is used with a send", err, argv)

    def test_a_multi_line_indented_file_is_folded_to_one_line_like_any_relay_text(self) -> None:
        rc, _, err = self.send("peer-fb", "--message-file", self.file(b"a:\n    b: 1\n\n  c\n"), "--wait", "2", "--via", "pane")
        self.assertEqual((rc, self.typed), (0, ["a: b: 1 c"]), err)

    def test_a_leading_bom_is_not_part_of_the_message(self) -> None:
        rc, _, err = self.send("peer-fb", "--message-file", self.file(b"\xef\xbb\xbfhello there friend\n"), "--wait", "2", "--via", "pane")
        self.assertEqual((rc, self.typed), (0, ["hello there friend"]), err)


class TestAckBeforeAFileSend(Base):
    """`relay.py --ack PEER --message-file -` (local Codex review of #211): `-` looks like an option, so no positional was counted and PEER was read as
    the id of an expectation to answer (the `--ack ID` verb) instead of the target of a send with the delivery watch on."""

    def test_split_ack_verb_leaves_a_file_send_alone_and_still_reads_the_bare_verb(self) -> None:
        for argv in (["--ack", "peer-fb", "--message-file", "-"], ["--ack", "peer-fb", "--message-file", "/tmp/m"],
                     ["--ack", "peer-fb", "--message-file=/tmp/m"], ["--message-file", "-", "--ack", "peer-fb"]):
            self.assertEqual(relay.split_ack_verb(argv), (None, argv), argv)
        self.assertEqual(relay.split_ack_verb(["--ack", "d7-k7c3f"]), ("d7-k7c3f", []))
        self.assertEqual(relay.split_ack_verb(["--ack", "d7-k7c3f", "--wait", "5"]), ("d7-k7c3f", ["--wait", "5"]))

    def test_ack_then_target_then_message_file_sends_to_the_target(self) -> None:
        for argv, stdin in ((["--ack", "peer-fb", "--message-file", "-"], TRICKY.encode() + b"\n"),
                            (["--ack", "peer-fb", "--message-file", self.file(TRICKY.encode())], None),
                            (["peer-fb", "--message-file", "-", "--ack"], TRICKY.encode())):
            self.typed.clear()
            _, _, err = self.send(*argv, "--wait", "1", "--via", "pane", stdin=stdin)
            self.assertEqual(self.typed, [TRICKY], (argv, err))
            self.assertNotIn("expectation", err, argv)
