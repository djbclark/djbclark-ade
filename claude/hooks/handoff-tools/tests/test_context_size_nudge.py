"""Contract tests for context_size_nudge.py's tiers, floor and paging, and for
the hook's messages (2026-10-18 rewrite: the old tests asserted
SOFT_THRESHOLD/HARD_THRESHOLD and a `hermes send` call the hook no longer has)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOOKS_DIR))

import context_size_nudge as nudge

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


@pytest.fixture(autouse=True)
def _no_fable_lead(monkeypatch, tmp_path_factory):
    """The relaunch-on-Opus tests run under the 2026-10-23 rule (`[lead].fable_lead` false); the shipped
    config/routing.toml allows a Fable lead (2026-11-07), tested on its own below."""
    policy = tmp_path_factory.mktemp("routing") / "routing.toml"
    policy.write_text("[lead]\nmodel = \"opus\"\nfable_lead = false\n")
    monkeypatch.setenv("ROUTING_POLICY", str(policy))


@pytest.fixture(autouse=True)
def settings_file(monkeypatch, tmp_path_factory):
    """The hook reads the session's compaction window from SETTINGS_PATH and the env (2026-11-21): never
    the host's. Default: the shipped 300k autoCompactWindow, so the wall is 267k; a test rewrites it."""
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    path = tmp_path_factory.mktemp("claude") / "settings.json"
    path.write_text(json.dumps({"autoCompactWindow": 300_000}))
    monkeypatch.setattr(nudge, "SETTINGS_PATH", path)
    return path


@pytest.fixture
def hook(monkeypatch, tmp_path, capsys):
    """Run the hook once per call; returns (stdout, pings sent)."""
    monkeypatch.setattr(nudge, "STATE_PATH", tmp_path / "state.json")
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
    """The module constants are the FALLBACK tiers (a 300k window, wall 267k), 2026-11-21."""
    wall = nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER
    assert nudge.AUTO_COMPACT_WINDOW == 300_000 and wall == 267_000
    assert nudge.PAGE_TOTAL == 400_000
    # The hard tier fires with 50k+ tokens of headroom before the native wall (2026-10-28).
    assert nudge.ASK_TOTAL == wall - nudge.ASK_HEADROOM == 217_000
    assert nudge.ASK_HEADROOM >= 50_000
    # The boundary tier is near the limit, not a fixed 120k (2026-11-21).
    assert nudge.BOUNDARY_TOTAL == wall - nudge.BOUNDARY_HEADROOM == 187_000
    assert nudge.BOUNDARY_FLOOR == 120_000
    assert not hasattr(nudge, "ASK_GROWTH")
    assert nudge.EARLY_GROWTH == 32_000
    assert nudge.EARLY_GROWTH < nudge.BOUNDARY_TOTAL < nudge.ASK_TOTAL < wall


@pytest.mark.parametrize("wall, ask, boundary, page_total, page_growth", [
    (267_000, 217_000, 187_000, 400_000, 300_000),
    (967_000, 917_000, 887_000, 917_000, 817_000),     # a [1m] model with no autoCompactWindow
    (167_000, 117_000, 117_000, 400_000, 300_000),     # 200k window: 120k floor, capped at the hard tier
    (217_000, 167_000, 137_000, 400_000, 300_000),
    (200_000, 150_000, 120_000, 400_000, 300_000),     # wall - 80k = 120k exactly
])
def test_tiers_derive_from_the_wall(wall, ask, boundary, page_total, page_growth):
    assert tuple(nudge._tiers(wall)) == (wall, ask, boundary, page_total, page_growth)
    assert boundary <= ask


def _write_settings(path, **kw):
    path.write_text(json.dumps(kw))


def test_wall_from_the_configured_window(settings_file):
    assert nudge.compaction_wall() == 267_000   # fixture: autoCompactWindow 300k
    assert nudge.compaction_wall(nudge.read_settings(), "claude-opus-5-5") == 267_000


def test_wall_of_a_1m_model_without_a_window_is_967k(settings_file):
    _write_settings(settings_file)
    assert nudge.compaction_wall(None, "claude-opus-5-5[1m]") == 967_000
    _write_settings(settings_file, model="opus[1m]")  # settings' own default model
    assert nudge.compaction_wall() == 967_000


def test_wall_is_the_lower_of_the_window_and_the_model(settings_file):
    _write_settings(settings_file, autoCompactWindow=300_000)
    assert nudge.compaction_wall(None, "claude-haiku-5-5") == 167_000
    _write_settings(settings_file, autoCompactWindow=2_000_000)
    assert nudge.compaction_wall(None, "claude-opus-5-5[1m]") == 967_000


