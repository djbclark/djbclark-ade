#!/usr/bin/env python3
"""`relay.py --status ID`, `--pending --queued-only|--older-than|--summary`, `--sweep` STUCK lines, the named obstacle in the `queued:` line,
the deferred.log cap and the week-old prune (2026-10-31).

Why: on 2026-10-30/31 an agent relaying to a Paseo peer whose tab had a question card up could not tell "queued" from "delivered" (the only
authoritative answer was `--cancel`, which destroyed two still-queued messages), read a 346-line `--pending` with `tail`, and escalated to the
operator twice about silence that was a queue. Every id, path and text here is fake; every state lives under a temp directory.
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import threading
import re
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import test_relay_fallback as fb  # noqa: E402  # pyright: ignore[reportMissingImports]

relay, fleet = fb.relay, fb.fleet
NOW = 1_800_000_000.0
SECRET = "the deploy token is hunter2-not-a-real-token"
CARD_ID = "frm_18f85bead001xBPfK85BC2N2Gx"
QUEUED = "20261030-211457-b98c64"
SENDING = "20261030-210000-cccccc"
DELIVERED = "20261030-190000-aaaaaa"
FAILED = "20261029-100000-bbbbbb"
TARGET = {"id": "d2a505dd", "paseo": fb.AGENT, "name": "dann-vps"}
SENDER = "claude aaaaaaaa aka alice (here)"
CARD_LOOK = {"state": "card:question", "why": "blocked on a permission or question (a QUESTION (AskUserQuestion)): typed text would answer it",
             "agree": True, "at": NOW - 800, "cards": [{"id": CARD_ID, "tool": "AskUserQuestion", "kind": "question"}]}


def rec(rid: str, state: str, age: float, **kw: Any) -> dict[str, Any]:
    return {"id": rid, "target": dict(TARGET), "text": SECRET, "sender": SENDER, "sender_ident": "", "kind": "", "created": NOW - age,
            "expires": NOW + 20000, "state": state, "outcome": "", "pid": 0, "notice": "", **kw}


class Base(unittest.TestCase):
    """The deferred directory, the links file and the clock pinned; the deliverer never started."""

    def setUp(self) -> None:
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="relay-status-"))
        for name, val in (("DEFER_DIR", self.tmp / "relay" / "deferred"), ("UNSENT", self.tmp / "unsent.json")):
            self.addCleanup(setattr, relay, name, getattr(relay, name))
            setattr(relay, name, val)
        self.addCleanup(setattr, fleet, "LINKS_FILE", fleet.LINKS_FILE)
        fleet.LINKS_FILE = self.tmp / "links.json"
        self.addCleanup(setattr, relay, "spawn_deliverer", relay.spawn_deliverer)
        self.spawned: list[str] = []
        relay.spawn_deliverer = lambda rid: self.spawned.append(rid) or 4242
        patcher = mock.patch.dict(os.environ, {"RELAY_DEFER_DIR": str(relay.DEFER_DIR)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = relay.DEFER_DIR.parent / "deferred.log"
        self.log.parent.mkdir(parents=True)    # the state directory exists in real use (defer_dir made it); DEFER_DIR itself still does not

    def cli(self, *argv: str, now: float | None = NOW) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                (mock.patch.object(relay.time, "time", lambda: now) if now is not None else contextlib.nullcontext()):
            rc = relay.main(list(argv), sweep=False)
        return rc, out.getvalue(), err.getvalue()

    def fixture(self) -> None:
        for r in (rec(FAILED, "failed", 100000, outcome="target changed: another session now holds that pane", finished=NOW - 99000),
                  rec(DELIVERED, "delivered", 7300, outcome="relayed to [d2a505dd] dann-vps", finished=NOW - 7200),
                  rec(QUEUED, "queued", 860, look=CARD_LOOK, pid=os.getpid()),
                  rec(SENDING, "sending", 400)):
            relay.rec_write(r)
        relay.expect_write({"id": "ack1", "state": "open", "sender": "aaaaaaaa", "sender_label": "alice", "target": dict(TARGET), "created": NOW - 100,
                            "within": 1800})
        self.log.write_text(
            f"2026-10-30T21:14:57-04:00 {QUEUED} queued target={fb.AGENT} blocked on a permission or question\n"
            f"2026-10-30T21:15:02-04:00 {QUEUED} look target={fb.AGENT} card:question: blocked on card {CARD_ID} (question: AskUserQuestion)\n"
            f"2026-10-30T21:15:03-04:00 {DELIVERED} delivered target={fb.AGENT} relayed to [d2a505dd] dann-vps\n")

    def snapshot(self) -> dict[str, Any]:
        root = self.tmp
        return {"files": {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode) for p in root.rglob("*") if p.is_file()},
                "dirs": sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir())}


class TestStatus(Base):
    def test_status_changes_nothing_in_the_record_the_log_or_the_expectation_store(self) -> None:
        self.fixture()
        relay.expect_write({"id": QUEUED, "state": "open", "sender": "aaaaaaaa", "sender_label": "alice", "target": dict(TARGET), "created": NOW - 600,
                            "within": 300})    # an expectation that shares the record's id
        before = self.snapshot()
        for argv in (("--status", QUEUED), ("--status", QUEUED, "--json"), ("--show", DELIVERED), ("--status", FAILED), ("--status", SENDING)):
            rc, out, err = self.cli(*argv)
            self.assertEqual((rc, err), (0, ""), argv)
            self.assertNotIn(SECRET, out)    # the text stays in the 0600 record
        self.assertEqual(self.snapshot(), before)    # byte-for-byte (and mtime, mode, no new file or directory: no lock was even taken)

    def test_a_queued_record_shows_state_age_the_card_the_timeline_and_the_expectation_with_its_id(self) -> None:
        self.fixture()
        relay.expect_write({"id": QUEUED, "state": "open", "sender": "aaaaaaaa", "sender_label": "alice", "target": dict(TARGET), "created": NOW - 600,
                            "within": 300})
        rc, out, _ = self.cli("--status", QUEUED)
        self.assertEqual(rc, 0)
        self.assertRegex(out, rf"^{QUEUED}  queued  \[d2a505dd\] dann-vps  from {re.escape(SENDER)}\n")
        self.assertIn("age 14m 20s", out)
        self.assertIn(f"last look: card:question at ", out)
        self.assertIn(f"blocked on card {CARD_ID} (question: AskUserQuestion)", out)
        self.assertIn("(800s ago)", out)
        self.assertIn(f"2026-10-30T21:14:57-04:00 queued", out)    # the timeline, in order
        self.assertLess(out.index("21:14:57"), out.index("21:15:02"))
        self.assertIn(f"expect-ack {QUEUED}: open, 10m old (reply due within 5m)  OVERDUE", out)
        self.assertNotIn("21:15:03", out)    # another record's event is not this one's
        data = json.loads(self.cli("--status", QUEUED, "--json")[1])
        self.assertEqual((data["state"], data["final"], data["age_s"], data["look"]["age_s"], [e["event"] for e in data["events"]]),
                         ("queued", False, 860, 800, ["queued", "look"]))
        self.assertEqual(data["events"][1]["detail"], f"card:question: blocked on card {CARD_ID} (question: AskUserQuestion)")
        self.assertEqual(data["deliverer"], {"pid": os.getpid(), "running": True})
        self.assertEqual([e["id"] for e in data["expectations"]], [QUEUED])

    def test_a_delivered_record_says_so_and_a_final_one_has_no_deliverer(self) -> None:
        self.fixture()
        rc, out, _ = self.cli("--status", DELIVERED)
        self.assertEqual(rc, 0)
        self.assertIn("delivered", out.splitlines()[0])
        self.assertIn("outcome: relayed to [d2a505dd] dann-vps", out)
        self.assertNotIn("deliverer:", out)
        self.assertIn("2026-10-30T21:15:03-04:00 delivered relayed to [d2a505dd] dann-vps", out)

    def test_an_unknown_or_malformed_id_exits_1_and_creates_nothing(self) -> None:
        for argv in (("--status", "20261030-000000-abcdef"), ("--show", "../../etc/passwd"), ("--status", "")):
            rc, out, err = self.cli(*argv)
            self.assertEqual((rc, out), (1, ""), argv)
            self.assertIn("no deferred message", err)
        self.assertFalse(relay.DEFER_DIR.exists())    # not even the directory: --status never mkdirs
        self.assertEqual(json.loads(self.cli("--status", "20261030-000000-abcdef", "--json")[1])["found"], False)

    def test_it_cannot_be_mixed_with_a_send_or_another_command(self) -> None:
        self.assertEqual(self.cli("--status", QUEUED, "--pending")[0], 2)
        self.assertEqual(self.cli("--status", QUEUED, "someone", "hello")[0], 2)

    def test_a_status_query_never_runs_the_mutation_it_is_combined_with(self) -> None:
        self.fixture()
        relay.expect_write({"id": "open1", "state": "open", "sender": "aaaaaaaa", "sender_label": "alice", "target": dict(TARGET), "created": NOW - 100, "within": 1800})
        before = self.snapshot()
        for argv in (("--status", QUEUED, "--cancel", QUEUED), ("--show", QUEUED, "--cancel", QUEUED),
                     ("--status", "open1", "--retire", "open1", "--reason", "gone"), ("--status", QUEUED, "--transfer-expectations", "old"),
                     ("--status", QUEUED, "--deliver", QUEUED), ("--status", QUEUED, "--reason", "x"), ("--status", QUEUED, "--sweep"),
                     ("--status", QUEUED, "--why"), ("--status", QUEUED, "--no-defer"), ("--status", QUEUED, "--queued-only")):
            rc, out, err = self.cli(*argv)
            self.assertEqual((rc, out), (2, ""), argv)
            self.assertIn("--status is a query and cannot be combined with", err)
        self.assertEqual(self.snapshot(), before)    # nothing was withdrawn, retired, delivered or swept
        self.assertEqual((relay.rec_read(QUEUED)["state"], relay.expect_read("open1")["state"]), ("queued", "open"))
        self.assertEqual(self.cli("--status", QUEUED, "--json")[0], 0)    # --json is the one companion

    def test_the_timeline_reads_the_rotated_logs_too(self) -> None:
        self.fixture()
        self.log.rename(self.log.with_name("deferred.log.1"))
        self.log.write_text(f"2026-10-30T21:20:00-04:00 {QUEUED} look target={fb.AGENT} working\n")
        data = json.loads(self.cli("--status", QUEUED, "--json")[1])
        self.assertEqual([e["event"] for e in data["events"]], ["queued", "look", "look"])


class TestPendingFilters(Base):
    GOLDEN = (
        f"{FAILED}  failed    [d2a505dd] dann-vps  from {SENDER}  1666m old  target changed: another session now holds that pane\n"
        f"{DELIVERED}  delivered [d2a505dd] dann-vps  from {SENDER}  121m old  relayed to [d2a505dd] dann-vps\n"
        f"{QUEUED}  queued    [d2a505dd] dann-vps  from {SENDER}  14m old  [why: {CARD_LOOK['why']}]\n"
        f"{SENDING}  sending   [d2a505dd] dann-vps  from {SENDER}  6m old\n"
        "expect-ack ack1  open   [d2a505dd] dann-vps  from alice  1m old (reply due within 30m)\n")

    def test_plain_pending_is_byte_identical_to_what_scripts_parse(self) -> None:
        self.fixture()
        rc, out, _ = self.cli("--pending")
        self.assertEqual((rc, out), (0, self.GOLDEN))    # the golden was produced by the code at fix-relay-ack bc338bed
        rows = json.loads(self.cli("--pending", "--json")[1])
        self.assertEqual([r["id"] for r in rows if "kind" not in r], [FAILED, DELIVERED, QUEUED, SENDING])
        self.assertEqual(self.cli("--pending", "--text")[1].count(" | "), 4)

    def test_queued_only_keeps_the_non_final_records_and_drops_expectation_rows(self) -> None:
        self.fixture()
        rc, out, _ = self.cli("--pending", "--queued-only")
        self.assertEqual((rc, [ln.split()[0] for ln in out.splitlines()]), (0, [QUEUED, SENDING]))
        self.assertEqual(out, "".join(ln + "\n" for ln in self.GOLDEN.splitlines() if ln.startswith((QUEUED, SENDING))))    # the rows as always
        rows = json.loads(self.cli("--pending", "--queued-only", "--json")[1])
        self.assertEqual([r["id"] for r in rows], [QUEUED, SENDING])

    def test_older_than_is_a_floor_on_age_and_combines_with_queued_only(self) -> None:
        self.fixture()
        ids = lambda *argv: [ln.split()[0] for ln in self.cli(*argv)[1].splitlines()]    # noqa: E731
        self.assertEqual(ids("--pending", "--older-than", "7200"), [FAILED, DELIVERED])
        self.assertEqual(ids("--pending", "--older-than", "860"), [FAILED, DELIVERED, QUEUED])    # at least S old: 860 s is old enough
        self.assertEqual(ids("--pending", "--older-than", "861"), [FAILED, DELIVERED])
        self.assertEqual(ids("--pending", "--queued-only", "--older-than", "600"), [QUEUED])
        self.assertEqual(self.cli("--pending", "--older-than", "999999")[1], "no matching deferred messages\n")

    def test_summary_counts_by_state_and_names_the_oldest_open_one_with_its_obstacle(self) -> None:
        self.fixture()
        rc, out, _ = self.cli("--pending", "--summary")
        self.assertEqual((rc, out), (0, f"pending: 1 queued, 1 sending, 1 delivered, 1 failed; oldest non-final: 14m {QUEUED} -> [d2a505dd] "
                                        f"blocked on card {CARD_ID} (question: AskUserQuestion) [why: {CARD_LOOK['why']}]\n"))
        data = json.loads(self.cli("--pending", "--summary", "--json")[1])
        self.assertEqual((data["total"], data["counts"], data["oldest_non_final"]["id"], data["oldest_non_final"]["age_s"]),
                         (4, {"failed": 1, "delivered": 1, "queued": 1, "sending": 1}, QUEUED, 860))
        self.assertEqual(self.cli("--pending", "--summary", "--queued-only")[1].split(";")[0], "pending: 1 queued, 1 sending")
        self.assertEqual(self.cli("--pending", "--summary", "--older-than", "999999")[1], "pending: no deferred messages\n")

    def test_summary_with_nothing_open_says_so(self) -> None:
        relay.rec_write(rec(DELIVERED, "delivered", 7300, finished=NOW - 7200))
        self.assertEqual(self.cli("--pending", "--summary")[1], "pending: 1 delivered; none non-final\n")
        self.assertEqual(json.loads(self.cli("--pending", "--summary", "--json")[1])["oldest_non_final"], None)

    def test_the_filters_need_pending_and_a_sane_number(self) -> None:
        for argv in (("--queued-only",), ("--summary",), ("--older-than", "5"), ("--stuck-after", "5"),
                     ("--pending", "--older-than", "-1"), ("--pending", "--older-than", "nan"), ("--sweep", "--stuck-after", "inf")):
            self.assertEqual(self.cli(*argv)[0], 2, argv)


class TestStuck(Base):
    def test_sweep_flags_a_non_final_record_past_the_threshold_and_only_that(self) -> None:
        self.fixture()
        relay.rec_write(rec("20261030-211800-dddddd", "queued", 200, pid=os.getpid()))    # 3m: not yet
        with relay.deliverer_lock(SENDING) as held:    # a live deliverer: the sweep leaves a `sending` record alone (it fails one whose deliverer is gone)
            self.assertTrue(held)
            rc, out, _ = self.cli("--sweep")
        stuck = [ln for ln in out.splitlines() if ln.startswith("STUCK")]
        self.assertEqual(rc, 0)
        self.assertEqual([ln.split()[2] for ln in stuck], [QUEUED, SENDING])    # oldest first; final records and the 3-minute one are not there
        self.assertEqual(stuck[0], f"STUCK 14m {QUEUED} -> [d2a505dd] blocked on card {CARD_ID} (question: AskUserQuestion) [why: {CARD_LOOK['why']}]")
        self.assertEqual(stuck[1], f"STUCK 6m {SENDING} -> [d2a505dd] sending")

    def test_the_threshold_is_exclusive_and_settable(self) -> None:
        relay.rec_write(rec(QUEUED, "queued", 300, pid=os.getpid()))
        self.assertEqual([ln for ln in self.cli("--sweep")[1].splitlines() if ln.startswith("STUCK")], [])    # 300 s is not past 300
        relay.rec_write(rec(QUEUED, "queued", 301, pid=os.getpid()))
        self.assertEqual(len([ln for ln in self.cli("--sweep")[1].splitlines() if ln.startswith("STUCK")]), 1)
        relay.rec_write(rec(QUEUED, "queued", 100, pid=os.getpid()))
        self.assertEqual([ln for ln in self.cli("--sweep")[1].splitlines() if ln.startswith("STUCK")], [])
        out = self.cli("--sweep", "--stuck-after", "60")[1]
        self.assertIn(f"STUCK 1m {QUEUED} -> [d2a505dd] no look yet", out)    # no card, no look: said so, not guessed

    def test_a_look_without_a_card_names_its_state_and_why(self) -> None:
        relay.rec_write(rec(QUEUED, "queued", 900, look={"state": "silent", "why": "running, but nothing new for 20 min", "agree": True, "at": NOW - 5}))
        out = self.cli("--sweep")[1]
        self.assertIn(f"STUCK 15m {QUEUED} -> [d2a505dd] silent [why: running, but nothing new for 20 min]", out)

    def test_nothing_stuck_prints_nothing_extra(self) -> None:
        relay.rec_write(rec(DELIVERED, "delivered", 99999, finished=NOW - 99000))
        out = self.cli("--sweep")[1]
        self.assertNotIn("STUCK", out)
        self.assertTrue(out.startswith("swept: "), out)


class TestLogCap(Base):
    def test_the_log_rotates_at_the_cap_and_keeps_two_generations(self) -> None:
        self.addCleanup(setattr, relay, "DEFER_LOG_CAP", relay.DEFER_LOG_CAP)
        relay.DEFER_LOG_CAP = 600
        ids = [f"20261030-0000{n:02d}-abcdef" for n in range(60)]
        for rid in ids:
            relay.defer_log({"id": rid, "target": {"paseo": fb.AGENT}}, "look", "x" * 20)
        names = sorted(p.name for p in self.log.parent.iterdir() if p.name.startswith("deferred.log"))
        self.assertEqual(names, ["deferred.log", "deferred.log.1", "deferred.log.2"])    # never a .3
        sizes = [self.log.with_name(n).stat().st_size for n in names]
        self.assertTrue(all(s < 600 + 200 for s in sizes), sizes)    # a file holds the cap plus at most the line that crossed it
        have = {ln.split()[1] for n in names for ln in self.log.with_name(n).read_text().splitlines()}
        self.assertIn(ids[-1], have)    # the newest line is in the live log
        self.assertNotIn(ids[0], have)    # the oldest generation was dropped
        order = [ln.split()[1] for n in ("deferred.log.2", "deferred.log.1", "deferred.log") for ln in self.log.with_name(n).read_text().splitlines()]
        self.assertEqual(order, sorted(order))    # generations are contiguous and in order: nothing lost between them
        self.assertEqual(order, ids[len(ids) - len(order):])
        self.assertEqual(oct(self.log.stat().st_mode & 0o777), "0o600")

    def test_a_log_under_the_cap_is_only_appended_to(self) -> None:
        relay.defer_log({"id": QUEUED, "target": {"paseo": fb.AGENT}}, "queued", "waiting")
        relay.defer_log({"id": QUEUED, "target": {"paseo": fb.AGENT}}, "look", "card")
        self.assertEqual([p.name for p in self.log.parent.iterdir() if p.name.startswith("deferred.log")], ["deferred.log"])
        self.assertEqual(len(self.log.read_text().splitlines()), 2)


class TestPrune(Base):
    OLD = 8 * 86400

    def old_final(self, rid: str, **kw: Any) -> None:
        relay.rec_write(rec(rid, "delivered", self.OLD + 100, finished=NOW - self.OLD, **kw))

    def test_sweep_prunes_a_week_old_final_record_and_keeps_a_younger_and_an_open_one(self) -> None:
        self.old_final("20261020-000000-aaaaaa")
        relay.rec_write(rec("20261029-000000-bbbbbb", "delivered", 3 * 86400, finished=NOW - 3 * 86400))
        relay.rec_write(rec(QUEUED, "queued", self.OLD + 100, pid=os.getpid()))    # old but not final: never pruned
        rc, out, _ = self.cli("--sweep")
        self.assertEqual(rc, 0)
        self.assertIn("1 pruned", out)
        self.assertEqual(sorted(r["id"] for r in relay.rec_all()), ["20261029-000000-bbbbbb", QUEUED])

    def test_one_record_with_a_junk_field_does_not_stop_the_prune_of_the_others(self) -> None:
        relay.rec_write(rec("20261001-000000-cccccc", "delivered", self.OLD + 99999, finished="soon"))    # oldest: revive meets it first
        self.old_final("20261020-000000-aaaaaa")
        self.old_final("20261020-000001-aaaaab")
        self.assertIn("2 pruned", self.cli("--sweep")[1])
        self.assertEqual([r["id"] for r in relay.rec_all()], ["20261001-000000-cccccc"])

    def test_a_pruned_record_is_no_longer_found_and_the_message_says_why(self) -> None:
        self.old_final("20261020-000000-aaaaaa")
        self.cli("--sweep")
        rc, _, err = self.cli("--status", "20261020-000000-aaaaaa")
        self.assertEqual(rc, 1)
        self.assertIn("pruned a week after they finish", err)


class QueueBase(fb.Harness):
    """A busy Paseo target and an identified sender (the setup of fb.TestDeferredSend), for the `queued:` line."""

    def setUp(self) -> None:
        super().setUp()
        saved = relay.hosted_by
        relay.hosted_by = lambda a: False
        self.addCleanup(setattr, relay, "hosted_by", saved)
        os.environ["PASEO_AGENT_ID"] = fb.SENDER
        self.cards: list[dict[str, Any]] = []
        self.timeline_calls: list[str] = []
        target = fb.pasess(agent="cline", status="working")
        sender = fb.sess(id="bbbbbbbb", name="alice", agent="claude", host="paseo", paseo=fb.SENDER, chan=("paseo", fb.SENDER), status="idle")
        carol = fb.sess(id="ffffffff", name="carol", agent="cline", host="paseo", paseo=fb.CAROL, chan=("paseo", fb.CAROL), status="idle")
        rows = [target, sender, carol]
        self.status = "running"    # the target's Paseo status: "idle" lets a deliverer send
        self.sent: list[tuple[str, str]] = []
        relay.send_paseo = lambda s, text, wait: self.sent.append((s["paseo"], text)) or "delivered"    # proven in the target's timeline: the send counts
        relay.fleet.sessions = lambda: [dict(r, self=bool(r.get("paseo") == os.environ.get("PASEO_AGENT_ID"))) for r in rows]
        saved_links = relay.fleet.LINKS_FILE
        relay.fleet.LINKS_FILE = self.tmp / "links.json"
        self.addCleanup(setattr, relay.fleet, "LINKS_FILE", saved_links)
        relay.fleet.LINKS_FILE.write_text(json.dumps({"links": {relay.fleet.link_key(a["id"], b["id"]): {"sent": 1, "acked": None}
                                                                 for a in rows for b in rows}}))
        relay.paseo_inspect = lambda agent: {"Id": agent, "Status": self.status, "Cwd": "/x", "Archived": False, "PendingPermissions": list(self.cards)}
        relay.paseo_probe = lambda agent: (relay.paseo_inspect(agent), "ok")
        relay.paseo_card_detail = lambda agent: ("Which branch?" if self.cards else "", bool(self.cards))
        self.addCleanup(setattr, relay, "paseo_timeline", relay.paseo_timeline)
        relay.paseo_timeline = lambda agent, tail=0, timeout=None: self.timeline_calls.append(agent)
        relay.paseo_gate = lambda s: (relay.paseo_blocker(relay.paseo_inspect(fb.AGENT)) if self.cards
                                      else s.update(status="working" if self.status == "running" else "idle"))

    def go(self, *argv: str, text: str = "hello there friend", to: str = fb.AGENT) -> tuple[int, str, str]:
        return self.run_relay(to, text, "--wait", "2", *argv)

    def run_relay(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main(list(argv))
        return rc, out.getvalue(), err.getvalue()


class TestQueuedLineNamesTheObstacle(QueueBase):
    def test_a_question_card_is_named_by_id_and_tool_in_the_line_and_in_json(self) -> None:
        self.cards = [{"id": CARD_ID, "tool": "AskUserQuestion"}]
        rc, out, err = self.go()
        self.assertEqual(rc, 0, err)
        rid = relay.rec_all()[0]["id"]
        self.assertRegex(out, rf"^queued: {rid} for \[cccccccc\] peer-fb: blocked on card {CARD_ID} \(question: AskUserQuestion\)\. Delivered once its card is answered ")
        self.assertIn(f"`relay.py --status {rid}` shows what became of it", out)
        self.assertNotIn("Which branch?", out)    # the card's own text is a tool input: `--why` only
        self.go()    # a second identical message collapses into the first: same naming
        rc, out, _ = self.go("--json")
        res = json.loads(out)
        self.assertEqual(res["obstacle"], f"blocked on card {CARD_ID} (question: AskUserQuestion)")
        self.assertEqual(res["cards"], [{"id": CARD_ID, "tool": "AskUserQuestion", "kind": "question"}])
        self.assertTrue(res["reason"].startswith("blocked on a permission or question"))    # the old field keeps its meaning

    def test_a_permission_card_says_permission_and_two_cards_are_both_named(self) -> None:
        self.cards = [{"id": "frm_a", "tool": "Bash"}, {"id": "frm_b", "tool": "ExitPlanMode"}]
        out = self.go()[1]
        self.assertIn("blocked on card frm_a (permission: Bash), card frm_b (plan: ExitPlanMode).", out)

    def test_a_busy_target_without_a_card_keeps_the_short_why(self) -> None:
        rc, out, err = self.go()
        self.assertEqual(rc, 0, err)
        self.assertNotIn("blocked on card", out)
        self.assertEqual(self.timeline_calls, [])    # no card: no extra look at the target
        res = json.loads(self.go("--json")[1])
        self.assertEqual((res["cards"], res["obstacle"]), ([], res["reason"]))

    def test_a_diagnosis_that_fails_never_stops_the_queue(self) -> None:
        self.cards = [{"id": CARD_ID, "tool": "AskUserQuestion"}]
        relay.paseo_timeline = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("daemon fell over"))
        rc, out, _ = self.go()
        self.assertEqual(rc, 0)
        self.assertIn("blocked on a permission or question", out)    # the plain why, as before
        self.assertEqual(len(relay.rec_all()), 1)

    def test_the_deliverers_look_files_the_card_ids_and_logs_them_without_the_card_text(self) -> None:
        self.cards = [{"id": CARD_ID, "tool": "AskUserQuestion"}]
        self.go()
        rid = relay.rec_all()[0]["id"]
        relay.target_poll({"target": {"id": "cccccccc", "paseo": fb.AGENT}})
        look = relay.target_poll.look
        relay.note_look(rid, relay.rec_read(rid), look)
        filed = relay.rec_read(rid)["look"]
        self.assertEqual(filed["cards"], [{"id": CARD_ID, "tool": "AskUserQuestion", "kind": "question"}])
        log = (relay.DEFER_DIR.parent / "deferred.log").read_text()
        self.assertIn(f"{rid} look target={fb.AGENT} card:question: blocked on card {CARD_ID} (question: AskUserQuestion)", log)
        self.assertNotIn("Which branch?", log)
        self.assertNotIn("hello there friend", log)    # never the message text
        self.assertIn(f"blocked on card {CARD_ID}", relay.held_line(relay.queue_view(relay.rec_read(rid), time.time())))

    def test_a_send_run_prunes_a_week_old_final_record_on_its_opportunistic_sweep(self) -> None:
        relay.rec_write(rec("20261001-000000-aaaaaa", "delivered", 30 * 86400, finished=time.time() - 8 * 86400))
        self.assertEqual(self.go()[0], 0)
        self.assertEqual([r["id"] for r in relay.rec_all() if r["id"] == "20261001-000000-aaaaaa"], [])


class AckBase(QueueBase):
    """Expectation `q1`, asked by the target row (cccccccc) of the caller alice (bbbbbbbb, the `self` row): alice owes `ack q1`."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["PASEO_AGENT_ID"] = fb.SENDER
        os.environ.pop("RELAY_NO_ACK", None)    # the default delivery watch is what makes a send count for the closer (`CTX["accepted"]`), as in life
        self.addCleanup(setattr, relay, "IMPLICIT_ACK_WAIT", relay.IMPLICIT_ACK_WAIT)
        relay.IMPLICIT_ACK_WAIT = 0.1    # a queued send's watch must not wait ten real seconds
        self.open_expectation()

    def open_expectation(self, eid: str = "q1", **kw: Any) -> None:
        relay.atomic_json(relay.expect_dir() / f"{eid}.json", {
            "id": eid, "state": "open", "created": time.time(), "acked": None, "within": 1800, "sender": "cccccccc", "sender_sid": "", "sender_label": "peer-fb",
            "tx": None, "mark": 0, "sender_paseo": fb.AGENT,
            "target": {"id": "bbbbbbbb", "name": "alice", "paseo": fb.SENDER, "sid8": "", "sid": "", "host": "paseo"}, **kw})

    def state(self, eid: str = "q1") -> str:
        return relay.expect_read(eid)["state"]

    def deliver(self, rid: str) -> None:
        """The detached deliverer: a clean environment, the target idle."""
        with mock.patch.object(relay.subprocess, "Popen") as popen:
            fb.REAL_SPAWN("20261024-000000-abcdef")
        self.status = "idle"
        with mock.patch.dict(os.environ, popen.call_args.kwargs["env"], clear=True):
            self.assertEqual(relay.deliver(rid), 0)
        self.assertEqual(relay.rec_read(rid)["state"], "delivered")


