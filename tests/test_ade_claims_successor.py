"""ade_claims.rebind_successor + `successor-of` CLI (cl-succ): a self-handoff successor inherits the claims."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402

PRED = "11111111-1111-4111-8111-111111111111"
SUCC = "22222222-2222-4222-8222-222222222222"
THIRD = "33333333-3333-4333-8333-333333333333"
TOKEN = "44444444-4444-4444-8444-444444444444"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "ss").mkdir()
    return tmp_path / "ss"


def record(ss: Path, **over) -> Path:
    rec = {"kind": "handoff", "token": TOKEN, "predecessor": PRED, "successor": SUCC, "status": "acknowledged"}
    rec.update(over)
    p = ss / f"handoff-{TOKEN}.json"
    p.write_text(json.dumps(rec))
    return p


def claim(tmp_path, cid="c1", owner=PRED, **kw):
    p = tmp_path / f"wt-{cid}"
    p.mkdir()
    ade_claims.create_claim(ade_claims.make_claim(id=cid, path=p, branch="b", base_sha="a" * 40,
                                                  owner_agent=owner, owner_record=owner, **kw), pointer_for=None)


def rebind(ss, caller=SUCC, **kw):
    return ade_claims.rebind_successor(PRED, caller=caller, record_path=kw.pop("path", None) or record(ss),
                                       self_session_state=ss)


@pytest.mark.parametrize("status", ["acknowledged", "archived"])
def test_successor_takes_over_same_id_with_audit_line(tmp_path, state, status):
    claim(tmp_path)
    assert ade_claims.rebind_successor(PRED, caller=SUCC, record_path=record(state, status=status),
                                       self_session_state=state) == ["c1"]
    c = ade_claims.read_claim("c1")
    assert c["id"] == "c1" and c["state"] == "active"
    assert c["owner"]["agent"] == SUCC and c["owner"]["record"] == SUCC
    assert c["history"][-1].endswith(f"rebound from {PRED} by self-handoff {TOKEN}")


def test_no_claims_is_a_no_op(state):
    assert rebind(state) == []


def test_other_owners_claim_is_untouched(tmp_path, state):
    claim(tmp_path, owner=THIRD)
    assert rebind(state) == []
    assert ade_claims.read_claim("c1")["owner"]["agent"] == THIRD


def test_third_agent_caller_is_refused(tmp_path, state):
    claim(tmp_path)
    with pytest.raises(ValueError, match="successor"):
        rebind(state, caller=THIRD)
    assert ade_claims.read_claim("c1")["owner"]["agent"] == PRED


def test_empty_caller_is_refused(tmp_path, state):
    claim(tmp_path)
    with pytest.raises(ValueError, match="successor"):
        rebind(state, caller="")


@pytest.mark.parametrize("status", ["awaiting-ack", "creation-unknown", "creation-refused", "archive-unknown"])
def test_record_not_yet_acknowledged_is_refused(tmp_path, state, status):
    claim(tmp_path)
    with pytest.raises(ValueError, match="status"):
        rebind(state, path=record(state, status=status))
    assert ade_claims.read_claim("c1")["owner"]["agent"] == PRED


def test_record_naming_another_successor_is_refused(tmp_path, state):
    claim(tmp_path)
    with pytest.raises(ValueError, match="successor"):
        rebind(state, path=record(state, successor=THIRD))


def test_record_naming_another_predecessor_is_refused(tmp_path, state):
    claim(tmp_path)
    with pytest.raises(ValueError, match="predecessor"):
        rebind(state, path=record(state, predecessor=THIRD))
    assert ade_claims.read_claim("c1")["owner"]["agent"] == PRED


def test_record_outside_state_dir_is_refused(tmp_path, state):
    claim(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="state dir"):
        rebind(state, path=record(elsewhere))


def test_symlinked_record_and_bad_names_are_refused(tmp_path, state):
    claim(tmp_path)
    real = record(tmp_path)  # outside; link it inside
    link = state / f"handoff-{TOKEN}.json"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        rebind(state, path=link)
    bad = state / "notes.json"
    bad.write_text("{}")
    with pytest.raises(ValueError, match="state dir"):
        rebind(state, path=bad)


@pytest.mark.parametrize("body", ["not json", "[]", '{"kind": "compact"}'])
def test_unreadable_or_wrong_kind_record_is_refused(tmp_path, state, body):
    claim(tmp_path)
    p = state / f"handoff-{TOKEN}.json"
    p.write_text(body)
    with pytest.raises(ValueError):
        rebind(state, path=p)
    assert ade_claims.read_claim("c1")["owner"]["agent"] == PRED


def test_a_non_handoff_kind_is_refused_even_if_otherwise_valid(tmp_path, state):
    claim(tmp_path)
    with pytest.raises(ValueError, match="not a handoff"):
        rebind(state, path=record(state, kind="compact"))


def test_missing_record_is_refused(state):
    with pytest.raises(ValueError, match="unreadable"):
        rebind(state, path=state / f"handoff-{TOKEN}.json")


def test_expired_and_released_claims_are_not_resurrected(tmp_path, state):
    claim(tmp_path, "old")
    ade_claims.update_claim("old", expires_at="2000-01-01T00:00:00Z")
    claim(tmp_path, "rel")
    ade_claims.set_state("rel", "released")
    assert rebind(state) == []
    for cid in ("old", "rel"):
        assert ade_claims.read_claim(cid)["owner"]["agent"] == PRED
    assert ade_claims.read_claim("rel")["state"] == "released"


def test_history_is_bounded(tmp_path, state):
    claim(tmp_path)
    ade_claims.update_claim("c1", history=[f"h{i}" for i in range(80)])
    rebind(state)
    assert len(ade_claims.read_claim("c1")["history"]) == 50


def test_second_rebind_by_the_old_owner_cannot_take_it_back(tmp_path, state):
    claim(tmp_path)
    rebind(state)
    assert ade_claims.rebind_successor(PRED, caller=SUCC, record_path=record(state), self_session_state=state) == []


def test_cli_successor_of(tmp_path, state):
    claim(tmp_path)
    p = record(state)
    env = {**os.environ, "ADE_STATE_DIR": str(tmp_path / "state"), "PASEO_AGENT_ID": SUCC}
    base = [sys.executable, "-I", str(ROOT / "bin/ade_claims.py"), "successor-of", PRED, "--record", str(p),
            "--self-session-state", str(state)]
    r = subprocess.run(base, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == {"rebound": ["c1"]}
    r = subprocess.run(base, env={**env, "PASEO_AGENT_ID": THIRD}, capture_output=True, text=True)
    assert r.returncode == 2 and "successor" in r.stderr
