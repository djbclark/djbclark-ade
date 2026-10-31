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
    monkeypatch.delenv("RW_AUTO_SEAT", raising=False)
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
    # Every `_pass(dry_run=False)` in this file would otherwise run the REAL deploy: `SELF_REPO`
    # defaults to the checkout these tests run from, so the suite would fetch over the network and,
    # on a clean checkout sitting behind origin, fast-forward the working tree mid-run — 43 call
    # sites' worth (adversary round 2, B1). Only the deploy tests exercise that, on fixture repos.
    monkeypatch.setattr(rw, "DEPLOY_OFF", True)
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

    def fake_split(cmd, timeout=20):
        if "--why" in cmd:
            asked.append(cmd)
            return 1, json.dumps({"state": "error", "why": "the pane is gone",
                                  "deliverable": False}), ""
        return 1, "", ("relay: [x] not sent: that session is busy and cannot take it now; deferring "
                      "needs an identifiable sender (it gets a notice if the send fails).")

    monkeypatch.setattr(rw, "run_split", fake_split)
    assert rw.to_session("one open loop") == "skipped"
    assert asked, "the whole point of the change: ask WHY before calling a refusal healthy"
    assert ": skipped" in rw.LOG.read_text()


def test_a_real_relay_failure_is_not_dressed_up_as_anything_else(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    # No JSON report, no refusal wording, and --why cannot read the target: the send failed for a
    # reason this code cannot name, so it says exactly that rather than inventing a seat state.
    monkeypatch.setattr(rw, "run_split",
                        lambda cmd, timeout=20: (1, "", "relay: no session(s) match 'd2a505dd'"))
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
                                        "it now"),
            send_stdout: str = ""):
    """Install a relay stand-in: the send returns SEND (rc, prose), and `--why` answers WHY_JSON.

    The send goes through `run_split` now, because it asks relay.py for its `--json` report; a
    refusal is rc != 0 with NO JSON on stdout and its prose on stderr, which is exactly what this
    stand-in reproduces. `send_stdout` is for the machine-report shapes.
    """
    def fake_split(cmd, timeout=20):
        if "--why" in cmd:
            return ((1, why_json, "") if why_json is not None
                    else (1, "", "Traceback: no such option"))
        return send[0], send_stdout, send[1]

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

    def delivered(cmd, timeout=20):
        if "--why" in cmd:
            return 1, why, ""
        return 0, json.dumps({"id": LIVE, "result": "delivered", "via": "paseo"}), ""

    monkeypatch.setattr(rw, "run_split", delivered)
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
    pending = [e["text"] for e in rw.load_state()["pending"]]
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
    pending = [e["text"] for e in rw.load_state()["pending"]]
    assert pending == ["pending C", "pending D"], "the NEWEST lines survive, or a flood starves them"
    assert "dropping 2 oldest line(s)" in rw.LOG.read_text(), "an evicted line must not vanish silently"

    # And the same bound when this pass adds a line of its own on top of a full queue.
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    rw._pass(quiet_pass(rw))
    pending = [e["text"] for e in rw.load_state()["pending"]]
    assert len(pending) == 2 and "from eve" in pending[-1]
    assert "dropping 1 oldest line(s)" in rw.LOG.read_text()


