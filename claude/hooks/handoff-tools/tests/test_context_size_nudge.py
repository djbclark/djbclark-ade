"""Contract tests for context_size_nudge.py's tiers, floor and paging, and for
bin/self-slash's /compact-/new gap (2026-10-18 rewrite: the old tests asserted
SOFT_THRESHOLD/HARD_THRESHOLD and a `hermes send` call the hook no longer has)."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2]
REPO = HOOKS_DIR.parents[1]
SELF_SLASH = REPO / "bin" / "self-slash"
sys.path.insert(0, str(HOOKS_DIR))

import context_size_nudge as nudge  # noqa: E402


ALT = "the in-context alternative"
_BOUNDARY_LINE = json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n"


def _usage(tokens, **extra):
    record = {"message": {"usage": {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": tokens,
    }}}
    record.update(extra)
    return json.dumps(record) + "\n"


def _transcript(tmp_path, *sizes, name="transcript.jsonl"):
    path = tmp_path / name
    path.write_text("".join(_usage(s) for s in sizes))
    return path


def _append(path, text):
    with path.open("a") as f:
        f.write(text)


@pytest.fixture
def hook(monkeypatch, tmp_path, capsys):
    """Run the hook once per call; returns (stdout, pings sent)."""
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(nudge, "QUOTA_GUARD_PATH", tmp_path / "quota-guard.json")  # absent unless a test writes it
    monkeypatch.delenv("HERDR_ENV", raising=False)
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    monkeypatch.setattr(nudge, "_which", lambda name: None)  # no orca CLI unless a test says so
    monkeypatch.setenv("PASEO_CLI", "/usr/bin/true")  # a Paseo host needs an executable CLI
    pings = []
    monkeypatch.setattr(
        subprocess, "Popen", lambda cmd, **kwargs: pings.append(cmd),
    )

    def run(session_id, transcript_path):
        payload = json.dumps({
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": str(tmp_path),
        })
        monkeypatch.setattr(
            sys, "stdin",
            type("FakeStdin", (), {"read": staticmethod(lambda: payload)})(),
        )
        before = len(pings)
        nudge.main()
        return capsys.readouterr().out, pings[before:]

    run.state = lambda: json.loads((tmp_path / "state.json").read_text())
    return run


def test_constants_match_the_300k_window():
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    assert nudge.AUTO_COMPACT_WINDOW == 300_000 and wall == 267_000
    assert nudge.PAGE_TOTAL == 400_000
    assert nudge.BOUNDARY_TOTAL == 120_000
    # The hard tier fires with 50k+ tokens of headroom before the native wall (2026-10-28).
    assert nudge.ASK_TOTAL == wall - nudge.ASK_HEADROOM == 217_000
    assert nudge.ASK_HEADROOM >= 50_000
    assert nudge.EARLY_GROWTH == 32_000 < nudge.ASK_GROWTH == 140_000
    assert nudge.ASK_GROWTH < nudge.ASK_TOTAL < wall


def test_below_early_tier_stays_silent(hook, tmp_path):
    out, pings = hook("s-low", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH - 1))
    assert out == ""
    assert pings == []


def test_early_message_at_plus_32k(hook, tmp_path):
    out, pings = hook("s-early", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH))
    assert "Context check" in out
    assert "Do not compact yet" in out
    assert pings == []
    # Same level on the next prompt: no repeat.
    out2, _ = hook("s-early", _transcript(tmp_path, 50_000, 50_000 + nudge.EARLY_GROWTH + 1))
    assert out2 == ""


def test_boundary_note_once_at_120k(hook, tmp_path):
    out, _ = hook("s-bound", _transcript(tmp_path, 100_000, nudge.BOUNDARY_TOTAL - 1))
    assert "handoff" not in out
    path = _transcript(tmp_path, 100_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-bound", path)
    assert "At the next task completion" in out
    assert "/new is ready" in out and "self-slash" not in out
    assert "Do not compact mid-task" in out
    assert hook.state()["s-bound"]["boundary"] is True
    _append(path, _usage(nudge.BOUNDARY_TOTAL + 5_000))
    out, _ = hook("s-bound", path)
    assert "At the next task completion" not in out


def test_boundary_note_survives_compaction(hook, tmp_path):
    """Once per session id: a compaction does not re-arm it, a /new (new id) does."""
    path = _transcript(tmp_path, 50_000, 160_000)
    out, _ = hook("s-once", path)
    assert "At the next task completion" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    hook("s-once", path)
    _append(path, _usage(104_000) + _usage(170_000))
    out, _ = hook("s-once", path)
    assert "At the next task completion" not in out
    out, _ = hook("s-new-id", _transcript(tmp_path, 160_000, name="t2.jsonl"))
    assert "At the next task completion" in out


def test_ask_message_at_plus_200k_bare(hook, tmp_path):
    out, pings = hook("s-ask", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "Context is large" in out
    expected = f"{nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER:,}"
    assert f"by itself at about {expected} tokens" in out
    assert "handoff" in out and "/new is ready" in out
    assert "self-slash" not in out
    assert pings == []


def test_ask_message_at_ask_total(hook, tmp_path):
    out, _ = hook("s-total", _transcript(tmp_path, 150_000, nudge.ASK_TOTAL))
    assert "Context is large" in out


def _is_ask(out):
    return "Context is large" in out or "Context is still growing" in out


def test_growth_tier_boundary(hook, tmp_path):
    """Low floor: the growth tier decides (46k + 140k = 186k, below ASK_TOTAL)."""
    out, _ = hook("s-g-1", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH - 1))
    assert not _is_ask(out) and "Context check" in out  # still the early tier
    out, _ = hook("s-g-0", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "Context is large" in out


def test_total_tier_boundary_with_a_high_floor(hook, tmp_path):
    """Floor 100k (post-compaction size): growth stays below ASK_GROWTH, the total tier fires."""
    assert nudge.ASK_TOTAL - 100_000 < nudge.ASK_GROWTH
    out, _ = hook("s-t-1", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL - 1))
    assert not _is_ask(out)
    out, _ = hook("s-t-0", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "Context is large" in out


@pytest.mark.parametrize("floor", [35_000, 50_000, 71_000, 90_000, 104_000, 130_000, 164_000])
def test_hard_tier_leaves_50k_headroom_for_every_floor(floor):
    """The 267k wall case: whatever the floor (measured 0..164k, median 71k), the first size that
    reaches the hard tier is at least 50k below the wall (before: 200k growth = 271k at the median
    floor, past the wall, and ASK_TOTAL 300k could never fire)."""
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    first = next(t for t in range(floor, wall + 1, 1_000) if nudge._level(t, t - floor) >= 2)
    assert first <= wall - 50_000 or first == floor  # a floor already past the tier asks at once


def test_hard_tier_fires_again_after_compaction_before_the_wall(hook, tmp_path):
    """Compaction drops the floor to ~104k and resets the level; regrowth must reach the hard tier
    (growth 140k would be 244k, only 23k from the wall) by total, 50k+ before it."""
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    path = _transcript(tmp_path, 71_000, nudge.ASK_TOTAL)
    out, _ = hook("s-regrow", path)
    assert "Context is large" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    hook("s-regrow", path)
    _append(path, _usage(104_000))
    out, _ = hook("s-regrow", path)
    assert not _is_ask(out)
    _append(path, _usage(nudge.ASK_TOTAL - 1))
    out, _ = hook("s-regrow", path)
    assert not _is_ask(out)
    _append(path, _usage(nudge.ASK_TOTAL))
    out, _ = hook("s-regrow", path)
    assert "Context is large" in out
    assert nudge.ASK_TOTAL <= wall - 50_000
    assert hook.state()["s-regrow"]["level"] == 2


def test_shrink_without_boundary_record_rearms_the_hard_tier(hook, tmp_path):
    path = _transcript(tmp_path, 71_000, nudge.ASK_TOTAL)
    hook("s-rearm", path)
    _append(path, _usage(104_000))  # < 0.75 x last: a new floor, level reset
    hook("s-rearm", path)
    _append(path, _usage(nudge.ASK_TOTAL))
    out, _ = hook("s-rearm", path)
    assert "Context is large" in out


def test_hard_text_says_what_to_do_mid_task_bare(hook, tmp_path):
    out, _ = hook("s-mid-bare", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    assert "mid-task" in out
    assert "finish the current edit" in out
    assert f"{wall - nudge.ASK_TOTAL:,} tokens remain" in out
    assert "before the next tool round beyond" in out
    assert "when a prompt is submitted and between tool rounds" in out
    assert "only when a prompt is submitted" not in out
    assert "at the next natural boundary" not in out


def test_hard_text_says_what_to_do_mid_task_self_slash(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    out, _ = hook("s-mid-herdr", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "Context is large" in out and "self-slash" in out
    assert "finish the current edit" in out
    assert "before the next tool round beyond" in out
    assert "at the next natural boundary" not in out


def test_midtask_note_counts_rounds_from_what_is_left():
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    assert wall == 267_000 and nudge.ASK_TOTAL == 217_000
    # Literal numbers: 217k leaves 50k; (50k - 15k reserve) // 8k per round = 4.
    at_tier = nudge._midtask_note(217_000, ALT)
    assert "About 50,000 tokens remain" in at_tier and "beyond 4 more" in at_tier
    # 244k leaves 23k; (23k - 15k) // 8k = 1, the last total with a round to spare.
    last = nudge._midtask_note(244_000, ALT)
    assert "About 23,000 tokens remain" in last and "beyond 1 more" in last
    assert "right after" in nudge._midtask_note(244_001, ALT)
    # Near or past the wall: no rounds left, hand off straight after the edit.
    for total in (wall - nudge.HANDOFF_RESERVE, wall, wall + 5_000):
        note = nudge._midtask_note(total, ALT)
        assert "finish the current edit" in note and "right after" in note
        assert "beyond" not in note
    assert "About 0 tokens remain" in nudge._midtask_note(wall + 5_000, ALT)  # clamped, never negative


def test_midtask_note_keeps_the_in_context_path_open():
    """The same message allows an in-context alternative when the work must continue; the note
    must not say "hand off" unconditionally (adversary F2, PR 108) and names the caller's path."""
    for total in (nudge.ASK_TOTAL, nudge.AUTO_COMPACT_WALL):
        note = nudge._midtask_note(total, "the /compact path above")
        assert "work must continue in-context" in note and "the /compact path above" in note
        assert "let the auto-compaction" not in note


