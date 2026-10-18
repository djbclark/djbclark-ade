#!/usr/bin/env python3
"""routing-recalibrate --dry-run with a fake calibrate JSON."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
_loader = importlib.machinery.SourceFileLoader(
    "routing_recalibrate", str(ROOT / "bin" / "routing-recalibrate"))
_spec = importlib.util.spec_from_loader("routing_recalibrate", _loader)
assert _spec is not None
rr = importlib.util.module_from_spec(_spec)
_loader.exec_module(rr)


FAKE = {
    "generated_at": "2026-10-18T12:00:00+00:00",
    "since_days": 30,
    "min_n": 5,
    "in_flight": 0,
    "groups": [],
    "suggestions": [{
        "service": "claude",
        "kind": "code",
        "n": 8,
        "done_rate": 20.0,
        "peer_median_done_rate": 80.0,
        "suggest_rank_delta": 5,
        "reason": "done_rate 20.0 is >25 points below peer median 80.0",
    }],
}


def test_dry_run_prints_brief_and_command(capsys, tmp_path):
    with mock.patch.object(rr, "run_calibrate", return_value=FAKE), \
         mock.patch.object(rr, "STATE", tmp_path), \
         mock.patch.object(rr, "stamp_date", return_value="2026-10-18"), \
         mock.patch.object(rr.subprocess, "run") as run:
        rc = rr.main(["--dry-run"])
    assert rc == 0
    run.assert_not_called()
    out = capsys.readouterr().out
    assert "Routing recalibrate 2026-10-18" in out
    assert "claude" in out and "code" in out
    assert "# dispatch:" in out
    assert "--kind judgment" in out
    assert "--detach" in out and "--no-wait" in out
    # dry-run must not write briefs (state dir mkdir alone is fine)
    assert not any(tmp_path.rglob("brief.md"))
    assert not any(tmp_path.rglob("calibrate.json"))


def test_no_suggestions_exits_zero(capsys, tmp_path):
    empty = dict(FAKE, suggestions=[])
    with mock.patch.object(rr, "run_calibrate", return_value=empty), \
         mock.patch.object(rr, "STATE", tmp_path):
        rc = rr.main([])
    assert rc == 0
    assert "no suggestions" in capsys.readouterr().out


def test_dispatch_failure_hermes_pings(tmp_path):
    ping = tmp_path / "hermes-ping"
    ping.write_text("#!/bin/sh\necho \"$1\" > \"$(dirname \"$0\")/ping.out\"\n")
    ping.chmod(0o755)
    with mock.patch.object(rr, "run_calibrate", return_value=FAKE), \
         mock.patch.object(rr, "STATE", tmp_path / "state"), \
         mock.patch.object(rr, "stamp_date", return_value="2026-10-18"), \
         mock.patch.object(rr, "HERMES_PING", ping), \
         mock.patch.object(rr.subprocess, "run") as run:
        # First subprocess.run is acp-dispatch (failure); second is hermes-ping.
        run.side_effect = [
            mock.Mock(returncode=7),
            mock.Mock(returncode=0),
        ]
        rc = rr.main([])
    assert rc == 7
    assert run.call_count == 2
    ping_cmd = run.call_args_list[1][0][0]
    assert ping_cmd[0] == str(ping)
    assert "dispatch failed" in ping_cmd[1]
    assert "rc=7" in ping_cmd[1]


def test_run_calibrate_uses_since_30():
    with mock.patch.object(rr.subprocess, "run") as run:
        run.return_value = mock.Mock(
            returncode=0, stdout='{"suggestions":[],"min_n":5}', stderr="")
        rr.run_calibrate()
    cmd = run.call_args[0][0]
    assert "--since" in cmd
    assert cmd[cmd.index("--since") + 1] == "30"
