"""ade-install catalog / plan / doctor: observe-only; never writes real HOME or installs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
FIX = REPO / "tests" / "fixtures" / "install_catalog"
sys.path.insert(0, str(BIN))
import ade_install as ai  # noqa: E402


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-install"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), check=False)


def test_repo_install_toml_checks_clean():
    catalog = ai.load_catalog(root=REPO)
    assert catalog.data["schema_version"] == 1
    assert len(catalog.components) >= 20
    assert len(catalog.keys) >= 6
    assert len(catalog.logins) >= 4
    ids = [c["id"] for c in catalog.components]
    assert len(ids) == len(set(ids))
    assert "pi" in ids and "sudo-secretspec" in ids
    proc = _run("check", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_fixture_doctor_missing_vs_unchosen(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    catalog = ai.load_catalog(root=root)
    obs, rc = ai.doctor(catalog)
    by_id = {o.id: o for o in obs if o.kind == "component"}
    assert by_id["tool-a"].status == "ok"
    assert by_id["tool-b"].status == "unchosen"
    assert by_id["tool-c"].status == "missing"
    assert rc == 1  # chosen optional missing counts
    key_obs = [o for o in obs if o.kind == "key"]
    assert key_obs and key_obs[0].status == "unknown"


def test_plan_blocks_unknown_install(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    steps = ai.plan(ai.load_catalog(root=root))
    by_id = {s["id"]: s for s in steps}
    assert by_id["tool-a"]["action"] == "blocked"
    assert by_id["tool-b"]["action"] == "skip"
    assert by_id["tool-c"]["action"] == "would-install"


def test_refuses_when_ade_toml_present(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "ade.toml").write_text("schema_version = 1\n")
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    with pytest.raises(ai.InstallError, match="refuse transitional"):
        ai.load_catalog(root=root)


def test_duplicate_component_id_rejected(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\nid = \"x\"\nclass = \"hard\"\n"
        "[[component]]\nid = \"x\"\nclass = \"hard\"\n"
    )
    with pytest.raises(ai.InstallError, match="duplicate"):
        ai.load_catalog(root=root)


def test_offered_requires_chosen(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n[[component]]\nid = \"h\"\nclass = \"offered\"\n"
    )
    with pytest.raises(ai.InstallError, match="chosen"):
        ai.load_catalog(root=root)


def test_cli_catalog_and_plan_json(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    c = _run("catalog", "--json", root=root)
    assert c.returncode == 0, c.stderr
    assert len(json.loads(c.stdout)["component"]) == 3
    p = _run("plan", "--json", root=root)
    assert p.returncode == 0, p.stderr
    assert "print-only" in json.loads(p.stdout)["note"]


def test_commands_make_no_writes(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    dest = root / "config" / "install.toml"
    dest.write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    before = dest.read_bytes()
    mtime = dest.stat().st_mtime_ns
    for cmd in ("check", "catalog", "plan", "doctor"):
        _run(cmd, "--json", root=root)
    assert dest.read_bytes() == before
    assert dest.stat().st_mtime_ns == mtime
