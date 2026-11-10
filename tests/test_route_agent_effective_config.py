"""Runtime config adoption with isolated homes and no live provider calls."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import ade_config as ac
import route_agent as router


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    for name in ("route_agent.py", "ade_config.py", "ade_gates.py", "model_tiers.py"):
        shutil.copy2(REPO / "bin" / name, root / "bin" / name)
    shutil.copytree(REPO / "config", root / "config")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in ("ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"):
        monkeypatch.delenv(key, raising=False)
    return root, home


def local_file(home, text):
    path = home / ".config/djbclark-ade/local.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def unified_file(root, *, plenty=65):
    # Only temporary fixture trees get a unified file; no tracked/live config.
    routing = (root / "config/routing.toml").read_text()
    routing = routing.replace("plenty_min = 50.0", f"plenty_min = {plenty}.0")
    path = root / "config/ade.toml"
    path.write_text("schema_version = 1\n" + routing)
    return path


def cli(tree, *args, env=None):
    root, home = tree
    # Any accidental provider call fails visibly, instead of reaching a host daemon.
    traps = root / "traps"
    traps.mkdir(exist_ok=True)
    for name in ("paseo", "aiuse"):
        path = traps / name
        path.write_text("#!/bin/sh\nprintf 'unexpected provider call\\n' >&2\nexit 97\n")
        path.chmod(0o755)
    isolated = {
        **os.environ, "HOME": str(home), "PATH": str(traps),
        "ROUTE_AGENT_AIUSE": "off", "ROUTE_AGENT_PASEO": "off",
        "ROUTE_AGENT_CALIBRATED_FLOOR": "off", "ROUTE_AGENT_OMP_READY": "0",
        "AIUSE_SNAPSHOT": str(home / "absent-snapshot.json"),
    }
    if env:
        isolated.update(env)
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(root / "bin/route_agent.py"), *args],
        env=isolated, cwd=root, capture_output=True, text=True, check=False,
    )
    assert "unexpected provider call" not in result.stderr
    return result


def test_legacy_runtime_policy_matches_pure_reader_and_keeps_limits(tree):
    root, home = tree
    expected = router.load_policy(root / "config/routing.toml")
    actual, provenance = router.load_effective_policy(root=root, home=home, environ={})
    assert actual == expected
    assert actual["dispatch"]["estimate_floor"]["codex:frontier"] == 60
    assert actual["dispatch"]["repo_overrides"]["tendcf"]["estimate_floor"]["codex:frontier"] == 20
    assert provenance == {
        "routing_source": str(root / "config/routing.toml"),
        "new_config": None, "local_config": None,
    }
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)
    assert printed["routing"]["plenty_min"] == actual["routing"]["plenty_min"]
    assert printed["dispatch"]["estimate_floor"] == actual["dispatch"]["estimate_floor"]
    assert {row["name"]: row["retired"] for row in printed["services"]} == {
        row["name"]: row.get("retired", False) for row in expected["service"]
    }
    assert printed["frontier_gate"]["frontier2_per_wave"] == 1
    assert printed["frontier_gate"]["frontier2_min_left"] == 60


@pytest.mark.parametrize("unified", [False, True])
def test_runtime_applies_local_overlays_and_reports_sources(tree, unified):
    root, home = tree
    base_path = unified_file(root) if unified else root / "config/routing.toml"
    local = local_file(home, '''[routing]
plenty_min = 75.0
[lead]
fable_lead = false
[dispatch.repo_overrides.tendcf.estimate_floor]
"codex:frontier" = 25.0
[gates.frontier]
frontier1_judged = 0
frontier2_per_wave = 99
frontier2_min_left = 1
''')
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    policy = json.loads(result.stdout)
    assert policy["routing"]["plenty_min"] == 75
    assert policy["lead"]["fable_lead"] is False
    assert policy["lead"]["model"] == router.load_policy(root / "config/routing.toml")["lead"]["model"]
    assert policy["path"] == str(base_path)
    assert policy["provenance"]["local_config"] == str(local)
    assert policy["frontier_gate"]["frontier1_judged"] == 0
    assert policy["frontier_gate"]["frontier2_per_wave"] == 1
    assert policy["frontier_gate"]["frontier2_min_left"] == 60
    loaded, _ = router.load_effective_policy(root=root, home=home, environ={})
    assert loaded["dispatch"]["repo_overrides"]["tendcf"]["estimate_floor"]["codex:frontier"] == 25
    md = cli(tree, "policy", "--md")
    assert md.returncode == 0, md.stderr
    assert f"Local override: `{local}`" in md.stdout


def test_unified_base_is_used_without_legacy_fallback(tree):
    root, home = tree
    path = unified_file(root)
    (root / "config/routing.toml").write_text("invalid [ legacy")
    data, provenance = router.load_effective_policy(root=root, home=home, environ={})
    assert data["routing"]["plenty_min"] == 65
    assert provenance["routing_source"] == str(path)
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["routing"]["plenty_min"] == 65


def test_routing_policy_isolates_unified_and_local_but_not_gates(tree):
    root, home = tree
    selected = root / "selected.toml"
    shutil.copy2(root / "config/routing.toml", selected)
    unified_file(root)
    local_file(home, '[routing]\nplenty_min = 80.0\n[lead]\nfable_lead = false\n'
               '[gates.frontier]\nfrontier1_judged = 0\n')
    result = cli(tree, "policy", env={"ROUTING_POLICY": str(selected)})
    assert result.returncode == 0, result.stderr
    policy = json.loads(result.stdout)
    assert policy["routing"]["plenty_min"] == 50
    assert policy["lead"]["fable_lead"] is True
    assert policy["path"] == str(selected)
    assert policy["frontier_gate"]["frontier1_judged"] == 0


@pytest.mark.parametrize("text,match", [
    ("[invalid", "not valid TOML"),
    ("schema_version = 99", "unsupported schema_version"),
    ('[lead]\nfable_lead = "yes"', "type conflict at lead.fable_lead"),
    ('[lead]\neffort = "ultra"', "must be one of"),
    ('[lead]\nunknown = true', "unknown key"),
    ('[substrate]\nlifeline = 123', "type conflict at substrate.lifeline"),
    ('[[service]]\nname = "broken"', "missing required key"),
    ('[[service]]\nname = "x"\ncli="x"\ngood_at={}\nbilling="free"\nunknown=true', "unknown key"),
    ('[[service]]\nname = "x"\ncli="x"\ngood_at={}\nbilling="free"\npool=["x"]', "2-element string array"),
    ('[[service]]\nname="x"\n[[service]]\nname="x"', "duplicate service identity"),
])
def test_invalid_local_config_refuses_runtime_without_output(tree, text, match):
    root, home = tree
    local_file(home, text)
    with pytest.raises(ac.ConfigError, match=match):
        router.load_effective_policy(root=root, home=home, environ={})
    result = cli(tree, "policy")
    assert result.returncode != 0
    assert not result.stdout
    assert match in result.stderr


@pytest.mark.parametrize("text", ["[invalid", "schema_version = 99", "schema_version = 1\n"])
def test_invalid_or_incomplete_unified_config_refuses_runtime(tree, text):
    root, home = tree
    (root / "config/ade.toml").write_text(text)
    with pytest.raises(ValueError):
        router.load_effective_policy(root=root, home=home, environ={})
    result = cli(tree, "policy")
    assert result.returncode != 0
    assert not result.stdout


def test_raw_invalid_ignored_domain_still_refuses_runtime(tree):
    root, home = tree
    local_file(home, 'service = "not an array"\n')
    result = cli(tree, "policy", env={"ROUTING_POLICY": str(root / "config/routing.toml")})
    assert result.returncode != 0
    assert not result.stdout
    assert "service" in result.stderr


def test_explicit_pure_reader_and_reload_ignore_unified_and_local(tree, monkeypatch):
    root, home = tree
    selected = root / "config/routing.toml"
    expected = router.load_policy(selected)
    (root / "config/ade.toml").write_text("invalid [ unified")
    local_file(home, "invalid [ local")
    monkeypatch.setenv("ROUTING_POLICY", str(root / "missing.toml"))
    assert router.load_policy(selected) == expected
    try:
        assert router.reload_policy(selected) == expected
        assert router.POLICY_PATH == selected
        assert router.POLICY_PROVENANCE["local_config"] is None
    finally:
        router.reload_policy(REPO / "config/routing.toml")


def test_missing_selected_routing_path_refuses_runtime(tree):
    root, home = tree
    unified_file(root)
    result = cli(tree, "policy", env={"ROUTING_POLICY": str(root / "missing.toml")})
    assert result.returncode != 0
    assert not result.stdout
    assert "not a regular file" in result.stderr


def test_default_reload_adopts_local_config(tree, monkeypatch):
    root, home = tree
    local_file(home, '[routing]\nplenty_min = 83.0\n[lead]\nfable_lead = false\n')
    monkeypatch.setattr(ac, "repo_root_from_here", lambda: root)
    try:
        loaded = router.reload_policy()
        assert router.PLENTY_MIN == loaded["routing"]["plenty_min"] == 83
        assert router.LEAD_FABLE_ALLOWED is False
        assert router.POLICY_PATH == root / "config/routing.toml"
    finally:
        router.reload_policy(REPO / "config/routing.toml")


def test_local_service_array_replaces_whole_and_default_effort_is_retained(tree):
    root, home = tree
    local_file(home, '''[[service]]
name = "only-local"
cli = "only-local"
good_at = {}
billing = "free"
retired = true
''')
    pure = router.load_policy(root / "config/routing.toml")
    data, _ = router.load_effective_policy(root=root, home=home, environ={})
    assert [s["name"] for s in data["service"]] == ["only-local"]
    assert data["service"][0]["retired"] is True
    assert data["lead"] == pure["lead"]
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    assert [s["name"] for s in json.loads(result.stdout)["services"]] == ["only-local"]


def test_unified_policy_keeps_optional_pipeline_effort_default(tree):
    root, home = tree
    path = unified_file(root)
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(line for line in lines if not line.startswith("pipeline_effort =")))
    data, _ = router.load_effective_policy(root=root, home=home, environ={})
    assert data["lead"]["pipeline_effort"] == router.LEAD_PIPELINE_EFFORT_DEFAULT
