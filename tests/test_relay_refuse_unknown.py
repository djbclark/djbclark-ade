#!/usr/bin/env python3
"""relay.py refuses to send when it cannot resolve the sender (2026-10-25, djbclark via the load-watcher agent bb2a32df).

A message with no reverse contact (`[relay from unknown]`) cannot be answered, so relay exits 4 with nothing sent, queued or
recorded, and tells the CALLER what was checked and how to re-run. Every id here is fake; nothing reaches a live session.
"""
from __future__ import annotations

import json
import os
import unittest
from typing import Any

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, sess = fb.relay, fb.sess
CHECKED = ("PASEO_AGENT_ID", "HERDR_PANE_ID", "CLAUDE_CODE_SESSION_ID", "HERMES_SESSION_ID", "RELAY_SENDER_NAME", "RELAY_SENDER", "ancestor", "fleet")


class TestRefusal(fb.Harness):
    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("RELAY_SENDER_NAME", None)    # a caller with no identity: a launchd job, a script, Hermes
        self.typed: list[str] = []
        relay.type_line = lambda chan, text: self.typed.append(text) or True

    def assert_nothing_happened(self) -> None:
        self.assertEqual((self.typed, self.calls, self.spawned, relay.rec_all()), ([], [], [], []))
        self.assertFalse(relay.UNSENT.exists())
        self.assertFalse(relay.DEFER_DIR.exists() and any(relay.DEFER_DIR.iterdir()))

    def test_an_idle_target_is_not_sent_to_and_the_exit_is_distinct(self) -> None:
        rc, out, err = self.run_main(sess(status="idle"))
        self.assertEqual((rc, out), (relay.NO_SENDER_EXIT, ""))
        self.assertEqual(relay.NO_SENDER_EXIT, 4)
        self.assert_nothing_happened()

    def test_the_message_names_everything_checked_and_what_the_caller_does(self) -> None:
        _, _, err = self.run_main(sess(status="idle"))
        self.assertIn("not sent", err)
        for name in CHECKED:
            self.assertIn(name, err)
        self.assertIn("RELAY_SENDER_NAME=", err)
        self.assertNotIn("relay from unknown", err.replace("`[relay from unknown]`", ""))

    def test_a_busy_target_is_not_queued_either(self) -> None:
        rc, _, _ = self.run_main(sess(status="working"))
        self.assertEqual(rc, relay.NO_SENDER_EXIT)
        self.assert_nothing_happened()

    def test_the_refusal_comes_before_the_target_is_looked_up(self) -> None:
        relay.fleet.sessions = lambda: []
        self.assertEqual(relay.main(["nobody-here", "hello there friend", "--no-defer"]), relay.NO_SENDER_EXIT)

    def test_json_carries_the_reason(self) -> None:
        rc, out, _ = self.run_main(sess(status="idle"), "--json")
        self.assertEqual(rc, relay.NO_SENDER_EXIT)
        doc: dict[str, Any] = json.loads(out)
        self.assertEqual((doc["sent"], doc["error"], doc["exit"]), (False, "no_sender", 4))
        for name in CHECKED[:5]:
            self.assertIn(name, doc["reason"])
        self.assertEqual(doc["checked_env"], ["PASEO_AGENT_ID", "HERDR_PANE_ID", "CLAUDE_CODE_SESSION_ID", "HERMES_SESSION_ID", "RELAY_SENDER_NAME"])

    def test_ack_does_not_turn_the_refusal_into_another_code(self) -> None:
        rc, _, _ = self.run_main(sess(status="idle"), "--ack")
        self.assertEqual(rc, relay.NO_SENDER_EXIT)
        self.assert_nothing_happened()

    def test_a_usage_error_is_still_exit_2(self) -> None:
        rc, _, _ = self.run_main(sess(status="idle"), "--defer-for", "0")
        self.assertEqual(rc, 2)

    def test_plan_prints_routes_without_a_sender(self) -> None:
        rc, out, _ = self.run_main(sess(status="idle"), "--plan")
        self.assertEqual((rc, out.strip()), (0, "pane"))
        self.assert_nothing_happened()

    def test_a_declared_label_sends_under_it(self) -> None:
        os.environ["RELAY_SENDER_NAME"] = "load-watch"
        senders: list[str] = []
        relay.claude_socket = lambda s: "/tmp/sock"
        relay.socket_send = lambda sock, sender, text: senders.append(sender) or True
        rc, _, err = self.run_main(sess(status="working", chan=None, transcript=None))
        self.assertEqual((rc, senders), (0, ["load-watch"]), err)

    def test_a_declared_label_that_sanitizes_to_nothing_is_still_refused(self) -> None:
        os.environ["RELAY_SENDER_NAME"] = "!!!"
        rc, _, _ = self.run_main(sess(status="idle"))
        self.assertEqual(rc, relay.NO_SENDER_EXIT)
        self.assert_nothing_happened()

    def test_a_declared_label_cannot_pose_as_a_hermes_relay(self) -> None:
        """Adversary r1 A7 (2026-10-25): `hermes xxxx` is the label of a relayed Hermes turn or a Hermes-started relay, never a declared one."""
        for label in ("hermes abcd1234", "hermes x"):
            with self.subTest(label=label):
                os.environ["RELAY_SENDER_NAME"] = label
                self.assertEqual(relay.sender_name([]), "unknown")
                rc, _, _ = self.run_main(sess(status="idle"))
                self.assertEqual(rc, relay.NO_SENDER_EXIT)
                self.assert_nothing_happened()

    def test_a_declared_label_of_unknown_is_refused(self) -> None:
        os.environ["RELAY_SENDER_NAME"] = "unknown"
        rc, _, _ = self.run_main(sess(status="idle"))
        self.assertEqual(rc, relay.NO_SENDER_EXIT)


    def test_no_route_can_build_an_unknown_header(self) -> None:
        for build in (relay.sender_tag, relay.sender_header_name):
            with self.assertRaises(relay.NoSender):
                build([])

    def test_a_deliverer_with_no_stored_label_is_refused_too(self) -> None:
        relay.SENDER_OVERRIDE[0] = "unknown"    # a record queued before this rule, or whose label is reserved
        self.addCleanup(relay.SENDER_OVERRIDE.__setitem__, 0, None)
        rc, _, _ = self.run_main(sess(status="idle"))
        self.assertEqual(rc, relay.NO_SENDER_EXIT)
        self.assert_nothing_happened()


