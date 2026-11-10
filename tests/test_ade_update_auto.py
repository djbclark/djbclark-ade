"""S4 first-slice ade-update-auto: mid-turn skip, apply + keys."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AUTO = REPO / "bin" / "ade-update-auto"
UPDATE = REPO / "bin" / "ade-update"


def _load_auto():
    import importlib.machinery
    import types

    loader = importlib.machinery.SourceFileLoader("ade_update_auto", str(AUTO))
    mod = types.ModuleType(loader.name)
    loader.exec_module(mod)
    return mod


def test_deferred_when_live_agents(tmp_path, monkeypatch):
    mod = _load_auto()

    def fake_run(argv, **kwargs):
        if argv[:1] == ["paseo"] or (argv and str(argv[0]).endswith("paseo")):
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps([{"id": "a1", "status": "running"}]), stderr=""
            )
        raise AssertionError(f"unexpected argv {argv}")

    rc = mod.run_auto(
        repo=tmp_path,
        as_json=True,
        which=lambda name: "/usr/bin/paseo" if name == "paseo" else None,
        run=fake_run,
    )
    assert rc == 0


def test_runs_update_then_keys_when_idle(tmp_path, monkeypatch, capsys):
    mod = _load_auto()

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "paseo" in str(argv[0]) or argv[:1] == ["paseo"]:
            return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")
        if "ade-update" in str(argv[0]):
            return subprocess.CompletedProcess(argv, 0, stdout="ade-update: ok\n", stderr="")
        if "ade-install" in str(argv[0]):
            return subprocess.CompletedProcess(argv, 0, stdout="keys ok\n", stderr="")
        raise AssertionError(argv)

    update_bin = tmp_path / "ade-update"
    install_bin = tmp_path / "ade-install"
    update_bin.write_text("#!/bin/true\n")
    install_bin.write_text("#!/bin/true\n")
    rc = mod.run_auto(
        repo=tmp_path,
        as_json=False,
        which=lambda name: "/usr/bin/paseo" if name == "paseo" else None,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
    )
    assert rc == 0
    assert any("ade-update" in c[0] for c in calls)
    assert any("ade-install" in c[0] and "keys" in c for c in calls)


def test_ade_update_auto_flag_dispatches():
    # --auto --check refuses
    r = subprocess.run(
        [sys.executable, str(UPDATE), "--auto", "--check", "--repo", str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "mutually exclusive" in (r.stderr or "")


def test_inventory_row_has_plist():
    sys.path.insert(0, str(REPO / "bin"))
    import ade_install as ai  # noqa: E402

    catalog = ai.load_catalog(root=REPO)
    by_name = {j["name"]: j for j in catalog.jobs}
    row = by_name["update-auto"]
    assert row["label"] == "com.djbclark.update-auto"
    assert row["plist"].endswith("com.djbclark.update-auto.plist")
    assert row["command"] == "bin/ade-update-auto"
    assert (REPO / row["plist"]).is_file()
