#!/usr/bin/env python3
"""`relay.py --status ID`, `--pending --queued-only|--older-than|--summary`, `--sweep` STUCK lines, the named obstacle in the `queued:` line,
the deferred.log cap and the week-old prune (2026-10-31).

Why: on 2026-10-30/31 an agent relaying to a Paseo peer whose tab had a question card up could not tell "queued" from "delivered" (the only
authoritative answer was `--cancel`, which destroyed two still-queued messages), read a 346-line `--pending` with `tail`, and escalated to the
operator twice about silence that was a queue. Every id, path and text here is fake; every state lives under a temp directory.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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
        rows = [target, sender]
        relay.fleet.sessions = lambda: [dict(r, self=bool(r.get("paseo") == os.environ.get("PASEO_AGENT_ID"))) for r in rows]
        saved_links = relay.fleet.LINKS_FILE
        relay.fleet.LINKS_FILE = self.tmp / "links.json"
        self.addCleanup(setattr, relay.fleet, "LINKS_FILE", saved_links)
        relay.fleet.LINKS_FILE.write_text(json.dumps({"links": {relay.fleet.link_key(a["id"], b["id"]): {"sent": 1, "acked": None}
                                                                 for a in rows for b in rows}}))
        relay.paseo_inspect = lambda agent: {"Id": agent, "Status": "running", "Cwd": "/x", "Archived": False, "PendingPermissions": list(self.cards)}
        relay.paseo_probe = lambda agent: (relay.paseo_inspect(agent), "ok")
        relay.paseo_card_detail = lambda agent: ("Which branch?" if self.cards else "", bool(self.cards))
        self.addCleanup(setattr, relay, "paseo_timeline", relay.paseo_timeline)
        relay.paseo_timeline = lambda agent, tail=0, timeout=None: self.timeline_calls.append(agent)
        relay.paseo_gate = lambda s: (relay.paseo_blocker(relay.paseo_inspect(fb.AGENT)) if self.cards
                                      else s.update(status="working"))

    def go(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = relay.main([fb.AGENT, "hello there friend", "--wait", "2", *argv])
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


if __name__ == "__main__":
    unittest.main()