def test_bare_branch_does_not_point_at_a_compact_path_it_lacks(hook, tmp_path):
    """The bare message (no herdr/Orca/Paseo, also every ACP slice) has no /compact path:
    the mid-task note must say to let the auto-compaction take it (adversary round 2, F2)."""
    out, _ = hook("s-bare-alt", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "/compact path above" not in out
    assert "(or, if the work must continue in-context, let the auto-compaction take it)" in out
    assert "keep going and let" not in out


def test_self_slash_branch_points_at_its_own_compact_path(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    out, _ = hook("s-slash-alt", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "the /compact path above" in out
    assert "let the auto-compaction take it" not in out
    assert out.index('self-slash "/compact <focus>"') < out.index("the /compact path above")


def test_a_small_dip_does_not_reprint_the_hard_tier(hook, tmp_path):
    """A session hovering around the hard tier (floor 71k; /rewind or dropped tool output dips
    it by <25%) printed the full message on every climb back past 217k (adversary F1)."""
    path = _transcript(tmp_path, 71_000, 217_000)
    out, _ = hook("s-hover", path)
    assert out.count("Context is large") == 1
    outs = []
    for size in (205_000, 218_000, 206_000, 219_000):
        _append(path, _usage(size))
        outs.append(hook("s-hover", path)[0])
    assert [_is_ask(o) for o in outs] == [False] * 4
    assert hook.state()["s-hover"]["level"] == 2



def test_mid_turn_compaction_between_prompts_rearms_the_hard_tier(hook, tmp_path):
    """Adversary round 2, F1: an auto-compaction mid-turn is followed by more tool rounds, so at
    the next prompt the newest record is a usage record and the regrowth (104k -> 180k) stays
    above 0.75 x the last prompt's size. The hook must still learn of the boundary."""
    path = _transcript(tmp_path, 71_000, 230_000)
    out, _ = hook("s-mid", path)
    assert _is_ask(out)
    _append(path, _BOUNDARY_LINE + _usage(104_000))  # compacted mid-turn, no prompt in between
    _append(path, _usage(180_000))
    out, _ = hook("s-mid", path)
    assert not _is_ask(out)
    state = hook.state()["s-mid"]
    assert state["baseline"] == 104_000 and state["level"] == 1  # floor = first usage after it
    _append(path, _usage(220_000))
    out, _ = hook("s-mid", path)
    assert _is_ask(out)
    assert hook.state()["s-mid"]["level"] == 2


def test_mid_turn_compaction_after_a_growth_tier_fire(hook, tmp_path):
    """The adversary's fourth probe row: fired at 217k, compaction, 104k, then 170k, 200k, 230k."""
    path = _transcript(tmp_path, 71_000, 217_000)
    assert _is_ask(hook("s-mid2", path)[0])
    _append(path, _BOUNDARY_LINE + _usage(104_000))
    outs = []
    for size in (170_000, 200_000, 230_000):
        _append(path, _usage(size))
        outs.append(_is_ask(hook("s-mid2", path)[0]))
    assert outs == [False, False, True]


def test_two_compactions_between_prompts_use_the_floor_after_the_last(hook, tmp_path):
    path = _transcript(tmp_path, 71_000, 230_000)
    hook("s-mid3", path)
    _append(path, _BOUNDARY_LINE + _usage(104_000) + _usage(250_000)
            + _BOUNDARY_LINE + _usage(96_000) + _usage(190_000))
    hook("s-mid3", path)
    assert hook.state()["s-mid3"]["baseline"] == 96_000


def test_a_sidechain_boundary_is_not_a_compaction(hook, tmp_path):
    """A sub-agent's compaction (isSidechain) must not reset the main session's tier."""
    path = _transcript(tmp_path, 71_000, 230_000)
    assert _is_ask(hook("s-side", path)[0])
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary", "isSidechain": True})
            + "\n" + _usage(104_000, isSidechain=True))
    _append(path, _usage(228_000))
    out, _ = hook("s-side", path)
    assert not _is_ask(out)
    state = hook.state()["s-side"]
    assert state["level"] == 2 and state["baseline"] == 71_000


def test_a_boundary_before_the_previous_prompt_is_not_found_again(hook, tmp_path):
    """Only the bytes appended since the previous prompt are scanned: an old boundary earlier in
    the transcript must not reset the tier at every later prompt."""
    path = _transcript(tmp_path, 71_000)
    _append(path, _BOUNDARY_LINE + _usage(104_000) + _usage(230_000))
    assert _is_ask(hook("s-old-boundary", path)[0])
    state = hook.state()["s-old-boundary"]
    _append(path, _usage(228_000))
    out, _ = hook("s-old-boundary", path)
    assert out == ""
    after = hook.state()["s-old-boundary"]
    assert after["level"] == 2 and after["baseline"] == state["baseline"]


_BIG_TOOL = json.dumps({"type": "user", "message": {"content": [
    {"type": "tool_result", "content": "x" * 600_000}]}}) + "\n"
# A structured tool_use input holds a raw JSON object: the needle text appears unescaped.
_FAKE_BOUNDARY = json.dumps({"type": "assistant", "isSidechain": False, "message": {"content": [
    {"type": "tool_use", "name": "mcp__x__y", "input": {"subtype": "compact_boundary"}}]}},
    separators=(",", ":")) + "\n"


def _pad(n):
    return json.dumps({"type": "progress", "x": "z" * n}) + "\n"


def _floor(path, since):
    return nudge._compaction_floor_since(path, since, path.stat().st_size)


def test_a_boundary_more_than_2mb_before_the_next_prompt_is_found(hook, tmp_path):
    """Adversary round 3, F1: a heavy turn (images, big tool results) writes >2 MB after a
    mid-turn compaction; the old 2 MB window never saw the boundary and the hard tier stayed
    stuck (real session a0c69a11 missed three climbs)."""
    path = _transcript(tmp_path, 71_000, 225_000)
    assert _is_ask(hook("s-big", path)[0])
    after = _BIG_TOOL * 4
    assert len(after) > 2 * 1024 * 1024
    _append(path, _usage(267_000) + _BOUNDARY_LINE + _usage(104_000) + after)
    _append(path, _usage(180_000))
    out, _ = hook("s-big", path)
    assert not _is_ask(out)
    state = hook.state()["s-big"]
    assert state["baseline"] == 104_000 and state["level"] == 1
    _append(path, _usage(220_000))
    assert _is_ask(hook("s-big", path)[0])


def test_a_boundary_straddling_a_chunk_edge_is_found(tmp_path, monkeypatch):
    """The raw-bytes search reads chunks that overlap by the needle's length: no boundary hides
    on an edge, wherever the edge falls."""
    monkeypatch.setattr(nudge, "_SCAN_CHUNK", 4096)
    straddled = 0
    for pad in range(3800, 4200, 2):
        path = _transcript(tmp_path, 71_000, name=f"edge{pad}.jsonl")
        since = path.stat().st_size
        _append(path, _pad(9000) + _BOUNDARY_LINE + _pad(pad) + _usage(104_000))
        size = path.stat().st_size
        needle_at = path.read_bytes().index(b'"subtype"')
        if 0 < (size - needle_at) % 4096 < 29:
            straddled += 1
        assert _floor(path, since) == 104_000, pad
    assert straddled >= 3  # the sweep really put an edge inside the needle


def test_a_boundary_record_cut_at_the_previous_prompt_is_found_once_complete(hook, tmp_path):
    """Adversary round 3, F4: the record was mid-write when the previous prompt took its size
    snapshot, with its needle already written (and far enough back that a few bytes of margin
    would not reach it)."""
    record = json.dumps({"type": "system", "subtype": "compact_boundary", "content": "c" * 600})
    cut = record.index("compact_boundary") + 300
    path = _transcript(tmp_path, 71_000, 225_000)
    _append(path, record[:cut])  # no newline: the writer is mid-record
    assert _is_ask(hook("s-cut", path)[0])
    _append(path, record[cut:] + "\n" + _usage(104_000) + _usage(180_000))
    out, _ = hook("s-cut", path)
    assert not _is_ask(out)
    assert hook.state()["s-cut"]["baseline"] == 104_000


def test_the_scan_cap_falls_back_to_the_tail_window(tmp_path, monkeypatch):
    """Past _SCAN_CAP appended bytes only the largest tail window is searched (a safety bound)."""
    monkeypatch.setattr(nudge, "_SCAN_CAP", 3 * 1024 * 1024)
    head = _transcript(tmp_path, 71_000, name="cap-head.jsonl")
    since = head.stat().st_size
    base = head.read_text()

    in_tail = tmp_path / "cap-in-tail.jsonl"
    in_tail.write_text(base + _BIG_TOOL * 5 + _BOUNDARY_LINE + _usage(104_000) + _BIG_TOOL)
    assert in_tail.stat().st_size - since > nudge._SCAN_CAP
    assert _floor(in_tail, since) == 104_000

    outside = tmp_path / "cap-outside.jsonl"
    outside.write_text(base + _BOUNDARY_LINE + _usage(104_000) + _BIG_TOOL * 6)
    assert outside.stat().st_size - since > nudge._SCAN_CAP
    assert _floor(outside, since) is None  # beyond the cap AND beyond the tail window
    monkeypatch.setattr(nudge, "_SCAN_CAP", 8 * 1024 * 1024)
    assert _floor(outside, since) == 104_000  # within the cap: the whole region is searched


def test_a_boundary_named_in_a_tool_input_is_not_a_compaction(hook, tmp_path):
    """Adversary round 3, F3: a structured tool_use input is raw JSON, so its text matches the
    needle; only a real `system` record counts, in the scan and in the newest-record read."""
    path = _transcript(tmp_path, 71_000, 230_000)
    assert _is_ask(hook("s-fake", path)[0])
    _append(path, _FAKE_BOUNDARY + _usage(232_000))
    out, _ = hook("s-fake", path)
    assert not _is_ask(out)
    state = hook.state()["s-fake"]
    assert state["level"] == 2 and state["baseline"] == 71_000

    low = _transcript(tmp_path, 71_000, 150_000, name="low.jsonl")
    assert "Context check" in hook("s-fake-low", low)[0]
    _append(low, _FAKE_BOUNDARY + _usage(152_000))
    hook("s-fake-low", low)
    assert hook.state()["s-fake-low"]["baseline"] == 71_000

    newest = _transcript(tmp_path, 71_000, 230_000, name="newest.jsonl")
    _append(newest, _FAKE_BOUNDARY)
    assert nudge._last_context_tokens(newest) == 230_000
    _append(newest, _BOUNDARY_LINE)
    assert nudge._last_context_tokens(newest) == nudge.COMPACTED
    for record in ({"type": "user", "subtype": "compact_boundary"},
                   {"type": "system", "subtype": "compact_boundary", "isSidechain": True},
                   {"type": "system", "subtype": "other"}):
        assert not nudge._is_boundary_line(json.dumps(record).encode())
    assert nudge._is_boundary_line(json.dumps({"type": "system", "subtype": "compact_boundary"}).encode())


def test_a_dip_below_the_total_tier_keeps_the_fired_level_with_a_low_floor(hook, tmp_path):
    """Adversary round 3, F2: floor 20k, level 2 fired at 160k (growth 140k). A dip to 125k is
    inside the 25% band but below the total tiers; clamping the stored level against the dipped
    total lowered it to 1 and the next climb printed the hard message again."""
    (tmp_path / "state.json").write_text(json.dumps({"s-lowfloor": {"level": 0, "baseline": 20_000}}))
    path = _transcript(tmp_path, 160_000)
    assert _is_ask(hook("s-lowfloor", path)[0])
    outs = []
    for size in (125_000, 161_000, 126_000, 162_000):
        _append(path, _usage(size))
        outs.append(_is_ask(hook("s-lowfloor", path)[0]))
    assert outs == [False] * 4
    assert hook.state()["s-lowfloor"]["level"] == 2


def test_state_without_a_stored_size_scans_nothing_and_keeps_working(hook, tmp_path):
    """State written before the size field existed: no boundary scan, no crash, later prompts store it."""
    path = _transcript(tmp_path, 71_000, 230_000)
    hook("s-oldstate", path)
    state = hook.state()
    state["s-oldstate"].pop("size")
    (tmp_path / "state.json").write_text(json.dumps(state))
    _append(path, _BOUNDARY_LINE + _usage(104_000) + _usage(230_000))
    out, _ = hook("s-oldstate", path)
    assert not _is_ask(out)  # level already 2, nothing to scan against
    assert hook.state()["s-oldstate"]["size"] == path.stat().st_size


def test_gradual_rewinds_that_sum_to_a_real_shrink_rearm(hook, tmp_path):
    """Several dips, each under 25% of the previous prompt, but together far below the peak
    (adversary round 2, F1 lesser variant): the level must reset and the tiers fire on regrowth."""
    path = _transcript(tmp_path, 71_000, 220_000)
    assert _is_ask(hook("s-rewind", path)[0])
    for size in (170_000, 130_000, 100_000, 76_000):
        _append(path, _usage(size))
        out, _ = hook("s-rewind", path)
        assert not _is_ask(out)
    assert hook.state()["s-rewind"]["level"] == 0
    _append(path, _usage(150_000))
    out, _ = hook("s-rewind", path)
    assert "Context check" in out  # EARLY again
    _append(path, _usage(218_000))
    out, _ = hook("s-rewind", path)
    assert _is_ask(out)


@pytest.mark.parametrize("stored", [5, 9])
def test_a_stored_level_above_what_the_total_can_compute_is_clamped(hook, tmp_path, stored):
    """Old or corrupt state (adversary round 2, F4): level 5 at a 218k total (highest tier that
    total can compute is 2) must not stick for the rest of the session."""
    path = _transcript(tmp_path, 71_000, 218_000)
    hook("s-clamp", path)
    state = hook.state()
    state["s-clamp"]["level"] = stored
    (tmp_path / "state.json").write_text(json.dumps(state))
    _append(path, _usage(219_000))
    out, _ = hook("s-clamp", path)
    assert not _is_ask(out)
    assert hook.state()["s-clamp"]["level"] == 2


def _host(monkeypatch, var):
    """Set one self-slash host the way bin/self-slash selects it: a herdr pane needs
    HERDR_ENV=1 as well, an Orca terminal needs the orca CLI on PATH."""
    monkeypatch.setenv(var, "w1:p1")
    if var == "HERDR_PANE_ID":
        monkeypatch.setenv("HERDR_ENV", "1")
    if var == "ORCA_TERMINAL_HANDLE":
        monkeypatch.setattr(nudge, "_which", lambda name: "/usr/local/bin/orca" if name == "orca" else None)


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "PASEO_AGENT_ID"])
def test_ask_message_in_herdr_or_orca_puts_new_before_compact(hook, tmp_path, monkeypatch, var):
    _host(monkeypatch, var)
    out, _ = hook("s-herdr-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "Handle it yourself" in out
    assert out.index('self-slash "/new"') < out.index('"/compact <focus>"')
    assert out.index("`handoff` skill") < out.index('"/compact <focus>"')
    assert "must continue in-context" in out
    # The boundary note fires in the same call (total >= 150k) and names self-slash here.
    assert 'the `handoff` skill (its Step 9 runs ~/src/djbclark-ade/bin/self-slash "/new" and queues /baton) instead of /compact' in out
    assert "Do not run /new yourself as well" in out


def test_repeat_ask_every_100k(hook, tmp_path):
    path = _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH)
    hook("s-rep", path)
    _append(path, _usage(46_000 + nudge.ASK_GROWTH + nudge.REPEAT_EVERY - 1))
    out, _ = hook("s-rep", path)
    assert "Context is" not in out
    _append(path, _usage(46_000 + nudge.ASK_GROWTH + nudge.REPEAT_EVERY))
    out, _ = hook("s-rep", path)
    assert "Context is still growing" in out


