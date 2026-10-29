#!/usr/bin/env python3
"""rumination-watch must find the session it speaks to AT RUN TIME.

A launchd job has no session identity, so the first implementation resolved the target from
`RW_SESSION`/`PASEO_AGENT_ID` only and returned False when both were unset — which under launchd is
always. It ran every 5 minutes for two days and logged `session=False` 870 times: the entity's "voice
in the head" had never once been audible (2026-10-29). These tests pin the resolution chain, the
liveness check that keeps a stale registry row from swallowing the line, and the honest failure.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import time
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LIVE = "d2a505dd-8c93-4ba5-8684-e98a3865a1ae"


def load(monkeypatch, tmp_path, registry: dict | None = None):
    loader = importlib.machinery.SourceFileLoader("rumination_watch", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    repo = tmp_path / "techno-euphora"
    (repo / "agents" / "comm").mkdir(parents=True)
    if registry is not None:
        (repo / "agents" / "comm" / "registry.json").write_text(json.dumps(registry))
    monkeypatch.setattr(rw, "REPO", repo)
    monkeypatch.setattr(rw, "HOME", tmp_path)          # no relay.py, no fleet.py: nothing to exec
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    monkeypatch.setattr(rw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(rw, "LOG", tmp_path / "state" / "rumination.log")
    return rw


def test_launchd_resolves_the_registry_row(monkeypatch, tmp_path):
    """No env at all — the launchd case — and the registry's paseo id is the target."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE, "instance": "Dann 7"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    assert rw.owner_session() == (LIVE, "registry")


def test_an_env_override_wins_without_a_lookup(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setenv("RW_SESSION", "abcd1234")
    assert rw.owner_session() == ("abcd1234", "RW_SESSION")


def test_a_stale_registry_row_does_not_swallow_the_line(monkeypatch, tmp_path):
    """A died-and-replaced seat leaves an id fleet no longer lists: try the next source, never send."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    mail = rw.REPO / "projects/hiwymi/spec/composite-individual/tools/peer-comms/peer_mail.py"
    mail.parent.mkdir(parents=True)
    mail.write_text("")
    seen = []

    def fake_run(cmd, timeout=20):
        seen.append(cmd)
        if "peer_mail.py" in cmd[2]:
            return 0, json.dumps({"live_paseo_ids": [LIVE]})
        return 1, ""

    monkeypatch.setattr(rw, "run", fake_run)
    # peer_mail's JSON is read from stdout alone, the same way fleet.py's is.
    monkeypatch.setattr(rw, "run_split",
                        lambda cmd, timeout=20: (fake_run(cmd, timeout)[0], fake_run(cmd, timeout)[1], ""))
    assert rw.owner_session() == (LIVE, "peer_mail")


def test_nothing_live_is_an_honest_failure_not_a_silent_one(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {})
    assert rw.owner_session()[0] == ""
    assert "no live session" in rw.owner_session()[1]
    called = []
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: called.append(cmd) or (0, ""))
    assert rw.to_session("one open loop") == "unreachable"
    assert called == []                                  # no relay attempt into a void
    assert "cannot speak to session" in rw.LOG.read_text()


def test_a_dead_seat_wakes_the_operator_even_on_a_quiet_pass(monkeypatch, tmp_path):
    """A seat that is GONE is the one thing worth a message to djbclark: nothing else will ever speak.

    It is checked on a quiet pass too, because a dead seat stops producing changes — the pass would
    then stay silent forever, which is the outage this watcher exists to prevent.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {})
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (1, ""))   # peer_mail resolves nothing
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    assert rw._pass(a) == 0                              # quiet: nothing new to say to the session
    assert len(told) == 1 and "no live session" in told[0]
    # the cooldown stops it becoming a 5-minute drumbeat
    assert rw._pass(a) == 0
    assert len(told) == 1


def test_an_archived_agent_is_not_usable(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "live_sessions",
                        lambda: {LIVE[:8]: {"paseo": LIVE, "ended": True, "archived": True}})
    assert rw.usable(LIVE) is False
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    assert rw.usable(LIVE) is True
    assert rw.usable("0000dead") is False                # not listed at all


