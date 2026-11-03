"""Pi native seats are discoverable; RPC/JSON workers are not interactive seats."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "session-finder"))
import fleet  # noqa: E402


@pytest.mark.parametrize("flags", [[], ["--mode", "text"], ["--mode=text"], ["--", "--print"]])
def test_pi_interactive_seat_and_resume(flags):
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


def test_proc_scan_ignores_pi_rpc_worker(monkeypatch):
    line = "12345 1 Tue Nov 3 12:00:00 2026 node /tmp/pi --mode rpc"
    monkeypatch.setattr(fleet, "run", lambda *args, **kwargs: (0, line))
    assert fleet._proc_scan(set(), set(), {}) == []
