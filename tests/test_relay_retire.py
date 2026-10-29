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
        relay.fleet.sessions = lambda: [{"id": "me123456", "self": True, "name": "c1-closed-port-pt"}]
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