def test_floor_resets_after_compact_boundary(hook, tmp_path):
    path = _transcript(tmp_path, 50_000, 260_000)
    out, _ = hook("s-floor", path)
    assert "Context is large" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    out, _ = hook("s-floor", path)
    assert out == ""
    state = hook.state()["s-floor"]
    assert state["baseline"] is None and state["level"] == 0
    _append(path, _usage(104_000))
    out, _ = hook("s-floor", path)
    assert out == ""
    assert hook.state()["s-floor"]["baseline"] == 104_000
    _append(path, _usage(104_000 + nudge.EARLY_GROWTH))
    out, _ = hook("s-floor", path)
    assert "Context check" in out


def test_shrink_between_prompts_is_a_new_floor(hook, tmp_path):
    path = _transcript(tmp_path, 50_000, 260_000)
    hook("s-shrink", path)
    _append(path, _usage(110_000))  # < 0.75 x 260k, no boundary record seen
    out, _ = hook("s-shrink", path)
    assert out == ""
    assert hook.state()["s-shrink"]["baseline"] == 110_000


def test_zero_usage_error_stub_is_not_a_context_reading(hook, tmp_path):
    assert nudge._usage_from_line(_usage(0).encode()) is None
    path = _transcript(tmp_path, 100_000)
    hook("s-zero", path)
    # "You've hit your session limit": the stub is the newest record when the next prompt
    # arrives (the usual sequence: the user re-prompts after the reset)
    _append(path, _usage(0))
    out, _ = hook("s-zero", path)
    assert out == ""
    assert hook.state()["s-zero"]["baseline"] == 100_000
    _append(path, _usage(140_000))  # +40k of real growth, not 140k from a zero baseline
    out, _ = hook("s-zero", path)
    assert "Context is large" not in out and "still growing" not in out