def test_a_send_that_may_have_arrived_is_not_sent_again(monkeypatch, tmp_path):
    """relay.py's unverified shapes say "do not resend"; `FAILED` + retry spoke twice.

    `paseo send` failing on an unknown reason, a queue entry pulled back out of the box, a recalled
    copy: relay took (or may have taken) the text and could not prove it. It is a different fact
    from "not sent", and the watcher used to retry it every 5 minutes against that contract. This
    exercise uses the PROSE fallback (no JSON report), which must still settle it.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps({"state": "idle", "why": "idle", "deliverable": True}),
            send=(1, "relay: [d2a505dd] `paseo send` failed (rc=1); it may have reached the daemon, "
                    "so no other route was tried"))
    assert rw.to_session("x") == "unverified"

    sent = []
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "skipped")
    rw._pass(quiet_pass(rw))                                  # refused: carried
    assert "from eve" in rw.load_state()["pending"][0]["text"]
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "unverified")
    rw._pass(quiet_pass(rw))                                  # may have arrived: settled, not retried
    assert rw.load_state()["pending"] == []
    monkeypatch.setattr(rw, "to_session", lambda text: sent.append(text) or "delivered")
    rw._pass(quiet_pass(rw))
    assert len(sent) == 2, "an unverified line must never be handed to the seat twice"
    assert any("could not be PROVEN delivered" in t for t in told), "a possibly lost line is his to hear"


def test_a_failed_disclosure_of_an_unverified_send_is_tried_again(monkeypatch, tmp_path):
    """The line is settled, but the ADMISSION that it may be lost must not be lost too.

    One failed `hermes send` at the moment of an unverified send used to consume the trigger: the
    line was dropped on purpose and he was never told it might have vanished — the double failure
    that ends in silence. The disclosure is carried until a send actually returns True.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["from eve"], "jobs": [], "prs": [], "stale": None})
    monkeypatch.setattr(rw, "to_session", lambda text: "unverified")
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("unknown", ""))
    calls = []
    told = []

    def djb(text):
        calls.append(text)
        if len(calls) == 1:
            return False                       # hermes blipped on the ONE attempt
        told.append(text)
        return True

    monkeypatch.setattr(rw, "to_djbclark", djb)
    rw._pass(quiet_pass(rw))
    assert len(calls) == 1, "he was tried once"
    assert "could not be PROVEN delivered" in rw.load_state()["undisclosed"], "the admission is kept"

    # The next pass has NOTHING new (the line is gone on purpose): only the carried admission speaks.
    rw._pass(quiet_pass(rw))
    assert len(calls) == 2
    assert told and "could not be PROVEN delivered" in told[0]
    state = rw.load_state()
    assert "undisclosed" not in state, "delivered once is enough"
    assert "unverified send" in state["told"], "and the cooldown starts only after the real send"

    rw._pass(quiet_pass(rw))
    assert len(calls) == 2, "no third attempt: the disclosure is not a drumbeat"


def test_a_failed_needs_him_page_is_retried_next_pass(monkeypatch, tmp_path):
    """The same stamp-after-send rule at the `needs_him` site, which had no such test.

    A stale chain log is a line HE must act on. Stamping the cooldown before the send (or on a
    failure) silences it for six hours with nothing retrying it.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "to_session", lambda text: "delivered")
    mail = iter([["from eve"], ["from eve", "from eve again"], ["a third", "from eve", "again"]])
    monkeypatch.setattr(rw, "survey", lambda: {"mail": next(mail), "jobs": [], "prs": [],
                                              "stale": "Tier 1 log records 1234, repo is at abcd"})
    calls = []
    told = []

    def djb(text):
        calls.append(text)
        if len([c for c in calls if "stale chain log" in c]) == 1:
            return False                       # the first attempt for that item fails
        told.append(text)
        return True

    monkeypatch.setattr(rw, "to_djbclark", djb)
    rw._pass(quiet_pass(rw))
    assert any("stale chain log" in c for c in calls)
    assert not any("stale chain log" in t for t in told), "the failed page reached nobody"

    rw._pass(quiet_pass(rw))
    assert any("stale chain log" in t for t in told), "a failed page must be retried, not silenced"
    assert "stale chain log" in rw.load_state()["told"], "and only a real send starts the cooldown"

    before = len([c for c in calls if "stale chain log" in c])
    rw._pass(quiet_pass(rw))
    assert len([c for c in calls if "stale chain log" in c]) == before, "the cooldown still applies"


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


def test_a_card_kind_this_table_has_never_heard_of_is_still_dark(monkeypatch, tmp_path):
    """`card:slash_menu` (relay.py `pane_look`) was missing, exactly as `picker` once was.

    Membership-only was the bug, not the key: relay.py gained a card kind after `DARK_MEANING` was
    written, and every unlisted kind logged as ordinary status, reset the streak, and was never
    paged — dark, reported as fine. The prefix is the rule now; the table is only the wording.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    assert rw.seat_dark("card:slash_menu") == "card:slash_menu"
    assert rw.seat_dark("card:invented_tomorrow") == "card:invented_tomorrow"
    assert rw.seat_dark("working") == "" and rw.seat_dark("idle") == "" and rw.seat_dark("") == ""

    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 1)
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["a"], "jobs": [], "prs": [], "stale": None})
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "card:slash_menu", "why": "the command menu is open", "deliverable": False}))
    rw._pass(quiet_pass(rw))
    assert len(told) == 1, "a slash menu is darkness, not ordinary status"
    assert "menu" in told[0].lower()


