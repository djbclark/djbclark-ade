#!/usr/bin/env python3
"""The card alert (2026-11-02): a message queued behind a question or permission card for 30 minutes sends ONE `hermes-ping`.

Why: agent f111c672 reported a relay from the lead sat queued 184 minutes behind a question card, and its own reply to the lead sat behind a card
too; relay deferred correctly but nobody was told the real blocker was a card only djbclark can answer. The deliverer pings once per card and
target, a failed ping never costs the message, and `--pending` shows the state. A fake `hermes-ping` script on RELAY_HERMES_PING records its
argv; every id is fake and every state lives in a temp directory.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]
import test_relay_status as st  # noqa: E402  # pyright: ignore[reportMissingImports]

relay = fb.relay
CARD_ID = st.CARD_ID
CARD = [{"id": CARD_ID, "tool": "AskUserQuestion"}]


class Base(st.QueueBase):
    def setUp(self) -> None:
        super().setUp()
        self.pings = self.tmp / "pings.txt"
        self.ping_rc = 0
        self.script("ok")
        os.environ["RELAY_CARD_ALERT_S"] = "1800"
        os.environ.pop("RELAY_HERMES", None)
        self.cards = list(CARD)    # the target shows a question card from the first look

    def script(self, kind: str) -> None:
        """A fake hermes-ping: records its one argument; `fail` exits 1, `hang` never returns."""
        path = self.tmp / "hermes-ping"
        body = {"ok": f'printf "%s\\n" "$1" >> {self.pings}\n',
                "fail": f'printf "%s\\n" "$1" >> {self.pings}\nexit 1\n',
                "hang": f'printf "%s\\n" "$1" >> {self.pings}\nsleep 30\n'}[kind]
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        os.environ["RELAY_HERMES_PING"] = str(path)

    def ping_lines(self) -> list[str]:
        return self.pings.read_text().splitlines() if self.pings.exists() else []

    def queue(self, text: str = "hello there friend") -> str:
        rc, out, err = self.go(text=text)
        self.assertEqual(rc, 0, (out, err))
        self.assertTrue(out.startswith("queued: "), out)
        return out.split()[1]

    def patch_rec(self, rid: str, **kw: Any) -> None:
        r = relay.rec_read(rid)
        assert r
        r.update(kw)
        relay.rec_write(r)

    def drive(self, rid: str, plan: list[Any]) -> list[Any]:
        """Run the deliverer; the Nth sleep it takes runs PLAN[N] (a callable), then the card is answered when PLAN is used up, so it ends."""
        steps = iter(plan)
        seen: list[Any] = []

        def sleeper(_secs: float) -> None:
            step = next(steps, None)
            if step is None:
                self.cards, self.status = [], "idle"
                return
            seen.append(step())

        with mock.patch.object(relay.time, "sleep", side_effect=sleeper):
            relay.deliver(rid)
        return seen

    def waited(self, rid: str, secs: float) -> Any:
        """A plan step: the card clock of record RID reads SECS older (the 30 minutes pass without a real wait)."""
        def step() -> None:
            r = relay.rec_read(rid)
            assert r and r.get("card_since")
            self.patch_rec(rid, card_since=time.time() - secs)
        return step

    def nothing(self) -> None:
        return None

    def pending(self) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            relay.pending_cmd(False)
        return out.getvalue()


class TestCardAlert(Base):
    def test_a_message_that_waited_past_the_threshold_pings_once_naming_target_card_sender_and_message(self) -> None:
        rid = self.queue()
        rows: list[str] = []
        self.drive(rid, [self.nothing, self.waited(rid, 1900), self.nothing, lambda: rows.append(self.pending()), self.nothing])
        lines = self.ping_lines()
        self.assertEqual(len(lines), 1, lines)    # three more looks behind the same card: still one ping
        for needle in (fb.AGENT[:8], CARD_ID, rid, "AskUserQuestion", "Only you can answer"):
            self.assertIn(needle, lines[0])
        self.assertIn("alice", lines[0])    # the sender's label
        self.assertNotIn("hello there friend", lines[0])    # never the message text
        self.assertEqual(relay.rec_read(rid)["state"], "delivered")    # the card was answered later: the message still went out
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("[card alert: pinged", rows[0])

    def messages(self) -> list[tuple[str, str]]:
        return [(a, t) for a, t in self.sent if "your message to" not in t]

    def test_no_ping_before_the_threshold(self) -> None:
        rid = self.queue()
        self.drive(rid, [self.nothing, self.waited(rid, 1700), self.nothing, self.nothing])
        self.assertEqual(self.ping_lines(), [])
        self.assertNotIn("card alert", self.pending())

    def test_the_threshold_is_RELAY_CARD_ALERT_S(self) -> None:
        os.environ["RELAY_CARD_ALERT_S"] = "60"
        rid = self.queue()
        self.drive(rid, [self.nothing, self.waited(rid, 90), self.nothing])
        self.assertEqual(len(self.ping_lines()), 1)

    def test_zero_turns_it_off(self) -> None:
        os.environ["RELAY_CARD_ALERT_S"] = "0"
        rid = self.queue()
        self.patch_rec(rid, card_since=time.time() - 100000)    # a card clock that would long since have fired, were it on
        self.drive(rid, [self.nothing, self.nothing, self.nothing])
        self.assertEqual(self.ping_lines(), [])
        self.assertEqual(relay.rec_read(rid)["state"], "delivered")

    def test_a_later_message_behind_the_same_card_does_not_ping_again(self) -> None:
        first = self.queue("first message to the peer")
        second = self.queue("second message to the peer")
        # the first expires while the card still stands, then the second becomes the head of the queue
        self.drive(first, [self.nothing, self.waited(first, 1900), lambda: self.patch_rec(first, expires=time.time() - 1)])
        self.assertEqual(relay.rec_read(first)["state"], "expired")
        self.assertEqual(len(self.ping_lines()), 1)
        self.cards, self.status = list(CARD), "running"
        self.drive(second, [self.nothing, self.waited(second, 1900), self.nothing])
        self.assertEqual(len(self.ping_lines()), 1)    # same card, same target: already told
        self.assertEqual(relay.rec_read(second)["state"], "delivered")

    def test_a_different_card_on_the_same_target_is_a_new_alert(self) -> None:
        rid = self.queue()
        self.drive(rid, [self.nothing, self.waited(rid, 1900), lambda: setattr(self, "cards", [{"id": "frm_other", "tool": "Bash"}]),
                         self.nothing, self.waited(rid, 1900), self.nothing])
        lines = self.ping_lines()
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("frm_other", lines[1])

    def test_an_answered_card_restarts_the_clock_for_the_next_one(self) -> None:
        rid = self.queue()
        self.drive(rid, [self.nothing, lambda: self.waited(rid, 1000)(), lambda: setattr(self, "status", "running") or setattr(self, "cards", []),
                         self.nothing, lambda: (setattr(self, "cards", list(CARD)), setattr(self, "status", "idle")), self.nothing])
        self.assertEqual(self.ping_lines(), [])    # 1000 s behind one card, then a gap with none: never 1800 s behind one

    def test_a_ping_that_fails_is_logged_and_never_costs_the_message(self) -> None:
        self.script("fail")
        rid = self.queue()
        shown: list[str] = []
        self.drive(rid, [self.nothing, self.waited(rid, 1900), lambda: shown.append(self.pending())])
        self.assertEqual(len(self.ping_lines()), 1)
        self.assertIn("PING FAILED", shown[0])
        self.assertEqual((relay.rec_read(rid)["state"], len(self.messages())), ("delivered", 1))
        self.assertRegex((relay.DEFER_DIR.parent / "deferred.log").read_text(), rf"{rid} card-alert-failed ")

    def test_a_failed_ping_is_retried_later_but_not_every_look_and_not_forever(self) -> None:
        self.script("fail")
        rid = self.queue()
        retry = lambda: self.patch_rec(rid, card_since=time.time() - 1900)  # noqa: E731
        agelog = lambda: json.loads(relay.card_alerts_path().read_text())  # noqa: E731

        def later() -> None:    # the retry delay passes
            data = agelog()
            for v in data.values():
                v["retry_at"] = 0
            relay.card_alerts_path().write_text(json.dumps(data))
        self.drive(rid, [self.nothing, retry, retry, later, retry, later, retry, later, retry, self.nothing])
        self.assertEqual(len(self.ping_lines()), relay.CARD_ALERT_TRIES)    # tried 3 times, then it gives up

    def test_a_ping_that_hangs_is_cut_off_at_the_timeout(self) -> None:
        self.script("hang")
        with mock.patch.object(relay, "CARD_ALERT_TIMEOUT", 1):
            started = time.monotonic()
            ok, why = relay.card_alert_ping("relay: test")
        self.assertFalse(ok)
        self.assertIn("timed out", why)
        self.assertLess(time.monotonic() - started, 10)

    def test_a_missing_ping_binary_is_a_failure_not_a_crash(self) -> None:
        os.environ["RELAY_HERMES_PING"] = str(self.tmp / "no-such-binary")
        ok, why = relay.card_alert_ping("relay: test")
        self.assertFalse(ok)
        self.assertIn("cannot run", why)

    def test_answering_one_of_two_cards_does_not_alert_again_for_the_one_that_remains(self) -> None:
        self.cards = [{"id": "frm_a", "tool": "AskUserQuestion"}, {"id": "frm_b", "tool": "Bash"}]
        rid = self.queue()
        self.drive(rid, [self.nothing, self.waited(rid, 1900), lambda: setattr(self, "cards", [{"id": "frm_a", "tool": "AskUserQuestion"}]), self.nothing, self.nothing])
        self.assertEqual(len(self.ping_lines()), 1, self.ping_lines())

    def test_a_new_card_beside_one_already_told_is_told_once(self) -> None:
        rid = self.queue()
        self.drive(rid, [self.nothing, self.waited(rid, 1900), lambda: setattr(self, "cards", [*CARD, {"id": "frm_new", "tool": "Bash"}]), self.nothing, self.nothing])
        lines = self.ping_lines()
        self.assertEqual(len(lines), 2, lines)
        self.assertIn("frm_new", lines[1])

    def test_a_pane_dialog_has_no_id_so_a_later_dialog_is_a_new_alert_but_the_same_one_is_not(self) -> None:
        rid = self.queue()
        keys = ["w2N:pZ|card:picker"]
        t0 = time.time()
        self.assertTrue(relay.alert_once(rid, relay.rec_read(rid), keys, "card_alert", "card-alert", "relay: dialog one", fresh_after=t0 - 5))
        self.assertIsNone(relay.alert_once(rid, relay.rec_read(rid), keys, "card_alert", "card-alert", "relay: dialog one again", fresh_after=t0 - 5))
        self.assertTrue(relay.alert_once(rid, relay.rec_read(rid), keys, "card_alert", "card-alert", "relay: dialog two", fresh_after=time.time() + 5))
        self.assertEqual(self.ping_lines(), ["relay: dialog one", "relay: dialog two"])

    def test_a_successor_of_an_expired_record_shares_the_pane_dialog_episode_and_does_not_ping_again(self) -> None:
        """A pane dialog has no id: the claim is scoped to the episode. A record that takes over from one that expired while the dialog was still up
        inherits its card clock, so the same dialog is not told twice (local-review round 2)."""
        first = self.queue("first message to the peer")
        second = self.queue("second message to the peer")
        for r in (first, second):    # a herdr pane target: only a pane dialog has no id (a Paseo card always has one)
            self.patch_rec(r, target={"id": "w2N:pZ", "name": "pane-peer"})
        look = {"state": "card:picker", "why": "blocked on a question or permission prompt", "at": time.time()}
        long_ago = time.time() - 20000
        # the filed `look` is as old as the dialog (note_look files only a CHANGED look): the episode must not depend on its `at`
        self.patch_rec(first, card_since=long_ago, look=dict(look, at=long_ago))
        relay.card_alert_step(first, relay.rec_read(first), look)    # 20000 s behind the dialog: pinged, and this look refreshes card_seen
        self.assertGreater(relay.rec_read(first)["card_seen"], time.time() - 30)
        self.assertEqual(len(self.ping_lines()), 1)
        claims = json.loads(relay.card_alerts_path().read_text())
        relay.card_alerts_path().write_text(json.dumps({k: dict(v, at=long_ago + 1900) for k, v in claims.items()}))    # that ping went out long ago
        self.patch_rec(first, state="expired", finished=time.time())    # it expired with the dialog still up (its last look is recent)
        relay.card_alert_step(second, relay.rec_read(second), look)    # its clock starts: inherited from the expired record
        self.assertEqual(relay.rec_read(second)["card_since"], long_ago)
        relay.card_alert_step(second, relay.rec_read(second), look)
        self.assertEqual(len(self.ping_lines()), 1, self.ping_lines())

    def test_a_daemon_restart_between_two_card_looks_does_not_restart_the_card_clock(self) -> None:
        """r1b A4: a miss or an error says nothing about the card; only a look that saw the target idle or busy clears the clock."""
        rid = self.queue()
        seen: list[Any] = []
        good = relay.paseo_probe

        def restart() -> None:
            relay.paseo_probe = lambda agent: (None, "error")    # the next look cannot ask
            self.patch_rec(rid, card_since=time.time() - 1000)

        def back() -> None:
            seen.append(relay.rec_read(rid).get("card_since"))
            relay.paseo_probe = good
        self.drive(rid, [restart, back, self.nothing])
        self.assertTrue(seen[0] and time.time() - seen[0] > 900, seen)    # still the old clock after the failed look
        relay.paseo_probe = good

    def test_a_paseo_look_without_a_card_id_never_alerts_and_never_claims(self) -> None:
        """r1b A5b: a Paseo card always has an id; a look that names none (inspect and permit ls disagreeing) would key a second claim for it."""
        rid = self.queue()
        self.patch_rec(rid, card_since=time.time() - 100000)
        relay.card_alert_step(rid, relay.rec_read(rid), {"state": "card:unknown", "why": "a card may have just appeared"})
        self.assertEqual(self.ping_lines(), [])
        self.assertFalse(relay.card_alerts_path().exists())
        relay.card_alert_step(rid, relay.rec_read(rid), {"state": "card:question", "cards": [{"id": CARD_ID, "tool": "AskUserQuestion", "kind": "question"}]})
        self.assertEqual(len(self.ping_lines()), 1)

    def test_a_cancelled_head_leaves_its_dialog_episode_to_the_next_record(self) -> None:
        """local-review r4: a sender who withdraws the head (--cancel) leaves the dialog up; its successor must not start a fresh clock and re-ping."""
        first = self.queue("first message to the peer")
        second = self.queue("second message to the peer")
        long_ago = time.time() - 20000
        self.patch_rec(first, card_since=long_ago, card_seen=time.time() - 5, state="cancelled", finished=time.time())
        self.assertEqual(relay.card_episode_start(second, relay.rec_read(second), time.time()), long_ago)
        self.patch_rec(first, state="delivered")    # delivered means the card was answered: no episode to inherit
        self.assertGreater(relay.card_episode_start(second, relay.rec_read(second), time.time()), long_ago + 1000)

    def test_a_garbage_threshold_means_the_default(self) -> None:
        for raw, expect in (("abc", 1800), ("", 1800), ("-5", 0), ("0", 0), ("90", 90)):
            with self.subTest(raw=raw):
                os.environ["RELAY_CARD_ALERT_S"] = raw
                self.assertEqual(relay.card_alert_after(), expect)


class TestBusyAlert(Base):
    """A target that is merely WORKING (inside a long blocking wait it never goes idle, so it is deaf as well as silent): the lead's messages to f111c672
    sat queued for hours (2026-11-02). After RELAY_BUSY_ALERT_S the sender gets ONE notice and the operator ONE ping. Nothing is ever auto-steered."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["RELAY_BUSY_ALERT_S"] = "1800"
        self.cards, self.status = [], "running"

    def old(self, rid: str, secs: float) -> None:
        self.patch_rec(rid, created=time.time() - secs)

    def to_sender(self) -> list[str]:
        return [t for a, t in self.sent if a == fb.SENDER]

    def messages(self) -> list[tuple[str, str]]:
        return [(a, t) for a, t in self.sent if a == fb.AGENT]

    def test_a_message_past_the_threshold_gets_one_notice_and_one_ping_however_many_looks(self) -> None:
        rid = self.queue()
        self.old(rid, 1900)
        shown: list[str] = []
        self.drive(rid, [self.nothing, self.nothing, self.nothing, lambda: shown.append(self.pending())])
        lines = self.ping_lines()
        self.assertEqual(len(lines), 1, lines)
        for needle in (fb.AGENT[:8], rid, "alice", "WORKING for 31m", "cannot receive it"):
            self.assertIn(needle, lines[0])
        notes = self.to_sender()
        self.assertEqual(len(notes), 1, notes)
        self.assertIn(rid, notes[0])
        self.assertIn("--steer", notes[0])
        self.assertIn("lost", notes[0])    # the risk of a steer is named
        self.assertIn(f"--cancel {rid}", notes[0])    # the queued copy is withdrawn first: a steer resend beside it would deliver the text twice
        self.assertLess(notes[0].index("--cancel"), notes[0].index("--steer"))
        self.assertIn("[busy alert: pinged", shown[0])
        self.assertEqual((relay.rec_read(rid)["state"], len(self.messages())), ("delivered", 1))
        self.assertNotIn("--steer", "".join(t for _a, t in self.messages()))    # the queued text itself went out as written: never steered

    def test_nothing_before_the_threshold(self) -> None:
        rid = self.queue()
        self.old(rid, 1000)
        self.drive(rid, [self.nothing, self.nothing])
        self.assertEqual((self.ping_lines(), self.to_sender()), ([], []))

    def test_zero_turns_it_off(self) -> None:
        os.environ["RELAY_BUSY_ALERT_S"] = "0"
        rid = self.queue()
        self.old(rid, 100000)
        self.drive(rid, [self.nothing, self.nothing])
        self.assertEqual((self.ping_lines(), self.to_sender()), ([], []))

    def test_a_failed_ping_does_not_cost_the_notice_or_the_message_and_the_retry_does_not_repeat_the_notice(self) -> None:
        self.script("fail")
        rid = self.queue()
        self.old(rid, 1900)

        def retry_ready() -> None:    # the retry delay passes
            data = json.loads(relay.card_alerts_path().read_text())
            relay.card_alerts_path().write_text(json.dumps({k: dict(v, retry_at=0) for k, v in data.items()}))
        self.drive(rid, [self.nothing, retry_ready, self.nothing])
        self.assertGreaterEqual(len(self.ping_lines()), 2)    # retried after the delay passed
        self.assertEqual(len(self.to_sender()), 1)    # one notice
        self.assertEqual((relay.rec_read(rid)["state"], len(self.messages())), ("delivered", 1))

    def test_a_message_behind_the_head_of_the_queue_still_tells_its_sender_and_the_operator(self) -> None:
        """local-review r2: only the head of a target's queue looks at the target, so a later record's deliverer waits in `earlier_unfinished`; its sender
        would otherwise hear nothing for the whole life of the record."""
        head = self.queue("first message to the peer")
        behind = self.queue("second message to the peer")
        self.old(head, 4000)
        self.old(behind, 1900)
        self.patch_rec(head, expires=time.time() + 86400)
        seen: list[Any] = []

        def finish_head() -> None:
            seen.append(self.to_sender())
            seen.append(self.ping_lines())    # while still behind
            relay.finish(head, "failed", "test: gone", allowed=("queued",), notify=None)
        self.drive(behind, [finish_head, self.nothing])
        self.assertEqual(seen[1], [])    # no operator ping for a backlog record: what holds the head pings for itself, with its own wording
        self.assertEqual(len(self.ping_lines()), 1)    # once it IS the head of a working target it pings as any working-target message does
        self.assertEqual(len(seen[0]), 1, seen)    # the notice went out while it was still behind
        self.assertIn("behind it", seen[0][0])
        self.assertNotIn("--steer", seen[0][0])    # a steer is advice for a WORKING target, not for a backlog
        self.assertIn(f"--cancel {behind}", seen[0][0])

    def test_a_message_that_is_itself_a_notice_never_gets_one(self) -> None:
        rid = self.queue()
        self.old(rid, 1900)
        self.patch_rec(rid, kind="notice")
        self.drive(rid, [self.nothing])
        self.assertEqual(len(self.ping_lines()), 1)    # the operator is still told
        self.assertEqual(self.to_sender(), [])

    def test_a_target_on_a_card_gets_the_card_alert_not_the_busy_one(self) -> None:
        self.cards = list(CARD)
        rid = self.queue()
        self.old(rid, 5000)    # old, but the target is not merely working: the card clock decides
        self.drive(rid, [self.nothing, self.nothing])
        self.assertEqual((self.ping_lines(), self.to_sender()), ([], []))


if __name__ == "__main__":
    unittest.main()