class TestHermesStartedRelay(fb.Harness):
    """Adversary r1 A3 (2026-10-25): a relay Hermes starts itself (terminal tool, background process) has only HERMES_SESSION_ID."""

    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("RELAY_SENDER_NAME", None)
        os.environ.pop("HERMES_SESSION_ID", None)
        self.senders: list[str] = []
        relay.claude_socket = lambda s: "/tmp/sock"
        relay.socket_send = lambda sock, sender, text: self.senders.append(sender) or True

    def send(self) -> int:
        rc, _, err = self.run_main(sess(status="working", chan=None, transcript=None))
        return rc if rc == 0 else self.fail(err)

    def test_it_sends_as_hermes_with_the_last_eight_characters_of_its_session_id(self) -> None:
        os.environ["HERMES_SESSION_ID"] = "20261023_000000_abcdef12"
        self.assertEqual((self.send(), self.senders), (0, ["hermes abcdef12"]))

    def test_a_live_session_identity_outranks_it(self) -> None:
        os.environ["HERMES_SESSION_ID"] = "20261023_000000_abcdef12"
        os.environ["CLAUDE_CODE_SESSION_ID"] = "12345678-aaaa-4000-8000-000000000001"
        self.send()
        self.assertTrue(self.senders[0].startswith("claude 12345678"), self.senders)

    def test_an_id_that_makes_no_label_is_still_refused(self) -> None:
        os.environ["HERMES_SESSION_ID"] = "not a label!!"
        rc, _, _ = self.run_main(sess(status="working", chan=None, transcript=None))
        self.assertEqual((rc, self.senders), (relay.NO_SENDER_EXIT, []))


if __name__ == "__main__":
    unittest.main()