def test_alternating_darkness_classes_still_add_up(monkeypatch, tmp_path):
    """A per-class streak counted to one forever: a seat flipping question → silent stayed mute.

    A permission prompt whose turn times out and re-prompts is exactly this pattern, so the count is
    CONSECUTIVE darkness and does not care which class it was. The page item is class-independent
    too, or a flipping class re-arms the six-hour cooldown and pages him every three passes.
    """
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 3)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: True)
    state: dict = {}
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ("", "")
    assert rw.escalate_dark("silent", LIVE, state, time.time()) == ("", "")
    item, msg = rw.escalate_dark("card:question", LIVE, state, time.time())
    assert item == "seat dark", "one item, whatever class it happened to be"
    assert "3 passes in a row" in msg and "latest:" in msg, "the count, and the LATEST class only"
    assert state["stuck"] == {"n": 3} and state["stuck_class"] == "card:question"
    # and a healthy word clears both
    assert rw.escalate_dark("idle", LIVE, state, time.time()) == ("", "")
    assert state["stuck"] == {} and "stuck_class" not in state


def test_a_card_refusal_with_an_unreadable_why_is_dark_not_skipped(monkeypatch, tmp_path):
    """relay's own refusal words say "blocked on a card" while `--why` cannot name the kind.

    The old fallback filed every "not sent" refusal as the healthy `skipped`, so a card-dark seat
    behind a broken `--why` read as fine. It is knowably a card, not which one: `card:unknown`.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    refusal(monkeypatch, rw, why_json=None,
            send=(1, "relay: [x] not sent: blocked on a permission or question card; deferring "
                     "needs an identifiable sender"))
    assert rw.to_session("x") == "card:unknown"
    assert rw.seat_dark("card:unknown") == "card:unknown"


def test_the_card_detail_relay_shows_once_never_reaches_the_log(monkeypatch, tmp_path):
    """relay.py's `--why` `why` field can carry `paseo_card_detail`: the agent's own tool input.

    relay.py documents that field as "shown by `--why` only, never filed on a record or logged" — a
    permission prompt can be a command with a token in it. The outcome word is all this log needs.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    refusal(monkeypatch, rw, why_json=json.dumps(
        {"state": "card:permission", "why": "a permission card is open: curl -H 'Authorization: "
                                            "Bearer sk-LEAKED'", "deliverable": False}))
    assert rw.to_session("x") == "card:permission"
    log = rw.LOG.read_text()
    assert "sk-LEAKED" not in log, "the card's tool input is not this log's business"
    assert "card:permission" in log, "but the outcome still is"


def test_a_flaky_send_does_not_wipe_a_darkness_streak(monkeypatch, tmp_path):
    """Only proof the channel worked / the seat is healthy resets the count.

    A `paseo send` blip or an unverified send says nothing about the seat: letting it reset the
    streak is how a genuinely parked seat hides behind a flaky route and is never paged.
    """
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: True)
    state: dict = {}
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ("", "")
    assert rw.escalate_dark("unverified", LIVE, state, time.time()) == ("", "")
    assert rw.escalate_dark("FAILED", LIVE, state, time.time()) == ("", "")
    assert rw.escalate_dark("skipped", LIVE, state, time.time()) == ("", "")
    item, msg = rw.escalate_dark("card:question", LIVE, state, time.time())
    assert item == "seat dark" and "question card" in msg


def test_a_healthy_idle_seat_resets_the_darkness_streak(monkeypatch, tmp_path):
    """`idle` is `deliverable: true` in relay.py — a quiet healthy pass, not "no change".

    It used to be in neither set, so a streak counted dark passes that were not consecutive: three
    card episodes spread over a day, with idle passes between them, paged him "unable to take text
    for 3 passes in a row" — false in both clauses.
    """
    rw = load(monkeypatch, tmp_path)
    assert "idle" in rw.HEALTHY_WORDS
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: True)
    state: dict = {}
    rw.escalate_dark("card:question", LIVE, state, time.time())     # streak 1
    rw.escalate_dark("idle", LIVE, state, time.time())              # healthy: reset
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ("", ""), \
        "streak 1 again, not 2: two NON-consecutive dark passes must not page"
    item, msg = rw.escalate_dark("card:question", LIVE, state, time.time())
    assert item and "2 passes in a row" in msg


