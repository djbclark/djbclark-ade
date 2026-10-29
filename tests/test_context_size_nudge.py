"""Persistent context-nudge telemetry and prompt/tool event contracts."""
import importlib.util
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "claude/hooks/context_size_nudge.py"


@pytest.fixture
def box(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("nudge_under_test", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    monkeypatch.setattr(hook, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(hook, "LOG_PATH", tmp_path / "log.jsonl", raising=False)
    monkeypatch.setattr(hook, "_session_successor", lambda _: None)
    monkeypatch.setattr(hook, "_can_self_slash", lambda: False)
    monkeypatch.setattr(hook, "_self_slash_host", lambda: None)
    monkeypatch.setattr(hook, "_send_ping", lambda *args: None)
    clock = [1_800_000_000.0]
    # Patching time.time works before the implementation imports time, too.
    monkeypatch.setattr("time.time", lambda: clock[0])
    transcript = tmp_path / "transcript.jsonl"

    def usage(total):
        return json.dumps({"message": {"usage": {"input_tokens": total,
                           "cache_read_input_tokens": 0}}}) + "\n"

    def run(total=90_000, event="UserPromptSubmit", sid="session-1", compact=False):
        if not transcript.exists():
            transcript.write_text(usage(50_000))
        with transcript.open("a") as stream:
            stream.write(json.dumps({"subtype": "compact_boundary"}) + "\n"
                         if compact else usage(total))
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
            "session_id": sid, "hook_event_name": event,
            "transcript_path": str(transcript),
        })))
        hook.main()
        return capsys.readouterr().out

    run.hook = hook
    run.clock = clock
    run.records = lambda: [json.loads(line) for line in hook.LOG_PATH.read_text().splitlines()]
    return run


@pytest.mark.parametrize("total,kinds,level", [
    (90_000, ["early"], 1), (125_000, ["early", "boundary"], 1),
    (300_000, ["ask", "boundary"], 2), (400_000, ["ask", "boundary"], 3),
    (120_000, ["boundary"], 0),
])
def test_emitted_nudges_are_logged(box, total, kinds, level):
    # Boundary-only case: seed its floor high enough to avoid early growth.
    if total == 120_000:
        box.hook.STATE_PATH.write_text(json.dumps({"session-1": {"baseline": 110_000}}))
    assert box(total)
    records = box.records()
    assert [r["kind"] for r in records] == kinds
    for record in records:
        assert set(record) == {"ts", "session_id", "event", "level", "total", "growth", "kind"}
        assert record["session_id"] == "session-1"
        assert record["event"] == "UserPromptSubmit"
        assert record["level"] == level
        assert record["total"] == total
        assert record["growth"] == total - (110_000 if total == 120_000 else 50_000)
        assert datetime.fromisoformat(record["ts"].replace("Z", "+00:00")).utcoffset().total_seconds() == 0


def test_quiet_and_repeated_checks_do_not_log(box):
    assert box(60_000) == ""
    assert not box.hook.LOG_PATH.exists()
    box(90_000)
    before = box.hook.LOG_PATH.read_bytes()
    assert box(91_000) == ""
    assert box.hook.LOG_PATH.read_bytes() == before


def test_log_survives_compaction_and_records_regrowth(box):
    box(90_000)
    original = box.hook.LOG_PATH.read_bytes()
    assert box(compact=True) == ""
    assert box.hook.LOG_PATH.read_bytes() == original
    box(50_000)
    box(90_000)
    assert [r["kind"] for r in box.records()] == ["early", "early"]
    assert box.hook.LOG_PATH.read_bytes().startswith(original)


def test_log_rotates_to_one_backup(box):
    old = b"x" * (2 * 1024 * 1024)
    box.hook.LOG_PATH.write_bytes(old)
    backup = Path(str(box.hook.LOG_PATH) + ".1")
    backup.write_text("previous backup")
    box()
    assert backup.read_bytes() == old
    assert len(box.records()) == 1


