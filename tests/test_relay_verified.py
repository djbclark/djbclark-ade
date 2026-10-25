#!/usr/bin/env python3
"""Verified peer messaging in relay.py (2026-10-25, docs/queue.md "Verified peer messaging"): `--ack`, `--expect-ack`, first contact.

Proof, not conversation: `--ack` tells delivered / unverified / not delivered apart by exit code; a message that asks a question needs
`--expect-ack` (a record, resolved by `--sweep`); the first message to a peer asks for an `ack <sender id>` and fleet shows a link
that never answered as one-way. Every id is fake; nothing reaches a live session.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet, sess, stamp = fb.relay, fb.fleet, fb.sess, fb.stamp
REAL_SLEEP = time.sleep
ME_SID = "dddddddd-0000-4000-8000-000000000004"


class Base(fb.Harness):
    """A sender row (`self`, with its own transcript) and a Claude pane target whose typed text lands in its transcript."""

    def setUp(self) -> None:
        super().setUp()
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
        self.sleeps: list[float] = []
        self.on_sleep: Any = None

        def typed(chan: Any, text: str) -> bool:
            self.calls.append("type")
            self.sent_texts.append(text)
            self.on_typed(text)
            return True
        self.sent_texts: list[str] = []
        self.on_typed = self.write_delivered
        relay.type_line = typed
        saved_sleep = relay.time.sleep
        relay.time.sleep = self.fake_sleep
        self.addCleanup(setattr, relay.time, "sleep", saved_sleep)

    def fake_sleep(self, n: float) -> None:
        self.sleeps.append(n)
        if self.on_sleep:
            self.on_sleep()
        REAL_SLEEP(0.01)

    def append(self, path: Path, row: dict[str, Any]) -> None:
        with path.open("a") as fh:
            fh.write(json.dumps({"timestamp": stamp(), **row}) + "\n")

    def write_delivered(self, text: str) -> None:
        self.append(self.tx, {"type": "user", "message": {"role": "user", "content": text}})

    def write_queued(self, text: str) -> None:
        self.append(self.tx, {"type": "queue-operation", "operation": "enqueue", "content": text})

    def go(self, text: str, *argv: str, rows: list[dict[str, Any]] | None = None, to: str = "peer-fb") -> tuple[int, str, str]:
        relay.fleet.sessions = lambda: [self.target, *(rows if rows is not None else [self.me])]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main([to, text, "--wait", "1", *argv])
        return rc, out.getvalue(), err.getvalue()

    def reply_to_me(self, text: str, tagged: bool = True) -> None:
        self.append(self.me_tx, {"type": "user", "message": {"role": "user", "content": f"[relay from peer-fb] {text}" if tagged else text}})

    def run_cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = relay.main(list(argv))
        return rc, out.getvalue()


class TestAck(Base):
    def test_a_queued_copy_that_a_turn_later_takes_is_delivered_with_ack(self) -> None:
        self.on_typed = self.write_queued
        self.on_sleep = lambda: self.write_delivered("hello there friend")
        rc, out, err = self.go("hello there friend", "--ack", rows=[])
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ack: delivered", out)

    def test_a_queued_copy_nothing_took_is_unverified_exit_3_never_0(self) -> None:
        self.on_typed = self.write_queued
        rc, out, err = self.go("hello there friend", "--ack", rows=[])
        self.assertEqual(rc, 3, (out, err))
        self.assertIn("ack: unverified", err)
        self.assertNotIn("ack: delivered", out + err)

    def test_a_queued_copy_pulled_back_is_not_delivered_exit_1(self) -> None:
        self.on_typed = self.write_queued
        self.on_sleep = lambda: self.append(self.tx, {"type": "queue-operation", "operation": "popAll"})
        rc, out, err = self.go("hello there friend", "--ack", rows=[])
        self.assertEqual(rc, 1, (out, err))
        self.assertIn("ack: not delivered", err)

    def test_without_ack_a_queued_send_still_exits_0_for_the_callers_that_rely_on_it(self) -> None:
        self.on_typed = self.write_queued
        rc, out, err = self.go("hello there friend", rows=[])
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("queued", out)

    def test_a_delivered_send_needs_no_watch(self) -> None:
        rc, out, err = self.go("hello there friend", "--ack", rows=[])
        self.assertEqual((rc, self.sleeps), (0, []), (out, err))

    def test_json_carries_the_verdict(self) -> None:
        self.on_typed = self.write_queued
        rc, out, _ = self.go("hello there friend", "--ack", "--json", rows=[])
        self.assertEqual(rc, 3)
        self.assertEqual(json.loads(out)["ack"], "unverified")

    def test_a_socket_frame_to_a_working_session_is_unverified_until_its_envelope_shows(self) -> None:
        relay.claude_socket = lambda s: "/tmp/x.sock"
        self.target = sess(transcript=str(self.tx), status="working")
        body = "hello there friend"

        def frame(sock: Any, sender: Any, text: str) -> bool:
            self.calls.append("socket")
            return True
        relay.socket_send = frame
        rc, out, err = self.go(body, "--ack", "--via", "socket", rows=[])
        self.assertEqual(rc, 3, (out, err))
        self.on_sleep = lambda: self.append(self.tx, {"attachment": {"type": "queued_command", "prompt":
                                                                      f'<cross-session-message from-mode="bypass">\n{body}\n</cross-session-message>'}})
        rc, out, err = self.go(body, "--ack", "--via", "socket", rows=[])
        self.assertEqual(rc, 0, (out, err))

    def test_a_deferred_record_is_watched_to_its_outcome(self) -> None:
        rec = {"id": "20261025-000000-abcdef", "state": "queued", "outcome": "", "created": time.time()}
        relay.rec_write(rec)
        self.assertEqual(relay.defer_ack(rec["id"], 0)[0], "unverified")    # still queued: not delivered yet, not failed
        relay.rec_write({**rec, "state": "delivered", "outcome": "relayed to [x] y via pane: queued; it takes the message"})
        self.assertEqual(relay.defer_ack(rec["id"], 0)[0], "unverified")    # sent, but only taken: no proof
        relay.rec_write({**rec, "state": "delivered", "outcome": "relayed to [x] y via pane: delivered; it takes the message now"})
        self.assertEqual(relay.defer_ack(rec["id"], 0)[0], "delivered")
        relay.rec_write({**rec, "state": "failed", "outcome": "the target is gone"})
        self.assertEqual(relay.defer_ack(rec["id"], 0)[0], "not delivered")
        relay.rec_write({**rec, "state": "failed", "outcome": "unverified, do not resend; check its pane"})
        self.assertEqual(relay.defer_ack(rec["id"], 0)[0], "unverified")

    def test_a_route_with_no_transcript_cannot_be_watched_and_says_so_at_once(self) -> None:
        word, note = relay.ack_watch({}, 60)
        self.assertEqual(word, "unverified")
        self.assertEqual(self.sleeps, [])
        self.assertIn("cannot be proven", note)


class TestExpectAck(Base):
    def test_a_question_without_expect_ack_is_refused_and_nothing_is_sent(self) -> None:
        rc, _, err = self.go("is the build green?")
        self.assertEqual((rc, self.calls), (2, []))
        self.assertIn("--expect-ack", err)

    def test_a_question_mark_inside_a_url_is_not_a_question(self) -> None:
        rc, out, err = self.go("see https://example.com/a?b=1 for the log")
        self.assertEqual(rc, 0, (out, err))

    def test_fyi_overrides_a_question_mark_that_is_not_one(self) -> None:
        rc, out, err = self.go("done with the 'why?' section", "--fyi")
        self.assertEqual(rc, 0, (out, err))

    def test_needs_reply_requires_expect_ack_without_a_question(self) -> None:
        rc, _, err = self.go("please merge the PR", "--needs-reply")
        self.assertEqual((rc, self.calls), (2, []), err)

    def test_a_caller_with_no_session_is_not_held_to_an_ack_it_could_never_receive(self) -> None:
        rc, out, err = self.go("is the build green?", rows=[])
        self.assertEqual(rc, 0, (out, err))

    def test_expect_ack_needs_a_transcript_to_watch(self) -> None:
        self.me["transcript"] = None
        rc, _, err = self.go("is the build green?", "--expect-ack", "build1")
        self.assertEqual((rc, self.calls), (2, []), err)
        self.assertIn("transcript", err)

    def test_the_peer_is_told_how_to_ack_and_the_expectation_is_listed_by_pending(self) -> None:
        rc, out, err = self.go("is the build green?", "--expect-ack", "build1")
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ack build1", self.sent_texts[0])
        rc, out = self.run_cli("--pending", "--json")
        rows = [r for r in json.loads(out) if r.get("kind") == "expect"]
        self.assertEqual([(r["id"], r["state"], r["sender"], r["target"]["name"], r["overdue"]) for r in rows],
                         [("build1", "open", "alice", "peer-fb", False)])
        rc, out = self.run_cli("--pending")
        self.assertIn("expect-ack build1", out)

    def test_an_open_id_cannot_be_reused(self) -> None:
        self.assertEqual(self.go("is the build green?", "--expect-ack", "build1")[0], 0)
        rc, _, err = self.go("and the lint?", "--expect-ack", "build1")
        self.assertEqual(rc, 2, err)
        self.assertIn("already open", err)

    def test_sweep_resolves_it_only_when_a_reply_naming_the_sender_arrives(self) -> None:
        self.go("is the build green?", "--expect-ack", "build1")
        self.assertIn("0 resolved", self.run_cli("--sweep")[1])
        # the sender's own tool call and its result quote the id: they are not a reply
        self.append(self.me_tx, {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "relay.py peer-fb 'x' --expect-ack build1 ack build1"}}]}})
        self.append(self.me_tx, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ack build1"}]}})
        self.assertIn("0 resolved", self.run_cli("--sweep")[1])
        self.reply_to_me("ack build1 yes, green")
        self.assertIn("1 resolved", self.run_cli("--sweep")[1])
        rows = [r for r in json.loads(self.run_cli("--pending", "--json")[1]) if r.get("kind") == "expect"]
        self.assertEqual(rows[0]["state"], "acked")
        self.assertFalse(rows[0]["overdue"])

    def test_a_longer_id_is_not_the_ack(self) -> None:
        self.go("is the build green?", "--expect-ack", "build1")
        self.reply_to_me("ack build12")
        self.assertIn("0 resolved", self.run_cli("--sweep")[1])

    def test_an_unanswered_expectation_goes_overdue_and_the_sweep_flags_it_for_the_operator(self) -> None:
        self.go("is the build green?", "--expect-ack", "build1", "--ack-within", "60")
        path = relay.expect_dir() / "build1.json"
        rec = json.loads(path.read_text())
        rec["created"] -= 3600
        path.write_text(json.dumps(rec))
        rc, out = self.run_cli("--sweep")
        self.assertIn("1 overdue", out)
        self.assertIn("OVERDUE ack build1", out)
        self.assertTrue([r for r in json.loads(self.run_cli("--pending", "--json")[1]) if r.get("kind") == "expect"][0]["overdue"])


class TestPeerAttribution(unittest.TestCase):
    """Adversary r1 A4 (2026-10-25): a first-contact `ack` names its peer by the header's ID word, not by a substring."""

    def test_an_id_that_only_starts_with_the_peers_id_is_another_peer(self) -> None:
        self.assertFalse(relay.ack_seen(["[relay from claude w34:p45 (x)] ack w1:p1"], "w1:p1", ["w34:p4"]))
        self.assertTrue(relay.ack_seen(["[relay from claude w34:p4 (x)] ack w1:p1"], "w1:p1", ["w34:p4"]))

    def test_a_short_name_matches_the_aka_name_only_and_never_a_line_that_says_main(self) -> None:
        self.assertFalse(relay.ack_seen(["[relay from claude w9:p9 aka main2 (x)] ack w1:p1 on the main line"], "w1:p1", ["main"]))
        self.assertTrue(relay.ack_seen(["[relay from claude w9:p9 aka main (x)] ack w1:p1"], "w1:p1", ["main"]))
        self.assertFalse(relay.ack_seen(["ack w1:p1 from main"], "w1:p1", ["main"]))    # no header: a short word is no evidence

    def test_a_header_quoted_in_the_body_is_not_the_sender(self) -> None:
        text = "[relay from claude w7:p7 (other)] ack w1:p1 [relay from claude w34:p4 (x)] says so"
        self.assertFalse(relay.ack_seen([text], "w1:p1", ["w34:p4"]))

    def test_the_socket_envelope_names_its_sender_the_same_way(self) -> None:
        env = '<cross-session-message from="relay.py" from-name="relay.py (claude w34:p4 aka lead (x))" from-mode="bypass"> ack w1:p1'
        self.assertTrue(relay.ack_seen([env], "w1:p1", ["w34:p4"]))
        self.assertFalse(relay.ack_seen([env], "w1:p1", ["w34:p"]))

    def test_a_paseo_label_with_no_relay_header_counts_by_the_whole_agent_id(self) -> None:
        agent = "aaaaaaaa-0000-4000-8000-000000000001"
        self.assertTrue(relay.ack_seen([f'<paseo-system from="{agent}"> ack w1:p1'], "w1:p1", [agent]))
        self.assertFalse(relay.ack_seen([f'<paseo-system from="{agent}9"> ack w1:p1'], "w1:p1", [agent]))