def test_page_once_at_plus_300k(hook, tmp_path):
    path = _transcript(tmp_path, 40_000, 40_000 + nudge.PAGE_GROWTH)
    _, pings = hook("s-page", path)
    assert len(pings) == 1
    assert pings[0][0] == str(nudge.PING_BIN)
    assert "/handoff then /new" in pings[0][1]
    _append(path, _usage(40_000 + nudge.PAGE_GROWTH + 10_000))
    _, pings = hook("s-page", path)
    assert pings == []


def test_page_at_400k_total(hook, tmp_path):
    _, pings = hook("s-page-total", _transcript(tmp_path, 350_000, nudge.PAGE_TOTAL))
    assert len(pings) == 1


def test_sidechain_usage_is_ignored(hook, tmp_path):
    path = _transcript(tmp_path, 50_000)
    _append(path, _usage(500_000, isSidechain=True))
    out, pings = hook("s-side", path)
    assert out == ""
    assert pings == []


def test_missing_transcript_path_is_silent_and_safe(hook, monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "stdin",
        type("FakeStdin", (), {"read": staticmethod(lambda: json.dumps({"session_id": "s-none"}))})(),
    )
    nudge.main()
    assert capsys.readouterr().out == ""


def test_malformed_stdin_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": staticmethod(lambda: "not json")})())
    nudge.main()  # must not raise


