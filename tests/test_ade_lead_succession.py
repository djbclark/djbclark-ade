"""bin/ade_lead_succession.py: a lead's replacement chain, read from ade-self-session's handoff records (offline)."""
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_lead_succession as succ  # noqa: E402

A, B, C, D = (f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-00000000000{n}" for n in "1234")
STRANGER = "99999999-0000-4000-8000-000000000009"


def write_link(state: Path, home_dir: Path, pred: str, nxt: str, status="archived", ack="ok", **over):
    state.mkdir(parents=True, exist_ok=True)
    rec = {"schema_version": 1, "kind": "handoff", "predecessor": pred, "successor": nxt, "home": str(home_dir.resolve()),
           "status": status, "ack": {"agent_id": nxt} if ack == "ok" else ack}
    rec.update(over)
    (state / f"handoff-{pred}.json").write_text(json.dumps(rec))


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "self-session", tmp_path / "paseo-home"


def chain3(state, home):
    for pred, nxt in ((A, B), (B, C), (C, D)):
        write_link(state, home, pred, nxt)


def test_three_step_chain_resolves_forward_and_back(ledger):
    state, home = ledger
    chain3(state, home)
    assert succ.chain(A, state, home) == [A, B, C, D]
    assert succ.effective_lead(A, state, home) == D and succ.effective_lead(C, state, home) == D
    assert succ.effective_lead(D, state, home) == D
    assert succ.predecessors(D, state, home) == {A, B, C}
    assert succ.lineage(D, state, home) == {A, B, C, D}
    assert succ.lineage(B, state, home) == {A, B}  # a mid-chain id inherits only what came before it


def test_unreplaced_lead_is_its_own_lineage(ledger):
    state, home = ledger
    assert succ.effective_lead(A, state, home) == A and succ.lineage(A, state, home) == {A}  # no state dir at all
    chain3(state, home)
    assert succ.lineage(STRANGER, state, home) == {STRANGER}


@pytest.mark.parametrize("bad", [
    {"status": "awaiting-ack"}, {"status": "acknowledged"}, {"status": "archive-unknown"}, {"status": "creation-unknown"},
    {"ack": None}, {"ack": {"agent_id": STRANGER}}, {"kind": "compact"}, {"predecessor": STRANGER},
    {"home": "/somewhere/else"}, {"successor": "not-a-uuid"}, {"successor": A}, {"successor": None},
])
def test_incomplete_or_foreign_record_is_no_link(ledger, bad):
    state, home = ledger
    write_link(state, home, A, B)
    write_link(state, home, B, C, **bad)  # the second hop is broken
    assert succ.chain(A, state, home) == [A, B]
    assert succ.effective_lead(A, state, home) == B
    assert succ.predecessors(C, state, home) == set()


def test_corrupt_oversized_symlinked_and_misnamed_records_are_no_link(ledger, tmp_path):
    state, home = ledger
    write_link(state, home, A, B)
    (state / f"handoff-{B}.json").write_text("{not json")
    assert succ.effective_lead(A, state, home) == B
    (state / f"handoff-{B}.json").write_text(json.dumps({"pad": "x" * (succ.MAX_RECORD_BYTES + 1)}))
    assert succ.effective_lead(A, state, home) == B
    (state / f"handoff-{B}.json").unlink()
    real = tmp_path / "elsewhere.json"
    write_link(tmp_path, home, B, C)
    (tmp_path / f"handoff-{B}.json").rename(real)
    os.symlink(real, state / f"handoff-{B}.json")
    assert succ.effective_lead(A, state, home) == B and succ.predecessors(C, state, home) == set()
    (state / "handoff-notauuid.json").write_text("{}")  # a stray name is skipped, not an error
    assert succ.predecessors(B, state, home) == {A}
    assert succ.successor_of("not-a-uuid", state, home) is None


def test_record_for_a_different_daemon_home_is_ignored(ledger, tmp_path):
    state, home = ledger
    write_link(state, tmp_path / "other-home", A, B)
    assert succ.effective_lead(A, state, home) == A and succ.predecessors(B, state, home) == set()


def test_cycle_raises_and_never_loops(ledger):
    state, home = ledger
    write_link(state, home, A, B)
    write_link(state, home, B, C)
    write_link(state, home, C, A)
    with pytest.raises(succ.SuccessionError):
        succ.chain(A, state, home)
    with pytest.raises(succ.SuccessionError):  # the backward walk terminates too, and resolves nothing
        succ.predecessors(A, state, home)
    with pytest.raises(succ.SuccessionError):
        succ.lineage(B, state, home)


def test_defaults_come_from_the_environment(tmp_path, monkeypatch):
    state, home = tmp_path / "s", tmp_path / "h"
    chain3(state, home)
    monkeypatch.setenv("ADE_SELF_SESSION_STATE", str(state))
    monkeypatch.setenv("PASEO_HOME", str(home))
    assert succ.effective_lead(A) == D and succ.lineage(D) == {A, B, C, D}
