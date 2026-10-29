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
    """A busy seat is not a dark one, and the log must not call it a failure (nor hide it)."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (
        1, "relay: [x] not sent: that session is busy and cannot take it now; deferring needs an "
           "identifiable sender (it gets a notice if the send fails)."))
    assert rw.to_session("one open loop") == "skipped"
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


def refusal(*, why_json: str | None, send: str = "busy") -> object:
    """A `run` stand-in: the send is refused, and --why answers WHY_JSON (None = unreadable)."""
    def fake_run(cmd, timeout=20):
        if "--why" in cmd:
            return (1, why_json) if why_json is not None else (1, "Traceback: no such option")
        return (1, "relay: [x] not sent: that session is busy and cannot take it now")
    return fake_run


def test_a_question_card_is_not_called_healthy(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    monkeypatch.setattr(rw, "run", refusal(why_json=json.dumps(
        {"state": "card:question", "why": "blocked on AskUserQuestion", "deliverable": False})))
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
    monkeypatch.setattr(rw, "run", refusal(why_json=json.dumps(
        {"state": "working", "why": "working: it takes the text when its turn ends", "deliverable": False})))
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
    monkeypatch.setattr(rw, "run", refusal(why_json=json.dumps(
        {"state": "card:permission", "why": "blocked on a permission prompt", "deliverable": False})))
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
    monkeypatch.setattr(rw, "run", refusal(why_json=json.dumps(
        {"state": "silent", "why": "running, but nothing new for 22 min", "deliverable": False})))
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
    monkeypatch.setattr(rw, "run", refusal(why_json=None))
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
    stuck = refusal(why_json=json.dumps({"state": "card:question", "why": "blocked", "deliverable": False}))
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    monkeypatch.setattr(rw, "run", stuck)
    rw._pass(a)                                   # streak 1
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (0, "relay: delivered to d2a505dd"))
    rw._pass(a)                                   # delivered: streak cleared
    monkeypatch.setattr(rw, "run", stuck)
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
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    monkeypatch.setattr(rw, "PENDING_MAX", 2)
    monkeypatch.setattr(rw, "to_session", lambda text: "skipped")
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a", "b", "c", "d"],
                                               "jobs": [], "prs": [], "stale": None})
    rw._pass(quiet_pass(rw))
    assert len(rw.load_state()["pending"]) <= 2


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


def test_a_broken_fleet_read_is_not_a_dead_seat(monkeypatch, tmp_path):
    """C3: `fleet.py` timing out is a blind watcher. Paging him "no live session" is false advice."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    fleet = tmp_path / "src/djbclark-ade/skills/session-finder/fleet.py"
    fleet.parent.mkdir(parents=True)
    fleet.write_text("")
    mail = rw.REPO / "projects/hiwymi/spec/composite-individual/tools/peer-comms/peer_mail.py"
    mail.parent.mkdir(parents=True)
    mail.write_text("")
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: (1, "boom"))
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
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
