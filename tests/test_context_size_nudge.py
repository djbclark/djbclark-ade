"""Persistent context-nudge telemetry and prompt/tool event contracts."""
import builtins
import importlib.util
import io
import json
import os
import subprocess
import sys
import threading
import time
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
            stream.write(json.dumps({"type": "system", "subtype": "compact_boundary"}) + "\n"
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
    (300_000, ["ask", "midtask", "boundary"], 3), (400_000, ["ask", "midtask", "boundary"], 4),
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


@pytest.mark.parametrize("self_slash", [False, True])
def test_posttooluse_json_matches_plain_prompt_messages(box, monkeypatch, self_slash):
    monkeypatch.setattr(box.hook, "_can_self_slash", lambda: self_slash)
    plain = box(300_000, sid="prompt")
    output = box(300_000, event="PostToolUse", sid="tool")
    prompt_sentence = "this reminder runs only when a prompt is submitted, not between tool rounds."
    tool_sentence = "this reminder also runs between tool rounds (at most every 20 s)."
    assert prompt_sentence in plain
    assert json.loads(output) == {"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": plain.rstrip("\n").replace(
            prompt_sentence, tool_sentence)}}
    assert plain.startswith("Context is large:")
    assert [r["event"] for r in box.records()] == ["UserPromptSubmit"] * 3 + ["PostToolUse"] * 3


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


@pytest.mark.parametrize("noise,count,expected", [
    ('{"type":"tool_result"}\n', 30_000, 90_000),
    ('{"type":"tool_result"}\n', 150_000, None),
    ('{"cache_read_input_tokens":0}\n', 10_000, None),
    ('{"type":"tool_use","subtype":"compact_boundary"}\n', 10_000, None),
])
def test_posttooluse_tail_cost_bound(box, tmp_path, monkeypatch, capsys, noise, count, expected):
    """Bound candidate validation, even with a tail full of false needle hits.

    Exercise the actual tool-event path. No timing assertion: count validations
    deterministically, including a widened window and a usage beyond the byte cap.
    """
    transcript = tmp_path / "noisy.jsonl"
    transcript.write_text(json.dumps({"message": {"usage": {
        "cache_read_input_tokens": 90_000}}}) + "\n" + noise * count)
    validations, measurements = [], []
    real_usage = box.hook._usage_from_line
    real_tail = box.hook._last_context_tokens

    def usage(line):
        validations.append(line)
        return real_usage(line)

    def tail(path):
        value = real_tail(path)
        measurements.append(value)
        return value

    monkeypatch.setattr(box.hook, "_usage_from_line", usage)
    monkeypatch.setattr(box.hook, "_last_context_tokens", tail)
    monkeypatch.setattr(box.hook, "_first_context_tokens", lambda _: 50_000)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "noisy", "hook_event_name": "PostToolUse",
        "transcript_path": str(transcript),
    })))
    box.hook.main()
    capsys.readouterr()
    assert measurements == [expected]
    assert len(validations) <= box.hook._TAIL_REJECT_LIMIT
    if "tool_result" in noise:
        assert len(validations) == (1 if expected else 0)
    else:
        assert len(validations) == box.hook._TAIL_REJECT_LIMIT
    assert json.loads(box.hook.STATE_PATH.read_text())["noisy"]["last_check"] == box.clock[0]


@pytest.mark.parametrize("padding", [200_000, 131_000])
@pytest.mark.parametrize("count", range(41))
def test_newest_usage_straddles_tail_boundary(box, tmp_path, padding, count):
    older = json.dumps({"message": {"usage": {"cache_read_input_tokens": 50_000}}}) + "\n"
    newest = json.dumps({"padding": "x" * padding,
                         "message": {"usage": {"cache_read_input_tokens": 222_000}}}) + "\n"
    noise = json.dumps({"isSidechain": True, "message": {"usage": {
        "cache_read_input_tokens": 1}}}) + "\n"
    data = (older + newest + noise * count).encode()
    boundary = len(data) - 128 * 1024
    # The first window skips this partial record, including its usage needle.
    assert len(older) < boundary < len(older) + len(newest)
    assert data.index(b"cache_read_input_tokens", boundary) < len(older) + len(newest)
    transcript = tmp_path / "straddling.jsonl"
    transcript.write_bytes(data)
    assert box.hook._last_context_tokens(transcript) == 222_000


