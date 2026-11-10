"""S4 ade-update --auto stub: observe-only then exit 5 not-implemented."""
from __future__ import annotations

import importlib.machinery
import json
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


def test_ade_update_auto_flag_dispatches_and_refuses_with_check():
    r = subprocess.run(
        [sys.executable, str(UPDATE), "--auto", "--check", "--repo", str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 2
    assert "mutually exclusive" in (r.stderr or "")


def test_inventory_row_still_planned():
    sys.path.insert(0, str(REPO / "bin"))
    import ade_install as ai  # noqa: E402

    catalog = ai.load_catalog(root=REPO)
    by_name = {j["name"]: j for j in catalog.jobs}
    row = by_name["update-auto"]
    assert "plist pending" in (row.get("schedule") or "")
    assert row.get("plist") in (None, "")
    assert "stub" in (row.get("notes") or "").lower() or "not-implemented" in (row.get("notes") or "")
