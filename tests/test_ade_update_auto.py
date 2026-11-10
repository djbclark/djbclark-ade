"""S4 ade-update --auto: observe-only exit 5, or --apply-checkout for this repo."""
from __future__ import annotations

import importlib.machinery
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AUTO = REPO / "bin" / "ade-update-auto"
UPDATE = REPO / "bin" / "ade-update"


def _load_auto():
    loader = importlib.machinery.SourceFileLoader("ade_update_auto", str(AUTO))
    mod = types.ModuleType(loader.name)
    loader.exec_module(mod)
    return mod


def test_observe_then_not_implemented(tmp_path):
    mod = _load_auto()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            assert "--check" in argv
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")
        if "ade-install" in str(argv[0]):
            assert "keys" in argv
            return subprocess.CompletedProcess(argv, 0, stdout="keys ok\n", stderr="")
        raise AssertionError(argv)

    update_bin = tmp_path / "ade-update"
    install_bin = tmp_path / "ade-install"
    update_bin.write_text("#!/bin/true\n")
    install_bin.write_text("#!/bin/true\n")
    rc = mod.run_auto(
        repo=tmp_path,
        as_json=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
    )
    assert rc == mod.EXIT_NOT_IMPLEMENTED
    assert any("--check" in c for c in calls)
    assert any("keys" in c for c in calls)
    assert not any(
        "ade-update" in c[0] and "--check" not in c for c in calls
    )


def test_apply_checkout_current_skips_apply(tmp_path):
    mod = _load_auto()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            assert "--check" in argv
            return subprocess.CompletedProcess(argv, 0, stdout="current\n", stderr="")
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
        apply_checkout=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
    )
    assert rc == mod.EXIT_OK
    assert sum(1 for c in calls if "ade-update" in c[0]) == 1  # check only


def test_apply_checkout_behind_runs_bare_update(tmp_path):
    mod = _load_auto()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            if "--check" in argv:
                return subprocess.CompletedProcess(argv, 10, stdout="behind\n", stderr="")
            # bare apply
            assert "--check" not in argv
            assert "--auto" not in argv
            return subprocess.CompletedProcess(argv, 0, stdout="applied\n", stderr="")
        if "ade-install" in str(argv[0]):
            return subprocess.CompletedProcess(argv, 0, stdout="keys ok\n", stderr="")
        raise AssertionError(argv)

    update_bin = tmp_path / "ade-update"
    install_bin = tmp_path / "ade-install"
    update_bin.write_text("#!/bin/true\n")
    install_bin.write_text("#!/bin/true\n")
    rc = mod.run_auto(
        repo=tmp_path,
        apply_checkout=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
    )
    assert rc == mod.EXIT_OK
    update_calls = [c for c in calls if "ade-update" in c[0]]
    assert len(update_calls) == 2
    assert "--check" in update_calls[0]
    assert "--check" not in update_calls[1]


def test_env_apply_opt_in(tmp_path, monkeypatch):
    mod = _load_auto()
    monkeypatch.setenv("ADE_UPDATE_AUTO_APPLY", "1")
    assert mod._env_apply() is True
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            if "--check" in argv:
                return subprocess.CompletedProcess(argv, 10, stdout="behind\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="applied\n", stderr="")
        if "ade-install" in str(argv[0]):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(argv)

    update_bin = tmp_path / "ade-update"
    install_bin = tmp_path / "ade-install"
    update_bin.write_text("#!/bin/true\n")
    install_bin.write_text("#!/bin/true\n")
    rc = mod.run_auto(
        repo=tmp_path,
        apply_checkout=mod._env_apply(),
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
    )
    assert rc == mod.EXIT_OK
    assert any("ade-update" in c[0] and "--check" not in c for c in calls)


def test_ade_update_auto_flag_dispatches_and_refuses_with_check():
    r = subprocess.run(
        [sys.executable, str(UPDATE), "--auto", "--check", "--repo", str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "mutually exclusive" in (r.stderr or "")


def test_ade_update_apply_checkout_requires_auto():
    r = subprocess.run(
        [sys.executable, str(UPDATE), "--apply-checkout", "--repo", str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "--apply-checkout requires --auto" in (r.stderr or "")


def test_inventory_row_still_planned():
    sys.path.insert(0, str(REPO / "bin"))
    import ade_install as ai  # noqa: E402

    catalog = ai.load_catalog(root=REPO)
    by_name = {j["name"]: j for j in catalog.jobs}
    row = by_name["update-auto"]
    assert "plist pending" in (row.get("schedule") or "")
    assert row.get("plist") in (None, "")
    assert "apply-checkout" in (row.get("notes") or "") or "stub" in (row.get("notes") or "").lower()
