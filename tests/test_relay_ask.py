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
import threading
import time
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay = fb.relay
LEAD, ALICE, BOB, CAROL = ("11111111-0000-4000-8000-00000000000%d" % i for i in (1, 2, 3, 4))
MALLORY = "99999999-0000-4000-8000-000000000009"    # a Paseo agent that is nobody's lead or asker
FAKE_PID = 424242    # the process Paseo's daemon hosts for the caller, in the ancestry the tests give relay
CSID = "dddddddd-0000-4000-8000-0000000000d4"    # a Claude session id


class Base(fb.Harness):
    """Four Paseo rows (a lead, two askers, a bystander). The caller's identity is modelled the way the machine proves it: `as_agent(X)` makes FAKE_PID, an ancestor of
    this process, the process Paseo's daemon hosts for X (`where.paseo_agent` is the seam; relay.hosted_by and the ledger's identity_proven run for real), and also exports
    PASEO_AGENT_ID, which fleet takes for `self`. `as_forged(X)` only exports the variable. The Paseo CLI and the deliverer are stubs."""

    def setUp(self) -> None:
        super().setUp()
        self.hosting: dict[int, str] = {}
        for obj, name, val in ((relay.fleet, "ancestors", lambda: {FAKE_PID}), (relay.where, "env_of", lambda pid: {}),
                               (relay.where, "paseo_agent", lambda pid, env: self.hosting.get(pid))):
            patcher = mock.patch.object(obj, name, val)
            patcher.start()
            self.addCleanup(patcher.stop)
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
        """fleet's own rule, which is forgeable: a Paseo row is `self` by PASEO_AGENT_ID alone, a Claude row by CLAUDE_CODE_SESSION_ID alone, a herdr row by HERDR_PANE_ID."""
        agent, csid, pane = os.environ.get("PASEO_AGENT_ID"), os.environ.get("CLAUDE_CODE_SESSION_ID"), os.environ.get("HERDR_PANE_ID")
        chan = row.get("chan") or (None, None)
        return (bool(agent and row.get("paseo") == agent) or bool(csid and row.get("agent") == "claude" and row.get("sid") == csid and not row.get("paseo"))
                or bool(pane and chan[0] == "herdr" and chan[1] == pane))

    def as_agent(self, agent: str | None) -> None:
        """The caller is Paseo agent AGENT: its process is hosted by it, and the variable says so. None: a process with no session at all."""
        self.hosting.clear()
        if agent is None:
            os.environ.pop("PASEO_AGENT_ID", None)
        else:
            os.environ["PASEO_AGENT_ID"] = agent
            self.hosting[FAKE_PID] = agent

    def as_forged(self, agent: str, hosted_by: str | None = None) -> None:
        """A process that merely exports PASEO_AGENT_ID=AGENT; it may genuinely be hosted by HOSTED_BY, another agent."""
        self.hosting.clear()
        os.environ["PASEO_AGENT_ID"] = agent
        if hosted_by:
            self.hosting[FAKE_PID] = hosted_by

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
        self.assertEqual([t.rsplit("] ", 1)[-1] if t.startswith("[relay from") else t for p, t in self.sent if p == ALICE], [f"ack {q} pick 2: No, wait \u2014 after lunch"])    # a hosted lead is labelled by Paseo itself; a header, when there is one, is not the text
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


def run_bounded(fn: Any, seconds: float = 10) -> Any:
    """FN() in a thread, failing the test (not hanging the suite) when it does not return: what a FIFO would do to an unguarded open."""
    box: list[Any] = []
    t = threading.Thread(target=lambda: box.append(fn()), daemon=True)
    t.start()
    t.join(seconds)
    assert box, f"{fn} did not return within {seconds}s"
    return box[0]


