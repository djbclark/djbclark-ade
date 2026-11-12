"""Offline admission contracts; never launch a provider or touch live state."""
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
spec = importlib.util.spec_from_file_location("nightly", BIN / "ade_nightly_learning.py")
nightly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nightly)


def cli(*args):
    return subprocess.run([sys.executable, str(BIN / "ade-nightly-learning"), *map(str, args)],
                          capture_output=True, text=True, timeout=10)


def test_exact_cap_restart_and_duplicate(tmp_path):
    ledger = tmp_path / "night.json"
    assert cli("init", ledger, "--limit", 100).returncode == 0
    assert cli("reserve", ledger, "--call-id", "first", "--tokens", 40).returncode == 0
    assert cli("reserve", ledger, "--call-id", "first", "--tokens", 40).returncode == 3
    assert cli("reserve", ledger, "--call-id", "retry", "--tokens", 60).returncode == 0
    assert cli("reserve", ledger, "--call-id", "last", "--tokens", 1).returncode == 3
    assert cli("init", ledger, "--limit", 1000).returncode == 2
    assert json.loads(ledger.read_text())["reservations"] == {"first": 40, "retry": 60}


@pytest.mark.parametrize("tokens", [True, False, -1, 0, 1.5, "10", None])
def test_invalid_token_counts(tmp_path, tokens):
    ledger = tmp_path / "night.json"
    with pytest.raises(ValueError):
        nightly.init_budget(ledger, tokens)
    nightly.init_budget(ledger, 10)
    with pytest.raises(ValueError):
        nightly.reserve(ledger, "a", tokens)
    assert json.loads(ledger.read_text())["reservations"] == {}


@pytest.mark.parametrize("body", [None, "broken", "[]", '{"limit":100}',
    '{"schema_version":1,"limit":10,"reservations":{"x":-1}}',
    '{"schema_version":true,"limit":10,"reservations":{}}',
    '{"schema_version":1,"limit":10,"reservations":{"x":11}}'])
def test_unavailable_or_corrupt_budget_is_refused(tmp_path, body):
    ledger = tmp_path / "night.json"
    if body is not None:
        ledger.write_text(body)
    result = cli("reserve", ledger, "--call-id", "next", "--tokens", 1)
    assert result.returncode == 2
    assert json.loads(result.stdout)["adoption_authorized"] is False
    if body is not None:
        assert ledger.read_text() == body
    else:
        assert not ledger.exists()


def test_concurrent_processes_cannot_overspend(tmp_path):
    ledger = tmp_path / "night.json"
    nightly.init_budget(ledger, 10)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: cli("reserve", ledger, "--call-id", f"call-{i}", "--tokens", 3), range(6)))
    assert sorted(r.returncode for r in results) == [0, 0, 0, 3, 3, 3]
    assert sum(json.loads(ledger.read_text())["reservations"].values()) == 9


def test_failed_persistence_never_admits(tmp_path, monkeypatch):
    ledger = tmp_path / "night.json"
    nightly.init_budget(ledger, 10)
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(nightly, "atomic_write", fail)
    with pytest.raises(OSError):
        nightly.reserve(ledger, "next", 1)
    assert json.loads(ledger.read_text())["reservations"] == {}


def manifest(*changes, injection="clear"):
    return {"changes": [{"path": p, "effect": e} for p, e in changes], "injection": injection}


@pytest.mark.parametrize("changes,kind", [
    ([("skills/retro/SKILL.md", "skill-local")], "skill-only"),
    ([("skills/retro/SKILL.md", "standing-order")], "standing-order"),
    ([("skills/retro/AGENTS.md", "skill-local")], "standing-order"),
    ([("AGENTS.md", "unknown")], "standing-order"),
    ([("cursor/home-agents.mdc", "other")], "standing-order"),
    ([("skills/a/SKILL.md", "skill-local"), ("bin/runner", "other")], "other"),
    ([("skills/a/SKILL.md", "unknown")], "other"),
    ([("skills/a/SKILL.md", "skill-local"), ("CLAUDE.md", "unknown")], "standing-order"),
])
def test_effect_classification(changes, kind):
    result = nightly.classify(manifest(*changes))
    assert result["classification"] == kind
    assert result["proposal_allowed"] is True
    assert result["reviewed_adoption_candidate"] == (kind == "skill-only")
    assert result["adoption_authorized"] is False


@pytest.mark.parametrize("injection", ["suspected", "unknown"])
@pytest.mark.parametrize("effect", ["skill-local", "standing-order", "other"])
def test_injection_blocks_every_proposal_kind(injection, effect):
    result = nightly.classify(manifest(("skills/a/SKILL.md", effect), injection=injection))
    assert result["proposal_allowed"] is False
    assert result["reviewed_adoption_candidate"] is False
    assert result["adoption_authorized"] is False


@pytest.mark.parametrize("path", ["/skills/a/SKILL.md", "skills/../AGENTS.md", "./skills/a/SKILL.md",
    "skills//a/SKILL.md", "skills/a/", "skills\\a\\SKILL.md", "skills/a\nSKILL.md", ""])
def test_noncanonical_paths_refused(path):
    with pytest.raises(ValueError):
        nightly.classify(manifest((path, "skill-local")))


@pytest.mark.parametrize("value", [{}, [], {"changes": [], "injection": "clear"},
    {"changes": [{"path": "skills/a/SKILL.md"}], "injection": "clear"},
    manifest(("skills/a/SKILL.md", "skill-local"), injection="benign"),
    manifest(("skills/a/SKILL.md", "skill-local"), ("skills/a/SKILL.md", "other"))])
def test_incomplete_or_conflicting_review_refused(value):
    with pytest.raises(ValueError):
        nightly.classify(value)


def test_cli_injection_hold(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(manifest(("skills/a/SKILL.md", "skill-local"), injection="suspected")))
    result = cli("classify", path)
    assert result.returncode == 3
    assert json.loads(result.stdout)["blocked_reason"] == "injection-suspected"
