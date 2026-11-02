#!/usr/bin/env python3
"""The question ledger of relay.py: `--ask`, `--inbox`, `--answer`, `--withdraw`, the `--cancel` guard, `--pending` and `--sweep` rows (2026-11-02).

Why: on 2026-11-02 a lead session that put a picklist to the operator was on a card for the whole round, so every reply to it queued (cap 20) and the
only way to free the queue was `--cancel`, which destroyed the replies. A decision for a lead is now a record the lead reads when it chooses. Every id,
path and text here is fake; every state lives under a temp directory (the suite never touches ~/.local/state/relay).
"""
from __future__ import annotations

import contextlib
import io
import itertools
import json
import os
import stat
import time
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay = fb.relay
LEAD, ALICE, BOB, CAROL = ("11111111-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3, 4))


class Base(fb.Harness):
    """Four Paseo rows (a lead, two askers, a bystander); the caller is the one PASEO_AGENT_ID names; the Paseo CLI and the deliverer are stubs."""

    def setUp(self) -> None:
        super().setUp()
        saved = relay.hosted_by
        relay.hosted_by = lambda a: False
        self.addCleanup(setattr, relay, "hosted_by", saved)
        self.sent: list[tuple[str, str]] = []
        self.rows = {
            "lead": fb.sess(id="11111111", name="lead", agent="claude", host="paseo", paseo=LEAD, chan=("paseo", LEAD), status="working"),
            "alice": fb.sess(id="22222222", name="alice", agent="claude", host="paseo", paseo=ALICE, chan=("paseo", ALICE), status="idle"),
            "bob": fb.sess(id="33333333", name="bob", agent="claude", host="paseo", paseo=BOB, chan=("paseo", BOB), status="idle"),
            "carol": fb.sess(id="44444444", name="carol", agent="claude", host="paseo", paseo=CAROL, chan=("paseo", CAROL), status="idle"),
        }
        relay.fleet.sessions = lambda: [dict(r, self=self.is_self(r)) for r in self.rows.values()]
        saved_links = relay.fleet.LINKS_FILE
        relay.fleet.LINKS_FILE = self.tmp / "links.json"
        self.addCleanup(setattr, relay.fleet, "LINKS_FILE", saved_links)
        relay.fleet.LINKS_FILE.write_text(json.dumps({"links": {relay.fleet.link_key(a["id"], b["id"]): {"sent": 1, "acked": None}
                                                                 for a in self.rows.values() for b in self.rows.values()}}))
        relay.paseo_inspect = lambda agent: {"Id": agent, "Status": "idle", "Cwd": "/x", "Archived": False, "PendingPermissions": []}
        relay.paseo_probe = lambda agent: (relay.paseo_inspect(agent), "ok")
        relay.paseo_card_detail = lambda agent: ("", None)
        relay.paseo_gate = lambda s: s.update(status=self.rows_status(s))

        def send(s: dict[str, Any], text: str, wait: float) -> str:
            self.sent.append((s["paseo"], text))
            return "accepted"
        relay.send_paseo = send

    def rows_status(self, s: dict[str, Any]) -> str:
        return next((r["status"] for r in self.rows.values() if r["paseo"] == s.get("paseo")), "idle")

    @staticmethod
    def is_self(row: dict[str, Any]) -> bool:
        agent = os.environ.get("PASEO_AGENT_ID")
        return bool(agent and row.get("paseo") == agent)

    def as_agent(self, agent: str | None) -> None:
        if agent is None:
            os.environ.pop("PASEO_AGENT_ID", None)
        else:
            os.environ["PASEO_AGENT_ID"] = agent

    def go(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main(list(argv), sweep=False)
        return rc, out.getvalue(), err.getvalue()

    def ask(self, asker: str = ALICE, question: str = "Merge it now", *extra: str, to: str = "lead") -> str:
        self.as_agent(asker)
        rc, out, err = self.go("--ask", to, question, "--option", "Yes, merge", "--option", "No, wait", "--recommend", "1", *extra)
        self.assertEqual(rc, 0, (out, err))
        return out.split()[1]

    def rec(self, qid: str) -> dict[str, Any]:
        r = relay.ask_read(qid)
        assert r is not None
        return r

    def patch(self, qid: str, **kw: Any) -> None:
        r = self.rec(qid)
        r.update(kw)
        relay.ask_write(r)

    def ordinary(self, n: int, target: str = LEAD) -> None:
        """N queued ordinary records addressed to TARGET (the cap of the incident: 20)."""
        now = time.time()
        for i in range(n):
            relay.rec_write({"id": f"20261102-1000{i:02d}-{i:06x}", "target": {"id": "11111111", "paseo": target, "name": "lead"}, "text": f"reply {i}",
                             "sender": "alice", "sender_ident": ALICE, "kind": "", "created": now - 100 + i, "expires": now + 20000, "state": "queued",
                             "outcome": "", "pid": 0, "notice": ""})


class TestAsk(Base):
    def test_ask_writes_a_record_and_one_nudge_outside_the_caps(self) -> None:
        self.ordinary(relay.DEFER_PER_TARGET)    # the lead's queue is full: regression for the incident's item 3
        q1 = self.ask(ALICE)
        q2 = self.ask(BOB, "Rebase first")
        a, b = self.rec(q1), self.rec(q2)
        self.assertEqual((a["state"], b["state"], a["v"], a["from"]["paseo"], b["from"]["paseo"], a["to"]["paseo"]), ("open", "open", 1, ALICE, BOB, LEAD))
        self.assertEqual((a["options"], a["recommend"], a["answer"], a["seen_by"]), (["Yes, merge", "No, wait"], 1, None, ""))
        self.assertEqual(a["from"]["fleet"], "22222222")
        self.assertRegex(a["nonce"], r"^[A-Za-z0-9_-]{16,}$")
        self.assertNotEqual(a["nonce"], b["nonce"])
        nudges = [r for r in relay.rec_all() if r.get("kind") == "nudge"]
        self.assertEqual(len(nudges), 1)    # the second ask collapsed into the first one's wake-up
        self.assertEqual((a["nudge"], b["nudge"]), (nudges[0]["id"], nudges[0]["id"]))
        self.assertEqual(self.spawned.count(nudges[0]["id"]), 1)
        self.assertEqual(sum(r.get("kind") == "" for r in relay.rec_all()), relay.DEFER_PER_TARGET)    # the ordinary queue is untouched
        self.assertEqual(nudges[0]["text"], relay.NUDGE_TEXT)
        self.assertEqual(nudges[0]["notice"], "")    # a failed wake-up tells nobody: the record is the truth
        for qid in (q1, q2):    # the ledger is the asker's expectation, closed by the answer
            self.assertEqual(relay.expect_read(qid)["state"], "open")
        self.assertEqual(stat.S_IMODE(relay.ask_path(q1).stat().st_mode), 0o600)

    def test_a_card_on_the_lead_does_not_stop_a_question(self) -> None:
        self.rows["lead"]["status"] = "blocked"
        self.rows["lead"]["paseo_state"] = "running"
        q = self.ask()
        self.assertEqual(self.rec(q)["state"], "open")
        self.assertEqual(self.sent, [])    # nothing was typed into the lead

    def test_ask_reads_the_question_from_a_file_and_folds_it(self) -> None:
        f = self.tmp / "q.txt"
        f.write_text("Use `rm -rf`?\n  and $(whoami)\n")
        self.as_agent(ALICE)
        rc, out, err = self.go("--ask", "lead", "--message-file", str(f), "--option", "A", "--option", "B")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.rec(out.split()[1])["question"], "Use `rm -rf`? and $(whoami)")

    def test_ask_refusals(self) -> None:
        opts = ("--option", "A", "--option", "B")
        self.as_agent(ALICE)
        cases = {
            "one option": ("--ask", "lead", "Q?", "--option", "A"),
            "seven options": ("--ask", "lead", "Q?", *[x for i in range(7) for x in ("--option", f"o{i}")]),
            "empty option": ("--ask", "lead", "Q?", "--option", "A", "--option", " "),
            "long option": ("--ask", "lead", "Q?", "--option", "A", "--option", "x" * 201),
            "bad recommend": ("--ask", "lead", "Q?", *opts, "--recommend", "3"),
            "this session": ("--ask", "alice", "Q?", *opts),
            "unknown lead": ("--ask", "nobody", "Q?", *opts),
            "no-defer": ("--ask", "lead", "Q?", *opts, "--no-defer"),
            "plan": ("--ask", "lead", "Q?", *opts, "--plan"),
            "idle": ("--ask", "lead", "Q?", *opts, "--idle", "5"),
            "expect-ack": ("--ask", "lead", "Q?", *opts, "--expect-ack", "x1"),
            "no text": ("--ask", "lead", *opts),
            "text and file": ("--ask", "lead", "Q?", "--message-file", "/nonexistent", *opts),
            "option without a command": ("lead", "hello there", "--option", "A"),
            "answer and ask": ("--ask", "lead", "Q?", *opts, "--answer", "q-20261102-100000-abcdef"),
        }
        for name, argv in cases.items():
            rc, out, err = self.go(*argv)
            self.assertEqual(rc, 2, (name, out, err))
        self.assertEqual(relay.ask_all(), [])
        self.as_agent(None)    # a caller nothing identifies cannot be answered
        self.assertEqual(self.go("--ask", "lead", "Q?", *opts)[0], 2)
        self.assertEqual(relay.ask_all(), [])

    def test_a_refused_ask_leaves_no_reservation(self) -> None:
        self.as_agent(ALICE)
        self.go("--ask", "lead", "Q?", "--option", "A")
        self.assertEqual(list((relay.expect_dir()).glob("q-*.json")) if relay.expect_dir().is_dir() else [], [])


class TestInbox(Base):
    def test_inbox_marks_seen_is_private_and_never_prints_the_nonce(self) -> None:
        q1, q2 = self.ask(ALICE), self.ask(BOB, "Rebase first")
        nonce = self.rec(q1)["nonce"]
        self.as_agent(CAROL)    # a bystander reads nothing and changes nothing
        self.assertEqual(self.go("--inbox"), (1, "inbox: nothing waiting\n", ""))
        self.assertEqual((self.rec(q1)["state"], self.rec(q2)["state"]), ("open", "open"))
        self.as_agent(LEAD)
        rc, out, err = self.go("--inbox")
        self.assertEqual((rc, err), (0, ""))
        self.assertLess(out.index(q1), out.index(q2))    # oldest first
        for needle in ("Q: Merge it now", "Q: Rebase first", "1. Yes, merge  (recommended)", "2. No, wait", f"--answer {q1} N"):
            self.assertIn(needle, out)
        self.assertNotIn(nonce, out)
        self.assertEqual((self.rec(q1)["state"], self.rec(q1)["seen_by"]), ("seen", LEAD))
        rc, out, _ = self.go("--inbox", "--json")    # a seen one is printed again until it is answered
        rows = json.loads(out)
        self.assertEqual((rc, [r["id"] for r in rows], [r["state"] for r in rows]), (0, [q1, q2], ["seen", "seen"]))
        self.assertTrue(all("nonce" not in r for r in rows))

    def test_inbox_all_adds_the_last_day_read_only(self) -> None:
        q = self.ask()
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q, "2")[0], 0)
        self.assertEqual(self.go("--inbox")[0], 1)
        rc, out, _ = self.go("--inbox", "--all")
        self.assertEqual(rc, 0)
        self.assertIn("answered: pick 2 by " + LEAD, out)
        self.patch(q, finished=time.time() - 2 * 86400)
        self.assertEqual(self.go("--inbox", "--all")[0], 1)

    def test_inbox_wait_returns_before_parking_and_times_out_with_124(self) -> None:
        self.ask()
        self.as_agent(LEAD)
        with mock.patch.object(relay.time, "sleep", side_effect=AssertionError("parked with a question waiting")):
            self.assertEqual(self.go("--inbox", "--wait", "30")[0], 0)    # lost-wakeup guard: the committed state is read first
        for r in relay.ask_all():
            self.patch(r["id"], state="answered", finished=time.time())
        clock = itertools.count(1_800_000_000.0, 5.0)
        with mock.patch.object(relay.time, "time", lambda: next(clock)), mock.patch.object(relay.time, "sleep"):
            rc, out, err = self.go("--inbox", "--wait", "30")
        self.assertEqual((rc, out), (124, ""))
        self.assertIn("no question arrived within 30s", err)

    def test_a_caller_with_no_session_needs_the_operator_token_to_read_any_question(self) -> None:
        q = self.ask()
        nonce = self.rec(q)["nonce"]
        self.as_agent(None)
        self.assertEqual(self.go("--inbox")[0], 2)    # any local process could otherwise read every question
        self.assertEqual(self.go("--inbox", "--json")[0], 2)
        wrong = self.tmp / "wrong.token"
        wrong.write_text("not-the-token\n")
        rc, out, err = self.go("--inbox", "--operator-token-file", str(wrong))
        self.assertEqual((rc, out), (2, ""))
        self.assertEqual(self.rec(q)["state"], "open")
        rc, out, err = self.go("--inbox", "--operator-token-file", str(relay.operator_token_path()))
        self.assertEqual((rc, self.rec(q)["state"]), (0, "open"))    # read only: it does not mark `seen`
        self.assertIn(q, out)
        self.assertNotIn(nonce, out)
        rows = json.loads(self.go("--inbox", "--json", "--operator-token-file", str(relay.operator_token_path()))[1])
        self.assertTrue(rows and all("nonce" not in r for r in rows))
        self.as_agent(BOB)    # a session reads only what is addressed to it, and a token with --mine is refused
        self.assertEqual(self.go("--inbox")[0], 1)
        self.assertEqual(self.go("--inbox", "--mine", "--operator-token-file", str(relay.operator_token_path()))[0], 2)

    def test_mine_returns_an_answer_the_deferred_send_could_not_carry_exactly_once(self) -> None:
        self.rows["alice"]["agent"], self.rows["alice"]["status"] = "cline", "working"    # cannot steer: the `ack` line must queue
        q = self.ask(ALICE)
        q_other = self.ask(BOB, "Rebase first")
        self.ordinary(relay.DEFER_PER_TARGET, target=ALICE)    # the asker's queue is full: the ack send is refused
        self.as_agent(LEAD)
        rc, out, err = self.go("--answer", q, "2", "--note", "later")
        self.assertEqual(rc, 1, (out, err))
        r = self.rec(q)
        self.assertEqual((r["state"], r["answer"]["pick"]), ("answered", 2))
        self.assertTrue(r["answer"]["delivery"].startswith("failed: "), r["answer"]["delivery"])
        self.assertEqual(sum(x.get("kind") == "" and x["text"].startswith("ack ") for x in relay.rec_all()), 0)    # nothing reached the queue
        self.as_agent(ALICE)
        rc, out, _ = self.go("--inbox", "--mine", "--json")
        rows = json.loads(out)
        self.assertEqual((rc, [x["id"] for x in rows]), (0, [q]))    # Bob's question is not Alice's
        self.assertEqual((rows[0]["answer"]["pick"], rows[0]["answer"]["text"], rows[0]["answer"]["note"]), (2, "No, wait", "later"))
        self.assertNotIn("nonce", rows[0])
        self.assertTrue(self.rec(q)["answer"]["seen_by_asker"])
        self.assertEqual(self.go("--inbox", "--mine")[0], 1)    # exactly once in "unseen"
        rc, out, _ = self.go("--inbox", "--mine", "--all")
        self.assertEqual((rc, q in out), (0, True))
        self.as_agent(BOB)
        self.assertEqual(self.go("--inbox", "--mine")[0], 1)    # its own is still open
        self.assertEqual(self.rec(q_other)["state"], "open")
        self.as_agent(CAROL)
        self.assertEqual(self.go("--inbox", "--mine", "--all")[0], 1)

    def test_mine_prints_in_full_oldest_first_and_refuses_what_it_cannot_tie_to_a_session(self) -> None:
        q1, q2 = self.ask(ALICE, "First one"), self.ask(ALICE, "Second one")
        self.as_agent(LEAD)
        self.go("--answer", q2, "1")
        self.go("--answer", q1, "2")
        self.as_agent(ALICE)
        self.assertEqual(self.go("--inbox", "--mine", "--wait", "5")[0], 2)
        rc, out, _ = self.go("--inbox", "--mine")
        self.assertEqual(rc, 0)
        self.assertLess(out.index(q1), out.index(q2))
        self.assertIn("Q: First one", out)
        self.as_agent(None)
        self.assertEqual(self.go("--inbox", "--mine")[0], 2)