class TestIdentityIsProven(Base):
    """A process with no identity cannot forge an answer (Argon review of PR 261, P1-1/P1-2): fleet marks a row `self` from PASEO_AGENT_ID or CLAUDE_CODE_SESSION_ID alone, and
    `sender_row` returns a lone `self` row unchecked, so every ledger command proves the caller (identity_proven) before it trusts it."""

    def setup_questions(self) -> tuple[str, str]:
        q_open = self.ask(ALICE, "Merge it now")
        q_done = self.ask(BOB, "Rebase first")
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q_done, "1")[0], 0)
        self.sent.clear()
        return q_open, q_done

    def test_a_forged_paseo_agent_id_is_refused_by_every_ledger_command(self) -> None:
        q_open, q_done = self.setup_questions()
        asks = len(relay.ask_all())
        before = {r["id"]: r for r in relay.ask_all()}
        for hosted in (None, MALLORY):    # a process nothing hosts, and one genuinely hosted by ANOTHER agent that exports the lead's id
            self.as_forged(LEAD, hosted)
            self.assertEqual(self.go("--answer", q_open, "1")[0], 2, hosted)
            self.assertEqual(self.go("--inbox")[0], 2, hosted)
            self.assertEqual(self.go("--inbox", "--json")[0], 2, hosted)
            self.as_forged(ALICE, hosted)
            self.assertEqual(self.go("--withdraw", q_open)[0], 2, hosted)
            self.assertEqual(self.go("--ask", "lead", "Impersonated?", "--option", "A", "--option", "B")[0], 2, hosted)
            self.as_forged(BOB, hosted)
            self.assertEqual(self.go("--inbox", "--mine")[0], 2, hosted)
        self.assertEqual({r["id"]: r for r in relay.ask_all()}, before)    # no question was read, answered, withdrawn, marked seen or added
        self.assertEqual((len(relay.ask_all()), self.sent), (asks, []))

    def test_the_genuine_session_is_still_served_beside_the_forger(self) -> None:
        q_open, q_done = self.setup_questions()
        self.as_forged(LEAD, MALLORY)
        self.assertEqual(self.go("--inbox")[0], 2)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--inbox")[0], 0)
        self.as_agent(BOB)
        self.assertEqual(self.go("--inbox", "--mine")[0], 0)
        self.as_agent(ALICE)
        self.assertEqual(self.go("--withdraw", q_open)[0], 0)

    def test_a_claude_session_id_in_the_environment_is_proved_by_the_registry_only(self) -> None:
        self.rows["claudy"] = fb.sess(id="c1c1c1c1", name="claudy", agent="claude", sid=CSID, status="idle", chan=("herdr", "w9:p9"))
        self.as_agent(None)
        os.environ["CLAUDE_CODE_SESSION_ID"] = CSID    # fleet takes this row for `self` on the variable alone
        argv = ("--ask", "lead", "Q?", "--option", "A", "--option", "B")
        self.assertEqual(self.go(*argv)[0], 2)
        self.assertEqual(relay.ask_all(), [])
        sessions = self.tmp / "claude" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "777.json").write_text(json.dumps({"pid": 777, "sessionId": CSID}))
        os.environ.update(CLAUDE_CONFIG_DIR=str(self.tmp / "claude"), CLAUDE_PID="777")
        with mock.patch.object(relay.fleet, "ancestors", lambda: {777}):    # the real claude_identity: CLAUDE_PID is an ancestor and its registry file names the session
            rc, out, err = self.go(*argv)
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual([r["from"]["fleet"] for r in relay.ask_all()], ["c1c1c1c1"])

    def test_a_pane_that_a_new_session_now_holds_is_not_the_old_lead(self) -> None:
        row = fb.sess(id="55555555", name="hlead", agent="cline", sid="eeeeeeee-0000-4000-8000-0000000000e1", status="working", chan=("herdr", "w5:p5"))
        row["pid"] = FAKE_PID
        self.rows["hlead"] = row
        q = self.ask(ALICE, "Merge it now", to="hlead")
        self.assertEqual(self.rec(q)["to"]["sid"], row["sid"])
        self.as_agent(None)
        os.environ["HERDR_PANE_ID"] = "w5:p5"
        row["sid"] = "eeeeeeee-0000-4000-8000-0000000000e2"    # the next TUI in the same pane: same pane id, another session
        self.assertEqual(self.go("--inbox")[0], 1)    # nothing is addressed to it
        self.assertEqual(self.go("--answer", q, "1")[0], 2)
        self.assertEqual(self.rec(q)["state"], "open")
        row["sid"] = self.rec(q)["to"]["sid"]    # the lead itself
        self.assertEqual(self.go("--inbox")[0], 0)
        self.assertEqual(self.rec(q)["state"], "seen")


