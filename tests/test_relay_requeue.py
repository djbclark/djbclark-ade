#!/usr/bin/env python3
"""A queued message is shaped ONCE, at queue time (2026-10-29).

The queueing run applied the reply rule, appended the `[reply through relay.py ...]` footer and reserved the
expectation for its text. The deliverer's re-send is not a new message, so it says `--requeued [EXPECT_ID]`: it
neither re-judges the text nor appends a second footer, and it writes no second link and no second expectation.
A deliverer also has no session of its own (it runs under SENDER_OVERRIDE with the sender's Paseo id only so
`paseo send` can attribute the message), so it can never resolve a `self` row and open an expectation nobody
could answer.

The failure this pins (2026-10-29): a queued question to Dann 7 was refused at re-send with "this message asks
for a reply or action, so it needs --expect-ack ID" and never arrived; the same path would have appended a
footer naming the sender itself and written a duplicate link. Every id here is fake.

Two boundaries the adversary round found and this pins: `--requeued` is internal (an ordinary session is refused,
because taken from one it would send a question with no footer, no link and no expectation), and the stored
`shape.expect` is validated before it can become an argument (a record is a JSON file; a value like `--pending`
would otherwise run the queue listing, exit 0, and be marked delivered).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import time
import unittest
from typing import Any

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet, sess, stamp = fb.relay, fb.fleet, fb.sess, fb.stamp
REAL_SLEEP = time.sleep
ME_SID = "dddddddd-0000-4000-8000-000000000004"
QUESTION = "does the pilot wait behind PR 131, or is its scope drafted now?"
FOOTER = "[reply through relay.py to bbbbbbbb: ack build1]"


class Base(fb.Harness):
    """A sender's own `self` row (with a transcript), so a run that resolves one is visible, and an idle pane target."""

    def setUp(self) -> None:
        super().setUp()    # RELAY_NO_ACK stays "1": no delivery watch rides on these sends
        saved = fleet.LINKS_FILE
        fleet.LINKS_FILE = self.tmp / "links.json"
        self.addCleanup(setattr, fleet, "LINKS_FILE", saved)
        self.me_tx = self.tmp / "me.jsonl"
        self.me_tx.write_text("{}\n")
        self.tx = self.tmp / "t.jsonl"
        self.tx.write_text("{}\n")
        self.me = sess(id="bbbbbbbb", name="alice", sid=ME_SID, chan=("herdr", "w1:p1"), status="working", transcript=str(self.me_tx))
        self.me["self"] = True
        self.target = sess(transcript=str(self.tx), status="idle")
        self.sent_texts: list[str] = []

        def typed(chan: Any, text: str) -> bool:
            self.calls.append("type")
            self.sent_texts.append(text)
            # The route proves a send by finding it in the transcript: write it as the target TUI writes it.
            line: dict[str, Any] = ({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}
                                    if self.tx_agent == "codex" else {"type": "user", "message": {"role": "user", "content": text}})
            with self.tx.open("a") as fh:
                fh.write(json.dumps(line) + "\n")
            return True
        relay.type_line = typed
        self.tx_agent = "claude"
        saved_sleep = relay.time.sleep
        relay.time.sleep = lambda n: REAL_SLEEP(0.01)    # a deliverer's own backoff: never a real wait
        self.addCleanup(setattr, relay.time, "sleep", saved_sleep)

    def rows(self, target: dict[str, Any] | None = None) -> None:
        t = target or self.target
        relay.fleet.sessions = lambda: [t, self.me]

    def go(self, text: str, *argv: str, rows: list[dict[str, Any]] | None = None, to: str = "peer-fb") -> tuple[int, str, str]:
        relay.fleet.sessions = lambda: [self.target, *(rows if rows is not None else [self.me])]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main([to, text, "--wait", "1", *argv])
        return rc, out.getvalue(), err.getvalue()

    def resend(self, text: str, *argv: str) -> tuple[int, str]:
        """A run as the DELIVERER runs one: inside `as_caller(...)`, where SENDER_OVERRIDE is set. (rc, last line)."""
        self.rows()
        return relay.run_captured(["peer-fb", text, "--wait", "1", *argv], relay.sender_label(self.me))

    def record(self, text: str = "", **kw: Any) -> dict[str, Any]:
        """A queued record as a deliverer finds it: `shape` only when KW has it (a record from before 2026-10-29 has none)."""
        rec = {"id": "20261029-200457-aaaaaa", "text": text or f"{QUESTION} [reply through relay.py to bbbbbbbb: ack build1]",
               "target": {"id": "cccccccc", "paseo": "", "name": "peer-fb", "agent": "claude", "sid": fb.SID,
                          "transcript": str(self.tx), "pid": 0},
               "sender": relay.sender_label(self.me), "sender_ident": "bbbbbbbb", "sender_paseo": "", "kind": "", "hops": 0,
               "created": time.time(), "expires": time.time() + 3600, "state": "queued", "outcome": "", "pid": 0, "notice": ""}
        rec.update(kw)
        relay.rec_write(rec)
        return rec

    def deliver(self, rid: str, target: dict[str, Any] | None = None) -> tuple[int, list[list[str]]]:
        """`relay.py --deliver RID` with the inner send's argv recorded: (exit code, the inner argv of every re-send)."""
        argv: list[list[str]] = []
        real = relay.run_captured

        def spy(a: list[str], sender: str, **kw: Any) -> tuple[int, str]:
            argv.append(list(a))
            return real(a, sender, **kw)
        relay.run_captured = spy
        self.addCleanup(setattr, relay, "run_captured", real)
        row = {**(target or self.target), "status": "idle"}
        self.tx_agent = row.get("agent") or "claude"
        self.rows(row)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.deliver(rid)
        return rc, argv

    def links(self) -> dict[str, Any]:
        return fleet.links_read()["links"]


