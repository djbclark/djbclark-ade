"""ade_claims.bind_owner + CLI (W3 / ade-claim plugin)."""
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


def test_bind_owner_merges_agent_and_record(tmp_path, state):
    path = tmp_path / "wt"
    path.mkdir()
    c = ade_claims.make_claim(
        id="wt-bind-1", path=path, branch="cursor/x", base_sha="abcd",
        owner_agent="", owner_record=None,
    )
    ade_claims.create_claim(c, pointer_for=None)
    out = ade_claims.bind_owner("wt-bind-1", owner_agent="agent-9", owner_record="agent-9")
    assert out["owner"]["agent"] == "agent-9"
    assert out["owner"]["record"] == "agent-9"
    reread = ade_claims.read_claim("wt-bind-1")
    assert reread is not None
    assert reread["owner"]["agent"] == "agent-9"


def test_bind_owner_refuses_missing_and_released(tmp_path, state):
    with pytest.raises(ValueError, match="no claim"):
        ade_claims.bind_owner("missing", owner_agent="a")
    path = tmp_path / "wt2"
    path.mkdir()
    c = ade_claims.make_claim(id="wt-rel", path=path, branch="b", base_sha="abcd")
    ade_claims.create_claim(c)
    ade_claims.set_state("wt-rel", "released")
    with pytest.raises(ValueError, match="not active"):
        ade_claims.bind_owner("wt-rel", owner_agent="a")


def test_bind_owner_refuses_foreign_overwrite(tmp_path, state):
    path = tmp_path / "wt-foreign"
    path.mkdir()
    c = ade_claims.make_claim(
        id="wt-own", path=path, branch="b", base_sha="abcd", owner_agent="agent-a",
    )
    ade_claims.create_claim(c)
    with pytest.raises(ValueError, match="already owned"):
        ade_claims.bind_owner("wt-own", owner_agent="agent-b")
    # Same owner may re-bind (idempotent).
    out = ade_claims.bind_owner("wt-own", owner_agent="agent-a", owner_record="agent-a")
    assert out["owner"]["agent"] == "agent-a"
    assert out["owner"]["record"] == "agent-a"


def test_bind_owner_cli(tmp_path, state):
    path = tmp_path / "wt3"
    path.mkdir()
    c = ade_claims.make_claim(id="wt-cli", path=path, branch="b", base_sha="abcd")
    ade_claims.create_claim(c)
    env = {k: v for k, v in os.environ.items() if k != "ADE_STATE_DIR"}
    env["ADE_STATE_DIR"] = str(state)
    r = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "ade_claims.py"),
         "bind-owner", "--id", "wt-cli", "--owner-agent", "agent-cli",
         "--owner-record", "agent-cli"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "wt-cli"
    claim = ade_claims.read_claim("wt-cli")
    assert claim is not None
    assert claim["owner"]["agent"] == "agent-cli"
    assert claim["owner"]["record"] == "agent-cli"