def test_a_settled_but_unverified_send_does_not_clear_the_streak(monkeypatch, tmp_path):
    """`accepted`/`queued`/`sent` are not evidence about the seat, and relay.py says so.

    Codex review, 2026-10-30 (P2): they used to be `HEALTHY_WORDS`, so a hung seat that kept
    ACCEPTING text reset its own count every pass and was never paged. They are now neither healthy
    nor dark — the streak neither grows nor clears — and the pass asks `--why` instead.
    """
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: True)
    state: dict = {}
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ("", "")   # streak 1
    for word in ("accepted", "queued", "sent"):
        assert word not in rw.HEALTHY_WORDS
        assert word in rw.UNPROVEN_SEND
        assert rw.escalate_dark(word, LIVE, state, time.time()) == ("", ""), \
            f"{word} is not proof of anything, so it cannot clear the streak either"
    item, msg = rw.escalate_dark("card:question", LIVE, state, time.time())
    assert item == "seat dark" and "2 passes in a row" in msg


def test_a_busy_pass_probes_the_seat_instead_of_trusting_an_accepted_send(monkeypatch, tmp_path):
    """A hung seat that ACCEPTS a line every pass must still be paged.

    The send is settled (the line is not resent) but it proves nothing about the seat, so the pass
    asks `--why`, whose `silent` is the darkness that used to be invisible here: the only probe ran
    on a QUIET pass, and a seat with a stale chain log has something to say every pass.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: item == "seat dark")
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    # A stale chain log is a line on EVERY pass, which is exactly the shape that used to keep the
    # quiet-pass probe from ever running.
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [],
                                               "stale": "standalone-a276"})
    asked = []

    def fake_split(cmd, timeout=20):
        if "--why" in cmd:
            asked.append(cmd)
            return 1, json.dumps({"state": "silent", "why": "nothing new for 22 min",
                                  "deliverable": False}), ""
        return 0, json.dumps({"id": LIVE, "result": "accepted", "via": "paseo"}), ""

    monkeypatch.setattr(rw, "run_split", fake_split)
    a = rw.argparse.Namespace(dry_run=False, quiet=True)
    rw._pass(a)
    assert told == [], "one accepted send is a turn boundary, not an outage"
    rw._pass(a)
    assert len(told) == 1 and "hung" in told[0]
    assert asked, "the seat must be asked what it is doing, not guessed from the send"
    assert "seat probe after accepted send: silent" in rw.LOG.read_text()


def test_a_delivered_send_is_proof_and_needs_no_probe(monkeypatch, tmp_path):
    """`delivered` is verified delivery: it clears the streak without spending a probe."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "should_tell_djbclark", lambda item, state, now: False)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [],
                                               "stale": "standalone-a276"})
    asked = []

    def fake_split(cmd, timeout=20):
        if "--why" in cmd:
            asked.append(cmd)
            return 1, "", ""
        return 0, json.dumps({"id": LIVE, "result": "delivered", "via": "paseo"}), ""

    monkeypatch.setattr(rw, "run_split", fake_split)
    rw._pass(rw.argparse.Namespace(dry_run=False, quiet=True))
    assert asked == [], "a proven send adds no probe to the 5-minute pass"


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