def test_a_busy_target_is_reported_as_skipped_not_failed(monkeypatch, tmp_path):
    """A busy seat is not a dark one, and the log must not call it a failure (nor hide it).

    The refusal is a real relay.py shape and `--why` answers something this code does not classify,
    so the honest word is `skipped` — with the reason logged, not swallowed.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    asked = []

    def fake_why(cmd, timeout=20):
        asked.append(cmd)
        return 1, json.dumps({"state": "error", "why": "the pane is gone", "deliverable": False}), ""

    monkeypatch.setattr(rw, "run_split", fake_why)
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        1, "relay: [x] not sent: that session is busy and cannot take it now; deferring needs an "
           "identifiable sender (it gets a notice if the send fails)."))
    assert rw.to_session("one open loop") == "skipped"
    assert asked, "the whole point of the change: ask WHY before calling a refusal healthy"
    assert ": skipped" in rw.LOG.read_text()


def test_a_real_relay_failure_is_not_dressed_up_as_anything_else(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (1, "relay: no session(s) match 'd2a505dd'"))
    assert rw.to_session("one open loop") == "FAILED"


# --- "busy" is three things and only one of them is healthy -------------------------------------
#
# Until now every refusal read as `skipped`. A seat parked on a question card only djbclark can
# answer, and a seat wedged with nothing new for 15 minutes, both logged the healthy word while the
# entity was dark — the watcher would have said "fine" all the way through an outage. `relay.py
# --why` knows the difference, so the watcher asks.

def fake_relay(tmp_path):
    """The relay must EXIST, or to_session gives up before it ever asks why (`unreachable`)."""
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True, exist_ok=True)
    relay.write_text("")
    return relay


def refusal(monkeypatch, rw, *, why_json: str | None,
            send: tuple[int, str] = (1, "relay: [x] not sent: that session is busy and cannot take "
                                        "it now")):
    """Install a relay stand-in: the send returns SEND, and `--why` answers WHY_JSON (None = blind).

    Two patch points, because the two reads are deliberately different: the send's output is a
    human-readable line (`run`), and `--why` is parsed as JSON from stdout alone (`run_split`).
    """
    def fake_split(cmd, timeout=20):
        if "--why" in cmd:
            return ((1, why_json, "") if why_json is not None
                    else (1, "", "Traceback: no such option"))
        return send[0], "", send[1]

    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: send)
    monkeypatch.setattr(rw, "run_split", fake_split)


def test_a_question_card_is_not_called_healthy(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "card:question", "why": "blocked on AskUserQuestion", "deliverable": False}))
    assert rw.to_session("one open loop") == "card:question"
    assert ": card:question" in rw.LOG.read_text()


def test_a_seat_mid_turn_stays_healthy_and_is_never_paged(monkeypatch, tmp_path):
    """`working` is the normal case. It must not accumulate a streak, let alone a message to him."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [{"name": "j", "done_exists": False}],
                                                "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "working", "why": "working: it takes the text when its turn ends", "deliverable": False}))
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    for _ in range(6):
        assert rw.to_session("x") == "working"
        rw._pass(a)
    assert told == []


def test_a_seat_parked_on_a_card_pages_him_once_it_repeats(monkeypatch, tmp_path):
    """Three passes, not one: a single refusal is a turn boundary. Then he hears about it, once."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 3)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "card:permission", "why": "blocked on a permission prompt", "deliverable": False}))
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    rw._pass(a)
    rw._pass(a)
    assert told == [], "two passes is a turn boundary, not an outage"
    rw._pass(a)
    assert len(told) == 1 and "permission" in told[0]
    rw._pass(a)
    assert len(told) == 1, "the cooldown must stop it becoming a 5-minute drumbeat"


def test_a_hung_turn_is_paged_too(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 1)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "silent", "why": "running, but nothing new for 22 min", "deliverable": False}))
    rw._pass(rw.argparse.Namespace(dry_run=False, quiet=True))
    assert len(told) == 1 and "hung" in told[0]


def test_an_unreadable_why_pages_nobody(monkeypatch, tmp_path):
    """A blind probe must never page him: it guesses `skipped`, which is not an outage."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 1)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=None)
    assert rw.to_session("x") == "skipped"
    rw._pass(rw.argparse.Namespace(dry_run=False, quiet=True))
    assert told == []


