"""Contract tests use probabilities, never real attack text or live credentials."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gate", ROOT / "bin/ade_injection_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def response(p):
    return {"model": "jev-test", "answers": {"injection": {"type": "choice", "choice": "injection" if p > .5 else "benign",
            "probabilities": {"injection": p, "benign": 1-p}}}, "usage": {}}


@pytest.mark.parametrize("p,expected", [(0, "benign"), (.1, "benign"), (.10001, "escalate"), (.89999, "escalate"), (.9, "injection"), (1, "injection")])
def test_thresholds(p, expected):
    result = gate.classify("ordinary fixture", "pr", request=lambda *_: response(p))
    assert result["decide"] == expected
    assert result["untrusted"] is True
    assert not result["hold_dispatch"]


@pytest.mark.parametrize("bad", [None, {}, [], {"model": "kev-latest"}, response(float("nan")), response(1.1), response(10**400),
    {**response(.01), "usage": {"truncated": True}}, {**response(.01), "usage": {"state_tokens_dropped": 1}}])
def test_bad_responses_hold(bad):
    result = gate.classify("ordinary fixture", "fleet-watch", request=lambda *_: bad)
    assert result["status"] == "unavailable"
    assert result["decide"] == "escalate"
    assert result["probabilities"] is None
    assert result["hold_dispatch"]


@pytest.mark.parametrize("error", [TimeoutError, OSError, ValueError, subprocess.TimeoutExpired])
def test_errors_never_echo_payload(error):
    def fail(*_):
        if error is subprocess.TimeoutExpired:
            raise error("sensitive fixture", 5)
        raise error("sensitive fixture")
    result = gate.classify("sensitive fixture", "web", request=fail)
    assert result["decide"] == "escalate"
    assert "sensitive fixture" not in json.dumps(result)


@pytest.mark.parametrize("surface", gate.SURFACES)
def test_surface_actions(surface):
    result = gate.classify("fixture", surface, request=lambda *_: response(.95))
    assert result["hold_dispatch"] == (surface == "fleet-watch")
    assert result["operator_attention"] == (surface in {"fleet-watch", "jira"})


def test_disabled_and_size_do_not_request():
    def fail(*_):
        pytest.fail("must not call provider")
    for text, kw in [("fixture", {"enabled": False}), ("", {}), ("x" * (gate.MAX_BYTES + 1), {}), ("fixture", {"max_ms": 0})]:
        result = gate.classify(text, "fleet-watch", request=fail, **kw)
        assert result["hold_dispatch"]
        assert result["decide"] == "escalate"


def test_late_answer_escalates(monkeypatch):
    ticks = iter([0, 6, 6])
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(ticks))
    assert gate.classify("fixture", "pr", request=lambda *_: response(0))["status"] == "unavailable"


def test_transport_deadline(monkeypatch):
    def run(argv, **kwargs):
        assert argv[1] == "-I"
        assert kwargs["timeout"] == .5
        assert kwargs["capture_output"]
        assert json.loads(kwargs["input"])["questions"] == {"injection": gate.QUESTION}
        raise subprocess.TimeoutExpired(argv, .5)
    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.classify("fixture", "fleet-watch", max_ms=500)["hold_dispatch"]


def test_measure_replay(tmp_path):
    corpus = tmp_path / "scores.jsonl"
    rows = [{"id": str(i), "source": "synthetic", "surface": "pr", "label": label, "response": response(p), "latency_ms": 100}
            for i, (label, p) in enumerate([("injection", .95), ("injection", .5), ("benign", .99), ("benign", .01)])]
    corpus.write_text("\n".join(json.dumps(r) for r in rows))
    cp = subprocess.run([sys.executable, str(ROOT / "bin/ade-injection-gate"), "measure", "--replay", str(corpus)], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    report = json.loads(cp.stdout)
    assert report["overall"]["recall_at_0_9"] == .5
    assert report["overall"]["false_positive_rate_at_0_9"] == .5
    assert report["overall"]["escalation_rate"] == .25
    assert report["adoption_authorized"] is False
    assert report["mode"] == "offline-replay"


def test_measurement_outages_not_dropped():
    bad = gate.classify("fixture", "pr", enabled=False)
    rows = [{"id": "a", "source": "synthetic", "label": "injection", "run": run, "result": bad} for run in (1, 2)]
    report = gate.measurement(rows)
    assert report["overall"]["recall_at_0_9"] == 0
    assert report["overall"]["unavailable"] == 2
    assert report["paired_samples"] == 1
    assert report["valid_pairs"] == report["stable_pairs"] == 0


def test_replay_deadline_preserves_fleet_hold(tmp_path):
    corpus = tmp_path / "scores.jsonl"
    corpus.write_text(json.dumps({"id": "late", "source": "synthetic", "surface": "fleet-watch", "label": "benign", "response": response(.01), "latency_ms": 5001}))
    cp = subprocess.run([sys.executable, str(ROOT / "bin/ade-injection-gate"), "measure", "--replay", str(corpus)], capture_output=True, text=True)
    assert cp.returncode == 0
    result = json.loads(cp.stdout)["scores"][0]["result"]
    assert result["status"] == "unavailable"
    assert result["hold_dispatch"]
    assert result["operator_attention"]
