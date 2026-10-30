#!/usr/bin/env python3
"""An idle seat with declared, unstarted work is told so, once per cooldown (2026-10-30).

Every other line the watcher speaks is a CHANGE, so a healthy watcher and an idle seat with a full
`- Next steps:` list produced `quiet (nothing new); seat idle` for 216 passes (18.1 h, 2026-10-26)
while nobody started the next slice. `next move: N declared step(s) still open` is the one keyed,
state-like line about WORK: it carries the count and never a step's text (several chains write to one
pointer; naming a step would send this seat to do another seat's slice), goes only to an `idle`
seat (never interrupts a working one), never pages djbclark, and retires through the SAME keyed-drop
path as `stale chain log`.
"""
from __future__ import annotations

import json
import time

import pytest

from test_rumination_watch_pending import QUIET, Seat, load, pending_on_disk, run_pass, write_state

SECRET = "ship the BYOK region picker before friday"


def pointer_path(tmp_path, name="techno-euphora"):
    return tmp_path / ".local/state/handoffs" / name / "main" / "SESSION_LOG.md"


def write_pointer(tmp_path, body, name="techno-euphora"):
    p = pointer_path(tmp_path, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def steps_body(n, trailer=""):
    bullets = "".join(f"  - step {i}: {SECRET}\n" for i in range(n))
    return f"head_sha: abcdef1\n## Current State\n- Branch: main\n- Next steps:\n{bullets}{trailer}\n## Recent History\n"


class Probe:
    """A stand-in for `why_blocked` that counts how many times the pass asked."""

    def __init__(self, rw, monkeypatch, word="idle"):
        self.word = word
        self.calls = 0
        monkeypatch.setattr(rw, "why_blocked", self._why)

    def _why(self, ident):
        self.calls += 1
        return self.word, "test"


@pytest.fixture
def rw(monkeypatch, tmp_path):
    mod = load(monkeypatch, tmp_path)
    mod.told_djb = []
    monkeypatch.setattr(mod, "to_djbclark", lambda text: mod.told_djb.append(text) or True)
    monkeypatch.setattr(mod, "NUDGE_ON", True)
    monkeypatch.setattr(mod, "NUDGE_S", 10800)
    return mod


def nudged_on_disk(rw):
    return json.loads(rw.STATE.read_text()).get("nudged", {})


# --- the line ---------------------------------------------------------------------------------


def test_an_idle_seat_with_three_declared_steps_gets_the_count_and_no_step_text(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(3))
    probe = Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "delivered")
    assert run_pass(rw, QUIET) == 10
    assert len(seat.sent) == 1
    line = seat.sent[0]
    assert "next move: 3 declared step(s) still open" in line
    assert SECRET not in line and "step 0" not in line
    assert probe.calls == 1, "the nudge gate and the quiet branch share ONE --why per pass"
    assert rw.told_djb == [], "a nudge is for the seat; it is never a page to djbclark"


@pytest.mark.parametrize("body", [
    "head_sha: abcdef1\n## Current State\n- Next steps:\n\n## Recent History\n",   # block, no bullets
    "head_sha: abcdef1\n## Current State\n- Branch: main\n",                       # no block at all
    None,                                                                          # no pointer file
])
def test_nothing_declared_means_no_item_and_a_quiet_pass(rw, monkeypatch, tmp_path, body):
    if body is not None:
        write_pointer(tmp_path, body)
    Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "delivered")
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []
    assert nudged_on_disk(rw) == {}


def test_a_working_seat_is_never_interrupted_however_much_is_declared(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(5))
    Probe(rw, monkeypatch, "working")
    seat = Seat(rw, monkeypatch, "delivered")
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []
    assert nudged_on_disk(rw) == {}


@pytest.mark.parametrize("word", ["silent", "card:question", "card:slash_menu", "unreachable", "unknown", ""])
def test_only_idle_passes_the_gate(rw, monkeypatch, tmp_path, word):
    write_pointer(tmp_path, steps_body(2))
    Probe(rw, monkeypatch, word)
    seat = Seat(rw, monkeypatch, "delivered")
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []


def test_the_switch_turns_the_item_off(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(2))
    monkeypatch.setattr(rw, "NUDGE_ON", False)
    probe = Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "delivered")
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []
    assert probe.calls == 1, "only the quiet branch's own probe"


# --- the parser -------------------------------------------------------------------------------


def test_a_top_level_bullet_ends_the_block_and_only_indented_sub_bullets_count(rw, tmp_path):
    write_pointer(tmp_path, "## Current State\n- Next steps:\n  - one\n  - two\n"
                            "- Substrate question answered: yes\n  - an indented child of ANOTHER bullet\n")
    assert rw.declared_next_steps() == 2