class TestLockDiscipline(Base):
    """One discipline: re-read under the ledger lock for every transition (Argon P1-3, P1-4, P2-3)."""

    def during_nudge(self, act: Any) -> Any:
        orig = relay.queue_nudge

        def hook(s: dict[str, Any], listed: Any) -> Any:
            saved = dict(relay.CTX)    # `act` is a whole relay run of its own in this process: ask_cmd's context is put back after it
            try:
                act()
            finally:
                relay.CTX.clear()
                relay.CTX.update(saved)
            return orig(s, listed)
        return mock.patch.object(relay, "queue_nudge", hook)

    def test_an_answer_during_the_nudge_window_leaves_the_expectation_settled(self) -> None:
        def operator_answers() -> None:
            q = relay.ask_all()[-1]
            self.as_agent(None)
            self.assertEqual(self.go("--answer", q["id"], "1", "--nonce", q["nonce"], "--operator-token-file", str(relay.operator_token_path()))[0], 0)
        self.as_agent(ALICE)
        with self.during_nudge(operator_answers):
            rc, out, err = self.go("--ask", "lead", "Q?", "--option", "A", "--option", "B")
        self.assertEqual(rc, 0, (out, err))
        q = relay.ask_all()[-1]["id"]
        self.assertEqual((self.rec(q)["state"], relay.expect_read(q)["state"]), ("answered", "acked"))    # main's link bookkeeping did not reopen it

    def test_a_withdrawal_during_the_nudge_window_leaves_the_expectation_retired(self) -> None:
        def asker_withdraws() -> None:
            self.assertEqual(self.go("--withdraw", relay.ask_all()[-1]["id"])[0], 0)
        self.as_agent(ALICE)
        with self.during_nudge(asker_withdraws):
            self.assertEqual(self.go("--ask", "lead", "Q?", "--option", "A", "--option", "B")[0], 0)
        q = relay.ask_all()[-1]["id"]
        self.assertEqual((self.rec(q)["state"], relay.expect_read(q)["state"]), ("withdrawn", "retired"))

    def test_the_delivery_merge_keeps_seen_by_asker_set_while_the_answer_was_being_sent(self) -> None:
        q = self.ask(ALICE)

        def asker_reads_during_the_send(asker: str, line: str, operator: bool) -> tuple[int, str, str]:
            relay.ask_transition(q, ("answered",), derive=lambda r: {"answer": {**r["answer"], "seen_by_asker": 1234.5}})    # what `--inbox --mine` does
            return 0, "", ""
        self.as_agent(LEAD)
        with mock.patch.object(relay, "send_answer_line", asker_reads_during_the_send):
            self.assertEqual(self.go("--answer", q, "2")[0], 0)
        a = self.rec(q)["answer"]
        self.assertEqual((a["seen_by_asker"], a["delivery"], a["pick"]), (1234.5, "delivered", 2))
        self.as_agent(ALICE)
        self.assertEqual(self.go("--inbox", "--mine")[0], 1)    # exactly once: it is not unseen again

    def test_the_sweep_prunes_only_a_record_that_is_still_old_when_it_holds_the_lock(self) -> None:
        q = self.ask(ALICE)
        self.as_agent(LEAD)
        self.go("--answer", q, "1")
        stale = {**self.rec(q), "finished": time.time() - relay.DEFER_KEEP - 10}    # the snapshot a sweep took
        self.patch(q, finished=time.time())    # the record was touched since
        with mock.patch.object(relay, "ask_all", lambda: [stale]):
            self.assertEqual(relay.ask_sweep()["pruned"], 0)
        self.assertIsNotNone(relay.ask_read(q))
        self.patch(q, finished=time.time() - relay.DEFER_KEEP - 10)
        self.assertEqual(relay.ask_sweep()["pruned"], 1)
        self.assertIsNone(relay.ask_read(q))

    def test_a_question_that_cannot_be_written_leaves_no_open_expectation(self) -> None:
        self.as_agent(ALICE)
        with mock.patch.object(relay, "ask_write", side_effect=OSError("disk full")):
            self.assertEqual(self.go("--ask", "lead", "Q?", "--option", "A", "--option", "B")[0], 2)
        self.assertEqual([p.name for p in relay.expect_dir().glob("q-*.json")], [])