def test_wall_env_beats_settings_and_modelsettings(settings_file, monkeypatch):
    _write_settings(settings_file, autoCompactWindow=300_000,
                    modelSettings={"claude-opus-5-5": {"autoCompactWindow": 500_000}})
    assert nudge.compaction_wall(None, "claude-opus-5-5") == 467_000  # per-model beats the top level
    assert nudge.compaction_wall(None, "claude-sonnet-5-5") == 267_000
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "150000")
    assert nudge.compaction_wall(None, "claude-opus-5-5") == 117_000
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "junk")  # not a window: settings decide again
    assert nudge.compaction_wall(None, "claude-opus-5-5") == 467_000


@pytest.mark.parametrize("raw", [None, "not json", "[]", json.dumps({"autoCompactWindow": "auto"}),
                                 json.dumps({"autoCompactWindow": 10})])
def test_unreadable_or_unusable_settings_fall_back_to_267k(settings_file, raw):
    if raw is None:
        settings_file.unlink()
    else:
        settings_file.write_text(raw)
    assert nudge.compaction_wall() == nudge.AUTO_COMPACT_WALL == 267_000
    assert nudge._tiers(nudge.compaction_wall()).ask_total == nudge.ASK_TOTAL


def test_level_scales_with_the_wall():
    big = nudge._tiers(967_000)
    assert nudge._level(300_000, 300_000, big) == 1      # only the early tier
    assert nudge._level(917_000, 0, big) == 2
    assert nudge._level(300_000, 0, nudge._tiers(267_000)) == 2


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