@pytest.mark.parametrize("count", [32, 40])
def test_widened_tail_does_not_recount_first_window(box, tmp_path, monkeypatch, count):
    # P1: the newest main usage is just outside 128 KiB, with <64 false hits.
    transcript = tmp_path / "widened.jsonl"
    noise = json.dumps({"isSidechain": True, "message": {"usage": {
        "cache_read_input_tokens": 1}}}) + "\n"
    padding = json.dumps({"type": "tool_result", "padding": "x" * 132_000}) + "\n"
    transcript.write_text(json.dumps({"message": {"usage": {
        "cache_read_input_tokens": 123_000}}}) + "\n" + padding + noise * count)
    calls = []
    real_usage = box.hook._usage_from_line
    monkeypatch.setattr(box.hook, "_usage_from_line", lambda line: calls.append(line) or real_usage(line))
    assert box.hook._last_context_tokens(transcript) == 123_000
    assert len(calls) == count + 1 <= 64


@pytest.mark.parametrize("event", ["Stop", "PreToolUse", None, 7, False, [], {}])
def test_unrelated_and_nonstring_events_stay_silent(box, event):
    assert box(400_000, event=event) == ""
    assert not box.hook.STATE_PATH.exists()
    assert not box.hook.LOG_PATH.exists()


def test_new_log_is_private(box):
    previous = os.umask(0)
    try:
        box()
    finally:
        os.umask(previous)
    assert box.hook.LOG_PATH.stat().st_mode & 0o777 == 0o600


def test_missing_usage_does_not_advance_size(box, monkeypatch):
    box(60_000)
    before = json.loads(box.hook.STATE_PATH.read_text())["session-1"]
    observed = []
    real_load = box.hook._load_state

    def loaded():
        state = real_load()
        observed.append(state)
        return state

    monkeypatch.setattr(box.hook, "_load_state", loaded)
    monkeypatch.setattr(box.hook, "_last_context_tokens", lambda _: None)
    assert box(400_000, event="PostToolUse") == ""
    # Inspect the in-memory object too: a later save would persist a bad size.
    assert observed[0]["session-1"]["size"] == before["size"]
    after = json.loads(box.hook.STATE_PATH.read_text())["session-1"]
    assert after["size"] == before["size"] and after["level"] == before["level"]


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform has no O_NOFOLLOW")
def test_log_does_not_follow_symlink(box, tmp_path):
    target = tmp_path / "target"
    target.write_text("untouched\n")
    box.hook.LOG_PATH.symlink_to(target)
    assert box()
    assert target.read_text() == "untouched\n"