class TestNudgeLifetime(Base):
    """A wake-up text belongs to an OPEN question: when none is open for the lead it is cancelled (Argon P2-3)."""

    def nudges(self) -> list[dict[str, Any]]:
        return [r for r in relay.rec_all() if r.get("kind") == "nudge"]

    def test_it_is_cancelled_when_the_last_open_question_is_answered_not_before(self) -> None:
        q1, q2 = self.ask(ALICE), self.ask(BOB, "Rebase first")
        self.assertEqual([n["state"] for n in self.nudges()], ["queued"])
        self.as_agent(LEAD)
        self.go("--answer", q1, "1")
        self.assertEqual([n["state"] for n in self.nudges()], ["queued"])    # q2 still waits
        self.go("--answer", q2, "1")
        self.assertEqual([n["state"] for n in self.nudges()], ["cancelled"])

    def test_it_is_cancelled_when_the_only_question_is_withdrawn_expired_or_read(self) -> None:
        q = self.ask(ALICE)
        self.as_agent(ALICE)
        self.go("--withdraw", q)
        self.assertEqual([n["state"] for n in self.nudges()], ["cancelled"])
        q = self.ask(ALICE, "Again")
        self.assertEqual(sorted(n["state"] for n in self.nudges()), ["cancelled", "queued"])    # a new question gets a new wake-up
        self.patch(q, expires=time.time() - 1)
        relay.ask_sweep()
        self.assertEqual(sorted(n["state"] for n in self.nudges()), ["cancelled", "cancelled"])
        self.ask(ALICE, "Third")
        self.as_agent(LEAD)
        self.assertEqual(self.go("--inbox")[0], 0)    # read: nothing is left to wake it for
        self.assertEqual(sorted(n["state"] for n in self.nudges()), ["cancelled", "cancelled", "cancelled"])

    def test_a_nudge_cancelled_before_it_was_found_is_queued_again(self) -> None:
        real = relay.defer_send
        calls = []

        def cancel_the_first(*args: Any, **kw: Any) -> int:
            rc = real(*args, **kw)
            if not calls:
                calls.append(1)
                relay.finish(relay.rec_all()[-1]["id"], "cancelled", "raced", allowed=("queued",), notify=None)
            return rc
        self.as_agent(ALICE)
        with mock.patch.object(relay, "defer_send", cancel_the_first):
            q = self.ask(ALICE)
        live = [n for n in self.nudges() if n["state"] == "queued"]
        self.assertEqual((len(live), self.rec(q)["nudge"]), (1, live[0]["id"]))


class TestExpectationSettles(Base):
    """An answered question never pages the operator as OVERDUE (Argon P2-1)."""

    def test_a_delivered_answer_settles_the_expectation_without_a_delivery_watch(self) -> None:
        self.assertEqual(os.environ.get("RELAY_NO_ACK"), "1")    # the harness default: no watch, so the verified closer proves nothing
        q = self.ask(ALICE)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q, "1")[0], 0)
        self.assertEqual(relay.expect_read(q)["state"], "acked")

    def test_an_answer_the_queue_refused_leaves_it_open_until_the_asker_reads_it(self) -> None:
        self.rows["alice"]["agent"], self.rows["alice"]["status"] = "cline", "working"
        q = self.ask(ALICE)
        self.ordinary(relay.DEFER_PER_TARGET, target=ALICE)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q, "1")[0], 1)
        self.assertEqual(relay.expect_read(q)["state"], "open")
        self.as_agent(ALICE)
        self.assertEqual(self.go("--inbox", "--mine")[0], 0)
        self.assertEqual(relay.expect_read(q)["state"], "acked")    # the asker has its answer: nothing is overdue

    def test_the_queued_marker_is_read_from_the_structured_result_not_from_echoed_text(self) -> None:
        q = self.ask(ALICE)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--answer", q, "1", "--note", "queued: 20261102-100000-abcdef")[0], 0)
        self.assertEqual(self.rec(q)["answer"]["delivery"], "delivered")


