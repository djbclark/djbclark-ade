"""bin/ade-claim-pilot --fixture: S4 cases 1–2 under a private ADE_STATE_DIR."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "bin" / "ade-claim-pilot"


def test_fixture_cases_1_and_2_pass():
    r = subprocess.run(
        [sys.executable, str(PILOT), "--fixture", "--cases", "1,2", "--json"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["ok"] is True
    assert report["hard_refuse"] is False
    assert report["path_shim"] is False
    by = {row["case"]: row for row in report["results"]}
    assert by[1]["status"] == "pass"
    assert by[2]["status"] == "pass"


def test_live_only_cases_are_skipped_in_fixture_mode():
    r = subprocess.run(
        [sys.executable, str(PILOT), "--fixture", "--cases", "3,6", "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert all(row["status"] == "skipped_fixture" for row in report["results"])


def test_list_prints_six_cases():
    r = subprocess.run(
        [sys.executable, str(PILOT), "--list"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert r.returncode == 0
    for n in range(1, 7):
        assert f"{n}." in r.stdout
