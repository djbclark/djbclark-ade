"""Only known missing observations authorize default component installation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_install as ai


def catalog(tmp_path, *, system=False):
    row = {"id": "fixture", "class": "hard", "install_argv": ["fixture-installer", "install"],
           "probe_argv": ["fixture-probe", "--version"]}
    if system:
        row.update(needs_system=True, system_argv=["fixture-manager", "install", "fixture"])
    return ai.Catalog(data={"component": [row]}, root=tmp_path, path=tmp_path / "catalog.toml")


@pytest.mark.parametrize("observation", ["unknown", "failed", "timeout", "exec-error"])
@pytest.mark.parametrize("system", [False, True])
@pytest.mark.parametrize("dry_run", [False, True])
def test_inconclusive_or_broken_probe_blocks_without_installer_or_ledger_writes(
    tmp_path, monkeypatch, observation, system, dry_run,
):
    cfg = catalog(tmp_path, system=system)
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: False)
    if observation == "unknown":
        cfg.components[0].pop("probe_argv")
        probe = Mock(side_effect=AssertionError("unknown presence must not execute a probe"))
    else:
        outcome = {"failed": subprocess.CompletedProcess([], 3, "", "broken tool"),
                   "timeout": subprocess.TimeoutExpired([], 15),
                   "exec-error": OSError("cannot execute existing tool")}[observation]
        probe = Mock(side_effect=[outcome])
    monkeypatch.setattr(ai, "_default_runner", probe)
    installer = Mock(side_effect=AssertionError("inconclusive/broken is not missing"))
    state_dir = tmp_path / "never-created-state"
    rows, rc = ai.apply(cfg, dry_run=dry_run, ids={"fixture"}, allow_system=system,
                        apply_system=system and not dry_run, state_dir=state_dir, runner=installer)
    assert rc == 1 and rows[0]["action"] == "blocked" and rows[0]["ok"] is False
    assert ("unknown" if observation == "unknown" else "error") in rows[0]["reason"]
    assert "--force" in rows[0]["reason"]
    assert "argv" not in rows[0] and not state_dir.exists()
    installer.assert_not_called()
    assert probe.call_count == (0 if observation == "unknown" else 1)


def test_refusal_preserves_existing_ledger_bytes(tmp_path, monkeypatch):
    cfg = catalog(tmp_path)
    monkeypatch.setattr(ai, "observe_component", lambda *a, **k: ai.Observation("component", "fixture", "unknown", "no metadata"))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ledger = state_dir / "ledger.json"
    before = b'{"schema_version":1,"entries":{"other":{"status":"installed"}}}\n'
    ledger.write_bytes(before)
    rows, rc = ai.apply(cfg, dry_run=False, ids={"fixture"}, state_dir=state_dir,
                        runner=Mock(side_effect=AssertionError("installer")))
    assert rc == 1 and rows[0]["action"] == "blocked"
    assert ledger.read_bytes() == before and list(state_dir.iterdir()) == [ledger]


@pytest.mark.parametrize("observed,action", [("missing", "installed"), ("ok", "skip")])
def test_default_preserves_known_missing_install_and_healthy_skip(tmp_path, monkeypatch, observed, action):
    cfg = catalog(tmp_path)
    monkeypatch.setattr(ai, "observe_component", lambda *a, **k: ai.Observation("component", "fixture", observed, "fixture observation"))
    installer = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    state_dir = tmp_path / "state"
    rows, rc = ai.apply(cfg, dry_run=False, ids={"fixture"}, state_dir=state_dir, runner=installer)
    assert rc == 0 and rows[0]["action"] == action
    assert installer.call_count == (1 if observed == "missing" else 0)
    assert state_dir.exists() is (observed == "missing")


@pytest.mark.parametrize("observed", ["unknown", "error"])
@pytest.mark.parametrize("system,allow_system,apply_system,action,rc", [
    (False, False, False, "installed", 0),
    (True, False, False, "refuse-system", 1),
    (True, True, False, "refuse-system-exec", 2),
    (True, True, True, "installed", 0),
])
def test_force_requests_repair_but_preserves_system_authority_and_ledger(
    tmp_path, monkeypatch, observed, system, allow_system, apply_system, action, rc,
):
    cfg = catalog(tmp_path, system=system)
    monkeypatch.setattr(ai, "observe_component", lambda *a, **k: ai.Observation("component", "fixture", observed, "fixture observation"))
    state_dir = tmp_path / "state"
    def install(argv, cwd):
        pending = json.loads((state_dir / "ledger.json").read_text())["entries"]["fixture"]
        assert pending["status"] == "pending" and pending["argv"] == argv
        return subprocess.CompletedProcess(argv, 0, "", "")
    installer = Mock(side_effect=install)
    rows, got_rc = ai.apply(cfg, dry_run=False, ids={"fixture"}, force=True,
                           allow_system=allow_system, apply_system=apply_system,
                           state_dir=state_dir, runner=installer)
    assert got_rc == rc and rows[0]["action"] == action
    if action == "installed":
        expected = ["fixture-manager", "install", "fixture"] if system else ["fixture-installer", "install"]
        assert installer.call_args.args == (expected, tmp_path)
        entry = json.loads((state_dir / "ledger.json").read_text())["entries"]["fixture"]
        assert entry["status"] == "installed" and entry["argv"] == expected
        assert entry["kind"] == ("system_argv" if system else "install_argv")
    else:
        installer.assert_not_called()
        assert not state_dir.exists()


@pytest.mark.parametrize("metadata,action", [
    ({"class": "optional", "chosen": False}, "skip"),
    ({"paseo_plugin": "fixture-plugin"}, "blocked"),
])
def test_force_does_not_override_choice_or_observe_only_plugin(tmp_path, monkeypatch, metadata, action):
    cfg = catalog(tmp_path, system=True)
    cfg.components[0].update(metadata)
    monkeypatch.setattr(ai, "observe_component", Mock(side_effect=AssertionError("not admitted for probing")))
    installer = Mock(side_effect=AssertionError("installer"))
    rows, rc = ai.apply(cfg, dry_run=False, ids={"fixture"}, force=True,
                        allow_system=True, apply_system=True, state_dir=tmp_path / "state", runner=installer)
    assert rows[0]["action"] == action and rc == (0 if action == "skip" else 1)
    assert not (tmp_path / "state").exists()
    installer.assert_not_called()
