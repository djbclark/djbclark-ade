"""bin/ade-claim-pilot: S4 six-case metrics recorder (no hard refuse)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "ade-claim-pilot"


def load_mod():
    loader = importlib.machinery.SourceFileLoader("ade_claim_pilot", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def run(state: Path, *args: str, check: bool = False):
    env = dict(os.environ, ADE_STATE_DIR=str(state))
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=check,
        timeout=30,
    )


@pytest.fixture
def state(tmp_path):
    d = tmp_path / "ade-state"
    d.mkdir()
    return d


def test_cases_lists_exactly_six(state):
    r = run(state, "cases", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["hard_refuse"] is False
    ids = [c["id"] for c in payload["cases"]]
    assert ids == ["1", "2", "3", "4", "5", "6"]
    names = [c["name"] for c in payload["cases"]]
    assert names[0] == "ADE code task"
    assert names[5] == "Long-lived server"


def test_gate_not_ready_when_unrun(state):
    r = run(state, "gate", "--json")
    assert r.returncode == 1, r.stderr
    payload = json.loads(r.stdout)
    assert payload["ready"] is False
    assert payload["hard_refuse"] is False
    assert payload["missing"] == ["1", "2", "3", "4", "5", "6"]
    assert "never enables" in payload["hard_refuse_note"]


def test_record_and_status_round_trip(state):
    r = run(
        state,
        "record",
        "1",
        "--result",
        "pass",
        "--setup-delay-s",
        "1.25",
        "--disk-delta-bytes",
        "4096",
        "--path-binding-failures",
        "0",
        "--false-refusals",
        "0",
        "--note",
        "smoke",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["case"] == "1"
    assert payload["hard_refuse"] is False
    assert payload["record"]["setup_delay_s"] == 1.25
    assert payload["record"]["disk_delta_bytes"] == 4096
    assert payload["record"]["result"] == "pass"

    path = state / "s4-pilot.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["hard_refuse"] is False
    assert on_disk["cases"]["1"]["note"] == "smoke"

    show = run(state, "show", "ADE code task", "--json")
    assert show.returncode == 0, show.stderr
    shown = json.loads(show.stdout)
    assert shown["recorded"] is True
    assert shown["record"]["result"] == "pass"

    status = run(state, "status", "--json")
    assert status.returncode == 0, status.stderr
    st = json.loads(status.stdout)
    assert st["passed"] == ["1"]
    assert st["missing"] == ["2", "3", "4", "5", "6"]
    assert st["hard_refuse"] is False


def test_record_accepts_case_name_and_false_refusal_reasons(state):
    r = run(
        state,
        "record",
        "Fixed-cwd agent",
        "--result",
        "fail",
        "--false-refusals",
        "1",
        "--false-refusal-reason",
        "owner -C write exit 77",
        "--false-refusal-reason",
        "second look",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["case"] == "5"
    assert payload["record"]["false_refusal_reasons"] == [
        "owner -C write exit 77",
        "second look",
    ]


def test_gate_ready_only_when_all_six_pass(state):
    for cid in ("1", "2", "3", "4", "5", "6"):
        r = run(state, "record", cid, "--result", "pass", "--setup-delay-s", "0")
        assert r.returncode == 0, r.stderr
    ready = run(state, "gate", "--json")
    assert ready.returncode == 0, ready.stderr
    payload = json.loads(ready.stdout)
    assert payload["ready"] is True
    assert payload["hard_refuse"] is False
    assert payload["missing"] == []
    assert payload["not_pass"] == []
    # Ready never means this tool flipped refusal.
    on_disk = json.loads((state / "s4-pilot.json").read_text(encoding="utf-8"))
    assert on_disk["hard_refuse"] is False


def test_gate_blocks_on_fail_or_skip(state):
    for cid in ("1", "2", "3", "4", "5"):
        assert run(state, "record", cid, "--result", "pass").returncode == 0
    assert run(state, "record", "6", "--result", "fail").returncode == 0
    r = run(state, "gate", "--json")
    assert r.returncode == 1
    assert json.loads(r.stdout)["not_pass"] == ["6"]

    assert run(state, "record", "6", "--result", "skip").returncode == 0
    r2 = run(state, "gate", "--json")
    assert r2.returncode == 1
    assert json.loads(r2.stdout)["not_pass"] == ["6"]


def test_clear_requires_yes_and_preserves_hard_refuse_off(state):
    assert run(state, "record", "2", "--result", "pass").returncode == 0
    refused = run(state, "clear", "2")
    assert refused.returncode == 2
    assert "without --yes" in refused.stderr
    assert (state / "s4-pilot.json").is_file()
    assert "2" in json.loads((state / "s4-pilot.json").read_text())["cases"]

    cleared = run(state, "clear", "2", "--yes", "--json")
    assert cleared.returncode == 0, cleared.stderr
    assert json.loads(cleared.stdout)["hard_refuse"] is False
    assert "2" not in json.loads((state / "s4-pilot.json").read_text())["cases"]

    assert run(state, "record", "3", "--result", "pass").returncode == 0
    all_clear = run(state, "clear", "--yes", "--json")
    assert all_clear.returncode == 0, all_clear.stderr
    on_disk = json.loads((state / "s4-pilot.json").read_text())
    assert on_disk["cases"] == {}
    assert on_disk["hard_refuse"] is False


def test_load_ignores_stale_hard_refuse_true(state, monkeypatch):
    mod = load_mod()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    path = state / "s4-pilot.json"
    path.write_text(
        json.dumps({"v": 1, "tool": "ade-claim-pilot", "hard_refuse": True, "cases": {}}),
        encoding="utf-8",
    )
    rec = mod.load_record()
    assert rec["hard_refuse"] is False
    gate = mod.gate_state(rec)
    assert gate["hard_refuse"] is False


def test_record_rejects_negative_metrics(state):
    r = run(state, "record", "1", "--result", "pass", "--setup-delay-s", "-1")
    assert r.returncode == 2
    r2 = run(state, "record", "1", "--result", "pass", "--false-refusals", "-3")
    assert r2.returncode == 2


def test_unknown_case_is_usage(state):
    r = run(state, "record", "99", "--result", "pass")
    assert r.returncode == 2
    assert "unknown case" in r.stderr


def test_atomic_write_leaves_valid_json(state, monkeypatch):
    mod = load_mod()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    mod.save_record(mod.empty_record())
    path = state / "s4-pilot.json"
    assert path.is_file()
    assert not list(state.glob(".s4-pilot.json.*.tmp"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tool"] == "ade-claim-pilot"
    assert data["hard_refuse"] is False
