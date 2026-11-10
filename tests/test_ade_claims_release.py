"""ade_claims.release CLI (W2 follow-up / ade-claim workspace.archive.after)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    st = tmp_path / "state"
    monkeypatch.setenv("ADE_STATE_DIR", str(st))
    return st


def test_release_marks_active_claim_released(tmp_path, state):
    path = tmp_path / "wt"
    path.mkdir()
    c = ade_claims.make_claim(id="wt-rel-1", path=path, branch="cursor/x", base_sha="abcd")
    ade_claims.create_claim(c, pointer_for=None)
    out = ade_claims.set_state("wt-rel-1", "released")
    assert out is not None
    assert out["state"] == "released"
    assert out.get("released_at")
    reread = ade_claims.read_claim("wt-rel-1")
    assert reread is not None
    assert reread["state"] == "released"


def test_release_cli_active_and_idempotent(tmp_path, state):
    path = tmp_path / "wt-cli"
    path.mkdir()
    c = ade_claims.make_claim(id="wt-rel-cli", path=path, branch="b", base_sha="abcd")
    ade_claims.create_claim(c, pointer_for=None)
    env = {k: v for k, v in os.environ.items() if k != "ADE_STATE_DIR"}
    env["ADE_STATE_DIR"] = str(state)
    r1 = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "ade_claims.py"), "release", "--id", "wt-rel-cli"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r1.returncode == 0, r1.stderr
    assert r1.stdout.strip() == "wt-rel-cli"
    claim = ade_claims.read_claim("wt-rel-cli")
    assert claim is not None
    assert claim["state"] == "released"
    first_released_at = claim.get("released_at")

    r2 = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "ade_claims.py"), "release", "--id", "wt-rel-cli"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r2.returncode == 0, r2.stderr
    again = ade_claims.read_claim("wt-rel-cli")
    assert again is not None
    assert again["state"] == "released"
    assert again.get("released_at")  # stamped again; still released
    assert first_released_at  # was set on first release


def test_release_cli_missing_exits_2(tmp_path, state):
    env = {k: v for k, v in os.environ.items() if k != "ADE_STATE_DIR"}
    env["ADE_STATE_DIR"] = str(state)
    r = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "ade_claims.py"), "release", "--id", "missing"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 2
    assert "no claim" in r.stderr