class TestCaps(Base):
    def test_live_questions_are_capped_per_asker_per_lead_and_in_total(self) -> None:
        for name, value, who in (("ASK_PER_SENDER", 2, ALICE), ("ASK_PER_TARGET", 3, CAROL), ("ASK_TOTAL", 4, CAROL)):
            for r in relay.ask_all():
                relay.ask_path(r["id"]).unlink()
            with self.subTest(cap=name), mock.patch.multiple(relay, ASK_PER_SENDER=20, ASK_PER_TARGET=50, ASK_TOTAL=200), mock.patch.object(relay, name, value):
                self.ask(ALICE)
                self.ask(ALICE, "Two")
                if name == "ASK_PER_SENDER":
                    self.as_agent(ALICE)
                    self.assertEqual(self.go("--ask", "lead", "Three", "--option", "A", "--option", "B")[0], 2)
                    self.as_agent(BOB)    # another asker is not held to it
                    self.assertEqual(self.go("--ask", "lead", "Other", "--option", "A", "--option", "B")[0], 0)
                else:
                    self.ask(BOB, "Three")
                    if name == "ASK_TOTAL":
                        self.ask(BOB, "Four")
                    self.as_agent(who)
                    self.assertEqual(self.go("--ask", "lead", "Over", "--option", "A", "--option", "B")[0], 2)
                    self.assertNotIn("Over", [r["question"] for r in relay.ask_all()])

    def test_an_answered_question_no_longer_counts(self) -> None:
        with mock.patch.object(relay, "ASK_PER_SENDER", 1):
            q = self.ask(ALICE)
            self.as_agent(LEAD)
            self.go("--answer", q, "1")
            self.ask(ALICE, "Next")


class TestInboxWait(Base):
    def test_wait_returns_for_a_seen_question_and_for_an_unshown_withdrawal(self) -> None:
        q = self.ask(ALICE)
        self.as_agent(LEAD)
        self.assertEqual(self.go("--inbox")[0], 0)    # now `seen`
        with mock.patch.object(relay.time, "sleep", side_effect=AssertionError("parked with a question waiting")):
            self.assertEqual(self.go("--inbox", "--wait", "30")[0], 0)
        self.as_agent(ALICE)
        self.go("--withdraw", q)
        self.as_agent(LEAD)
        with mock.patch.object(relay.time, "sleep", side_effect=AssertionError("parked with a withdrawal to show")):
            rc, out, _ = self.go("--inbox", "--wait", "30")
        self.assertEqual(rc, 0)
        self.assertIn("WITHDRAWN", out)