def test_a_delivered_pass_clears_the_streak(monkeypatch, tmp_path):
    """One good pass means the seat is alive: the count restarts, so an old streak cannot page him."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    why = json.dumps({"state": "card:question", "why": "blocked", "deliverable": False})
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    refusal(monkeypatch, rw, why_json=why)
    rw._pass(a)                                   # streak 1
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (0, "relay: delivered to d2a505dd"))
    rw._pass(a)                                   # delivered: streak cleared
    refusal(monkeypatch, rw, why_json=why)
    rw._pass(a)                                   # streak 1 again, not 3
    assert told == []


# --- the line survives the seat saying no ---------------------------------------------------------
#
# `state["last"] = cur` runs BEFORE the send, so a refused line was consumed by the change-detector
# and never spoken again: the seat stayed dark and the watcher stayed quiet about it. Mail tends to
# arrive exactly WHILE the seat is busy, so this is the everyday collision, not an edge case.

def quiet_pass(rw):
    return rw.argparse.Namespace(dry_run=False, quiet=True)


def test_a_refused_line_is_kept_and_retried(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    sent = []
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "skipped")
    rw._pass(quiet_pass(rw))
    assert len(sent) == 1 and "from eve" in sent[0]
    pending = rw.load_state()["pending"]
    assert pending and "from eve" in pending[0], "a refused line must be carried, not consumed"

    # The survey has NOT changed (nothing new arrived), so only the pending list can make it speak.
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "delivered")
    rw._pass(quiet_pass(rw))
    assert len(sent) == 2 and "from eve" in sent[1], "the retry has to happen on the next pass"
    assert rw.load_state()["pending"] == [], "and only a real send clears it"


def test_the_pending_list_cannot_grow_without_bound(monkeypatch, tmp_path):
    """Bounded, and bounded at the RIGHT end: the newest lines survive and the drop is logged.

    A single line (the old shape of this test) passes with the cap ignored entirely, so it pinned
    nothing; four lines through a cap of two pins both the bound and which end is dropped.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    monkeypatch.setattr(rw, "PENDING_MAX", 2)
    monkeypatch.setattr(rw, "to_session", lambda text: "skipped")
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    # Four lines carried in from four busy passes (one summary line per pass, so they cannot be
    # produced in a single pass) and a cap of two.
    rw.save_state({"pending": ["pending A", "pending B", "pending C", "pending D"]})
    rw._pass(quiet_pass(rw))
    pending = rw.load_state()["pending"]
    assert pending == ["pending C", "pending D"], "the NEWEST lines survive, or a flood starves them"
    assert "dropping 2 oldest line(s)" in rw.LOG.read_text(), "an evicted line must not vanish silently"

    # And the same bound when this pass adds a line of its own on top of a full queue.
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    rw._pass(quiet_pass(rw))
    pending = rw.load_state()["pending"]
    assert len(pending) == 2 and "from eve" in pending[-1]
    assert "dropping 1 oldest line(s)" in rw.LOG.read_text()