def test_a_hand_edited_state_VALUE_does_not_kill_the_pass_either(monkeypatch, tmp_path):
    """Shapes were guarded, values were not: `float(last)` / `int(count)` died on a hand edit."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    rw.STATE.parent.mkdir(parents=True)
    rw.STATE.write_text(json.dumps({"told": {"seat card:question": "yesterday"},
                                    "stuck": {f"{LIVE[:8]}:card:question": "three"}}))
    state = rw.load_state()
    assert state["told"] == {} and state["stuck"] == {}, "the unreadable entries are dropped"
    assert rw.should_tell_djbclark("seat card:question", state, time.time()) is True
    assert rw.escalate_dark("card:question", LIVE, state, time.time()) == ("", ""), \
        "a dropped count starts the streak over instead of raising"


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
    # "via <route>: ", so a startswith() test sees none of them. No JSON report: the prose fallback.
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: accepted; it takes the message when its turn "
           "ends", ""))
    assert rw.to_session("x") == "accepted"
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: queued; it takes the message when its turn "
           "ends", ""))
    assert rw.to_session("x") == "queued"
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (
        0, "relayed to [d2a505dd] Dann 7 via paseo: delivered; it takes the message when its turn "
           "ends", ""))
    assert rw.to_session("x") == "delivered"


def test_the_send_reads_relays_json_report_not_its_prose(monkeypatch, tmp_path):
    """The machine contract: relay.py `--json` prints `result`, and `state: queued` for a deferral.

    The prose shapes this used to match are a string contract with a tool that moves; a reworded
    "do not resend" would be retried forever and a reworded refusal would never be explained.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    asked = []

    sends = []

    def split(cmd, timeout=20):
        if "--why" in cmd:
            asked.append(cmd)
            return 1, "", "no --why for this one"
        sends.append(cmd)
        return 0, json.dumps({"id": LIVE, "result": "accepted", "via": "paseo"}), ""

    monkeypatch.setattr(rw, "run_split", split)
    assert rw.to_session("x") == "accepted"
    assert "--json" in sends[0], "the send has to ask for the machine report"

    # An unverified report is settled WITHOUT asking why: a seat that happens to be `working` when
    # the send was unverified must not have the line handed to it again.
    def unverified(cmd, timeout=20):
        if "--why" in cmd:
            asked.append(cmd)
            return 1, json.dumps({"state": "working", "why": "working", "deliverable": False}), ""
        return 1, json.dumps({"id": LIVE, "result": "unverified", "reason": "do not resend"}), ""

    asked.clear()
    monkeypatch.setattr(rw, "run_split", unverified)
    assert rw.to_session("x") == "unverified"
    assert asked == [], "an unverified report is already an answer"

    # A deferral's report has no `result`: it is a queue record.
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (
        0, json.dumps({"id": LIVE, "state": "queued", "queued": True, "record": "r1"}), ""))
    assert rw.to_session("x") == "queued"


def test_the_relay_send_contract_this_reads_still_exists(monkeypatch, tmp_path):
    """CI cannot see drift in another tool's output, so it reads that tool's own source.

    `to_session` now depends on three strings in `skills/session-finder/relay.py`: the `--json` flag
    on the send, the `result` field, and the deferred `state: queued` shape. Rename one upstream and
    this fails here instead of silently resending lines into a live seat.
    """
    relay = BIN.parent / "skills/session-finder/relay.py"
    if not relay.is_file():
        return                                # a source tarball without the sibling skill
    src = relay.read_text()
    assert '"--json"' in src, "relay.py must still offer --json on the send"
    assert 'add_argument("--json", action="store_true")' in src, (
        "and on the SEND PARSER specifically: `'\"--json\"' in src` also matches relay.py's own "
        "inner paseo_run argvs, so renaming the parser flag (argparse exit 2 on every watcher send) "
        "left this green")
    assert '"result": res[2]' in src, "the send report must still carry `result`"
    assert '"state": "queued"' in src, "a deferral must still be identifiable by `state`"