class TestExpectationClosedOnlyByItsTarget(Base):
    """Adversary r1 A2 (2026-10-25): an `--expect-ack` is closed by the target's own reply, not by a compaction summary or a stranger."""

    def setUp(self) -> None:
        super().setUp()
        self.assertEqual(self.go("is the build green?", "--expect-ack", "build1")[0], 0)

    def swept(self) -> str:
        return self.run_cli("--sweep")[1]

    def quoted(self, flag: str) -> None:
        self.append(self.me_tx, {"type": "user", flag: True, "message": {"role": "user", "content": "Summary: waiting for ack build1 from cccccccc."}})
        self.assertIn("0 resolved", self.swept())

    def test_a_compaction_summary_that_quotes_the_ack_is_not_a_reply(self) -> None:
        self.quoted("isCompactSummary")

    def test_a_transcript_only_notice_that_quotes_the_ack_is_not_a_reply(self) -> None:
        self.quoted("isVisibleInTranscriptOnly")

    def test_a_reply_from_another_peer_is_not_the_targets(self) -> None:
        self.append(self.me_tx, {"type": "user", "message": {"role": "user", "content": "[relay from claude w7:p7 (other)] ack build1"}})
        self.assertIn("0 resolved", self.swept())

    def test_the_targets_own_reply_closes_it(self) -> None:
        self.append(self.me_tx, {"type": "user", "message": {"role": "user", "content": "[relay from claude cccccccc aka peer-fb (x)] ack build1"}})
        self.assertIn("1 resolved", self.swept())