def test_a_send_that_may_have_arrived_is_not_sent_again(monkeypatch, tmp_path):
    """relay.py's rc==1 unverified shapes say "do not resend"; `FAILED` + retry spoke twice.

    `paseo send` failing on an unknown reason, a queue entry pulled back out of the box, a recalled
    copy: relay took (or may have taken) the text and could not prove it. It is a different fact
    from "not sent", and the watcher used to retry it every 5 minutes against that contract.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    # relay.py:1650, verbatim.
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        1, "relay: [d2a505dd] `paseo send` failed (rc=1); it may have reached the daemon, so no "
           "other route was tried"))
    assert rw.to_session("x") == "unverified"

    sent = []
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "skipped")
    rw._pass(quiet_pass(rw))                                  # refused: carried
    assert "from eve" in rw.load_state()["pending"][0]
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "unverified")
    rw._pass(quiet_pass(rw))                                  # may have arrived: settled, not retried
    assert rw.load_state()["pending"] == []
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "delivered")
    rw._pass(quiet_pass(rw))
    assert len(sent) == 2, "an unverified line must never be handed to the seat twice"
    assert any("could not be PROVEN delivered" in t for t in told), "a possibly lost line is his to hear"


def test_a_picker_card_and_an_unknown_card_are_dark(monkeypatch, tmp_path):
    """Every `card:*` is a human waiting. `picker` and `unknown` used to log as ordinary status."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    assert rw.seat_dark("card:picker") == "card:picker"
    assert rw.seat_dark("card:unknown") == "card:unknown"

    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 1)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "card:picker", "why": "a picker is on screen", "deliverable": False}))
    rw._pass(quiet_pass(rw))
    assert len(told) == 1 and "picker" in told[0]


def test_a_flaky_send_does_not_wipe_a_darkness_streak(monkeypatch, tmp_path):
    """Only proof the channel worked / the seat is healthy resets the count.

    A `paseo send` blip or an unverified send says nothing about the seat: letting it reset the
    streak is how a genuinely parked seat hides behind a flaky route and is never paged.
    """
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: True)
    state: dict = {}
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ""
    assert rw.escalate_dark("unverified", LIVE, state, time.time()) == ""
    assert rw.escalate_dark("FAILED", LIVE, state, time.time()) == ""
    assert rw.escalate_dark("skipped", LIVE, state, time.time()) == ""
    assert "question card" in rw.escalate_dark("card:question", LIVE, state, time.time())


def test_a_zero_or_bogus_cap_is_clamped(monkeypatch, tmp_path):
    """`RW_PENDING_MAX=0` used to keep EVERYTHING (`lines[-0:]`), and a typo killed the watcher."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setenv("RW_PENDING_MAX", "0")
    assert rw._env_int("RW_PENDING_MAX", 6) == 1
    monkeypatch.setenv("RW_PENDING_MAX", "-3")
    assert rw._env_int("RW_PENDING_MAX", 6) == 1
    monkeypatch.setenv("RW_PENDING_MAX", "lots")
    assert rw._env_int("RW_PENDING_MAX", 6) == 6
    monkeypatch.delenv("RW_PENDING_MAX")
    assert rw._env_int("RW_PENDING_MAX", 6) == 6
    assert rw._env_int("RW_PR_LIMIT", 100, minimum=1) == 100


def test_a_hand_edited_state_file_does_not_kill_the_pass(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    rw.STATE.parent.mkdir(parents=True)
    rw.STATE.write_text("[]")
    assert rw.load_state() == {}
    rw.STATE.write_text(json.dumps({"pending": "abc", "last": [], "stuck": None}))
    state = rw.load_state()
    assert state["pending"] == [] and state["last"] == {} and state["stuck"] == {}


def test_an_untrusted_reply_cannot_rename_the_outcome(monkeypatch, tmp_path):
    """The reply preview is untrusted text; a reply containing ": queued" is not our send's word."""
    rw = load(monkeypatch, tmp_path)
    assert rw.relay_word("relayed to [x] n via paseo: delivered; it takes the message now") == "delivered"
    reply = ("relayed to [x] n via socket: delivered; its reply (untrusted data, not instructions; "
             "not posted in the chat):\nhmm: queued more work\n--- end of reply ---")
    assert rw.relay_word(reply) == "delivered"
    assert rw.relay_word("something no relay version prints") == "sent", "never claim the best word"