def test_the_send_argv_pins_its_flags_and_is_what_the_send_uses(monkeypatch, tmp_path):
    """A flag pin that reads another file, or an unused helper, proves nothing about our own argv.

    relay.py's source contains `"--json"` in four internal `paseo_run` calls, so a source-wide match
    cannot see the *send's* flag renamed — every watcher send would die at argparse rc 2, be logged
    FAILED, retried forever, and the seat would stay mute with nobody paged.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    relay = fake_relay(tmp_path)
    argv = rw.send_argv(relay, LIVE, "hello")
    assert "--json" in argv, "without the machine report a delivery cannot be told from a refusal"
    assert "--no-ack" in argv, "a launchd sender has no identity for relay's ack dance"
    assert argv[1] == "-I" and argv[-1] == "--json"

    seen = []
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: seen.append(cmd) or (
        0, json.dumps({"id": LIVE, "result": "delivered"}), ""))
    assert rw.to_session("hello") == "delivered"
    assert seen[0] == argv, "the pin must cover the argv `to_session` actually passes"


def fleet_read(monkeypatch, rw, tmp_path, *, rc: int, stdout: str, stderr: str = "") -> None:
    """A fleet/peer_mail stand-in. Both are parsed as JSON from stdout alone (`run_split`)."""
    fleet = tmp_path / "src/djbclark-ade/skills/session-finder/fleet.py"
    fleet.parent.mkdir(parents=True, exist_ok=True)
    fleet.write_text("")
    mail = rw.REPO / "projects/hiwymi/spec/composite-individual/tools/peer-comms/peer_mail.py"
    mail.parent.mkdir(parents=True, exist_ok=True)
    mail.write_text("")
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (rc, stdout, stderr))
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")


def test_run_split_really_keeps_the_two_streams_apart(tmp_path):
    """The separation lives in five lines, and every other test monkeypatches them away.

    So this one runs a real child process that writes to BOTH streams: a caller that glued them (the
    bug behind "a broken read is not a dead seat") would see a body no parser can read.
    """
    import sys

    rw = load_no_patch(tmp_path)
    rc, out, err = rw.run_split([sys.executable, "-c",
                                 "import sys; print('{\"body\": 1}'); print('warning: noise', "
                                 "file=sys.stderr)"])
    assert rc == 0
    assert out == '{"body": 1}' and json.loads(out) == {"body": 1}
    assert err == "warning: noise", "stderr must not be glued onto the JSON body"
    # and the convenience wrapper, for log-only callers, still shows both
    rc, both = rw.run([sys.executable, "-c",
                       "import sys; print('body'); print('err', file=sys.stderr)"])
    assert rc == 0 and "body" in both and "err" in both


def load_no_patch(tmp_path):
    """`load` without the HOME/REPO monkeypatching, for a test that runs the real module I/O."""
    loader = importlib.machinery.SourceFileLoader("rumination_watch_io", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    return rw


def test_a_fleet_warning_on_stderr_does_not_spoil_a_good_body(monkeypatch, tmp_path):
    """The successful `list --json` path warns on stderr (fleet.py:1593): the body is still good."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    fleet_read(monkeypatch, rw, tmp_path, rc=0, stdout=json.dumps([{"paseo": LIVE}]),
               stderr="warning: cross-session messaging override differs from settings")
    assert rw.owner_session() == (LIVE, "registry")


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


# --- the page itself: a failed send must not silence the next one --------------------------------

def test_a_page_that_fails_is_retried_not_silenced_for_six_hours(monkeypatch, tmp_path):
    """The cooldown used to be stamped BEFORE the send, so one hermes blip was a 6 h blackout.

    That is the worst possible item to lose: the "no live session" page is the watcher's only
    human channel, and nothing else would ever retry it.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {})
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    attempts = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: attempts.append(text) or (len(attempts) > 1))
    a = quiet_pass(rw)
    assert rw._pass(a) == 0
    assert len(attempts) == 1, "the send was attempted"
    assert rw.load_state()["told"] == {}, "a FAILED page must not start the cooldown"
    assert rw._pass(a) == 0
    assert len(attempts) == 2, "so the next pass tries again"
    # and now that he has it, the cooldown holds
    assert rw._pass(a) == 0
    assert len(attempts) == 2
    assert "no live session" in rw.load_state()["told"]


def test_a_quiet_pass_still_notices_a_wedged_seat(monkeypatch, tmp_path):
    """The probe branch had no test at all, and it is where a dark seat is actually caught.

    Nothing changed, so the pass has no line for the seat — the only observation of the seat is
    `--why`. Two card passes, then he hears about it.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "SEAT_STUCK_PASSES", 2)
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    told = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: told.append(text) or True)
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (
        1, json.dumps({"state": "card:permission", "why": "blocked", "deliverable": False}), ""))
    a = quiet_pass(rw)
    assert rw._pass(a) == 0
    assert told == [], "one dark pass is a turn boundary"
    assert rw._pass(a) == 0
    assert len(told) == 1 and "permission" in told[0], "a quiet pass must still notice a wedged seat"
    assert "seat card:permission" in rw.LOG.read_text()