class TestAckTokenOnAnyLine(AckBase):
    """H1 (2026-10-31): Dann 7's queued reply ENDED with `ack host-branch-durability-2` and the expectation never closed."""

    def test_an_ack_on_the_last_line_of_a_direct_send_closes_it(self) -> None:
        self.status = "idle"
        rc, out, err = self.go(text="merged, all green\nack q1")
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual((self.state(), relay.expect_read("q1").get("acked_via")), ("acked", "relay"))

    def test_the_measured_scenario_a_queued_reply_with_the_ack_last_closes_when_it_is_delivered_not_before(self) -> None:
        rc, out, err = self.go(text="the durability branch is merged\nack q1")
        self.assertEqual(rc, 3, err)    # queued under the default delivery watch: unverified, exit 3 (never 0 for a message not yet delivered)
        rid = relay.rec_all()[0]["id"]
        self.assertEqual((self.state(), self.sent), ("open", []))    # queued: not delivered, so not closed
        self.assertIn("answers expectation q1, which closes only when the queued message is delivered (or on `relay.py --sweep`), not now", out)
        self.deliver(rid)
        self.assertEqual((self.state(), relay.expect_read("q1").get("acked_via")), ("acked", "relay"))
        self.assertEqual(len(self.sent), 1)

    def test_a_queued_text_that_answers_nothing_says_nothing_about_expectations(self) -> None:
        out = self.go(text="a plain status line")[1]
        self.assertNotIn("answers expectation", out)
        self.assertNotIn("answers", json.loads(self.go("--json", text="another plain status line")[1]))
        res = json.loads(self.go("--json", text="x\nack q1")[1])
        self.assertEqual(res["answers"], ["q1"])

    def test_a_third_partys_identical_text_closes_nothing(self) -> None:
        self.status = "idle"
        os.environ["PASEO_AGENT_ID"] = fb.CAROL    # carol is not the expectation's target
        rc, out, err = self.go(text="merged, all green\nack q1")
        self.assertEqual((rc, len(self.sent)), (0, 1), (out, err))    # it was sent, as any text is
        self.assertEqual(self.state(), "open")

    def test_an_ack_to_someone_who_did_not_ask_closes_nothing(self) -> None:
        self.status = "idle"
        rc, out, err = self.go(text="merged\nack q1", to=fb.CAROL)    # alice is the target, but carol is not the expectation's sender
        self.assertEqual((rc, len(self.sent)), (0, 1), (out, err))
        self.assertEqual(self.state(), "open")

    def test_an_ack_quoted_inside_a_line_closes_nothing(self) -> None:
        self.status = "idle"
        for text in ("I will ack q1 later, first the merge", "see the footer: ack q1", "> ack q1\nnot yet", "ack q10 means another question",
                     "the token is `x ack q1`"):
            rc, out, err = self.go(text=text)
            self.assertEqual(rc, 0, (text, out, err))
            self.assertEqual(self.state(), "open", text)
        rc, out, err = self.go(text="done.\n  `ack q1`")    # a line that BEGINS with the token (quote marks and indent stripped) does close it
        self.assertEqual((rc, self.state()), (0, "acked"), (out, err))

    def test_an_ack_on_a_line_of_a_queued_reply_from_another_caller_closes_nothing(self) -> None:
        self.go(text="merged\nack q1")
        rid = relay.rec_all()[0]["id"]
        rec = relay.rec_read(rid)
        rec["ack_caller"] = {"id": "zzzzzzzz", "sid": "", "host": ""}    # a record is plain JSON: only the caller it names can answer
        relay.rec_write(rec)
        self.deliver(rid)
        self.assertEqual(self.state(), "open")