def test_boundary_note_once_near_the_wall(hook, tmp_path):
    out, _ = hook("s-bound", _transcript(tmp_path, 170_000, nudge.BOUNDARY_TOTAL - 1))
    assert "handoff" not in out
    path = _transcript(tmp_path, 170_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-bound", path)
    assert "At the next task completion" in out
    assert "80,000 tokens left before Claude Code compacts this session at 267,000" in out
    assert "a finished task alone is no reason to hand off or compact" in out
    assert "never hand the operator a /new" in out and "when handing off, do it yourself" in out
    assert "handoff Step 9 yourself" in out and "ade-self-session handoff" in out
    assert "/new is ready" not in out and "self-slash" not in out
    assert "Do not compact mid-task" in out
    assert hook.state()["s-bound"]["boundary"] is True
    _append(path, _usage(nudge.BOUNDARY_TOTAL + 5_000))
    out, _ = hook("s-bound", path)
    assert "At the next task completion" not in out


def test_boundary_note_survives_compaction(hook, tmp_path):
    """Once per session id: a compaction does not re-arm it, a /new (new id) does."""
    path = _transcript(tmp_path, 50_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-once", path)
    assert "At the next task completion" in out
    _append(path, json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n")
    hook("s-once", path)
    _append(path, _usage(104_000) + _usage(nudge.BOUNDARY_TOTAL + 10_000))
    out, _ = hook("s-once", path)
    assert "At the next task completion" not in out
    out, _ = hook("s-new-id", _transcript(tmp_path, nudge.BOUNDARY_TOTAL, name="t2.jsonl"))
    assert "At the next task completion" in out


def test_ask_message_at_the_hard_tier_bare(hook, tmp_path):
    out, pings = hook("s-ask", _transcript(tmp_path, 46_000, nudge.ASK_TOTAL))
    assert "Context is large" in out
    expected = f"{nudge.AUTO_COMPACT_WINDOW - nudge.AUTO_COMPACT_BUFFER:,}"
    assert f"by itself at about {expected} tokens" in out
    assert "handoff Step 9 yourself" in out and "ade-self-session handoff" in out
    assert "/new is ready" not in out and "never hand the operator a /new" in out
    assert "self-slash" not in out
    assert f"{nudge.AUTO_COMPACT_WALL - nudge.ASK_TOTAL:,} from now" in out
    assert pings == []


def test_ask_message_at_ask_total(hook, tmp_path):
    out, _ = hook("s-total", _transcript(tmp_path, 150_000, nudge.ASK_TOTAL))
    assert "Context is large" in out


def _is_ask(out):
    return "Context is large" in out or "Context is still growing" in out


def test_growth_no_longer_fires_the_hard_tier(hook, tmp_path):
    """2026-11-21: floor 35k + the old ASK_GROWTH 140k = 175k fired "hand off" with 92k left to the wall.
    Now only the early tier speaks there, and neither the boundary nor the hard text."""
    out, _ = hook("s-g-175", _transcript(tmp_path, 35_000, 175_000))
    assert "Context check" in out and not _is_ask(out)
    assert "At the next task completion" not in out and "handoff Step 9" not in out
    out, _ = hook("s-g-186", _transcript(tmp_path, 46_000, nudge.BOUNDARY_TOTAL - 1))
    assert "Context check" in out and not _is_ask(out) and "handoff Step 9" not in out
    assert hook.state()["s-g-186"]["level"] == 1


def test_no_early_handoff_message_at_150k_on_a_267k_wall(hook, tmp_path):
    """The 2026-11-21 incident: a lead handed itself off at ~150k with 117k left. Whatever the floor,
    nothing at 150k may read as a handoff instruction."""
    for floor in (35_000, 71_000, 104_000, 150_000):
        out, pings = hook(f"s-150-{floor}", _transcript(tmp_path, floor, 150_000, name=f"t{floor}.jsonl"))
        for phrase in ("handoff Step 9", "At the next task completion", "hand off", "Context is large"):
            assert phrase not in out, (floor, phrase)
        assert pings == []
    assert nudge.BOUNDARY_TOTAL - 150_000 >= 30_000


def test_total_tier_boundary_with_a_high_floor(hook, tmp_path):
    """Floor 100k (post-compaction size): the total tier fires (growth is no trigger)."""
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


def test_hard_text_says_what_to_do_mid_task(hook, tmp_path):
    out, _ = hook("s-mid", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "Context is large" in out and "self-slash" not in out
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


def test_the_in_context_path_lets_auto_compaction_take_it(hook, tmp_path):
    """2026-11-06 (slim-down E4): bin/self-slash is gone; a Claude session cannot run built-in slash commands."""
    out, _ = hook("s-compact-alt", _transcript(tmp_path, 100_000, nudge.ASK_TOTAL))
    assert "(or, if the work must continue in-context, let the auto-compaction take it)" in out
    assert "run /compact yourself" not in out and "self-slash" not in out


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
    """Adversary round 3, F2: floor 20k, level 2 fired at the hard tier. A dip inside the 25% band
    (165k after 217k) is below the total tier; clamping the stored level against the dipped
    total lowered it to 1 and the next climb printed the hard message again. (Rebased 2026-11-21:
    it used to fire by growth at 160k; only the total fires the hard tier now.)"""
    (tmp_path / "state.json").write_text(json.dumps({"s-lowfloor": {"level": 0, "baseline": 20_000}}))
    path = _transcript(tmp_path, nudge.ASK_TOTAL)
    assert _is_ask(hook("s-lowfloor", path)[0])
    outs = []
    for size in (165_000, 218_000, 166_000, 219_000):
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


def test_repeat_ask_every_100k(hook, tmp_path):
    path = _transcript(tmp_path, 46_000, nudge.ASK_TOTAL)
    hook("s-rep", path)
    _append(path, _usage(nudge.ASK_TOTAL + nudge.REPEAT_EVERY - 1))
    out, _ = hook("s-rep", path)
    assert "Context is" not in out
    _append(path, _usage(nudge.ASK_TOTAL + nudge.REPEAT_EVERY))
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


# --- successor form (2026-10-23): a Fable session hands off to Opus unless [lead].fable_lead (2026-11-07) ---
_FABLE = "claude-fable-5-2"


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


_OPUS_NOTE = "relaunch `claude --model claude-opus-5-5`"


def test_fable_session_gets_the_relaunch_note_in_both_messages(hook, tmp_path):
    path = _model_transcript(tmp_path, _FABLE, 46_000, nudge.BOUNDARY_TOTAL)
    out, _ = hook("s-fable", path)
    assert out.count(_OPUS_NOTE) == 1 and "At the next task completion" in out
    assert "this session runs on Fable" in out and "self-slash" not in out
    _append(path, _model_transcript(tmp_path, _FABLE, nudge.ASK_TOTAL, name="x.jsonl").read_text())
    out, _ = hook("s-fable", path)
    assert "Context is large" in out and _OPUS_NOTE in out


def test_fable_lead_true_means_no_relaunch_note(hook, tmp_path, monkeypatch):
    """Operator 2026-11-07: `[lead].fable_lead = true` allows a Fable lead, so the Opus note goes; the shipped file says true."""
    policy = tmp_path / "routing.toml"
    policy.write_text("[routing]\nkinds = []\n\n[lead]  # the lead\nmodel = \"opus\"\nfable_lead = true  # flip to false\n")
    monkeypatch.setenv("ROUTING_POLICY", str(policy))
    assert nudge._fable_lead_allowed() is True
    out, _ = hook("s-fable-lead", _model_transcript(tmp_path, _FABLE, 46_000, nudge.BOUNDARY_TOTAL))
    assert "relaunch" not in out
    monkeypatch.delenv("ROUTING_POLICY")
    shipped = Path(nudge.__file__).resolve().parents[2] / "config" / "ade.toml"
    assert nudge._routing_policy_path() == shipped and nudge._fable_lead_allowed() is True


def test_unified_ade_toml_wins_over_legacy_routing_in_the_same_checkout(tmp_path, monkeypatch):
    """W16 (2026-11-12): config/ade.toml is the repo base once present; its `[lead]` decides, legacy is ignored."""
    cfg = tmp_path / "repo" / "config"
    cfg.mkdir(parents=True)
    (cfg / "routing.toml").write_text("[lead]\nfable_lead = true\n")
    monkeypatch.delenv("ROUTING_POLICY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(nudge, "__file__", str(tmp_path / "repo" / "claude" / "hooks" / "context_size_nudge.py"))
    assert nudge._routing_policy_path() == cfg / "routing.toml" and nudge._fable_lead_allowed() is True
    (cfg / "ade.toml").write_text("schema_version = 1\n[lead]\nfable_lead = false\n")
    assert nudge._routing_policy_path() == cfg / "ade.toml" and nudge._fable_lead_allowed() is False


@pytest.mark.parametrize("text", ["[lead]\nmodel = \"opus\"\n", "[lead]\nfable_lead = false\n",
                                  "[other]\nfable_lead = true\n", "not = [toml\n", None])
def test_fable_lead_absent_false_or_unreadable_keeps_the_relaunch_note(hook, tmp_path, monkeypatch, text):
    policy = tmp_path / "routing.toml"
    if text is not None:
        policy.write_text(text)
    monkeypatch.setenv("ROUTING_POLICY", str(policy))
    assert nudge._fable_lead_allowed() is False
    out, _ = hook("s-fable-nolead", _model_transcript(tmp_path, _FABLE, 46_000, nudge.BOUNDARY_TOTAL))
    assert _OPUS_NOTE in out


def test_other_models_get_no_relaunch_note(hook, tmp_path):
    out, _ = hook("s-opus", _model_transcript(tmp_path, "claude-opus-5-5", 46_000, nudge.BOUNDARY_TOTAL))
    assert "relaunch" not in out


def test_sidechain_and_synthetic_records_do_not_decide_the_model(tmp_path):
    path = tmp_path / "t.jsonl"
    rows = [
        {"message": {"model": "claude-opus-5-5", "role": "assistant"}},
        {"isSidechain": True, "message": {"model": "claude-fable-5-2", "role": "assistant"}},
        {"message": {"model": "<synthetic>", "role": "assistant"}},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert nudge._last_assistant_model(path) == "claude-opus-5-5"
    assert nudge._last_assistant_model(tmp_path / "missing.jsonl") is None


@pytest.mark.parametrize("model", ["claude-fable-5-2[1m]", "claude-fable-5-2", "claude-fable-5-1[1m]", "claude-fable-6"])
def test_l5_any_fable_id_with_or_without_a_suffix_is_detected(model):
    assert nudge._successor_target(model) == (nudge.SUCCESSOR_OPUS, "this session runs on Fable")
    assert nudge._successor_target("claude-opus-5-5[1m]") is None


@pytest.mark.parametrize("model", [None, "", "claude-haiku-4-5", "claude-haiku-4-5[1m]", "gpt-6", "claude-opus-5-5",
                                   "claude-sonnet-5-5"])
def test_r2_l4_no_successor_for_an_unknown_or_non_fable_model(model):
    assert nudge._successor_target(model) is None


def test_r2_l4_unreadable_model_gives_no_relaunch_note(hook, tmp_path):
    out, _ = hook("s-nomodel", _transcript(tmp_path, 46_000, nudge.BOUNDARY_TOTAL))  # no assistant model
    assert "relaunch" not in out


@pytest.mark.parametrize("text, want", [("[lead]\nfable_lead = true  # on\n", True), ("[lead]\nfable_lead = false\n", False),
                                        ("[other]\nfable_lead = true\n[lead]\nmodel = \"opus\"\n", False)])
def test_fable_lead_line_scan_without_tomllib(monkeypatch, tmp_path, text, want):
    """Under a Python older than 3.11 (no tomllib) the [lead] table is scanned by line, same answer."""
    policy = tmp_path / "routing.toml"
    policy.write_text(text)
    monkeypatch.setenv("ROUTING_POLICY", str(policy))
    monkeypatch.setitem(sys.modules, "tomllib", None)
    assert nudge._fable_lead_allowed() is want


# --- the real wall per session (2026-11-21): every tier scales with the model's and settings' window ---


def test_a_1m_model_without_a_window_has_its_tiers_near_967k(hook, tmp_path, settings_file):
    _write_settings(settings_file)  # no autoCompactWindow: the model's own 1M window
    path = _model_transcript(tmp_path, "claude-opus-5-5[1m]", 150_000, 400_000)
    out, pings = hook("s-1m", path)
    assert "At the next task completion" not in out and "Context is large" not in out
    assert pings == []  # 400k total, no paging below the hard tier
    _append(path, _model_transcript(tmp_path, "claude-opus-5-5[1m]", 886_999, name="y.jsonl").read_text())
    out, _ = hook("s-1m", path)
    assert "At the next task completion" not in out
    _append(path, _model_transcript(tmp_path, "claude-opus-5-5[1m]", 887_000, name="z.jsonl").read_text())
    out, _ = hook("s-1m", path)
    assert "At the next task completion" in out and "80,000 tokens left before Claude Code compacts this session at 967,000" in out
    assert "Context is large" not in out
    _append(path, _model_transcript(tmp_path, "claude-opus-5-5[1m]", 917_000, name="w.jsonl").read_text())
    out, pings = hook("s-1m", path)
    assert "Context is large" in out and "by itself at about 967,000 tokens" in out
    assert len(pings) == 1  # paging scales: first at the hard tier, not at 400k


def test_settings_model_with_1m_and_no_window_sets_the_wall_from_a_bare_transcript(hook, tmp_path, settings_file):
    _write_settings(settings_file, model="opus[1m]")
    out, _ = hook("s-1m-set", _transcript(tmp_path, 170_000, 230_000))  # a 267k wall would be hard (217k)
    assert not _is_ask(out) and "At the next task completion" not in out


def test_env_window_moves_the_tiers(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200000")  # wall 167k: boundary = hard = 117k
    out, _ = hook("s-env", _transcript(tmp_path, 100_000, 118_000))
    assert "Context is large" in out and "by itself at about 167,000 tokens" in out
    assert "At the next task completion" in out and "49,000 tokens left" in out


def test_a_larger_window_pushes_the_boundary_out(hook, tmp_path, settings_file):
    _write_settings(settings_file, autoCompactWindow=500_000)  # wall 467k: boundary 387k, hard 417k
    out, _ = hook("s-500", _transcript(tmp_path, 300_000, 386_999))
    assert "At the next task completion" not in out and not _is_ask(out)
    out, _ = hook("s-500b", _transcript(tmp_path, 300_000, 387_000, name="b.jsonl"))
    assert "At the next task completion" in out and "467,000" in out


def test_unreadable_settings_keep_todays_267k_behaviour(hook, tmp_path, settings_file):
    settings_file.write_text("{ not json")
    out, _ = hook("s-fallback", _transcript(tmp_path, 170_000, 186_999))
    assert out == ""
    out, _ = hook("s-fallback", _transcript(tmp_path, 170_000, 187_000, name="a.jsonl"))
    assert "At the next task completion" in out and "267,000" in out
    out, _ = hook("s-fallback2", _transcript(tmp_path, 170_000, nudge.ASK_TOTAL, name="b.jsonl"))
    assert "Context is large" in out and "by itself at about 267,000 tokens" in out


def test_settings_are_read_once_per_run(hook, tmp_path, monkeypatch):
    reads = []
    real = nudge.read_settings
    monkeypatch.setattr(nudge, "read_settings", lambda: reads.append(1) or real())
    hook("s-once-read", _transcript(tmp_path, 170_000, 190_000))
    assert len(reads) == 1


def test_messages_never_print_the_constant_when_the_wall_differs(hook, tmp_path, settings_file):
    _write_settings(settings_file, autoCompactWindow=250_000)  # wall 217k: hard = 167k
    out, _ = hook("s-217", _transcript(tmp_path, 100_000, 170_000))
    assert "by itself at about 217,000 tokens" in out and "267,000" not in out
    assert "About 47,000 tokens remain before Claude Code compacts this session at 217,000" in out