class TestExpectReservation(Base):
    """Adversary r1 A6 (2026-10-25): --expect-ack ID is claimed before the send, so two senders of one ID cannot both send."""

    def test_while_the_first_relay_is_typing_the_id_is_already_taken(self) -> None:
        taken: list[bool] = []
        self.on_typed = lambda text: (taken.append(relay.expect_reserve("q1", "dddddddd")), self.write_delivered(text))[-1]
        self.assertEqual(self.go("is the build green?", "--expect-ack", "q1")[0], 0)
        self.assertEqual(taken, [False])

    def test_a_reserved_id_refuses_a_second_send_before_anything_is_typed(self) -> None:
        self.assertTrue(relay.expect_reserve("q1", "dddddddd"))
        rc, _, err = self.go("is the build green?", "--expect-ack", "q1")
        self.assertEqual((rc, self.calls), (2, []), err)
        self.assertIn("already open", err)

    def test_a_reservation_whose_relay_died_frees_the_id_after_its_ttl(self) -> None:
        self.assertTrue(relay.expect_reserve("q1", "dddddddd"))
        path = relay.expect_dir() / "q1.json"
        rec = json.loads(path.read_text())
        rec["created"] -= relay.EXPECT_RESERVE_TTL + 5
        path.write_text(json.dumps(rec))
        self.assertEqual(self.go("is the build green?", "--expect-ack", "q1")[0], 0)

    def test_a_relay_that_sends_nothing_gives_the_id_back(self) -> None:
        rc, _, _ = self.go("is the build green?", "--expect-ack", "q1", to="nobody-here")
        self.assertEqual(rc, 1)
        self.assertIsNone(relay.expect_read("q1"))
        self.assertEqual(self.go("is the build green?", "--expect-ack", "q1")[0], 0)

    def test_the_send_turns_it_into_the_open_expectation_and_a_reservation_is_not_listed(self) -> None:
        self.assertEqual(self.go("is the build green?", "--expect-ack", "q1")[0], 0)
        self.assertEqual((relay.expect_read("q1") or {}).get("state"), "open")
        self.assertTrue(relay.expect_reserve("q2", "dddddddd"))
        rows = [r for r in json.loads(self.run_cli("--pending", "--json")[1]) if r.get("kind") == "expect"]
        self.assertEqual([r["id"] for r in rows], ["q1"])