def test_a_real_pass_deploys_first_and_a_dry_run_never_does(monkeypatch, tmp_path):
    """The PR's entire reason to exist is one call site: `_pass` -> `deploy_update`.

    Round 1 asked for this and round 2 found the call site still unpinned (deleting the two lines in
    `_pass` kept every deploy test green) AND reaching the real checkout from this very file. So pin
    both halves: a real pass deploys exactly once, and a dry run never moves anyone's checkout.
    """
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", tmp_path / "state" / "state.json")
    monkeypatch.setattr(rw, "survey", lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    calls = []
    monkeypatch.setattr(rw, "deploy_update", lambda state, now: calls.append(now) or "")

    assert rw._pass(rw.argparse.Namespace(dry_run=True, quiet=True)) == 0
    assert calls == [], "a dry run must never move a checkout"

    assert rw._pass(quiet_pass(rw)) == 0
    assert len(calls) == 1, "a real pass must run the deploy exactly once, before anything else"

import pytest


@pytest.fixture(autouse=True)
def isolated_watcher_environment(monkeypatch, tmp_path):
    import os
    import subprocess
    for key in list(os.environ):
        if key.startswith("RW_") or key == "PASEO_AGENT_ID":
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("RW_NO_DEPLOY", "1")
    real = subprocess.run
    def guarded(argv, *args, **kwargs):
        command = list(argv) if not isinstance(argv, str) else [argv]
        if command[:3] == ["env", "-u", "PASEO_AGENT_ID"]:
            command = command[3:]
        git_read = {"rev-parse", "cat-file", "merge-base", "log", "status"}
        git_cwd = Path(command[command.index("-C") + 1]).resolve() if "-C" in command else Path.cwd()
        fixture_git = git_cwd.is_relative_to(tmp_path)
        allowed = command and ((command[0] == "git" and
                    (fixture_git or (command[3] if command[1:2] == ["-C"] else command[1]) in git_read)) or
                  (Path(command[0]).name.startswith("python") and "-c" in command))
        import shutil
        executable = shutil.which(command[0]) if command else None
        local_fixture = executable and Path(executable).resolve().is_relative_to(tmp_path)
        python_fixture = (command and Path(command[0]).name.startswith("python") and
                          any(Path(arg).is_absolute() and Path(arg).resolve().is_relative_to(tmp_path)
                              for arg in command[1:]))
        allowed = allowed or local_fixture or python_fixture
        if not allowed:
            raise AssertionError(f"unexpected external launcher: {command}")
        return real(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", guarded)


def test_relay_timeout_after_acceptance_is_unverified(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "owner_session", lambda: (LIVE, "registry"))
    accepted = []
    def timeout(argv, **kwargs):
        accepted.append(argv)
        raise rw.subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"accepted")
    monkeypatch.setattr(rw.subprocess, "run", timeout)
    assert rw.to_session("paid prompt") == "unverified"
    assert len(accepted) == 1


def test_target_loader_disables_inherited_auto_seat(monkeypatch, tmp_path):
    monkeypatch.setenv("RW_AUTO_SEAT", "1")
    rw = load(monkeypatch, tmp_path)
    assert not rw.AUTO_SEAT


def test_timed_out_send_is_not_retried_next_pass(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "STATE", rw.STATE_DIR / "state.json")
    monkeypatch.setattr(rw, "owner_session", lambda: (LIVE, "registry"))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle", "ok"))
    monkeypatch.setattr(rw, "survey", lambda: {"mail": ["new"], "jobs": [], "prs": [], "stale": None})
    monkeypatch.setattr(rw, "to_djbclark", lambda text: True)
    accepted = []
    def timeout(argv, **kwargs):
        accepted.append(argv)
        raise rw.subprocess.TimeoutExpired(argv, kwargs["timeout"])
    monkeypatch.setattr(rw.subprocess, "run", timeout)
    rw._pass(quiet_pass(rw))
    rw._pass(quiet_pass(rw))
    assert len(accepted) == 1
    assert rw.load_state()["pending"] == []


def test_fixture_keeps_deploy_safety_and_blocks_real_checkout_mutation(monkeypatch, tmp_path):
    import os
    import subprocess
    import pytest
    assert os.environ["RW_NO_DEPLOY"] == "1"
    with pytest.raises(AssertionError, match="unexpected external launcher"):
        subprocess.run(["git", "-C", str(BIN.parent), "fetch", "origin"])


def test_explicit_relay_report_with_rc124_is_not_timeout(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    fake_relay(tmp_path)
    monkeypatch.setattr(rw, "owner_session", lambda: (LIVE, "registry"))
    monkeypatch.setattr(rw, "run_split", lambda argv, timeout=20:
                        (124, json.dumps({"id": LIVE, "result": "delivered"}), ""))
    assert rw.to_session("line") == "delivered"