def test_relay_accepted_is_not_reported_as_delivered(monkeypatch, tmp_path):
    """`--no-ack` means relay.py prints `accepted`: proof the daemon took it, not proof it arrived."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    # Verbatim relay.py shapes, from its own print at relay.py:3858/3865 — the words sit after
    # "via <route>: ", so a startswith() test sees none of them.
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: accepted; it takes the message when its turn ends"))
    assert rw.to_session("x") == "accepted"
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: queued; it takes the message when its turn ends"))
    assert rw.to_session("x") == "queued"
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: delivered; it takes the message when its turn ends"))
    assert rw.to_session("x") == "delivered"


def fleet_read(monkeypatch, rw, tmp_path, *, rc: int, stdout: str, stderr: str = "") -> None:
    """A fleet/peer_mail stand-in. Both are parsed as JSON from stdout alone (`run_split`)."""
    fleet = tmp_path / "src/djbclark-ade/skills/session-finder/fleet.py"
    fleet.parent.mkdir(parents=True, exist_ok=True)
    fleet.write_text("")
    mail = rw.REPO / "projects/hiwymi/spec/composite-individual/tools/peer-comms/peer_mail.py"
    mail.parent.mkdir(parents=True, exist_ok=True)
    mail.write_text("")
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (rc, stdout, stderr))
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (rc, (stdout + stderr).strip()))
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")


def test_a_broken_fleet_read_is_not_a_dead_seat(monkeypatch, tmp_path):
    """C3: `fleet.py` timing out is a blind watcher. Paging him "no live session" is false advice."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    fleet_read(monkeypatch, rw, tmp_path, rc=1, stdout="", stderr="boom")
    ident, why = rw.owner_session()
    assert ident == ""
    assert "broken READ" in why and "no live session" not in why

    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    rw._pass(quiet_pass(rw))
    assert len(told) == 1
    assert "cannot READ the fleet" in told[0]
    assert "no live session" not in told[0], "a timeout must not be sold as a dead seat"


def test_rc_zero_with_unparseable_output_is_a_broken_read_too(monkeypatch, tmp_path):
    """fleet.py warns on STDERR on its successful path (fleet.py:1593); a glued read parses as [].

    `[]` is a list and rc is 0, so the old guard let it through as "an empty, healthy fleet" and
    paged him "Nothing is listening" — a false dead-seat page, the exact confusion this exists for.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    fleet_read(monkeypatch, rw, tmp_path, rc=0, stdout="",
               stderr="warning: cross-session messaging override differs from settings")
    ident, why = rw.owner_session()
    assert ident == ""
    assert "broken READ" in why and "no live session" not in why

    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    rw._pass(quiet_pass(rw))
    assert len(told) == 1 and "cannot READ the fleet" in told[0]


def test_a_capped_pr_listing_says_at_least(monkeypatch, tmp_path):
    """`gh` truncates silently, so the old `--limit 20` made "20 open PR(s)" mean "20 or 40".

    A page size reported as a count is precision that was never earned — the same lie as calling
    `accepted` "delivered". At the cap the phrase has to say "at least".
    """
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "PR_LIMIT", 3)
    monkeypatch.setattr(rw, "PR_CAP_MARK", "(at least 3: the listing is capped)")
    many = [{"number": i, "title": f"t{i}"} for i in range(1, 4)]
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (0, json.dumps(many), ""))
    assert rw.pr_phrase(rw.open_prs()) == "at least 3 open PR(s) of yours"
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (0, json.dumps(many[:1]), ""))
    assert rw.pr_phrase(rw.open_prs()) == "1 open PR(s) of yours"
    # A gh WARNING on stderr is not a broken body: the read still counts.
    monkeypatch.setattr(rw, "run_split",
                        lambda cmd, timeout=20: (0, json.dumps(many[:1]), "warning: 1 unread item"))
    assert rw.pr_phrase(rw.open_prs()) == "1 open PR(s) of yours"


def test_an_unreadable_pr_listing_is_unknown_not_zero(monkeypatch, tmp_path):
    """"gh is offline" and "you have no open PRs" are different facts; a confident 0 is a lie."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (1, "", "gh: offline"))
    assert rw.open_prs() is None
    assert rw.pr_phrase(None) == "PR count unknown (gh unreadable)"
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (0, "not json", ""))
    assert rw.open_prs() is None
    assert rw.pr_phrase([]) == "0 open PR(s) of yours", "a real empty listing still reads as zero"