class TestTheDelivererResendsWhatWasQueued(Base):
    def test_a_queued_question_arrives_unchanged_with_one_footer_and_one_link(self) -> None:
        pane = {**self.target, "agent": "codex", "status": "working"}    # a pane TUI that cannot steer: the send is queued
        relay.fleet.sessions = lambda: [pane, self.me]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main(["peer-fb", QUESTION, "--wait", "1", "--expect-ack", "build1"])
        self.assertEqual(rc, 0, (out.getvalue(), err.getvalue()))
        rec = relay.rec_all()[0]
        self.assertTrue(out.getvalue().startswith(f"queued: {rec['id']} "), out.getvalue())
        self.assertEqual(rec["shape"], {"expect": "build1", "fyi": False, "needs_reply": False})
        self.assertTrue(rec["text"].endswith(FOOTER), rec["text"])
        self.assertEqual(len(self.links()), 1)
        self.assertEqual(relay.expect_read("build1")["state"], "open")

        rc, argv = self.deliver(rec["id"], pane)    # the same row it was queued against, now idle
        self.assertEqual(rc, 0)
        self.assertEqual(len(argv), 1, argv)
        self.assertIn("--requeued=build1", argv[0])    # the expectation the queueing run reserved: never re-reserved here, and bound with `=` so a value can never read as an option
        self.assertIn("--no-defer", argv[0])
        self.assertIn("--no-ack", argv[0])
        self.assertEqual(self.sent_texts, [rec["text"]])    # not one character added: no second footer, no `?` refusal
        self.assertEqual(self.sent_texts[0].count("reply through relay.py"), 1)
        self.assertEqual(relay.rec_read(rec["id"])["state"], "delivered")
        self.assertEqual(len(self.links()), 1)
        self.assertEqual(next(iter(self.links().values()))["sent"], 1)    # the re-send wrote no second link
        self.assertEqual(relay.expect_read("build1")["state"], "open")    # and answered nothing on the sender's behalf

    def test_a_record_queued_before_the_shape_existed_is_resent_with_a_bare_flag(self) -> None:
        rec = self.record()    # no "shape": queued by the code that never stored one
        self.assertNotIn("shape", rec)
        rc, argv = self.deliver(rec["id"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(argv), 1, argv)
        self.assertEqual(argv[0][-1], "--requeued")    # no ID to carry, and none invented
        self.assertEqual(self.sent_texts, [rec["text"]])
        self.assertEqual(relay.rec_read(rec["id"])["state"], "delivered")

    def test_a_deliverer_has_no_session_of_its_own_so_it_cannot_open_an_expectation(self) -> None:
        """The root cause: the deliverer's env names the SENDER's Paseo id (so `paseo send` can attribute the message),
        which makes fleet mark the sender's own row `self`. That row is not this process's session: nothing here can be answered."""
        self.rows()
        self.assertTrue([r for r in relay.fleet.sessions() if r.get("self")], "the fixture must hold a `self` row")
        rc, line = relay.run_captured([self.target["id"], "is the build green?", "--no-defer", "--no-ack", "--expect-ack", "build2"],
                                      relay.sender_label(self.me))
        self.assertEqual(rc, 2, line)
        self.assertIn("needs a session an answer can reach", line)
        self.assertIsNone(relay.expect_read("build2"))
        self.assertEqual(relay.rec_all(), [])
        self.assertEqual(self.sent_texts, [])


class TestTheQueueTimeRuleStillHolds(Base):
    def test_an_ordinary_question_from_a_session_still_needs_expect_ack(self) -> None:
        rc, _, err = self.go(QUESTION)    # the gate is unchanged: only a re-send is exempt
        self.assertEqual(rc, 2)
        self.assertIn("asks for a reply or action", err)
        self.assertEqual((self.sent_texts, relay.rec_all()), ([], []))

    def test_an_ordinary_session_cannot_requeue(self) -> None:
        """`--requeued` is the deliverer's own flag: taken from a session it would be a way to send a question with no
        footer, no link and no expectation, which is exactly what the reply gate exists to prevent."""
        rc, _, err = self.go(QUESTION, "--needs-reply", "--requeued", "build1")
        self.assertEqual(rc, 2, err)
        self.assertIn("--requeued is internal", err)
        self.assertEqual((self.sent_texts, relay.rec_all()), ([], []))

    def test_a_requeued_send_is_not_judged_and_gets_no_new_footer(self) -> None:
        rec = self.record()
        rc, line = self.resend(rec["text"], "--requeued=build1")    # the deliverer's own run, inside as_caller(...)
        self.assertEqual(rc, 0, line)
        self.assertEqual(self.sent_texts, [rec["text"]])
        self.assertIsNone(relay.expect_read("build1"))    # nothing reserved again
        self.assertEqual(self.links(), {})                 # and no link written by a re-send

    def test_requeued_and_expect_ack_are_exclusive(self) -> None:
        rc, line = self.resend(QUESTION, "--requeued=build1", "--expect-ack", "build1")
        self.assertEqual(rc, 2, line)
        self.assertIn("exclusive", line)
        self.assertEqual(self.sent_texts, [])

    def test_a_malformed_requeued_id_is_refused(self) -> None:
        rc, line = self.resend(QUESTION, "--requeued", "not an id")
        self.assertEqual(rc, 2, line)
        self.assertIn("--requeued EXPECT_ID", line)
        self.assertEqual(self.sent_texts, [])


class TestAMalformedStoredShapeIsNeverSent(Base):
    def test_a_tampered_shape_expect_fails_the_record_and_sends_nothing(self) -> None:
        """A record is a plain JSON file: its stored value reaches the inner run's argv, so a value that parses as an
        OPTION (not an id) must fail the record rather than run `--pending` and report it delivered."""
        for bad in ("--pending", "--cancel=20261029-200457-aaaaaa", "-x", "not an id"):
            with self.subTest(bad=bad):
                rec = self.record(shape={"expect": bad, "fyi": False, "needs_reply": False})
                rc, argv = self.deliver(rec["id"])
                self.assertEqual(rc, 0)
                self.assertFalse([a for a in argv if any("--requeued" in x for x in a)], argv)    # no re-send was built
                self.assertFalse([a for a in argv if rec["text"] in a], argv)
                self.assertEqual(self.sent_texts, [])
                got = relay.rec_read(rec["id"])
                self.assertEqual(got["state"], "failed")
                self.assertIn("shape.expect is malformed", got["outcome"])
                self.assertEqual(self.links(), {})


class TestTheShapeIsStoredAtQueueTime(Base):
    def test_defer_send_keeps_expect_fyi_and_needs_reply(self) -> None:
        pane = {**self.target, "agent": "codex", "status": "working"}
        relay.fleet.sessions = lambda: [pane, self.me]
        # (argv after the text, text, the shape the deliverer must resend)
        cases = [(["--expect-ack", "q1"], "question 0?", {"expect": "q1", "fyi": False, "needs_reply": False}),
                 (["--fyi"], "question 1?", {"expect": "", "fyi": True, "needs_reply": False}),
                 (["--needs-reply", "--expect-ack", "q2"], "question 2?", {"expect": "q2", "fyi": False, "needs_reply": True}),
                 ([], "status: the build is green", {"expect": "", "fyi": False, "needs_reply": False})]
        for argv, text, want in cases:
            args = ["peer-fb", text, "--wait", "1", "--defer-for", "60", *argv]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(relay.main(args), 0, argv)
            rec = max(relay.rec_all(), key=lambda r: r["created"])
            self.assertEqual(rec["shape"], want, argv)
        self.assertEqual(len(relay.rec_all()), len(cases))
        self.assertEqual(self.sent_texts, [])    # queued, never sent while the pane works


if __name__ == "__main__":
    unittest.main()