class TestAnswer(Base):
    def lead_answers(self, q: str, *extra: str) -> tuple[int, str, str]:
        self.as_agent(LEAD)
        return self.go("--answer", q, *extra)

    def test_answer_once_sends_the_ack_line_and_then_goes_stale(self) -> None:
        q = self.ask()
        os.environ.pop("RELAY_NO_ACK", None)    # the default delivery watch of an agent session: its proof is what closes the expectation
        with mock.patch.object(relay, "ack_watch", lambda c, w: ("delivered", "")):
            rc, out, err = self.lead_answers(q, "2", "--note", "after lunch")
        self.assertEqual((rc, err), (0, ""), out)
        r = self.rec(q)
        self.assertEqual((r["state"], r["answer"]["pick"], r["answer"]["text"], r["answer"]["by"], r["answer"]["delivery"], r["answer"]["note"]),
                         ("answered", 2, "No, wait", LEAD, "delivered", "after lunch"))
        self.assertEqual([t.split("] ", 1)[1] for p, t in self.sent if p == ALICE], [f"ack {q} pick 2: No, wait \u2014 after lunch"])    # under the lead's `[relay from ...]` header
        self.assertEqual(relay.expect_read(q)["state"], "acked")    # the answer closed the asker's expectation
        self.sent.clear()
        rc, out, err = self.lead_answers(q, "1")    # a second answer is refused and prints the first one
        self.assertEqual((rc, self.sent), (10, []))
        self.assertIn("pick 2 (No, wait)", err)
        self.assertEqual(self.rec(q)["answer"]["pick"], 2)

    def test_a_withdrawn_or_expired_question_is_11_and_a_bad_number_is_2_before_any_write(self) -> None:
        q1, q2, q3 = self.ask(), self.ask(BOB, "Rebase first"), self.ask(ALICE, "Third")
        self.as_agent(ALICE)
        self.assertEqual(self.go("--withdraw", q1)[0], 0)
        self.patch(q2, expires=time.time() - 1)
        before = self.rec(q3)
        for n in ("0", "3", "9"):
            self.assertEqual(self.lead_answers(q3, n)[0], 2, n)
        self.assertEqual(self.rec(q3), before)
        self.assertEqual(self.lead_answers(q1, "1")[0], 11)
        self.assertEqual(self.lead_answers(q2, "1")[0], 11)
        self.assertEqual(self.rec(q2)["state"], "expired")    # the clock decided, no sweep needed
        self.assertEqual(self.sent, [])
        self.assertEqual(self.lead_answers("q-20261102-100000-abcdef", "1")[0], 2)    # unknown
        self.assertEqual(self.lead_answers(q3, "x")[0], 2)

    def test_a_route_that_cannot_prove_it_was_read_is_handed_over_not_failed(self) -> None:
        q = self.ask()
        os.environ.pop("RELAY_NO_ACK", None)
        with mock.patch.object(relay, "ack_watch", lambda c, w: ("unverified", "this route has no transcript to read")):
            rc, out, err = self.lead_answers(q, "1")
        self.assertEqual(rc, 0, (out, err))    # Paseo agents have no transcript: exit 1 here would send every lead to re-route a delivered answer
        self.assertTrue(self.rec(q)["answer"]["delivery"].startswith("unverified: "))
        self.assertIn("do not resend", out)

    def test_answer_queued_when_the_asker_is_working(self) -> None:
        self.rows["alice"]["agent"], self.rows["alice"]["status"] = "cline", "working"    # cannot steer: the line queues (DEFERRED SEND)
        q = self.ask()
        rc, out, err = self.lead_answers(q, "1")
        r = self.rec(q)
        queued = [x for x in relay.rec_all() if x.get("kind") == "" and x["text"].startswith(f"ack {q} pick 1")]
        self.assertEqual(len(queued), 1, (out, err))
        self.assertEqual((rc, r["state"], r["answer"]["delivery"], self.sent), (1, "answered", queued[0]["id"], []))
        self.assertEqual(relay.expect_read(q)["state"], "open")    # not closed until the queued line is delivered
        relay.resolve_deferred_ack(queued[0])    # what the deliverer does once it has sent it
        self.assertEqual(relay.expect_read(q)["state"], "acked")

    def test_answer_is_refused_for_any_other_agent_and_a_forged_operator(self) -> None:
        q = self.ask()
        nonce, token = self.rec(q)["nonce"], relay.operator_token_path()
        tokfile = self.tmp / "copy.token"
        tokfile.write_text("not-the-token\n")
        self.as_agent(BOB)
        self.assertEqual(self.go("--answer", q, "1")[0], 2)    # another agent
        self.assertEqual(self.go("--answer", q, "1", "--nonce", nonce)[0], 2)    # the nonce alone is no authority
        self.assertEqual(self.go("--answer", q, "1", "--nonce", nonce, "--operator-token-file", str(tokfile))[0], 2)    # a wrong token
        self.as_agent(None)    # no session is no authority either (the first design of this: forgeable)
        self.assertEqual(self.go("--answer", q, "1")[0], 2)
        self.assertEqual(self.go("--answer", q, "1", "--operator-token-file", str(token))[0], 2)    # the token without the nonce
        self.assertEqual(self.go("--answer", q, "1", "--nonce", "wrong", "--operator-token-file", str(token))[0], 2)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q, "1", "--nonce", "wrong")[0], 2)    # a lead that gives a nonce gives the right one
        self.assertEqual((self.rec(q)["state"], self.sent), ("open", []))

    def test_the_operator_answers_with_the_nonce_and_the_token_file(self) -> None:
        q = self.ask()
        self.assertTrue(relay.operator_token_path().is_file())    # made on the first question
        self.assertEqual(stat.S_IMODE(relay.operator_token_path().stat().st_mode), 0o600)
        nonce = self.rec(q)["nonce"]
        self.as_agent(None)
        rc, out, err = self.go("--answer", q, "1", "--nonce", nonce, "--operator-token-file", str(relay.operator_token_path()), "--via-label", "decisions-screen")
        self.assertEqual((rc, err), (0, ""), out)
        a = self.rec(q)["answer"]
        self.assertEqual((a["by"], a["via"], a["pick"], a["delivery"]), ("operator", "decisions-screen", 1, "delivered"))
        self.assertEqual([t for p, t in self.sent if p == ALICE], [f"[relay from operator] ack {q} pick 1: Yes, merge"])
        self.assertEqual(relay.expect_read(q)["state"], "acked")
        self.assertEqual(self.go("--answer", q, "2", "--nonce", nonce, "--operator-token-file", str(relay.operator_token_path()))[0], 10)

    def test_the_operator_answer_queues_under_its_own_label_when_the_asker_is_working(self) -> None:
        self.rows["alice"]["agent"], self.rows["alice"]["status"] = "cline", "working"
        q = self.ask()
        nonce = self.rec(q)["nonce"]
        self.as_agent(None)
        rc, out, err = self.go("--answer", q, "2", "--nonce", nonce, "--operator-token-file", str(relay.operator_token_path()))
        queued = [x for x in relay.rec_all() if x.get("kind") == "" and x["text"].startswith(f"ack {q}")]
        self.assertEqual((rc, len(queued), queued[0]["sender"] if queued else None), (1, 1, "operator"), (out, err))
        self.assertEqual(self.rec(q)["answer"]["delivery"], queued[0]["id"])

    def test_a_token_file_that_is_a_symlink_proves_nothing(self) -> None:
        q = self.ask()
        link = self.tmp / "link.token"
        link.symlink_to(relay.operator_token_path())
        self.as_agent(None)
        rc = self.go("--answer", q, "1", "--nonce", self.rec(q)["nonce"], "--operator-token-file", str(link))[0]
        self.assertEqual((rc, self.rec(q)["state"]), (2, "open"))