def test_wrapped_text_and_deeper_bullets_are_not_extra_steps(rw, tmp_path):
    write_pointer(tmp_path, "- Next steps:\n  - one wraps onto\n    a second line\n"
                            "    - a nested detail\n  - two\n\n  - after a blank: not in the block\n")
    assert rw.declared_next_steps() == 2


def test_an_unreadable_pointer_is_zero_not_a_crash(rw, tmp_path):
    p = write_pointer(tmp_path, "")
    p.write_bytes(b"- Next steps:\n  - \xff\xfe broken\n")
    assert rw.declared_next_steps() == 0
    p.unlink()
    p.mkdir()                                              # a directory where the file belongs
    assert rw.declared_next_steps() == 0


# --- one resolver for both callers ------------------------------------------------------------


def test_a_redirect_resolves_to_the_same_file_for_staleness_and_for_next_steps(rw, monkeypatch, tmp_path):
    target = tmp_path / ".local/state/handoffs/chains/standalone-b457/SESSION_LOG.md"
    target.parent.mkdir(parents=True)
    target.write_text(steps_body(4).replace("abcdef1", "1234567"))
    write_pointer(tmp_path, "redirect: chains/standalone-b457/SESSION_LOG.md\nhead_sha: deadbee\n")
    assert rw.resolve_pointer() == target
    assert rw.declared_next_steps() == 4                   # the redirect target, not the 0-step pointer
    # chain_staleness reads head_sha from the SAME file: "1234567" (target), never "deadbee" (pointer).
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (0, "f" * 40, "") if "rev-parse" in cmd
                        else (128, "", "") if "cat-file" in cmd else (1, "", ""))
    msg = rw.chain_staleness()
    assert msg and "1234567" in msg and "deadbee" not in msg


def test_a_dangling_redirect_reads_as_nothing_declared(rw, tmp_path):
    write_pointer(tmp_path, "redirect: chains/gone/SESSION_LOG.md\n")
    assert rw.declared_next_steps() == 0
    assert rw.chain_staleness() is None


# --- cooldown ---------------------------------------------------------------------------------


def test_the_cooldown_is_stamped_only_by_a_send_that_settled(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(3))
    Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "skipped")                # refused: nothing reached the seat
    assert run_pass(rw, QUIET) == 10
    assert nudged_on_disk(rw) == {}, "a refused send must leave the nudge due"
    assert [e["key"] for e in pending_on_disk(rw)] == ["next move"]

    seat.word = "delivered"
    assert run_pass(rw, QUIET) == 10                       # due again, and now it lands
    assert "next move" in nudged_on_disk(rw)
    assert pending_on_disk(rw) == []
    assert len(seat.sent) == 2

    seat.sent.clear()
    assert run_pass(rw, QUIET) == 0                        # inside the cooldown: silent
    assert seat.sent == []


def test_a_seat_that_stays_idle_is_nudged_again_once_the_cooldown_is_over(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(1))
    Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "delivered")
    write_state(rw, [], QUIET)
    state = json.loads(rw.STATE.read_text())
    state["nudged"] = {"next move": time.time() - 10801}
    rw.STATE.write_text(json.dumps(state))
    assert run_pass(rw, QUIET) == 10
    assert len(seat.sent) == 1

    state["nudged"] = {"next move": time.time() - 60}
    rw.STATE.write_text(json.dumps(state))
    seat.sent.clear()
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []


def test_a_hand_edited_nudged_map_does_not_kill_the_pass(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(1))
    Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "delivered")
    write_state(rw, [], QUIET)
    state = json.loads(rw.STATE.read_text())
    state["nudged"] = {"next move": "yesterday"}
    rw.STATE.write_text(json.dumps(state))
    assert run_pass(rw, QUIET) == 10
    assert len(seat.sent) == 1


# --- retirement is #152's keyed drop, not a new path ------------------------------------------


def test_a_queued_next_move_is_dropped_when_the_count_reaches_zero(rw, monkeypatch, tmp_path):
    p = write_pointer(tmp_path, steps_body(2))
    Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "skipped")
    run_pass(rw, QUIET)
    assert [e["key"] for e in pending_on_disk(rw)] == ["next move"]

    p.write_text(steps_body(0))                            # the work was started and the list emptied
    seat.sent.clear()
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []
    assert pending_on_disk(rw) == []
    assert rw.LOG.read_text().count("pending: dropping resolved next move") == 1


def test_a_queued_next_move_is_dropped_once_the_seat_is_working_again(rw, monkeypatch, tmp_path):
    write_pointer(tmp_path, steps_body(2))
    probe = Probe(rw, monkeypatch, "idle")
    seat = Seat(rw, monkeypatch, "skipped")
    run_pass(rw, QUIET)
    probe.word = "working"
    seat.sent.clear()
    assert run_pass(rw, QUIET) == 0
    assert seat.sent == []
    assert rw.LOG.read_text().count("pending: dropping resolved next move") == 1