def test_reads_large_transcript_from_tail_only(hook, tmp_path):
    """Real transcripts run tens of MB; the tail read still finds the newest
    usage block, and the head read the session's first one."""
    path = tmp_path / "big.jsonl"
    with path.open("w") as f:
        for _ in range(5000):
            f.write(_usage(1_000))
        f.write(_usage(1_000 + nudge.PAGE_GROWTH))
    out, pings = hook("s-big", path)
    assert "Context is large" in out
    assert len(pings) == 1


# bin/self-slash: --dry-run runs the same gap check a real call does, so the
# refusal is testable without a live pane. The Orca host needs only $ORCA_TERMINAL_HANDLE
# and an `orca` on PATH (never called on a dry run).
_needs_self_slash = pytest.mark.skipif(
    not (shutil.which("orca") and shutil.which("gdate") and shutil.which("ggrep")),
    reason="self-slash dry run needs orca, gdate and ggrep on PATH",
)


def _self_slash(tmp_path, text, handle="th1", log_lines=()):
    log = tmp_path / ".local" / "state" / "self-slash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    if log_lines:
        log.write_text("".join(line + "\n" for line in log_lines))
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "CURSOR_AGENT", "SELF_SLASH_COMPACT_GAP")}
    env.update(HOME=str(tmp_path), ORCA_TERMINAL_HANDLE=handle)
    return subprocess.run([str(SELF_SLASH), "--dry-run", text], env=env,
                          capture_output=True, text=True, timeout=30)