class TestSweepCostAndRobustness(Base):
    """Adversary r1 A10 (2026-10-25): a sweep reads each transcript once, prunes idle links, and survives a hand-edited record."""

    REPLY = "[relay from claude cccccccc aka peer-fb (x)] ack bbbbbbbb"

    def link(self) -> dict[str, Any]:
        return next(iter(json.loads(fleet.LINKS_FILE.read_text())["links"].values()))

    def test_the_scan_mark_advances_so_old_bytes_are_not_read_again_and_new_lines_still_count(self) -> None:
        self.go("PR 61 is merged")
        self.append(self.me_tx, {"type": "user", "message": {"role": "user", "content": "unrelated chatter"}})
        self.run_cli("--sweep")
        self.assertEqual(self.link()["mark"], self.me_tx.stat().st_size)
        reads: list[int] = []
        real = relay.scan_texts
        relay.scan_texts = lambda tx, mark: reads.append(mark) or real(tx, mark)
        self.addCleanup(setattr, relay, "scan_texts", real)
        self.run_cli("--sweep")
        self.assertEqual(reads, [self.me_tx.stat().st_size])    # nothing before the stored mark is read again
        self.reply_to_me("ack bbbbbbbb from cccccccc")
        self.assertIn("1 resolved", self.run_cli("--sweep")[1])

    def test_a_line_still_being_written_is_not_consumed(self) -> None:
        self.go("PR 61 is merged")
        line = json.dumps({"timestamp": fb.stamp(), "type": "user", "message": {"role": "user", "content": self.REPLY}})
        with self.me_tx.open("a") as fh:
            fh.write(line)    # no newline yet: the writer is mid-line
        self.assertIn("0 resolved", self.run_cli("--sweep")[1])
        with self.me_tx.open("a") as fh:
            fh.write("\n")
        self.assertIn("1 resolved", self.run_cli("--sweep")[1])

    def test_a_link_idle_for_the_keep_window_is_pruned_and_a_recent_one_is_not(self) -> None:
        self.go("PR 61 is merged")
        data = json.loads(fleet.LINKS_FILE.read_text())
        key = next(iter(data["links"]))
        data["links"]["old>peer"] = {**data["links"][key], "last_sent": time.time() - relay.EXPECT_KEEP - 60}
        fleet.LINKS_FILE.write_text(json.dumps(data))
        self.run_cli("--sweep")
        self.assertEqual(list(json.loads(fleet.LINKS_FILE.read_text())["links"]), [key])

    def test_hand_edited_records_never_crash_list_pending_or_sweep(self) -> None:
        self.assertEqual(self.go("is the build green?", "--expect-ack", "build1")[0], 0)
        path = relay.expect_dir() / "build1.json"
        rec = json.loads(path.read_text())
        path.write_text(json.dumps({**rec, "created": "yesterday", "within": [1], "mark": "zz", "target": "alice"}))
        data = json.loads(fleet.LINKS_FILE.read_text())
        data["links"]["junk>x"] = "not a dict"
        data["links"][next(iter(data["links"]))]["sent"] = "many"
        data["links"]["bbbbbbbb>cccccccc"] = {**next(v for v in data["links"].values() if isinstance(v, dict)), "sent": "many", "mark": "x", "last_sent": "never"}
        fleet.LINKS_FILE.write_text(json.dumps(data))
        self.assertEqual(self.run_cli("--pending", "--json")[0], 0)
        self.assertEqual(self.run_cli("--sweep")[0], 0)
        self.assertEqual(len(fleet.annotate_links([dict(self.target), dict(self.me)])), 2)