class TestWithdrawCancelPendingSweep(Base):
    def test_withdraw_only_by_the_asker_and_the_lead_sees_it_once(self) -> None:
        q = self.ask()
        self.as_agent(BOB)
        self.assertEqual(self.go("--withdraw", q)[0], 2)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--withdraw", q)[0], 2)
        self.as_agent(ALICE)
        self.assertEqual(self.go("--withdraw", q)[0], 0)
        self.assertEqual(self.rec(q)["state"], "withdrawn")
        self.assertEqual(self.go("--withdraw", q)[0], 11)
        self.assertEqual(relay.expect_read(q)["state"], "retired")    # no OVERDUE page for a question nobody waits on
        self.as_agent(LEAD)
        rc, out, _ = self.go("--inbox")
        self.assertEqual(rc, 0)
        self.assertIn("WITHDRAWN by its asker", out)
        self.assertEqual(self.go("--inbox")[0], 1)    # shown once

    def test_cancel_refuses_a_queued_record_addressed_to_the_caller(self) -> None:
        self.ordinary(3)
        rid = relay.rec_all()[0]["id"]
        self.as_agent(LEAD)
        rc, out, err = self.go("--cancel", rid)
        self.assertEqual(rc, 2)
        self.assertIn("addressed to you", err)
        self.assertEqual(relay.rec_read(rid)["state"], "queued")
        self.as_agent(ALICE)    # its sender (or anyone else) still can
        self.assertEqual(self.go("--cancel", rid)[0], 0)
        self.assertEqual(relay.rec_read(rid)["state"], "cancelled")
        self.as_agent(None)    # the operator in a shell keeps today's behaviour
        self.assertEqual(self.go("--cancel", relay.rec_all()[1]["id"])[0], 0)

    def test_pending_lists_asks_without_the_question_and_the_filters_leave_them_out(self) -> None:
        q = self.ask(ALICE, "Secret question text")
        rc, out, _ = self.go("--pending")
        self.assertEqual(rc, 0)
        self.assertRegex(out, rf"ask {q}  open +\[11111111\] lead  from .*alice.*  0m old  2 options")
        self.assertNotIn("Secret question", out)
        self.assertIn("| Secret question text", self.go("--pending", "--text")[1])
        rows = [r for r in json.loads(self.go("--pending", "--json")[1]) if r.get("kind") == "ask"]
        self.assertEqual([(r["id"], r["state"], r["options"]) for r in rows], [(q, "open", 2)])
        self.assertNotIn("question_preview", rows[0])
        self.assertEqual([r for r in json.loads(self.go("--pending", "--json", "--queued-only")[1]) if r.get("kind") == "ask"], [])

    def test_sweep_expires_and_prunes_asks(self) -> None:
        q1, q2, q3 = self.ask(), self.ask(BOB, "Rebase first"), self.ask(ALICE, "Third")
        self.patch(q1, expires=time.time() - 5)
        self.patch(q3, state="answered", finished=time.time() - relay.DEFER_KEEP - 10)
        rc, out, _ = self.go("--sweep")
        self.assertEqual(rc, 0)
        self.assertIn("asks: 1 expired, 1 pruned", out)
        self.assertEqual((self.rec(q1)["state"], self.rec(q2)["state"], relay.ask_read(q3)), ("expired", "open", None))
        self.assertIn("asks: 0 expired, 0 pruned", self.go("--sweep")[1])

    def test_a_sweep_without_a_ledger_prints_what_it_always_printed(self) -> None:
        self.assertNotIn("asks:", self.go("--sweep")[1])
        self.assertFalse(relay.ask_root().exists())
