"""Configured dependency candidates must never become observations or execution."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config/install.schema.json").write_bytes((REPO / "config/install.schema.json").read_bytes())
    (root / "config/install.toml").write_text('''schema_version = 1
[[component]]
id = "tool"
class = "hard"
update_argv = ["{bin}/fake-update", "{root}", "{home}", "{prefix}"]
probe_argv = ["must-not-run"]
platforms = ["mac"]
[[component]]
id = "unchosen"
class = "offered"
chosen = false
update_argv = ["must-not-run"]
[[component]]
id = "never"
class = "never"
update_argv = ["must-not-run"]
[[component]]
id = "chosen"
class = "optional"
chosen = true
update_argv = ["vendor", "update"]
[[component]]
id = "no-command"
class = "hard"
update = "some shell command that must never be interpreted"
[[component]]
id = "system"
class = "hard"
needs_system = true
update_argv = ["vendor", "update"]
[[component]]
id = "plugin"
class = "optional"
chosen = true
paseo_plugin = "explicit-plugin-id"
update_argv = ["must-not-run"]
[[component]]
id = "bad-token"
class = "hard"
update_argv = ["{unsupported}"]
[[key]]
name = "NO_KEY_CHECKS"
verify_argv = ["must-not-run"]
''')
    return ai.load_catalog(root=root)


def test_candidate_semantics_and_purity(catalog, tmp_path, monkeypatch):
    before = copy.deepcopy(catalog.data)
    # Any execution, observation or persisted state would violate this unit.
    forbidden = Mock(side_effect=AssertionError("planning invoked an effect"))
    monkeypatch.setattr(ai.subprocess, "run", forbidden)
    monkeypatch.setattr(ai.shutil, "which", forbidden)
    for name in ("observe_component", "keys_observe", "load_ledger", "save_ledger", "doctor"):
        monkeypatch.setattr(ai, name, forbidden)
    prefix = tmp_path / "prefix-not-created"
    steps = {r["id"]: r for r in ai.update_plan(catalog, prefix=prefix)}
    assert steps["tool"]["argv"] == [str(catalog.root / "bin/fake-update"), str(catalog.root), str(Path.home()), str(prefix)]
    assert steps["tool"]["action"] == steps["chosen"]["action"] == "candidate"
    assert steps["unchosen"]["action"] == steps["never"]["action"] == "skip"
    assert "argv" not in steps["unchosen"] and "argv" not in steps["never"]
    assert steps["no-command"]["action"] == "unconfigured"
    assert steps["system"]["needs_system"] is True
    assert steps["tool"]["needs_system"] is False
    assert steps["plugin"]["owner_managed"] is True
    assert steps["plugin"]["action"] == "owner-managed"
    assert "argv" not in steps["plugin"]
    assert steps["bad-token"]["action"] == "blocked"
    assert "argv" not in steps["bad-token"]
    for row in steps.values():
        for key in ("installed", "version", "activity", "ownership", "root_effects", "platform_compatibility"):
            assert row[key] == "unknown"
        assert row["execution_authorized"] is False
    assert steps["tool"]["owner_managed"] is None
    assert steps["tool"]["platforms"] == ["mac"]  # no host compatibility guessed
    assert catalog.data == before
    assert not prefix.exists()
    forbidden.assert_not_called()


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


@pytest.mark.parametrize("before_command", [False, True])
@pytest.mark.parametrize("root_option", ["--root", "--root=", "--roo", "--roo="])
def test_cold_cli_has_no_state_cache_or_command_effects(catalog, tmp_path, before_command, root_option):
    bindir = catalog.root / "bin"
    bindir.mkdir()
    for name in ("ade-install", "ade_install.py", "ade_config.py", "model_tiers.py"):
        shutil.copyfile(REPO / "bin" / name, bindir / name)
    executable = bindir / "ade-install"
    executable.chmod(0o755)
    (bindir / "fake-update").write_text("#!/bin/sh\ntouch unexpected-update\n")
    (bindir / "fake-update").chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    before = snapshot(tmp_path)
    root_args = ([root_option + str(catalog.root)] if root_option.endswith("=")
                 else [root_option, str(catalog.root)])
    argv = [*root_args, "update-plan"] if before_command else ["update-plan", *root_args]
    # No -B: a cold real executable must suppress its own repository cache writes.
    result = subprocess.run([str(executable), *argv, "--json"], cwd=tmp_path,
                            env={**os.environ, "HOME": str(home)}, capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "plan-only"
    assert "no execution authorized" in payload["note"]
    assert len(payload["steps"]) == len(catalog.components)
    assert snapshot(tmp_path) == before


def test_cli_text_and_invalid_catalog(catalog, tmp_path):
    command = [sys.executable, "-I", "-B", str(REPO / "bin/ade-install"), "update-plan", "--root", str(catalog.root)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    for text in ("configured candidates only", "ownership and root effects unknown", "no execution authorized",
                 "needs_system=true", "owner_managed=true", "unconfigured: no-command"):
        assert text in result.stdout
    (catalog.root / "config/install.toml").write_text("not valid toml")
    invalid = subprocess.run([*command, "--json"], capture_output=True, text=True, timeout=15)
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["mode"] == "plan-only"
    assert json.loads(invalid.stdout)["errors"]