class TestFirstContact(Base):
    def test_the_first_message_to_a_peer_asks_for_an_ack_and_the_second_does_not(self) -> None:
        self.assertEqual(self.go("PR 61 is merged")[0], 0)
        self.assertIn("reply `ack bbbbbbbb` through relay.py", self.sent_texts[0])
        self.assertEqual(self.go("PR 62 is merged")[0], 0)
        self.assertNotIn("ack bbbbbbbb", self.sent_texts[1])

    def test_a_caller_with_no_session_adds_nothing(self) -> None:
        self.go("PR 61 is merged", rows=[])
        self.assertEqual(self.sent_texts, ["PR 61 is merged"])

    def test_fleet_shows_a_peer_that_never_answered_as_one_way_until_it_does(self) -> None:
        self.go("PR 61 is merged")
        rows = fleet.annotate_links([dict(self.target), dict(self.me)])
        self.assertEqual(rows[0]["link"], {"sent": 1, "acked": None})
        self.assertIn("ONE-WAY", fleet.render({**rows[0], "title": "", "where": "", "reach": ""}))
        self.reply_to_me("ack bbbbbbbb", tagged=False)    # does not say whose reply it is: not attributed to the peer
        self.run_cli("--sweep")
        self.assertIsNone(fleet.annotate_links([dict(self.target), dict(self.me)])[0]["link"]["acked"])
        self.reply_to_me("ack bbbbbbbb from cccccccc")
        self.run_cli("--sweep")
        rows = fleet.annotate_links([dict(self.target), dict(self.me)])
        self.assertTrue(rows[0]["link"]["acked"])
        self.assertIn("link: acked", fleet.render({**rows[0], "title": "", "where": "", "reach": ""}))

    def test_an_answered_question_also_proves_the_link(self) -> None:
        self.go("is the build green?", "--expect-ack", "build1")
        self.reply_to_me("ack build1")
        self.run_cli("--sweep")
        self.assertTrue(fleet.annotate_links([dict(self.target), dict(self.me)])[0]["link"]["acked"])

    def test_a_failed_send_records_no_link(self) -> None:
        relay.type_line = lambda chan, text: False    # every route fails before anything is typed
        rc, _, _ = self.go("PR 61 is merged")
        self.assertEqual(rc, 1)
        self.assertFalse(fleet.LINKS_FILE.exists())

    def test_no_ledger_means_no_link_line(self) -> None:
        self.assertNotIn("link", fleet.annotate_links([dict(self.target), dict(self.me)])[0])


if __name__ == "__main__":
    sys.exit(unittest.main())