def test_relative_log_override_uses_default(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("\n".join(json.dumps({"message": {"usage": {
        "cache_read_input_tokens": n}}}) for n in (50_000, 90_000)))
    result = subprocess.run([sys.executable, str(HOOK)], text=True, capture_output=True,
                            timeout=5, cwd=tmp_path,
                            input=json.dumps({"session_id": "relative", "transcript_path": str(transcript)}),
                            env={**os.environ, "HOME": str(tmp_path),
                                 "CONTEXT_NUDGE_LOG_PATH": "relative.jsonl"})
    assert result.returncode == 0 and result.stdout and result.stderr == ""
    assert not (tmp_path / "relative.jsonl").exists()
    assert (tmp_path / ".claude/state/context-nudge-log.jsonl").exists()


def test_interleaved_runs_preserve_other_session_flags(box, monkeypatch):
    """A stale B snapshot must not undo A's hard tier, boundary or page."""
    a_loaded, b_loaded, release_a, a_done = (threading.Event() for _ in range(4))
    real_load = box.hook._load_state
    failures = []

    def loaded():
        state = real_load()
        if threading.current_thread().name == "writer-a":
            a_loaded.set()
            assert release_a.wait(1)
        else:
            b_loaded.set()
            assert a_done.wait(1)
        return state

    class Input:
        def read(self):
            return json.dumps({"session_id": threading.current_thread().name,
                               "transcript_path": "unused"})

    monkeypatch.setattr(sys, "stdin", Input())
    monkeypatch.setattr(box.hook, "_load_state", loaded)
    monkeypatch.setattr(box.hook, "_file_size", lambda _: 100)
    monkeypatch.setattr(box.hook, "_first_context_tokens", lambda _: 50_000)
    monkeypatch.setattr(box.hook, "_compaction_floor_since", lambda *args: None)
    monkeypatch.setattr(box.hook, "_last_context_tokens", lambda _: (
        400_000 if threading.current_thread().name == "writer-a" else 90_000))

    def run():
        try:
            box.hook.main()
        except BaseException as exc:
            failures.append(exc)
        finally:
            if threading.current_thread().name == "writer-a":
                a_done.set()

    a = threading.Thread(target=run, name="writer-a")
    b = threading.Thread(target=run, name="writer-b")
    a.start()
    try:
        assert a_loaded.wait(1)
        b.start()
        # With the lock B cannot load until A saves; without it B loads stale.
        b_loaded.wait(0.05)
    finally:
        release_a.set()
        a.join(2)
        if b.ident is not None:
            b.join(2)
    assert not a.is_alive() and not b.is_alive() and not failures
    state = json.loads(box.hook.STATE_PATH.read_text())
    assert state["writer-a"]["level"] == 4
    assert state["writer-a"]["boundary"] is True
    assert state["writer-a"]["paged"] is True
    assert state["writer-b"]["level"] == 1


def test_concurrent_state_writers_never_share_temporary_file(box, monkeypatch):
    """Both files are opened before long then short writes, exposing O_TRUNC races."""
    opened = threading.Barrier(2)
    long_written = threading.Event()
    real_open = io.open
    failures = []

    class Writer:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, data):
            opened.wait(timeout=2)
            if threading.current_thread().name == "short":
                assert long_written.wait(2)
            result = self.stream.write(data)
            self.stream.flush()
            if threading.current_thread().name == "long":
                long_written.set()
            return result

    def intercepted(file, mode="r", *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        return Writer(stream) if mode == "w" else stream

    monkeypatch.setattr(io, "open", intercepted)

    def save(value):
        try:
            box.hook._save_state(value)
        except BaseException as exc:
            failures.append(exc)

    long_state, short_state = {"long": "x" * 1000}, {"short": True}
    threads = [threading.Thread(target=save, args=(value,), name=name)
               for name, value in (("long", long_state), ("short", short_state))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
    assert not any(thread.is_alive() for thread in threads) and not failures
    assert json.loads(box.hook.STATE_PATH.read_text()) in (long_state, short_state)


@pytest.mark.skipif(not getattr(os, "O_NOFOLLOW", 0), reason="O_NOFOLLOW unavailable")
@pytest.mark.parametrize("target_exists", [False, True])
def test_state_lock_does_not_follow_symlink(box, tmp_path, target_exists):
    target = tmp_path / "lock-target"
    if target_exists:
        target.write_bytes(b"untouched")
    box.hook.STATE_PATH.with_suffix(".lock").symlink_to(target)
    assert box(90_000)  # rejected lock still permits a nudge and an atomic save
    assert json.loads(box.hook.STATE_PATH.read_text())["session-1"]["level"] == 1
    if target_exists:
        assert target.read_bytes() == b"untouched"
    else:
        assert not target.exists()


def test_state_temp_sweep_runs_under_lock(box, tmp_path, monkeypatch):
    if box.hook.fcntl is None:
        pytest.skip("flock unavailable")
    monkeypatch.setattr(box.hook, "STATE_PATH", tmp_path / "context-nudges.json")
    old = tmp_path / "context-nudges.json.old.tmp"
    fresh = tmp_path / "context-nudges.json.fresh.tmp"
    threshold = tmp_path / "context-nudges.json.threshold.tmp"
    unrelated = tmp_path / "other.json.old.tmp"
    directory = tmp_path / "context-nudges.json.directory.tmp"
    link = tmp_path / "context-nudges.json.link.tmp"
    for path in (old, fresh, threshold, unrelated):
        path.write_bytes(b"keep unless orphaned")
        age = 86_401 if path != fresh else 60
        if path == threshold:
            age = 86_400
        os.utime(path, (box.clock[0] - age, box.clock[0] - age))
    directory.mkdir()
    link.symlink_to(unrelated)
    real_sweep = box.hook._sweep_state_temps
    calls = []

    def sweep():
        # An independently opened fd cannot acquire the flock during cleanup.
        with box.hook.STATE_PATH.with_suffix(".lock").open("rb") as stream:
            with pytest.raises(BlockingIOError):
                box.hook.fcntl.flock(stream.fileno(), box.hook.fcntl.LOCK_EX | box.hook.fcntl.LOCK_NB)
        calls.append(True)
        real_sweep()

    monkeypatch.setattr(box.hook, "_sweep_state_temps", sweep)
    with box.hook._state_lock():
        assert not old.exists()
    assert calls == [True]
    assert all(path.exists() for path in (fresh, threshold, unrelated, directory))
    assert link.is_symlink()


def test_state_temp_sweep_is_bounded(box, monkeypatch):
    inspected = []

    class Entries:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            for index in range(200):
                inspected.append(index)
                yield type("Entry", (), {"name": "unrelated"})()

    monkeypatch.setattr(os, "scandir", lambda _: Entries())
    with box.hook._state_lock():
        pass
    assert len(inspected) == 128


def test_state_temp_sweep_failure_is_ignored(box, tmp_path, monkeypatch):
    old = tmp_path / "state.json.old.tmp"
    old.write_bytes(b"orphan")
    os.utime(old, (box.clock[0] - 86_401, box.clock[0] - 86_401))
    real_unlink = os.unlink
    attempts = []

    def unlink(path, *args, **kwargs):
        if Path(path) == old:
            attempts.append(path)
            raise PermissionError("cannot remove orphan")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    assert box(90_000)
    assert attempts and old.read_bytes() == b"orphan"
    assert json.loads(box.hook.STATE_PATH.read_text())["session-1"]["level"] == 1


def test_failed_state_replace_unlinks_temporary_file(box, tmp_path, monkeypatch):
    box.hook.STATE_PATH.write_text('{"previous": true}')
    attempts = []

    def replace(source, target):
        attempts.append(Path(source))
        assert Path(source).is_file()
        assert Path(target) == box.hook.STATE_PATH
        raise OSError("simulated failed replace")

    monkeypatch.setattr(os, "replace", replace)
    box.hook._save_state({"new": True})
    assert len(attempts) == 1
    assert not attempts[0].exists()
    assert not list(tmp_path.glob("state.json.*.tmp"))
    assert json.loads(box.hook.STATE_PATH.read_text()) == {"previous": True}


def test_lock_contention_is_nonblocking_and_bounded(box, monkeypatch):
    clock, flags = [0.0], []

    class BusyLock:
        LOCK_EX, LOCK_NB = 2, 4

        @staticmethod
        def flock(fd, operation):
            flags.append(operation)
            assert operation & BusyLock.LOCK_NB
            assert len(flags) <= 22  # also makes a missing timeout fail deterministically
            raise BlockingIOError()

    monkeypatch.setattr(box.hook, "fcntl", BusyLock, raising=False)
    monkeypatch.setattr(box.hook, "_sweep_state_temps", lambda: pytest.fail("sweep without lock"))
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    assert box(90_000)
    assert flags
    assert 0.19 <= clock[0] <= 0.21
    assert json.loads(box.hook.STATE_PATH.read_text())["session-1"]["level"] == 1


def test_missing_fcntl_still_emits_and_saves(box, monkeypatch):
    monkeypatch.setattr(box.hook, "fcntl", None, raising=False)
    assert box(90_000)
    assert json.loads(box.hook.STATE_PATH.read_text())["session-1"]["level"] == 1


def test_hook_imports_without_fcntl(monkeypatch):
    real_import = builtins.__import__

    def without_fcntl(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("simulated non-POSIX")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_fcntl)
    spec = importlib.util.spec_from_file_location("nudge_no_fcntl", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.fcntl is None
