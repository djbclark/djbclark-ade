"""S4 ade-update --auto: observe-only exit 5, or --apply-checkout for this repo."""
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


# --- S4 scheduled apply (options 2-3, operator ruling 2026-11-12) ---


def _bins(tmp_path):
    update_bin = tmp_path / "ade-update"
    install_bin = tmp_path / "ade-install"
    update_bin.write_text("#!/bin/true\n")
    install_bin.write_text("#!/bin/true\n")
    return update_bin, install_bin


def _auto_run_factory(check_rc=0):
    """Fake run: ade-update --check returns check_rc; bare update and deps succeed."""
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            if "--check" in argv:
                return subprocess.CompletedProcess(argv, check_rc, stdout="behind\n", stderr="")
            assert "--check" not in argv
            return subprocess.CompletedProcess(argv, 0, stdout="applied\n", stderr="")
        if "ade-install" in str(argv[0]):
            if "keys" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="keys ok\n", stderr="")
            assert "update" in argv and "--yes" in argv
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps({"mode": "apply", "exit": 0, "doctor": {"after_fail": []}}), stderr="",
            )
        raise AssertionError(argv)

    return fake_run, calls


def test_apply_full_busy_fleet_defers_durably(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    fake_run, calls = _auto_run_factory()
    state = tmp_path / "state" / "update-auto.json"
    pings: list[str] = []
    rc = mod.run_auto(
        repo=tmp_path,
        as_json=False,
        apply_full=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: ([{"id": "a1", "short": "a1", "name": "W2 fixer", "status": "running"}], None),
        ping_fn=pings.append,
        state_path=state,
    )
    assert rc == mod.EXIT_DEFERRED
    # no writes happened: no bare update, no dependency update
    assert not any("ade-update" in c[0] and "--check" not in c for c in calls)
    assert not any("--yes" in c for c in calls)
    assert pings == []  # deferral is normal operation, not a failure
    saved = json.loads(state.read_text())
    assert saved["status"] == "deferred"
    assert "mid-turn" in saved["reason"]
    assert saved["behind"] is False


def test_apply_full_unknown_fleet_defers(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    fake_run, calls = _auto_run_factory()
    state = tmp_path / "state" / "update-auto.json"
    rc = mod.run_auto(
        repo=tmp_path,
        apply_full=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: (None, "no `paseo` on PATH"),
        ping_fn=lambda msg: None,
        state_path=state,
    )
    assert rc == mod.EXIT_DEFERRED
    saved = json.loads(state.read_text())
    assert saved["status"] == "deferred"
    assert "fleet-unknown" in saved["reason"]


def test_apply_full_idle_applies_checkout_and_deps(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    fake_run, calls = _auto_run_factory(check_rc=10)
    state = tmp_path / "state" / "update-auto.json"
    pings: list[str] = []
    rc = mod.run_auto(
        repo=tmp_path,
        apply_full=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: ([], None),
        ping_fn=pings.append,
        state_path=state,
    )
    assert rc == mod.EXIT_OK
    assert any("ade-update" in c[0] and "--check" not in c for c in calls)
    deps_calls = [c for c in calls if "ade-install" in c[0] and "--yes" in c]
    assert deps_calls == [[str(install_bin), "update", "--root", str(tmp_path), "--yes", "--json"]]
    assert pings == []
    saved = json.loads(state.read_text())
    assert saved["status"] == "applied"


def test_apply_full_deps_failure_pings_once_and_records(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            return subprocess.CompletedProcess(argv, 0, stdout="current\n", stderr="")
        if "keys" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="keys ok\n", stderr="")
        # dependency update fails after its internal doctor retry
        return subprocess.CompletedProcess(
            argv, 1, stdout=json.dumps({"mode": "apply", "exit": 1, "doctor": {"after_fail": ["pi"]}}), stderr="",
        )

    state = tmp_path / "state" / "update-auto.json"
    pings: list[str] = []
    rc = mod.run_auto(
        repo=tmp_path,
        apply_full=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: ([], None),
        ping_fn=pings.append,
        state_path=state,
    )
    assert rc == 1
    assert len(pings) == 1  # one ping per failure event
    assert "FAILED" in pings[0]
    saved = json.loads(state.read_text())
    assert saved["status"] == "failed"
    assert "ade-install update failed" in saved["detail"]


def test_apply_full_checkout_failure_pings_and_skips_deps(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        if "ade-update" in str(argv[0]):
            if "--check" in argv:
                return subprocess.CompletedProcess(argv, 10, stdout="behind\n", stderr="")
            return subprocess.CompletedProcess(argv, 3, stdout="", stderr="git conflict")
        if "keys" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(argv)

    state = tmp_path / "state" / "update-auto.json"
    pings: list[str] = []
    rc = mod.run_auto(
        repo=tmp_path,
        apply_full=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: ([], None),
        ping_fn=pings.append,
        state_path=state,
    )
    assert rc == 3
    assert len(pings) == 1
    assert not any("--yes" in c for c in calls)  # deps never ran
    saved = json.loads(state.read_text())
    assert saved["status"] == "failed"


def test_apply_full_intent_recorded_before_apply(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    fake_run, _calls = _auto_run_factory(check_rc=10)
    state = tmp_path / "state" / "update-auto.json"
    seen: list[str] = []

    real_run = fake_run

    def spy_run(argv, **kwargs):
        if any("--yes" in str(a) for a in argv):
            saved = json.loads(state.read_text())
            seen.append(saved["status"])  # record state when the first dependency write begins
        return real_run(argv, **kwargs)

    rc = mod.run_auto(
        repo=tmp_path,
        apply_full=True,
        run=spy_run,
        update_bin=update_bin,
        install_bin=install_bin,
        paseo_ls=lambda: ([], None),
        ping_fn=lambda msg: None,
        state_path=state,
    )
    assert rc == mod.EXIT_OK
    assert seen == ["applying"]  # pending intent was durable before the write


def test_apply_checkout_stays_checkout_only(tmp_path):
    mod = _load_auto()
    update_bin, install_bin = _bins(tmp_path)
    fake_run, calls = _auto_run_factory(check_rc=10)
    state = tmp_path / "state" / "update-auto.json"
    rc = mod.run_auto(
        repo=tmp_path,
        apply_checkout=True,
        run=fake_run,
        update_bin=update_bin,
        install_bin=install_bin,
        state_path=state,
    )
    assert rc == mod.EXIT_OK
    assert not any("--yes" in c for c in calls)  # option 1: no dependency updates
    assert not state.exists()  # option 1 writes no auto state


def test_apply_flag_via_ade_update_requires_auto():
    r = subprocess.run(
        [sys.executable, str(UPDATE), "--apply", "--repo", str(REPO)],
        capture_output=True, text=True, check=False,
    )
    assert r.returncode == 2
    assert "--apply requires --auto" in (r.stderr or "")


def test_inventory_row_documents_apply():
    sys.path.insert(0, str(REPO / "bin"))
    import ade_install as ai  # noqa: E402

    catalog = ai.load_catalog(root=REPO)
    row = {j["name"]: j for j in catalog.jobs}["update-auto"]
    assert "plist pending" in (row.get("schedule") or "")
    assert row.get("plist") in (None, "")
    assert "--apply" in (row.get("notes") or "")
    assert "mid-turn" in (row.get("notes") or "")