def _self_slash_paseo(tmp_path, text, agent="ag1"):
    """The Paseo host: $PASEO_AGENT_ID and a CLI path; a dry run never calls the CLI."""
    log = tmp_path / ".local" / "state" / "self-slash.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "CURSOR_AGENT",
                        "SELF_SLASH_COMPACT_GAP")}
    env.update(HOME=str(tmp_path), PASEO_AGENT_ID=agent, PASEO_CLI="/usr/bin/true")
    return subprocess.run([str(SELF_SLASH), "--dry-run", text], env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(not (shutil.which("gdate") and shutil.which("ggrep")),
                    reason="self-slash dry run needs gdate and ggrep on PATH")
def test_self_slash_paseo_host_maps_new_to_clear(tmp_path):
    r = _self_slash_paseo(tmp_path, "/new")
    assert r.returncode == 0, r.stderr
    assert "would send to paseo ag1" in r.stdout and ": /clear" in r.stdout
    r = _self_slash_paseo(tmp_path, "/compact keep the open items")
    assert r.returncode == 0, r.stderr
    assert ": /compact keep the open items" in r.stdout


@pytest.mark.skipif(not (shutil.which("gdate") and shutil.which("ggrep")),
                    reason="self-slash dry run needs gdate and ggrep on PATH")
def test_self_slash_paseo_needs_a_cli(tmp_path):
    env = {k: v for k, v in os.environ.items()
           if k not in ("HERDR_ENV", "HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE", "PASEO_CLI")}
    # The script prepends /opt/homebrew/bin to PATH, so a bare PATH cannot hide a real
    # paseo; a non-executable PASEO_CLI is the refusal path.
    env.update(HOME=str(tmp_path), PASEO_AGENT_ID="ag1", PASEO_CLI="/nonexistent/paseo")
    r = subprocess.run([str(SELF_SLASH), "--dry-run", "/compact"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 3 and "no paseo CLI" in r.stderr


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


@_needs_self_slash
@pytest.mark.parametrize("sent", ["/compact focus", "/new", "/clear", "/reset"])
@pytest.mark.parametrize("text", ["/new", "/compact x", "/clear", "/reset"])
def test_self_slash_refuses_reset_family_within_gap(tmp_path, sent, text):
    r = _self_slash(tmp_path, text, log_lines=[f"{_now()} orca th1: sent {sent}"])
    assert r.returncode == 7, r.stderr
    assert "not sending" in r.stderr


@_needs_self_slash
def test_self_slash_allows_after_gap_other_pane_and_other_commands(tmp_path):
    lines = [f"{_now()} orca th1: sent /new", "2026-01-01 00:00:00 orca th2: sent /compact"]
    assert _self_slash(tmp_path, "/rename foo", log_lines=lines).returncode == 0
    assert _self_slash(tmp_path, "/new", handle="th2").returncode == 0
    assert _self_slash(tmp_path, "/new", handle="th3").returncode == 0


@_needs_self_slash
def test_self_slash_not_sent_lines_do_not_count(tmp_path):
    lines = [f"{_now()} orca th1: NOT sent: /compact was already sent to orca th1 5s ago",
             f"{_now()} orca th1: waiter 123 still queued after 900s; NOT sent: /new"]
    assert _self_slash(tmp_path, "/new", log_lines=lines).returncode == 0


def test_paseo_host_gets_the_finish_note(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    out, _ = hook("s-paseo", _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "self-slash --finish" in out and "archives this agent" in out
    # the model offers the loose Rule 4 choices; it does not archive itself
    assert "offer the `loose` Rule 4 choices" in out and "rather than archiving yourself" in out
    assert "finish as the last action instead" not in out
    assert 'self-slash "/new" ONCE' in out
    assert "so do not run /new yourself as well" in out


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE"])
def test_finish_note_is_paseo_only(hook, tmp_path, monkeypatch, var):
    _host(monkeypatch, var)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")  # herdr and Orca win in self-slash
    out, _ = hook("s-nofinish-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "--finish" not in out


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE"])
def test_finish_note_when_the_other_host_var_is_stale(hook, tmp_path, monkeypatch, var):
    # A HERDR_PANE_ID without HERDR_ENV=1, or an ORCA_TERMINAL_HANDLE with no orca CLI,
    # is not a host for self-slash: it falls through to Paseo, and so does the note
    # (Codex P2 on PR 19, 2026-10-20).
    monkeypatch.setenv(var, "w1:p1")
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    out, _ = hook("s-stale-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "self-slash --finish" in out


@pytest.mark.parametrize("cli", ["unset", "/nonexistent/paseo", "not-executable"])
def test_paseo_host_needs_an_executable_cli(hook, tmp_path, monkeypatch, cli):
    # self-slash exits 3 when PASEO_AGENT_ID is set but no paseo CLI is usable (PASEO_CLI
    # unset and none on PATH, or not executable); the hook must not promise Step 9 there.
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    if cli == "unset":
        monkeypatch.delenv("PASEO_CLI", raising=False)
    elif cli == "not-executable":
        f = tmp_path / "paseo"
        f.write_text("")
        f.chmod(0o600)
        monkeypatch.setenv("PASEO_CLI", str(f))
    else:
        monkeypatch.setenv("PASEO_CLI", cli)
    out, _ = hook("s-nocli-" + cli.replace("/", "_"), _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "tell the operator /new is ready" in out
    assert "--finish" not in out


def test_orca_lookup_searches_self_slash_path(monkeypatch, tmp_path):
    # self-slash prepends /opt/homebrew/bin to PATH before picking the host; the hook's
    # lookup must see the same prefix even when the hook's own PATH lacks it.
    seen = {}

    def fake_which(name, path=None):
        seen["path"] = path
        return None

    monkeypatch.setattr(nudge.shutil, "which", fake_which)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert nudge._which("orca") is None
    assert seen["path"].split(os.pathsep)[0] == "/opt/homebrew/bin"
    assert str(tmp_path) in seen["path"].split(os.pathsep)


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE"])
def test_stale_host_var_alone_means_no_self_slash(hook, tmp_path, monkeypatch, var):
    monkeypatch.setenv(var, "w1:p1")
    out, _ = hook("s-stale-alone-" + var, _transcript(tmp_path, 46_000, 46_000 + nudge.ASK_GROWTH))
    assert "tell the operator /new is ready" in out
    assert "--finish" not in out


# --- successor form (2026-10-23): a Fable session, or a tight quota guard, hands off to Opus/Sonnet ---

def _model_transcript(tmp_path, model, *sizes, name="model-transcript.jsonl"):
    path = tmp_path / name
    lines = []
    for s in sizes:
        record = json.loads(_usage(s))
        record["message"]["model"] = model
        record["message"]["role"] = "assistant"
        lines.append(json.dumps(record) + "\n")
    path.write_text("".join(lines))
    return path


def _guard(tmp_path, level):
    (tmp_path / "quota-guard.json").write_text(json.dumps({"level": level}))


_OPUS_FORM = "self-slash --finish --successor claude/claude-opus-5-5 --thinking high"


def test_fable_session_on_paseo_names_the_successor_form_in_both_messages(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    path = _model_transcript(tmp_path, nudge.FABLE_MODEL, 46_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-fable", path)
    assert out.count(_OPUS_FORM) == 1 and "At the next task completion" in out  # the boundary message
    assert 'self-slash "/new"' not in out
    assert "this session runs on Fable" in out
    _append(path, _model_transcript(tmp_path, nudge.FABLE_MODEL, 46_000 + nudge.ASK_GROWTH,
                                    name="x.jsonl").read_text())
    out, _ = hook("s-fable", path)
    assert "Context is large" in out and _OPUS_FORM in out  # the ask message
    assert "archived agent's log" in out
    assert 'self-slash "/new"' not in out
    assert "so do not run /new yourself as well" in out


def test_other_models_keep_the_new_form(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    out, _ = hook("s-opus", _model_transcript(tmp_path, "claude-opus-5-5", 46_000, nudge.BOUNDARY_TOTAL))
    assert "--successor" not in out
    assert 'self-slash "/new" and queues /baton' in out


@pytest.mark.parametrize("level, model, spec", [
    ("tight", "claude-opus-5-5", "claude-sonnet-5-5"),
    ("tight", nudge.FABLE_MODEL, "claude-sonnet-5-5"),
    ("critical", nudge.FABLE_MODEL, "claude-opus-5-5"),
])
def test_guard_level_picks_the_successor_even_on_a_non_fable_model(hook, tmp_path, monkeypatch, level, model, spec):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    _guard(tmp_path, level)
    out, _ = hook("s-guard-" + level + model, _model_transcript(tmp_path, model, 46_000, nudge.BOUNDARY_TOTAL))
    assert f"--successor claude/{spec} --thinking high" in out
    assert f"the quota guard says {level}" in out


@pytest.mark.parametrize("content", [None, "not json", '{"level": 3}', '{"level": "ok"}', "[]"])
def test_absent_or_unusable_guard_state_changes_nothing(hook, tmp_path, monkeypatch, content):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    if content is not None:
        (tmp_path / "quota-guard.json").write_text(content)
    out, _ = hook("s-noguard", _model_transcript(tmp_path, "claude-opus-5-5", 46_000, nudge.BOUNDARY_TOTAL))
    assert "--successor" not in out and 'self-slash "/new"' in out


@pytest.mark.parametrize("var", ["HERDR_PANE_ID", "ORCA_TERMINAL_HANDLE"])
def test_successor_is_not_offered_on_herdr_or_orca(hook, tmp_path, monkeypatch, var):
    _host(monkeypatch, var)
    out, _ = hook("s-fable-" + var, _model_transcript(tmp_path, nudge.FABLE_MODEL, 46_000, nudge.BOUNDARY_TOTAL))
    assert "--successor claude" not in out
    assert "relaunch `claude --model claude-opus-5-5`" in out
    assert 'self-slash "/new"' in out


def test_sidechain_and_synthetic_records_do_not_decide_the_model(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [
        {"message": {"model": "claude-opus-5-5", "role": "assistant"}},
        {"isSidechain": True, "message": {"model": nudge.FABLE_MODEL, "role": "assistant"}},
        {"message": {"model": "<synthetic>", "role": "assistant"}},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert nudge._last_assistant_model(path) == "claude-opus-5-5"
    assert nudge._last_assistant_model(tmp_path / "missing.jsonl") is None


@pytest.mark.parametrize("level, model", [
    ("tight", "claude-sonnet-5-5"), ("tight", "claude-sonnet-5-5[1m]"),
    ("critical", "claude-opus-5-5"), ("critical", "claude-opus-5-5[1m]"),
    ("critical", "claude-sonnet-5-5"),
])
def test_a_session_already_on_the_target_gets_plain_new_not_a_same_model_successor(hook, tmp_path, monkeypatch, level, model):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    _guard(tmp_path, level)
    out, _ = hook("s-same-" + level + model, _model_transcript(tmp_path, model, 46_000, nudge.BOUNDARY_TOTAL))
    assert "--successor" not in out
    assert 'self-slash "/new" and queues /baton' in out
    assert nudge._successor_target(model, level) is None


@pytest.mark.parametrize("model", ["claude-fable-5-1[1m]", "claude-fable-5-2", "claude-fable-6"])
def test_l5_any_fable_id_with_or_without_a_suffix_is_detected(model):
    assert nudge._successor_target(model, "") == (nudge.SUCCESSOR_OPUS, "this session runs on Fable")
    assert nudge._successor_target("claude-opus-5-5[1m]", "") is None


@pytest.mark.parametrize("level", ["tight", "critical"])
@pytest.mark.parametrize("model", [None, "", "claude-haiku-4-5", "claude-haiku-4-5[1m]", "gpt-6"])
def test_r2_l4_guard_never_moves_an_unknown_or_lower_model_up(level, model):
    assert nudge._successor_target(model, level) is None


def test_r2_l4_guard_moves_only_models_known_to_be_above_the_target():
    assert nudge._successor_target("claude-opus-5-5", "tight") == (nudge.SUCCESSOR_SONNET, "the quota guard says tight")
    assert nudge._successor_target("claude-fable-5-1[1m]", "tight")[0] == nudge.SUCCESSOR_SONNET
    assert nudge._successor_target(nudge.FABLE_MODEL, "critical")[0] == nudge.SUCCESSOR_OPUS
    assert nudge._successor_target("claude-opus-5-5", "critical") is None


def test_r2_l4_unreadable_model_under_a_guard_hands_off_with_plain_new(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-1")
    _guard(tmp_path, "critical")
    out, _ = hook("s-nomodel", _transcript(tmp_path, 46_000, nudge.BOUNDARY_TOTAL))  # no assistant model
    assert "--successor" not in out and 'self-slash "/new"' in out