def test_append_is_one_os_write_with_append_flag(box, monkeypatch):
    writes, flags = [], []
    real_open, real_write = os.open, os.write

    def opened(path, mode, *args, **kwargs):
        if Path(path) == box.hook.LOG_PATH:
            flags.append(mode)
        return real_open(path, mode, *args, **kwargs)

    def written(fd, data):
        writes.append(data)
        return real_write(fd, data)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "write", written)
    box()
    assert len(writes) == 1 and writes[0].endswith(b"\n")
    assert len(writes[0].splitlines()) == 1
    assert flags and flags[0] & os.O_APPEND


def test_posttooluse_json_matches_plain_prompt_messages(box):
    plain = box(300_000, sid="prompt")
    output = box(300_000, event="PostToolUse", sid="tool")
    assert json.loads(output) == {"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": plain.rstrip("\n")}}
    assert plain.startswith("Context is large:")
    assert [r["event"] for r in box.records()] == ["UserPromptSubmit"] * 2 + ["PostToolUse"] * 2


def test_posttooluse_rate_limit_skips_tail_and_is_session_scoped(box, monkeypatch):
    box(60_000, event="PostToolUse")
    real_tail = box.hook._last_context_tokens
    calls = []
    monkeypatch.setattr(box.hook, "_last_context_tokens", lambda path: calls.append(path) or real_tail(path))
    box.clock[0] += 19
    assert box(90_000, event="PostToolUse") == ""
    assert calls == []
    assert box(90_000, event="PostToolUse", sid="another")
    box.clock[0] += 1
    assert box(90_000, event="PostToolUse")
    assert len(calls) == 2
    box.clock[0] += 20
    assert box(91_000, event="PostToolUse") == ""
    assert len(calls) == 3
    state = json.loads(box.hook.STATE_PATH.read_text())
    assert state["session-1"]["last_check"] == box.clock[0]


def test_prompt_checks_are_not_throttled_by_tool_checks(box):
    box(60_000, event="PostToolUse")
    assert box(90_000).startswith("Context check:")


def test_wall_clock_rollback_does_not_suppress_tool_check(box):
    box(60_000, event="PostToolUse")
    box.clock[0] -= 100
    assert box(90_000, event="PostToolUse")


def test_missing_usage_still_rate_limits_tool_checks(box, monkeypatch):
    calls = []
    monkeypatch.setattr(box.hook, "_last_context_tokens", lambda _: calls.append(1))
    assert box(event="PostToolUse") == ""
    assert box(event="PostToolUse") == ""
    assert calls == [1]


@pytest.mark.parametrize("event", ["UserPromptSubmit", "PostToolUse"])
def test_log_failure_preserves_subprocess_stdout_and_exit(tmp_path, event):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join(json.dumps({"message": {"usage": {
        "cache_read_input_tokens": n}}}) for n in (50_000, 90_000)))
    payload = json.dumps({"session_id": "log-failure", "hook_event_name": event,
                          "transcript_path": str(transcript)})
    outputs = []
    for name, logpath in (("good", tmp_path / "log.jsonl"), ("bad", tmp_path)):
        home = tmp_path / name
        home.mkdir()
        result = subprocess.run([sys.executable, str(HOOK)], input=payload, text=True,
                                capture_output=True, timeout=5,
                                env={**os.environ, "HOME": str(home),
                                     "CONTEXT_NUDGE_LOG_PATH": str(logpath)})
        assert result.returncode == 0 and result.stderr == ""
        outputs.append(result.stdout)
    assert outputs[0] and outputs[0] == outputs[1]
    assert (tmp_path / "log.jsonl").exists()


def test_invalid_json_exits_zero(tmp_path):
    result = subprocess.run([sys.executable, str(HOOK)], input="{", text=True,
                            capture_output=True, timeout=5, env={**os.environ, "HOME": str(tmp_path)})
    assert result.returncode == 0 and result.stdout == result.stderr == ""