class TestAckVerb(AckBase):
    """H2: `relay.py --ack ID` alone sends `ack ID` to the expectation's sender through the ordinary send."""

    def test_it_sends_ack_to_the_sender_and_the_verified_closer_settles_it(self) -> None:
        self.status = "idle"
        rc, out, err = self.run_relay("--ack", "q1", "--wait", "2")
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(self.sent, [(fb.AGENT, self.sent[0][1])])
        self.assertTrue(self.sent[0][1].endswith("ack q1"), self.sent)    # the ordinary text, so the sender sees it
        self.assertEqual((self.state(), relay.expect_read("q1").get("acked_via")), ("acked", "relay"))

    def test_a_fresh_reservation_of_a_send_still_running_is_answered_and_a_stale_one_is_not(self) -> None:
        """Codex P2 (PR 177 round 5): the sender's `--expect-ack` is `reserved` until its blocking send returns (a Hermes turn); the target's `--ack ID`
        inside that window must work like the typed `relay.py <sender> "ack ID"`, which `resolve_acks` already keeps."""
        self.status = "idle"
        self.open_expectation("r1", state="reserved", created=time.time() - 30)
        rc, out, err = self.run_relay("--ack", "r1", "--wait", "2")
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual((self.state("r1"), relay.expect_read("r1").get("acked_via"), relay.expect_read("r1").get("early")), ("acked", "relay", True))
        self.open_expectation("r2", state="reserved", created=time.time() - relay.EXPECT_RESERVE_TTL - 5)    # its relay died: the id is free, not answerable
        self.sent.clear()
        rc, out, err = self.run_relay("--ack", "r2")
        self.assertEqual((rc, self.sent, self.state("r2")), (1, [], "reserved"))
        self.assertIn("only an open one (or a fresh reservation", err)
        os.environ["PASEO_AGENT_ID"] = fb.CAROL    # a third party is refused on a fresh reservation exactly as on an open one
        self.open_expectation("r3", state="reserved", created=time.time() - 5)
        rc, out, err = self.run_relay("--ack", "r3")
        self.assertEqual((rc, self.sent, self.state("r3")), (1, [], "reserved"))
        self.assertIn("not its target", err)

    def test_a_caller_that_is_not_the_target_is_refused_naming_the_form_and_sends_nothing(self) -> None:
        os.environ["PASEO_AGENT_ID"] = fb.CAROL
        self.status = "idle"
        rc, out, err = self.run_relay("--ack", "q1")
        self.assertEqual((rc, self.sent, self.state()), (1, [], "open"))
        self.assertIn('to answer an expectation: relay.py <sender> "ack q1" (or `relay.py --ack q1` as the caller it is addressed to)', err)
        self.assertIn("you [ffffffff] are not its target [bbbbbbbb]", err)

    def test_an_unknown_settled_or_malformed_id_is_refused_the_same_way(self) -> None:
        self.status = "idle"
        rc, _, err = self.run_relay("--ack", "nope")
        self.assertEqual(rc, 1)
        self.assertIn("no such expectation", err)
        self.assertIn('relay.py <sender> "ack nope"', err)
        self.open_expectation("old", state="acked")
        rc, _, err = self.run_relay("--ack", "old")
        self.assertEqual(rc, 1)
        self.assertIn("the expectation is acked, only an open one (or a fresh reservation", err)
        rc, _, err = self.run_relay("--ack", "../x")
        self.assertEqual(rc, 2)
        self.assertIn("not an expectation id", err)
        self.assertEqual(self.sent, [])

    def test_with_a_target_and_a_text_ack_is_still_the_delivery_watch_in_every_position(self) -> None:
        self.status = "idle"
        for argv in ((fb.AGENT, "hello one", "--ack"), ("--ack", fb.AGENT, "hello two"), (fb.AGENT, "--ack", "hello three"),
                     ("--wait", "2", "--ack", fb.AGENT, "hello four"), ("--json", "--ack", fb.AGENT, "hello five")):
            self.sent.clear()
            rc, out, err = self.run_relay(*argv)
            self.assertEqual(rc, 0, (argv, out, err))
            self.assertEqual(len(self.sent), 1, argv)
            self.assertTrue(self.sent[0][1].split("] ", 1)[-1].startswith("hello"), (argv, self.sent))
        self.assertEqual(self.state(), "open")

    def test_it_is_alone_it_cannot_carry_a_text_or_another_command(self) -> None:
        for argv in (("--ack", "q1", "--pending"), ("--ack", "q1", "--sweep"), ("--ack", "q1", "--status", "q1")):
            rc, _, err = self.run_relay(*argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn("--ack ID is used alone", err)
        self.assertEqual((self.sent, self.state()), ([], "open"))

    def test_a_busy_sender_queues_the_ack_and_the_line_says_it_closes_on_delivery(self) -> None:
        rc, out, err = self.run_relay("--ack", "q1", "--wait", "2")
        self.assertEqual(rc, 3, err)
        self.assertTrue(out.startswith("queued: "), out)
        self.assertIn("this text answers expectation q1, which closes only when the queued message is delivered (or on `relay.py --sweep`), not now", out)
        self.assertEqual(self.state(), "open")
        self.deliver(relay.rec_all()[0]["id"])
        self.assertEqual(self.state(), "acked")


class TestPendingCollects(AckBase):
    """H3: `--pending` runs the ack sweep first, bounded, and says which rows it could not collect."""

    def transcript_backed(self, eid: str = "q2") -> None:
        tx = self.tmp / f"{eid}.jsonl"
        tx.write_text(fb.user_line(f"[relay from claude bbbbbbbb aka alice (here)] merged, ack {eid}") + "\n")
        self.open_expectation(eid, tx=str(tx), mark=0)

    def rows(self) -> list[dict[str, Any]]:
        return [r for r in json.loads(self.run_relay("--pending", "--json")[1]) if r.get("kind") == "expect"]

    def test_an_answered_transcript_backed_expectation_reads_acked_without_a_sweep_command(self) -> None:
        self.transcript_backed("q2")
        rc, out, err = self.run_relay("--pending")
        self.assertEqual(rc, 0, err)
        self.assertRegex(out, r"expect-ack q2  acked  ")
        self.assertRegex(out, r"expect-ack q1  open   ")    # the transcript-less one is as before
        self.assertNotIn("uncollected", out)
        self.assertEqual(err, "")

    def test_a_sweep_that_runs_out_of_time_marks_the_rows_it_could_not_collect_and_says_so(self) -> None:
        self.transcript_backed("q2")
        relay.atomic_json(relay.DEFER_DIR / ".ack-swept.json", {"at": 1_800_000_000.0})
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.addCleanup(setattr, relay, "ack_sweep", relay.ack_sweep)
        self.addCleanup(setattr, relay, "PENDING_SWEEP_CAP", relay.PENDING_SWEEP_CAP)
        relay.ack_sweep = lambda: gate.wait(5) and (0, [])
        relay.PENDING_SWEEP_CAP = 0.05
        rc, out, err = self.run_relay("--pending")
        stamp = datetime.datetime.fromtimestamp(1_800_000_000.0).astimezone().isoformat(timespec="seconds")
        self.assertEqual(rc, 0)
        self.assertIn(f"expect-ack q2  open (uncollected, last swept {stamp}) ", out)
        self.assertRegex(out, r"expect-ack q1  open   ")    # no transcript: closed only by a verified send, never waiting for a sweep
        self.assertIn("the ack sweep did not finish in 0.05 s", err)
        by_id = {r["id"]: r for r in self.rows()}
        self.assertEqual((by_id["q2"]["uncollected"], by_id["q2"]["last_swept"], "uncollected" in by_id["q1"]), (True, 1_800_000_000.0, False))
        gate.set()

    def test_a_sweep_that_fails_marks_them_too_and_the_time_of_the_last_one_is_never_when_none_ran(self) -> None:
        self.transcript_backed("q2")
        self.addCleanup(setattr, relay, "ack_sweep", relay.ack_sweep)

        def boom() -> Any:
            raise RuntimeError("transcript unreadable")
        relay.ack_sweep = boom
        rc, out, err = self.run_relay("--pending")
        self.assertEqual(rc, 0)
        self.assertIn("expect-ack q2  open (uncollected, last swept never) ", out)
        self.assertIn("the ack sweep failed (RuntimeError: transcript unreadable)", err)

    def test_a_complete_sweep_stamps_the_time_and_leaves_every_row_fresh(self) -> None:
        self.transcript_backed("q2")
        before = time.time()
        self.assertEqual(relay.swept_at(), None)
        self.run_relay("--pending")
        self.assertGreaterEqual(relay.swept_at() or 0, before)
        self.assertTrue(all("uncollected" not in r for r in self.rows()))

    def test_the_filtered_views_do_not_sweep_and_a_state_that_does_not_exist_is_not_created(self) -> None:
        self.addCleanup(setattr, relay, "ack_sweep", relay.ack_sweep)
        relay.ack_sweep = lambda: self.fail("a filtered listing must not sweep")
        for argv in (("--pending", "--queued-only"), ("--pending", "--summary"), ("--pending", "--older-than", "0")):
            self.assertEqual(self.run_relay(*argv)[0], 0, argv)


class TestPendingNothingToSweep(Base):
    def test_pending_on_a_machine_with_no_state_creates_none(self) -> None:
        rc, out, _ = self.cli("--pending")
        self.assertEqual((rc, out), (0, "no deferred messages\n"))
        self.assertFalse(relay.DEFER_DIR.exists())


class TestAckLeadsCap(QueueBase):
    """Adversary PR 177 B1: the stored leads, the live closer and the `queued:` promise read ONE list of closing lines."""

    def test_an_ack_after_line_40_is_stored_promised_and_closed(self) -> None:
        text = "\n".join([f"line {n}" for n in range(60)] + ["ack p4"])
        self.assertEqual(relay.ack_leads(text), ["ack p4"])    # every other line is dropped, so the cap is on acks, not on prose
        self.assertEqual(len(relay.ack_leads("\n".join(f"ack x{n}" for n in range(100)))), relay.ACK_LEADS_MAX)
        self.assertTrue(all(len(x) <= 120 for x in relay.ack_leads("ack " + "z" * 400)))

    def test_the_queued_record_keeps_only_closing_lines_and_the_delivery_closes(self) -> None:
        os.environ["PASEO_AGENT_ID"] = fb.SENDER
        relay.atomic_json(relay.expect_dir() / "p4.json", {
            "id": "p4", "state": "open", "created": time.time(), "acked": None, "within": 1800, "sender": "cccccccc", "sender_sid": "", "sender_label": "peer-fb",
            "tx": None, "mark": 0, "sender_paseo": fb.AGENT,
            "target": {"id": "bbbbbbbb", "name": "alice", "paseo": fb.SENDER, "sid8": "", "sid": "", "host": "paseo"}})
        os.environ.pop("RELAY_NO_ACK", None)
        text = "\n".join([f"detail {n}" for n in range(60)] + ["ack p4"])
        rc, out, err = self.go("--wait", "0.1", text=text)
        rec = relay.rec_all()[0]
        self.assertEqual(rec["ack_leads"], ["ack p4"])    # one short list, not 40 prose lines
        self.assertIn("this text answers expectation p4", out)
        self.status = "idle"
        with mock.patch.object(relay.subprocess, "Popen") as popen:
            fb.REAL_SPAWN("20261024-000000-abcdef")
        with mock.patch.dict(os.environ, popen.call_args.kwargs["env"], clear=True):
            self.assertEqual(relay.deliver(rec["id"]), 0)
        self.assertEqual(relay.expect_read("p4")["state"], "acked")    # the promise the line made is kept


class TestAckVerbOptions(AckBase):
    """Codex P2 (PR 177): `relay.py --ack ID` carries the send options it understands and refuses the rest, never drops one."""

    def seen(self, *argv: str) -> tuple[int, list[list[str]], str]:
        calls: list[list[str]] = []
        real = relay.main

        def spy(a: Any = None, sweep: bool = True) -> int:
            calls.append(list(a))
            return real(a, sweep)
        with mock.patch.object(relay, "main", spy):
            rc, out, err = self.run_relay(*argv)
        return rc, calls, err

    def test_the_send_options_are_carried_into_the_ordinary_send(self) -> None:
        self.status = "idle"
        rc, calls, err = self.seen("--ack", "q1", "--via", "paseo", "--steer", "--idle", "5", "--no-defer", "--defer-for", "60", "--wait", "3", "--no-ack", "--ack")
        inner = calls[-1]
        self.assertEqual((inner[0] == fb.AGENT, inner[1]), (True, "ack q1"), (rc, err))
        for flag in ("--steer", "--no-defer", "--no-ack", "--ack"):    # a second --ack is the caller's explicit delivery watch: carried, never dropped (adversary r2 B1)
            self.assertIn(flag, inner)
        for flag, val in (("--via", "paseo"), ("--idle", "5.0"), ("--defer-for", "60.0"), ("--wait", "3.0")):
            self.assertEqual(inner[inner.index(flag) + 1], val, flag)

    def test_an_option_the_ack_would_drop_is_refused_and_nothing_is_sent(self) -> None:
        self.status = "idle"
        for extra in (("--expect-ack", "x1"), ("--needs-reply",), ("--fyi",), ("--ack-within", "5"), ("--text",), ("--queued-only",),
                      ("--summary",), ("--requeued",), ("--older-than", "3"), ("--reason", "r")):
            rc, calls, err = self.seen("--ack", "q1", *extra)
            self.assertEqual(rc, 2, extra)
            self.assertIn("--ack ID is used alone or with", err)
            self.assertIn(extra[0], err)
            self.assertEqual(calls, [calls[0]], extra)    # the outer run only: no inner send began
        self.assertEqual((self.sent, self.state()), ([], "open"))


class TestMissingTranscriptIsUncollected(AckBase):
    """Codex P2 (PR 177): a complete sweep reads NOTHING for a transcript that is gone, so its `open` row is not current."""

    def test_a_transcript_backed_row_whose_file_is_gone_reads_uncollected_after_a_complete_sweep(self) -> None:
        tx = self.tmp / "gone.jsonl"
        tx.write_text("{}\n")
        self.open_expectation("g1", tx=str(tx), mark=0)
        self.open_expectation("g2", tx=str(self.tmp / "never-existed.jsonl"), mark=0)
        tx.unlink()
        rc, out, err = self.run_relay("--pending")
        self.assertEqual((rc, err), (0, ""))    # the sweep itself completed
        self.assertIn("expect-ack g1  open (uncollected, last swept ", out)
        self.assertIn("expect-ack g2  open (uncollected, last swept ", out)
        self.assertRegex(out, r"expect-ack q1  open   ")    # no transcript recorded: not waiting for one
        rows = {r["id"]: r for r in json.loads(self.run_relay("--pending", "--json")[1]) if r.get("kind") == "expect"}
        self.assertEqual((rows["g1"].get("uncollected"), rows["g2"].get("uncollected"), "uncollected" in rows["q1"]), (True, True, False))


class TestCollapsedDuplicatesKeepTheirLeads(AckBase):
    """Codex P2 (PR 177 round 2): two texts equal after the whitespace fold can differ in the lines the closer reads."""

    def queued(self) -> list[dict[str, Any]]:
        return sorted(relay.rec_all(), key=lambda r: r["id"])

    def test_a_reply_that_ends_with_the_ack_is_not_collapsed_into_the_one_line_text_that_merely_contains_it(self) -> None:
        self.go(text="merged ack q1")    # one line: `ack q1` is mid-line, so this record closes nothing
        self.go(text="merged\nack q1")    # the same folded text, but the token begins a line
        recs = self.queued()
        self.assertEqual(sorted(r.get("ack_leads") for r in recs), [[], ["ack q1"]])    # two records: each keeps its own leads
        for r in recs:
            self.deliver(r["id"])
        self.assertEqual(self.state(), "acked")    # the second send's promise is kept

    def test_the_other_order_and_a_true_duplicate_still_collapse_as_before(self) -> None:
        self.go(text="merged\nack q1")
        self.go(text="merged ack q1")
        self.assertEqual(len(self.queued()), 2)
        out = self.go(text="merged\nack q1")[1]    # identical lines: the old collapse
        self.assertIn("an identical message was already queued", out)
        self.assertEqual(len(self.queued()), 2)


class TestMergeConditionRealMessages(AckBase):
    """The two real message shapes PR 173/177's merge condition names (lead 1e61c979, 2026-10-31): both close through the verified path with no
    timeline read, queued first and delivered later; a third party's identical text closes nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.timeline_reads: list[str] = []
        self.addCleanup(setattr, relay, "paseo_timeline", relay.paseo_timeline)
        self.addCleanup(setattr, relay, "timeline_messages", relay.timeline_messages)
        relay.paseo_timeline = lambda *a, **k: self.timeline_reads.append("paseo logs") or None
        relay.timeline_messages = lambda *a, **k: self.timeline_reads.append("timeline_messages") or None

    def expect(self, eid: str) -> None:
        self.open_expectation(eid, created=time.time() - 60)    # the target (alice, bbbbbbbb) owes the sender (cccccccc, Paseo agent AGENT) this ack

    def queue_and_deliver(self, text: str) -> str:
        rc, out, err = self.go("--wait", "0.1", text=text)
        self.assertEqual(rc, 3, (out, err))    # queued under the default delivery watch: unverified, and nothing is closed yet
        rec = relay.rec_all()[0]
        self.assertEqual(rec["state"], "queued")
        self.deliver(rec["id"])
        return rec["id"]

    def test_d7_k7c3f_a_reply_that_begins_with_the_token_closes_when_the_queued_message_is_delivered(self) -> None:
        self.expect("d7-k7c3f")
        text = "ack d7-k7c3f: the branch is merged and the checks are green"
        self.go("--wait", "0.1", text=text)
        self.assertEqual(self.state("d7-k7c3f"), "open")    # queued, not delivered
        self.deliver(relay.rec_all()[0]["id"])
        done = relay.expect_read("d7-k7c3f")
        self.assertEqual((done["state"], done.get("acked_via")), ("acked", "relay"))
        self.assertEqual(self.timeline_reads, [])

    def test_host_branch_durability_2_a_reply_that_ends_with_the_line_closes_when_the_deferred_record_is_delivered(self) -> None:
        self.expect("host-branch-durability-2")
        text = ("host branch durability is in: the branch survives a host restart.\n"
                "Evidence: the second run kept all 14 commits.\n"
                "ack host-branch-durability-2")
        self.queue_and_deliver(text)
        done = relay.expect_read("host-branch-durability-2")
        self.assertEqual((done["state"], done.get("acked_via")), ("acked", "relay"))
        self.assertEqual(self.timeline_reads, [])

    def test_a_third_partys_identical_text_closes_neither(self) -> None:
        for eid, text in (("d7-k7c3f", "ack d7-k7c3f: the branch is merged"),
                          ("host-branch-durability-2", "durability is in.\nack host-branch-durability-2")):
            self.expect(eid)
            self.status = "running"    # busy again, so the text is queued
            os.environ["PASEO_AGENT_ID"] = fb.CAROL    # carol is not the target
            self.queue_and_deliver(text)
            self.assertEqual(self.state(eid), "open", eid)
            for p in relay.DEFER_DIR.glob("2*.json"):
                p.unlink()    # the next shape starts with an empty queue
            os.environ["PASEO_AGENT_ID"] = fb.SENDER
        self.assertEqual(self.timeline_reads, [])

    def test_a_forwarded_quote_of_the_token_in_the_body_closes_nothing(self) -> None:
        self.expect("host-branch-durability-2")
        self.queue_and_deliver("as asked: please send host-branch-durability-2 later\n> ack host-branch-durability-2")
        self.assertEqual(self.state("host-branch-durability-2"), "open")


if __name__ == "__main__":
    unittest.main()
