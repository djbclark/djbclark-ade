"""ade_claims.rebind_owner + CLI (Q4, 2026-11-20: archived owner -> next agent created in the workspace)."""
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


def _claim(tmp_path, cid="wt-rb", owner="agent-old"):
    path = tmp_path / cid
    path.mkdir()
    c = ade_claims.make_claim(id=cid, path=path, branch="b", base_sha="abcd", owner_agent=owner,
                              owner_record=owner)
    ade_claims.create_claim(c)
    return cid


def test_rebind_swaps_exact_owner_and_records_history(tmp_path):
    cid = _claim(tmp_path)
    out = ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-new", owner_state="archived")
    assert out["owner"]["agent"] == "agent-new"
    assert out["owner"]["record"] == "agent-new"
    assert out["owner"].get("session") is None
    hist = ade_claims.read_claim(cid)["history"]
    assert any("agent-old" in h and "agent-new" in h and "(archived)" in h for h in hist)


def test_rebind_refuses_when_owner_changed_meanwhile(tmp_path):
    cid = _claim(tmp_path, owner="agent-live")
    with pytest.raises(ValueError, match="refusing rebind"):
        ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-new", owner_state="archived")
    assert ade_claims.read_claim(cid)["owner"]["agent"] == "agent-live"


def test_rebind_refuses_unowned_claim(tmp_path):
    cid = _claim(tmp_path, owner="")
    with pytest.raises(ValueError, match="refusing rebind"):
        ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-new", owner_state="archived")


def test_rebind_never_revives_released_or_missing(tmp_path):
    cid = _claim(tmp_path)
    ade_claims.set_state(cid, "released")
    with pytest.raises(ValueError, match="not active"):
        ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-new", owner_state="archived")
    assert ade_claims.read_claim(cid)["owner"]["agent"] == "agent-old"
    assert ade_claims.read_claim(cid)["state"] == "released"
    with pytest.raises(ValueError, match="no claim"):
        ade_claims.rebind_owner("missing", from_agent="a", to_agent="b", owner_state="gone")


def test_rebind_refuses_empty_or_same_ids(tmp_path):
    cid = _claim(tmp_path)
    with pytest.raises(ValueError):
        ade_claims.rebind_owner(cid, from_agent="", to_agent="agent-new", owner_state="gone")
    with pytest.raises(ValueError, match="same"):
        ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-old", owner_state="gone")


def test_rebind_owner_cli(tmp_path, state):
    cid = _claim(tmp_path)
    env = {**os.environ, "ADE_STATE_DIR": str(state)}
    cmd = [sys.executable, str(ROOT / "bin" / "ade_claims.py"), "rebind-owner", "--id", cid,
           "--from-agent", "agent-old", "--owner-agent", "agent-new",
           "--owner-state", "gone"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == cid
    assert ade_claims.read_claim(cid)["owner"]["agent"] == "agent-new"
    # second run: the claim no longer names agent-old, so it is refused and nothing changes
    r2 = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    assert r2.returncode == 2
    assert ade_claims.read_claim(cid)["owner"]["agent"] == "agent-new"


def test_rebind_refuses_harness_label_and_session_keyed_owners(tmp_path):
    """adversary H1: owner.agent may be a harness label with the real identity in owner.session."""
    for i, owner in enumerate([
        {"agent": "codex", "record": "codex", "session": "s1"},
        {"agent": "codex", "session": "s1"},
        {"agent": "codex"},
        {"agent": "agent-old", "record": "agent-old", "session": "s1"},
        {"agent": "agent-old", "record": "someone-else"},
    ]):
        path = tmp_path / f"wt-h{i}"
        path.mkdir()
        c = ade_claims.make_claim(id=f"wt-h{i}", path=path, branch="b", base_sha="abcd")
        c["owner"] = {**c.get("owner", {}), **owner}
        ade_claims.create_claim(c)
        before = ade_claims.read_claim(f"wt-h{i}")["owner"]
        frm = owner["agent"]
        with pytest.raises(ValueError, match="refusing rebind"):
            ade_claims.rebind_owner(f"wt-h{i}", from_agent=frm, to_agent="agent-new", owner_state="gone")
        assert ade_claims.read_claim(f"wt-h{i}")["owner"] == before


def test_rebind_requires_a_proven_owner_state(tmp_path):
    cid = _claim(tmp_path)
    with pytest.raises(ValueError, match="owner-state"):
        ade_claims.rebind_owner(cid, from_agent="agent-old", to_agent="agent-new", owner_state="live")