class TestHardening(Base):
    """Symlinks, FIFOs, foreign files and modes (Argon P2-4); a cancel guard that fails closed (P2-5, partly)."""

    def test_a_loose_operator_token_is_replaced_not_trusted(self) -> None:
        p = relay.operator_token_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("leaked-token\n")
        os.chmod(p, 0o644)
        tok = relay.operator_token()
        self.assertNotEqual(tok, "leaked-token")
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(relay.read_token(p), tok)
        loose = self.tmp / "loose.token"
        loose.write_text(tok + "\n")
        os.chmod(loose, 0o644)
        self.assertEqual(relay.read_token(loose), "")    # the right bytes in a file others can read prove nothing
        self.assertTrue(relay.operator_proves(p))
        self.assertFalse(relay.operator_proves(loose))

    def test_a_fifo_or_symlink_token_never_hangs_and_proves_nothing(self) -> None:
        fifo = self.tmp / "fifo.token"
        os.mkfifo(fifo)
        self.assertEqual(run_bounded(lambda: relay.read_token(fifo)), "")
        real = self.tmp / "real.token"
        real.write_text("x" * 40 + "\n")
        os.chmod(real, 0o600)
        link = self.tmp / "link.token"
        link.symlink_to(real)
        self.assertEqual(relay.read_token(link), "")
        p = relay.operator_token_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(p)    # the token's own path is a FIFO: it is replaced, atomically, by a real 0600 file
        tok = run_bounded(relay.operator_token)
        self.assertTrue(stat.S_ISREG(p.lstat().st_mode) and stat.S_IMODE(p.lstat().st_mode) == 0o600)
        self.assertEqual(relay.read_token(p), tok)

    def test_a_symlinked_ledger_directory_is_never_used(self) -> None:
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        relay.ask_root().parent.mkdir(parents=True, exist_ok=True)
        relay.ask_root().symlink_to(elsewhere)
        self.as_agent(ALICE)
        self.assertEqual(self.go("--ask", "lead", "Q?", "--option", "A", "--option", "B")[0], 2)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertEqual(relay.ask_all(), [])
        self.assertEqual([p.name for p in relay.expect_dir().glob("q-*.json")] if relay.expect_dir().is_dir() else [], [])

    def test_the_ledger_directory_is_made_and_kept_0700(self) -> None:
        relay.ask_root().parent.mkdir(parents=True, exist_ok=True)
        relay.ask_root().mkdir(mode=0o755)
        os.chmod(relay.ask_root(), 0o755)
        q = self.ask(ALICE)
        self.assertEqual((stat.S_IMODE(relay.ask_root().stat().st_mode), stat.S_IMODE(relay.ask_path(q).stat().st_mode)), (0o700, 0o600))

    def test_a_record_that_is_a_symlink_or_a_fifo_is_not_read(self) -> None:
        q = self.ask(ALICE)
        path = relay.ask_path(q)
        copy = self.tmp / "copy.json"
        copy.write_text(path.read_text())
        path.unlink()
        path.symlink_to(copy)
        self.assertIsNone(relay.ask_read(q))
        path.unlink()
        os.mkfifo(path)
        self.assertIsNone(run_bounded(lambda: relay.ask_read(q)))
        self.assertEqual(run_bounded(relay.ask_all), [])

    def test_ask_reads_only_a_small_regular_file_of_this_user(self) -> None:
        argv = ("--ask", "lead", "--option", "A", "--option", "B")
        self.as_agent(ALICE)
        fifo = self.tmp / "q.fifo"
        os.mkfifo(fifo)
        self.assertEqual(run_bounded(lambda: self.go(*argv[:2], "--message-file", str(fifo), *argv[2:]))[0], 2)
        real = self.tmp / "q.txt"
        real.write_text("Merge it now?")
        link = self.tmp / "q.link"
        link.symlink_to(real)
        self.assertEqual(self.go(*argv[:2], "--message-file", str(link), *argv[2:])[0], 2)
        big = self.tmp / "big.txt"
        big.write_text("x" * (relay.ASK_FILE_MAX + 10))
        self.assertEqual(self.go(*argv[:2], "--message-file", str(big), *argv[2:])[0], 2)
        self.assertEqual(relay.ask_all(), [])
        self.assertEqual(self.go(*argv[:2], "--message-file", str(real), *argv[2:])[0], 0)

    def test_cancel_fails_closed_when_it_cannot_tell_who_is_asking(self) -> None:
        self.ordinary(1)
        rid = relay.rec_all()[0]["id"]
        with mock.patch.object(relay.fleet, "sessions", side_effect=RuntimeError("paseo ls failed")):
            rc, _, err = self.go("--cancel", rid)
        self.assertEqual(rc, 2)
        self.assertIn("could not tell who you are", err)
        self.assertEqual(relay.rec_read(rid)["state"], "queued")
