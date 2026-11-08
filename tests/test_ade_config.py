"""bin/ade_config.py + bin/ade-config: schema_version=1 read-only effective config.

Synthetic fixtures under tests/fixtures/ade_config. Every test isolates HOME/local.toml.
No writes to repo config; no network/auth probes; no secret resolution.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
FIX = REPO / "tests" / "fixtures" / "ade_config"
sys.path.insert(0, str(BIN))
import ade_config as ac  # noqa: E402
import ade_gates as ag  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Temp HOME so ~/.config/djbclark-ade/local.toml never touches the real one."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    # Clear isolated overrides unless a test sets them.
    monkeypatch.delenv("ROUTING_POLICY", raising=False)
    monkeypatch.delenv("GATES_TOML", raising=False)
    return h


def _local_write(home: Path, text: str) -> Path:
    path = home / ".config" / "djbclark-ade" / "local.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _run_cli(*args: str, home: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, "HOME": str(home), "PATH": str(BIN) + os.pathsep + os.environ.get("PATH", "")}
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-I", str(BIN / "ade-config"), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=str(REPO),
        check=False,
    )


def test_legacy_effective_matches_routing_toml_and_clamped_gates(home):
    import tomllib

    eff = ac.load_effective(root=REPO, home=home)
    shipped = tomllib.loads((REPO / "config" / "routing.toml").read_text())
    for key in ("routing", "lead", "dispatch", "substrate", "hermes", "calibrate", "service"):
        assert eff.data.get(key) == shipped.get(key)
    assert eff.data["schema_version"] == 1
    frontier, info = ag.load_frontier()
    assert eff.data["gates"]["frontier"] == frontier
    assert eff.provenance["routing_source"].endswith("config/routing.toml")
    assert eff.provenance["gates_source"].endswith("config/gates.toml")
    assert eff.provenance["local_config"] is None
    assert info["source"] == "gates.toml"


def test_local_override_preserves_sibling_lead_leaves(home):
    import tomllib

    shipped_lead = tomllib.loads((REPO / "config" / "routing.toml").read_text())["lead"]
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home)
    assert eff.data["lead"]["fable_lead"] is False
    for key, value in shipped_lead.items():
        if key == "fable_lead":
            continue
        assert eff.data["lead"][key] == value


def test_local_service_array_replaces_whole_not_concat(home):
    _local_write(home, (FIX / "local_services_replace.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home)
    names = [e["name"] for e in eff.data["service"]]
    assert names == ["only-local"]


def test_duplicate_service_identity_rejected(home, monkeypatch):
    monkeypatch.setenv("ROUTING_POLICY", str(FIX / "routing_dup_service.toml"))
    with pytest.raises(ac.ConfigError, match="duplicate service identity"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_unknown_schema_version_rejected(home):
    with pytest.raises(ac.ConfigError, match="unsupported schema_version"):
        ac.load_effective(
            root=REPO,
            home=home,
            new_config=FIX / "ade_unknown_version.toml",
        )


def test_invalid_new_config_rejected_no_legacy_fallback(home):
    with pytest.raises(ac.ConfigError, match="not valid TOML"):
        ac.load_effective(
            root=REPO,
            home=home,
            new_config=FIX / "ade_invalid.toml",
        )


def test_local_type_conflict_rejected(home):
    _local_write(home, (FIX / "local_type_conflict.toml").read_text())
    with pytest.raises(ac.ConfigError, match="type conflict"):
        ac.load_effective(root=REPO, home=home)


def test_routing_policy_isolates_domain_from_local(home, monkeypatch):
    import tomllib

    # Point routing at shipped file via env; local tries to flip fable_lead.
    monkeypatch.setenv("ROUTING_POLICY", str(REPO / "config" / "routing.toml"))
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    shipped = tomllib.loads((REPO / "config" / "routing.toml").read_text())
    assert eff.data["lead"] == shipped["lead"]
    assert eff.data["lead"]["fable_lead"] is True
    assert eff.provenance["routing_env"] == str(REPO / "config" / "routing.toml")


def test_gates_toml_isolates_and_bad_frontier_is_closed(home, monkeypatch):
    monkeypatch.setenv("GATES_TOML", str(FIX / "gates_bad_frontier.toml"))
    # Also try a local gates widen that must be ignored under isolation.
    _local_write(
        home,
        "[gates.frontier]\nfrontier1_per_wave = 2\nfrontier1_judged = 1\n",
    )
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    assert eff.data["gates"]["frontier"] == ac.FRONTIER_DEFAULTS
    assert eff.provenance["gates_info"]["source"] == "code"
    assert eff.provenance["gates_env"] == str(FIX / "gates_bad_frontier.toml")


def test_gate_loosen_clamped_to_code_defaults(home):
    eff = ac.load_effective(
        root=REPO,
        home=home,
        new_config=FIX / "ade_loose_gate.toml",
    )
    # 99 > bound 2 → code default 1; min_left 1.0 < 15 → code default 15
    assert eff.data["gates"]["frontier"]["frontier1_per_wave"] == 1.0
    assert eff.data["gates"]["frontier"]["frontier1_min_left"] == 15.0


def test_missing_selected_routing_policy_errors(home, monkeypatch):
    missing = home / "no-such-routing.toml"
    monkeypatch.setenv("ROUTING_POLICY", str(missing))
    with pytest.raises(ac.ConfigError, match="not a regular file"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_check_ok_and_cli_makes_no_writes(home, tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("x")
    before = {
        "sentinel": sentinel.stat().st_mtime_ns,
        "routing": (REPO / "config" / "routing.toml").stat().st_mtime_ns,
        "gates": (REPO / "config" / "gates.toml").stat().st_mtime_ns,
    }
    errors, eff = ac.check(root=REPO, home=home)
    assert errors == []
    assert eff is not None
    proc = _run_cli("check", "--root", str(REPO), "--home", str(home), home=home)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert sentinel.stat().st_mtime_ns == before["sentinel"]
    assert (REPO / "config" / "routing.toml").stat().st_mtime_ns == before["routing"]
    assert (REPO / "config" / "gates.toml").stat().st_mtime_ns == before["gates"]
    assert not (home / ".config" / "djbclark-ade" / "local.toml").exists()


def test_cli_get_and_diff_json(home):
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    got = _run_cli(
        "get", "lead.fable_lead", "--root", str(REPO), "--home", str(home), "--json",
        home=home,
    )
    assert got.returncode == 0, got.stderr
    payload = json.loads(got.stdout)
    assert payload["value"] is False
    diff = _run_cli(
        "diff", "--root", str(REPO), "--home", str(home), "--json",
        home=home,
    )
    assert diff.returncode == 0, diff.stderr
    changes = json.loads(diff.stdout)["changes"]
    assert any(c["path"] == "lead.fable_lead" and c["after"] is False for c in changes)


def test_schema_file_present_and_check_sees_it(home):
    schema = REPO / "config" / "ade.schema.json"
    assert schema.is_file()
    data = json.loads(schema.read_text())
    assert data["title"] == "djbclark-ade effective config"
    assert data["properties"]["schema_version"]["const"] == 1
    errs = ac.validate_schema_file(schema)
    assert errs == []


def test_new_minimal_ade_toml_loads(home):
    eff = ac.load_effective(
        root=REPO,
        home=home,
        new_config=FIX / "ade_minimal.toml",
    )
    assert eff.data["lead"]["fable_lead"] is True
    assert eff.data["service"][0]["name"] == "claude"
    assert eff.data["gates"]["frontier"]["frontier1_per_wave"] == 2.0


def test_mapping_table_covers_routing_and_gates():
    targets = {row[2] for row in ac.LEGACY_PROJECTION}
    assert "[routing]" in targets
    assert "[[service]]" in targets
    assert "[gates.frontier]" in targets
    assert "[gates.floors.frontier]" in targets
