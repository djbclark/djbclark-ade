#!/usr/bin/env python3
"""A reason-bearing retirement for expectations in relay.py (2026-10-29): `--retire ID --reason "..."` closes an expectation that will
never be answered instead of hand-editing or deleting its record, which is why a backlog of them could not be cleared with a reason.

Rules pinned here: only an `open` expectation retires (`acked` is settled, `reserved` is a send that has not returned yet); the reason is
mandatory and blank is a usage error; an unknown ID is exit 1; re-retiring is a no-op that exits 0; the record keeps its reason, evidence
and retiring session, `--pending` shows them, and neither `--pending` nor `--sweep` calls a retired record OVERDUE. Every id here is fake
and every record lives in the harness's throwaway queue.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import time
import unittest
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet = fb.relay, fb.fleet


def record(eid: str, state: str = "open", **kw: Any) -> dict[str, Any]:
    """An expectation as relay writes it: a Paseo sender with no transcript (`tx` null), one live-looking target."""
    now = time.time()
    return {"id": eid, "state": state, "created": kw.pop("created", now - 3600), "acked": None, "within": 1800,
            "sender": "w9:p9", "sender_sid": "", "sender_label": "", "tx": None, "mark": 0,
            "target": {"id": "aaaa1111", "name": "peer-fb", "paseo": "aaaa1111-0000-4000-8000-000000000000",
                       "sid8": "", "sid": "", "host": "paseo"}, **kw}


class Base(fb.Harness):
    def setUp(self) -> None:
        super().setUp()
        saved = fleet.LINKS_FILE
        fleet.LINKS_FILE = self.tmp / "links.json"    # `--sweep` reads the link ledger: never the operator's
        self.addCleanup(setattr, fleet, "LINKS_FILE", saved)

    def write(self, rec: dict[str, Any]) -> dict[str, Any]:
        relay.expect_write(rec)
        return rec

    def read(self, eid: str) -> dict[str, Any]:
        rec = relay.expect_read(eid)
        self.assertIsNotNone(rec, f"expectation {eid} vanished")
        return rec  # type: ignore[return-value]

    def retire(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay._main(["--retire", *argv])
        return rc, out.getvalue(), err.getvalue()

    def pending(self, as_json: bool = False) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            relay.pending_cmd(as_json)
        return out.getvalue()


class TestRetire(Base):
    def test_retires_an_open_expectation_and_keeps_why(self) -> None:
        self.write(record("q-dead-both"))
        rc, out, err = self.retire("q-dead-both", "--reason", "both ends dead", "--evidence", "20261029-111906-5d0bb4")
        self.assertEqual((rc, err), (0, ""), out + err)
        rec = self.read("q-dead-both")
        self.assertEqual(rec["state"], "retired")
        self.assertEqual(rec["reason"], "both ends dead")
        self.assertEqual(rec["evidence"], "20261029-111906-5d0bb4")
        self.assertEqual(rec["retired_by"], "harness-job")    # RELAY_SENDER_NAME: a declared job names itself
        self.assertGreater(rec["retired"], rec["created"])
        self.assertEqual(rec["sender"], "w9:p9")    # the identity of the ask stays: who asked, whom, when
        self.assertEqual(rec["target"]["id"], "aaaa1111")
        self.assertIn("retired: q-dead-both", out)

    def test_a_missing_or_blank_reason_is_a_usage_error_and_writes_nothing(self) -> None:
        self.write(record("q-needs-reason"))
        for argv in (("q-needs-reason",), ("q-needs-reason", "--reason", ""), ("q-needs-reason", "--reason", "   \n ")):
            rc, out, err = self.retire(*argv)
            self.assertEqual(rc, 2, out + err)
            self.assertIn("--reason", err)
            self.assertEqual(self.read("q-needs-reason")["state"], "open")

    def test_only_an_open_expectation_retires(self) -> None:
        self.write(record("q-answered", state="acked", acked=time.time() - 60))
        self.write(record("q-in-flight", state="reserved"))
        for eid, state in (("q-answered", "acked"), ("q-in-flight", "reserved")):
            rc, out, err = self.retire(eid, "--reason", "not really")
            self.assertEqual(rc, 1, out + err)
            self.assertIn(state, err)
            rec = self.read(eid)
            self.assertEqual(rec["state"], state)
            self.assertNotIn("reason", rec)

    def test_unknown_and_malformed_ids(self) -> None:
        rc, _, err = self.retire("no-such-expect", "--reason", "x")
        self.assertEqual(rc, 1)
        self.assertIn("no expectation", err)
        rc, _, err = self.retire("bad id!", "--reason", "x")
        self.assertEqual(rc, 2)
        self.assertIn("no expectation", err)

    def test_re_retiring_is_a_no_op_that_keeps_the_first_reason(self) -> None:
        self.write(record("q-twice"))
        self.assertEqual(self.retire("q-twice", "--reason", "first why")[0], 0)
        first = self.read("q-twice")
        rc, out, err = self.retire("q-twice", "--reason", "second why")
        self.assertEqual((rc, err), (0, ""), out + err)
        self.assertIn("already retired", out)
        self.assertEqual(self.read("q-twice"), first)    # nothing rewritten: a re-run cannot lose the recorded reason

    def test_the_retiring_session_is_recorded_when_a_session_runs_it(self) -> None:
        os.environ.pop("RELAY_SENDER_NAME", None)    # a session, not a declared job: the fleet `self` row names it
        # patch.object, never a bare assignment: `fleet` is shared by every other test module in this pytest process.
        patcher = mock.patch.object(fleet, "sessions", lambda: [{"id": "me123456", "self": True, "name": "c1-closed-port-pt"}])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write(record("q-by-session"))
        self.assertEqual(self.retire("q-by-session", "--reason", "superseded")[0], 0)
        self.assertEqual(self.read("q-by-session")["retired_by"], "me123456")

    def test_reason_needs_retire_and_retire_is_not_a_send(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(relay._main(["--reason", "orphan"]), 2)
            self.assertEqual(relay._main(["--evidence", "orphan"]), 2)
            self.assertEqual(relay._main(["--retire", "q-x", "--reason", "x", "peer-fb", "hello"]), 2)
        self.assertIn("used with --retire", err.getvalue())
        self.assertIn("cannot be combined", err.getvalue())


class TestWhoRetires(Base):
    """Adversary 2026-10-29 B1/B2: the record must name the side that acted, and the side being waited on must not be able to silence it."""

    def self_row(self, **row: Any) -> None:
        patcher = mock.patch.object(fleet, "sessions", lambda: [{"self": True, "name": "c1-closed-port-pt", **row}])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_session_identity_wins_over_a_declared_job_label(self) -> None:
        self.self_row(id="me123456")    # the harness sets RELAY_SENDER_NAME=harness-job, and a session still wins (sender_name's rule)
        self.write(record("q-both-names"))
        self.assertEqual(self.retire("q-both-names", "--reason", "superseded")[0], 0)
        self.assertEqual(self.read("q-both-names")["retired_by"], "me123456")

    def test_a_declared_label_is_sanitized_and_can_never_claim_hermes(self) -> None:
        self.self_row()    # a row with no id: the declared label is all relay has (a launchd job)
        os.environ["RELAY_SENDER_NAME"] = "operator\nOVERDUE expect-ack fake  open"
        self.write(record("q-forged"))
        self.assertEqual(self.retire("q-forged", "--reason", "target pane is dead")[0], 0)
        stored = self.read("q-forged")["retired_by"]
        self.assertNotIn("\n", stored)
        rows = [ln for ln in self.pending().splitlines() if "q-forged" in ln]
        self.assertEqual(len(rows), 1, self.pending())    # the reason cannot smuggle in a second row
        os.environ["RELAY_SENDER_NAME"] = "hermes 1234abcd"
        self.write(record("q-hermes"))
        self.assertEqual(self.retire("q-hermes", "--reason", "answered out of band")[0], 0)
        self.assertEqual(self.read("q-hermes")["retired_by"], "")    # no declared label may speak as Hermes
        self.assertIn("| by ?", next(ln for ln in self.pending().splitlines() if "q-hermes" in ln))

    def test_the_target_cannot_retire_its_own_expectation(self) -> None:
        self.self_row(id="aaaa1111")    # record()'s target id: the party that owes the ack
        self.write(record("q-owed"))
        rc, out, err = self.retire("q-owed", "--reason", "answered out of band")
        self.assertEqual(rc, 1, out + err)
        self.assertIn("ack q-owed", err)
        self.assertEqual(self.read("q-owed")["state"], "open")    # the operator's page stays up until it really answers

    def test_the_same_session_by_its_session_id_prefix_is_refused_too(self) -> None:
        self.self_row(id="w7:p1", sid="deadbeefcafe1111")
        self.write(record("q-owed-sid", target={"id": "bbbb2222", "name": "peer-fb", "sid8": "deadbeef", "sid": "", "host": "claude"}))
        rc, out, err = self.retire("q-owed-sid", "--reason", "answered out of band")
        self.assertEqual(rc, 1, out + err)
        self.assertEqual(self.read("q-owed-sid")["state"], "open")

    def test_another_session_may_still_retire_it(self) -> None:
        self.self_row(id="zzz99999")    # neither the sender (w9:p9) nor the target (aaaa1111)
        self.write(record("q-third-party"))
        self.assertEqual(self.retire("q-third-party", "--reason", "both ends gone")[0], 0)
        self.assertEqual(self.read("q-third-party")["retired_by"], "zzz99999")


class TestRetireText(Base):
    def test_control_characters_are_stripped_and_the_line_is_bounded(self) -> None:
        self.write(record("q-noisy"))
        self.assertEqual(self.retire("q-noisy", "--reason", "target \x1b[31mred\x7f\ttab\nnew line",
                                     "--evidence", "a" * 900)[0], 0)
        rec = self.read("q-noisy")
        self.assertEqual(rec["reason"], "target [31mred tab new line")    # no ESC, no DEL, one line
        self.assertEqual(len(rec["evidence"]), 500)    # capped, so every --pending --json stays small
        self.assertTrue(rec["evidence"].startswith("aaa") and rec["evidence"].endswith("…"))

    def test_a_long_reason_keeps_its_beginning(self) -> None:
        self.write(record("q-long"))
        self.assertEqual(self.retire("q-long", "--reason", "answered out of band: " + "x" * 900)[0], 0)
        reason = self.read("q-long")["reason"]
        self.assertTrue(reason.startswith("answered out of band:"))    # the kind of retirement leads, so the tail is what goes
        self.assertEqual(len(reason), 500)

    def test_json_reports_what_the_record_says(self) -> None:
        self.write(record("q-json"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(relay._main(["--retire", "q-json", "--reason", "target gone", "--json"]), 0)
        row = json.loads(out.getvalue())
        self.assertEqual({k: row[k] for k in ("id", "state", "reason", "already")},
                         {"id": "q-json", "state": "retired", "reason": "target gone", "already": False})
        self.assertEqual(row["retired_by"], "harness-job")


class TestRetiredRecordsStayInert(Base):
    def test_pending_shows_the_reason_and_never_overdue(self) -> None:
        self.write(record("q-cleared", created=time.time() - 4 * 86400))    # long past --ack-within, and past 72 h
        self.assertEqual(self.retire("q-cleared", "--reason", "sender pane w2N:pZ is dead")[0], 0)
        text = self.pending()
        line = next(ln for ln in text.splitlines() if "q-cleared" in ln)
        self.assertNotIn("OVERDUE", line)
        self.assertIn("retired expect-ack q-cleared", line)
        self.assertIn("sender pane w2N:pZ is dead", line)
        self.assertIn("harness-job", line)
        row = next(r for r in json.loads(self.pending(True)) if r["id"] == "q-cleared")
        self.assertEqual((row["kind"], row["state"], row["overdue"], row["assumed_lost"]), ("expect", "retired", False, False))
        self.assertEqual(row["reason"], "sender pane w2N:pZ is dead")

    def test_a_sweep_leaves_it_inert(self) -> None:
        self.write(record("q-swept", created=time.time() - 4 * 86400))
        self.assertEqual(self.retire("q-swept", "--reason", "answered out of band: 20261029-055748-32e0c6")[0], 0)
        before = self.read("q-swept")
        acked, overdue = relay.ack_sweep()
        self.assertEqual((acked, overdue), (0, []))
        self.assertEqual(self.read("q-swept"), before)    # neither re-acked nor re-dated by a sweep
        self.assertEqual(relay.expect_view()[-1]["state"], "retired")

    def test_cancel_still_refuses_an_expectation_and_points_at_retire(self) -> None:
        self.write(record("q-not-a-defer"))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(relay._main(["--cancel", "q-not-a-defer"]), 1)
        self.assertIn("--retire", err.getvalue())
        self.assertEqual(self.read("q-not-a-defer")["state"], "open")    # --cancel cannot close it, by design


if __name__ == "__main__":
    unittest.main()
