"""Pi native seats are discoverable; RPC/JSON workers are not interactive seats."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "session-finder"))
import fleet  # noqa: E402
from nativeid import native_id  # noqa: E402


@pytest.mark.parametrize("flags", [[], ["--mode", "text"], ["--mode=text"], ["--", "--print"]])
def test_pi_interactive_seat_and_resume(flags, monkeypatch):
    monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: "/dev/pts/4")
    argv = ["node", "/tmp/pi", *flags]
    record = {"argv": argv, "argv0": "node", "pid": 12345}
    assert fleet._tui_of([record])[:2] == ("pi", 12345)
    assert fleet.RESUME_FORMS["pi"].format(flags="", sid="test-session") == "pi --session test-session"


@pytest.mark.parametrize("flags", [["--mode", "rpc"], ["--mode=json"], ["--print"],
                                  ["-p"], ["--help"], ["--list-models"], ["--mode"]])
def test_pi_headless_is_not_a_seat(flags):
    argv = ["node", "/tmp/pi", *flags]
    record = {"argv": argv, "argv0": "node", "pid": 12345}
    assert fleet._tui_of([record]) == (None, None, None, None)


@pytest.mark.parametrize("sid,expected", [
    ("custom_session_id", "custom_session_id"),
    ("/tmp/pi/timestamp_custom_session_id.jsonl", "custom_session_id"),
    ("/tmp/omp/timestamp_native-id.jsonl", "native-id"),
    ("/tmp/native-id.jsonl", "native-id"),
])
def test_native_transcript_ids_preserve_underscores(sid, expected):
    assert native_id(sid) == expected


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("stdin,stdout,ps,expected", [
    ("/dev/pts/4", "/dev/pts/4", "123 123 pts/4", "/dev/pts/4"),
    ("pipe:[1]", "/dev/pts/4", "123 123 pts/4", ""),
    ("/dev/pts/4", "pipe:[1]", "123 123 pts/4", ""),
    ("pipe:[1]", "pipe:[2]", "123 123 pts/4", ""),
    ("/dev/null", "/dev/pts/4", "123 123 pts/4", ""),
    ("/dev/pts/4", "/dev/pts/5", "123 123 pts/4", ""),
    ("/dev/pts/4", "/dev/pts/4", "123 999 pts/4", ""),
    ("/dev/pts/4", "/dev/pts/4", "123 -1 ?", ""),
    ("/dev/pts/4", "/dev/pts/4", "", ""),
])
def test_pi_terminal_proof(monkeypatch, platform, stdin, stdout, ps, expected):
    monkeypatch.setattr(fleet.sys, "platform", platform)
    monkeypatch.setattr(fleet.os, "readlink", lambda path: stdin if path.endswith("/0") else stdout)
    monkeypatch.setattr(fleet, "run", lambda *a, **kw: (0, ps if a[0] == "ps" else f"f0\nn{stdin}\nf1\nn{stdout}\n"))
    assert fleet._pi_terminal(123) == expected


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_pi_unreadable_terminal_fails_closed(monkeypatch, platform):
    monkeypatch.setattr(fleet.sys, "platform", platform)
    def denied(path):
        raise PermissionError(path)
    monkeypatch.setattr(fleet.os, "readlink", denied)
    monkeypatch.setattr(fleet, "run", lambda *a, **kw: (0, "123 123 pts/4") if a[0] == "ps" else (1, ""))
    assert fleet._pi_terminal(123) == ""


@pytest.mark.parametrize("terminal,pane_tty,count", [
    ("", "/dev/pts/4", 0),  # pipes, even though TMUX_PANE is inherited
    ("/dev/pts/5", "/dev/pts/4", 0),  # interactive nested PTY, not the parent's pane
    ("/dev/pts/4", "/dev/pts/4", 1),
    ("/dev/pts/4", "", 0),
])
def test_pi_inherited_tmux_needs_its_own_terminal(monkeypatch, terminal, pane_tty, count):
    from types import SimpleNamespace
    line = "12345 1 Tue Nov 3 12:00:00 2026 node /tmp/pi --session-id daily_work"
    monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: terminal)
    monkeypatch.setattr(fleet, "run", lambda *a, **kw: (0, pane_tty if a[0] == "tmux" else line))
    monkeypatch.setattr(fleet, "_where", SimpleNamespace(
        env_of=lambda pid: {"TMUX_PANE": "%1", "PI_SESSION_ID": "parent-id"},
        lookup=lambda *args: {"cwd": "/project"}))
    rows = fleet._proc_scan(set(), set(), {})
    assert len(rows) == count
    if rows:
        assert rows[0]["sid"] == "daily_work"
        assert rows[0]["chan"] == ("tmux", "%1")


def test_pipe_pi_not_pane_seat_but_still_ancestry_boundary(monkeypatch):
    monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: "")
    record = {"argv": ["pi", "prompt"], "argv0": "pi", "pid": 12345}
    assert fleet._tui_of([record]) == (None, None, None, None)
    assert fleet.PROC_AGENTS["pi"] == "pi"
    # The new proof must not suppress another family's seats.
    record.update(argv=["codex"], argv0="codex")
    assert fleet._tui_of([record])[0] == "codex"


@pytest.mark.parametrize("sid", ["x", "daily_work", "/custom root/timestamp_daily_work.jsonl"])
def test_pi_native_id_is_not_truncated(monkeypatch, sid):
    monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: "/dev/pts/4")
    for flag in ("--session",) if "/" in sid else ("--session", "--session-id"):
        argv = ["pi", flag, sid]
        assert fleet._tui_of([{"argv": argv, "argv0": "pi", "pid": 12345}])[2] == sid


def test_proc_scan_ignores_pi_rpc_worker(monkeypatch):
    line = "12345 1 Tue Nov 3 12:00:00 2026 node /tmp/pi --mode rpc"
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (0, line))
    assert fleet._proc_scan(set(), set(), {}) == []


@pytest.mark.parametrize("argv", [["vim", "pi"], ["less", "/tmp/pi"], ["node", "/tmp/other", "pi"]])
def test_program_with_pi_argument_is_not_a_seat(monkeypatch, argv):
    monkeypatch.setattr(fleet, "_pi_terminal", lambda pid: "/dev/pts/4")
    assert fleet._tui_of([{"argv": argv, "argv0": argv[0], "pid": 12345}])[0] is None
    line = "12345 1 Tue Nov 3 12:00:00 2026 " + " ".join(argv)
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (0, line))
    assert fleet._proc_scan(set(), set(), {}) == []
