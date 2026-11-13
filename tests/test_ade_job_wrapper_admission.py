"""W21c: the ade-job-run wrapper + per-label admission lock let reconcile reload/remove a LOADED launchd job safely.

Offline: the fake launchctl of the W21b tests (a directory of marker files), real flock, a real wrapper process. Contract:
no kill, no foreign write or delete, never leave a ledger-owned loaded job unloaded without a durable recovery record."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_install as ai  # noqa: E402
import ade_sched as S  # noqa: E402
from test_ade_jobs_reconcile import _mini_catalog  # noqa: E402
from test_ade_sched_launchd_admission import KILLERS, LABEL, ld  # noqa: E402,F401  (ld is a fixture)

WRAPPER = BIN / "ade-job-run"


def _wrap(root: Path, label: str = LABEL, state: Path | None = None) -> None:
    """Route the mini catalog's plist through the wrapper, as config/launchd/ now does (the stub only has to be executable)."""
    stub = root / "bin" / "ade-job-run"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    plist = root / "config" / "launchd" / f"{label}.plist"
    text = plist.read_text()
    old = "<string>__ADE__/bin/deadline</string>"
    assert old in text
    text = text.replace(old, f"<string>__ADE__/bin/ade-job-run</string><string>{label}</string><string>--</string>{old}")
    if state is not None:   # the wrapper's own environment decides its lock directory (launchd plists set neither normally)
        text = text.replace("<key>DEADLINE_STATE_DIR</key>", f"<key>ADE_JOBS_STATE_DIR</key><string>{state}</string>\n    <key>DEADLINE_STATE_DIR</key>")
    plist.write_text(text)


def _drift(root: Path, label: str = LABEL) -> None:
    plist = root / "config" / "launchd" / f"{label}.plist"
    plist.write_text(plist.read_text().replace("<integer>60</integer>", "<integer>120</integer>"))


def _reconcile(ld, root, catalog, **kw):
    return S.reconcile(catalog.jobs, catalog.retired_jobs, dry_run=kw.pop("dry_run", False), backend="launchd", root=root,
                       ade=root, env=ld.env, state_dir=ld.state, names={"deadline-sweep"}, live=S.LiveScan("launchd", ()),
                       platform_name="mac", native_admission=True, **kw)


def _installed_wrapped(ld):
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    plist = ld.agents / f"{LABEL}.plist"
    assert S.wrapper_route_problem(plist.read_bytes(), LABEL) is None
    ld.reset()
    return root, catalog, plist


def _entry(ld):
    return S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["deadline-sweep"]


def _lock_is_free(ld, label=LABEL) -> bool:
    fd = S.acquire_admission_lock(label, exclusive=True, state_dir=ld.state)
    S.release_admission_lock(fd)
    return fd is not None


def _hold_a_run(ld):
    """A real wrapped run: `ade-job-run LABEL -- sleep 60` holds the shared lock until it is stopped."""
    p = subprocess.Popen([sys.executable, str(WRAPPER), LABEL, "--", "sleep", "60"], env=ld.env,
                         stderr=subprocess.DEVNULL)
    for _ in range(100):
        if not _lock_is_free(ld):
            return p
        time.sleep(0.1)
    p.kill()
    raise AssertionError("the wrapped run never took its shared lock")


# ------------------------------------------------------------------------------------------------ the wrapper

def test_wrapper_runs_the_command_holding_a_shared_lock_and_skips_while_reconcile_holds_it(ld, tmp_path):
    marker = tmp_path / "ran"
    cmd = [sys.executable, str(WRAPPER), LABEL, "--", "/usr/bin/touch", str(marker)]
    excl = S.acquire_admission_lock(LABEL, exclusive=True, state_dir=ld.state)
    assert excl is not None
    r = subprocess.run(cmd, env=ld.env, capture_output=True, text=True, timeout=30)
    S.release_admission_lock(excl)
    assert r.returncode == 0 and not marker.exists()
    assert r.stderr.count("\n") == 1 and "reconcile holds the admission lock" in r.stderr   # exactly one log line
    r = subprocess.run(cmd, env=ld.env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and marker.exists() and r.stderr == ""


def test_a_wrapped_run_in_flight_blocks_the_exclusive_lock_and_a_finished_one_does_not(ld):
    run = _hold_a_run(ld)
    try:
        assert S.acquire_admission_lock(LABEL, exclusive=True, state_dir=ld.state) is None   # busy, never waited on
    finally:
        run.terminate()
        run.wait(timeout=10)
    assert _lock_is_free(ld)


def test_wrapper_refuses_to_run_unlocked_and_rejects_bad_usage(ld, tmp_path):
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("x")
    env = {**ld.env, "ADE_JOBS_STATE_DIR": str(blocker)}
    marker = tmp_path / "ran"
    r = subprocess.run([sys.executable, str(WRAPPER), LABEL, "--", "/usr/bin/touch", str(marker)], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 75 and not marker.exists() and "not running" in r.stderr
    for argv in ([LABEL], [LABEL, "/bin/true"], ["bad label", "--", "/bin/true"]):
        r = subprocess.run([sys.executable, str(WRAPPER), *argv], env=ld.env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 2


@pytest.mark.parametrize("edit,why", [
    (lambda d: d.update(Program="/bin/sh"), "Program"),
    (lambda d: d.update(ProgramArguments=["/bin/true"]), "ProgramArguments"),
    (lambda d: d.update(Label="other"), "Label"),
    (lambda d: d["ProgramArguments"].__setitem__(1, "other"), "does not route"),
    (lambda d: d["ProgramArguments"].__setitem__(2, "-x"), "does not route"),
    (lambda d: d["ProgramArguments"].__setitem__(0, "/nonexistent/ade-job-run"), "not an executable"),
])
def test_wrapper_route_proof_is_read_from_the_installed_bytes(tmp_path, edit, why):
    import plistlib
    stub = tmp_path / "ade-job-run"
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)
    d = {"Label": LABEL, "ProgramArguments": [str(stub), LABEL, "--", "/bin/true"]}
    assert S.wrapper_route_problem(plistlib.dumps(d), LABEL) is None
    edit(d)
    assert why in (S.wrapper_route_problem(plistlib.dumps(d), LABEL) or "")
    assert S.wrapper_route_problem(b"not a plist", LABEL) is not None


# ------------------------------------------------------------------------------------------------ reload under the lock

def test_idle_wrapped_loaded_job_is_reloaded_under_the_exclusive_lock(ld):
    root, catalog, plist = _installed_wrapped(ld)
    before = plist.read_bytes()
    _drift(root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "installed" for r in rows), rows
    assert plist.read_bytes() != before and b"<integer>120</integer>" in plist.read_bytes()
    assert ld.verbs()[:1] == ["print"] and ld.verbs().count("bootout") == 1 and ld.verbs().count("bootstrap") == 1
    assert ld.loaded() and _entry(ld)["status"] == "committed"
    assert _entry(ld)["artifact_hash"] == S.artifact_hash({plist: plist.read_text()})
    assert _lock_is_free(ld) and not list((ld.state / "admission").glob("*.recovery.json"))


def test_a_run_in_flight_defers_the_reload_with_no_bootout_and_no_write(ld):
    root, catalog, plist = _installed_wrapped(ld)
    before = plist.read_bytes()
    _drift(root)
    run = _hold_a_run(ld)
    try:
        ld.reset()
        rows, rc = _reconcile(ld, root, catalog)
    finally:
        run.terminate()
        run.wait(timeout=10)
    assert rc == 6 and any(r["action"] == "deferred" and "run of" in r["detail"] for r in rows), rows
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs()) and not ld.killed()
    assert _entry(ld)["status"] == "committed"


def test_non_wrapped_loaded_job_still_defers_and_an_old_install_is_not_reloaded(ld):
    root = _mini_catalog(ld.tmp)                      # installed with the OLD bytes: no wrapper
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    plist = ld.agents / f"{LABEL}.plist"
    old = plist.read_bytes()
    _wrap(root)                                       # the catalog moves to the wrapper: the render now differs
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("ade-job-run" in r["detail"] for r in rows if r["action"] == "deferred"), rows
    assert plist.read_bytes() == old and ld.loaded() and set(ld.verbs()) <= {"print"}


def test_wrapped_job_the_ledger_does_not_own_defers(ld):
    root, catalog, plist = _installed_wrapped(ld)
    (ld.state / "jobs.json").unlink()                 # nobody recorded ownership of this plist
    _drift(root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and "ledger" in " ".join(r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"} and b"<integer>60</integer>" in plist.read_bytes()


def test_loaded_from_another_path_defers(ld):
    root, catalog, plist = _installed_wrapped(ld)
    (ld.root / "path").mkdir(exist_ok=True)
    (ld.root / "path" / LABEL).write_text("/elsewhere/other.plist")   # launchd loaded this label from a different file
    _drift(root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("loaded from" in r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"} and ld.loaded()


def test_failure_after_bootout_restores_the_prior_bytes_and_reloads_them(ld):
    root, catalog, plist = _installed_wrapped(ld)
    before, prior_entry = plist.read_bytes(), _entry(ld)
    _drift(root)
    ld.mark("fail_once", "bootstrap")                 # the NEW definition fails to load; the restore succeeds
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and any(r["action"] == "failed" and "prior definition is loaded again" in r["detail"] for r in rows), rows
    assert plist.read_bytes() == before and ld.loaded() and not ld.killed()
    assert _entry(ld) == prior_entry                  # still ADE's, still the old artifact
    assert _lock_is_free(ld) and not list((ld.state / "admission").glob("*.recovery.json"))


def test_failed_restore_keeps_a_durable_record_and_the_next_reconcile_loads_the_job(ld):
    root, catalog, plist = _installed_wrapped(ld)
    before = plist.read_bytes()
    _drift(root)
    ld.fail("bootstrap")                              # nothing can be bootstrapped: not the new bytes, not the prior
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and any("recovery record kept" in r["detail"] for r in rows), rows
    rec = ld.state / "admission" / f"{LABEL}.recovery.json"
    assert rec.exists() and (ld.state / "admission" / f"{LABEL}.prior.plist").read_bytes() == before
    assert not ld.loaded() and plist.exists() and _lock_is_free(ld)
    dry, _ = _reconcile(ld, root, catalog, dry_run=True)
    assert any(r["action"] == "would-recover" for r in dry)
    (ld.root / "fail" / "bootstrap").unlink()         # launchd works again
    rows, rc = _reconcile(ld, root, catalog)
    assert any(r["action"] == "recover" and r["ok"] for r in rows), rows
    assert ld.loaded() and not rec.exists()
    assert _entry(ld)["status"] == "committed"


def test_sigterm_between_bootout_and_bootstrap_leaves_a_recovery_record(ld):
    root, catalog, plist = _installed_wrapped(ld)
    before = plist.read_bytes()
    _drift(root)
    ld.flag("sigterm_after_bootout")                  # the fake bootout terminates its parent: the reconcile process
    child = (
        "import json, sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
        "import ade_install as ai, ade_sched as S\n"
        "root, state = sys.argv[3], sys.argv[4]\n"
        "c = ai.load_catalog(root=__import__('pathlib').Path(root))\n"
        "S.reconcile(c.jobs, c.retired_jobs, dry_run=False, backend='launchd', root=__import__('pathlib').Path(root),\n"
        "            ade=__import__('pathlib').Path(root), state_dir=__import__('pathlib').Path(state), names={'deadline-sweep'},\n"
        "            live=S.LiveScan('launchd', ()), platform_name='mac', native_admission=True)\n")
    p = subprocess.run([sys.executable, "-c", child, str(BIN), str(REPO / "tests"), str(root), str(ld.state)],
                       env=ld.env, capture_output=True, text=True, timeout=60)
    assert p.returncode == -signal.SIGTERM, (p.returncode, p.stderr)
    rec = ld.state / "admission" / f"{LABEL}.recovery.json"
    assert rec.exists() and not ld.loaded()           # unloaded, but a durable record says how to load it again
    assert json.loads(rec.read_text())["label"] == LABEL
    assert (ld.state / "admission" / f"{LABEL}.prior.plist").read_bytes() == before
    (ld.root / "sigterm_after_bootout").unlink()
    rows, rc = _reconcile(ld, root, catalog)          # the next reconcile acts on the record
    assert any(r["action"] == "recover" and r["ok"] for r in rows), rows
    assert not rec.exists() and ld.loaded()


# ------------------------------------------------------------------------------------------------ removal under the lock

def _wrapped_retired(ld, loaded=True):
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state)
    catalog = ai.load_catalog(root=root)
    label = "com.djbclark.skillopt-sleep"
    plist = ld.agents / f"{label}.plist"
    import plistlib
    pa = [str(root / "bin" / "ade-job-run"), label, "--", "/bin/true"]
    plist.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": pa,
                                      "EnvironmentVariables": {"ADE_JOBS_STATE_DIR": str(ld.state)}}))
    if loaded:
        ld.mark("loaded", label)
        ld.mark("args", label, "\n".join(pa))
        (ld.root / "path").mkdir(exist_ok=True)
        (ld.root / "path" / label).write_text(str(plist))
    ledger = S.empty_jobs_ledger(env=ld.env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep", "label": label, "owner": "djbclark-ade", "backend": "launchd", "scope": "user",
        "paths": [str(plist)], "generation": 1, "status": "committed",
        "artifact_hash": S.artifact_hash({plist: plist.read_text()}),
    }
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    return root, catalog, label, plist


def _remove(ld, root, catalog, label):
    return S.reconcile(catalog.jobs, catalog.retired_jobs, dry_run=False, backend="launchd", root=root, ade=root, env=ld.env,
                       state_dir=ld.state, names={"skillopt-sleep"},
                       live=S.LiveScan("launchd", (S.LiveJob(label, "launchd", "generated", True),)),
                       platform_name="mac", native_admission=True)


@pytest.mark.parametrize("loaded", [False, True])
def test_wrapped_ledger_owned_hash_matching_job_is_removed_under_the_lock(ld, loaded):
    root, catalog, label, plist = _wrapped_retired(ld, loaded=loaded)
    rows, rc = _remove(ld, root, catalog, label)
    assert rc == 0 and not plist.exists() and not ld.loaded(label), rows
    assert ("bootout" in ld.verbs()) is loaded and not ld.killed(label)
    assert _lock_is_free(ld, label) and not list((ld.state / "admission").glob("*.recovery.json"))
    assert "skillopt-sleep" not in S.load_jobs_ledger(ld.state, env=ld.env)["entries"]


def test_removal_defers_while_a_run_is_in_flight(ld):
    root, catalog, label, plist = _wrapped_retired(ld)
    run = subprocess.Popen([sys.executable, str(WRAPPER), label, "--", "sleep", "60"], env=ld.env, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if not _lock_is_free(ld, label):
                break
            time.sleep(0.1)
        rows, rc = _remove(ld, root, catalog, label)
    finally:
        run.terminate()
        run.wait(timeout=10)
    assert rc == 6 and plist.exists() and ld.loaded(label) and not KILLERS & set(ld.verbs()), rows
    assert "skillopt-sleep" in S.load_jobs_ledger(ld.state, env=ld.env)["entries"]


def test_removal_of_a_replaced_file_is_not_deleted(ld):
    root, catalog, label, plist = _wrapped_retired(ld, loaded=False)
    entry_hash = S.artifact_hash({plist: plist.read_text()})
    plist.write_bytes(plist.read_bytes() + b"<!-- a different writer -->")     # same route, different bytes: not the ledger's
    rows, rc = _remove(ld, root, catalog, label)
    assert rc == 6 and plist.exists() and b"different writer" in plist.read_bytes(), rows
    assert entry_hash != S.artifact_hash({plist: plist.read_text()})
    assert "bootout" not in ld.verbs()


def test_installed_bytes_that_differ_from_the_ledger_artifact_defer_untouched(ld):
    root, catalog, plist = _installed_wrapped(ld)
    plist.write_bytes(plist.read_bytes() + b"\n<!-- hand edit -->\n")          # still routes through the wrapper, not ADE's bytes
    edited = plist.read_bytes()
    _drift(root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("ledger" in r["detail"] for r in rows), rows
    assert plist.read_bytes() == edited and set(ld.verbs()) <= {"print"} and ld.loaded()


# ------------------------------------------------------------------------------------------------ adversary round 1 (BLOCK)

def test_file_says_wrapper_but_the_loaded_definition_is_unwrapped_defers(ld):
    # F1: `install --no-activate` wrote the wrapped file while the old, unwrapped definition stayed loaded.
    root, catalog, plist = _installed_wrapped(ld)
    (ld.root / "args").mkdir(exist_ok=True)
    (ld.root / "args" / LABEL).write_text("/old/ade/bin/deadline\nsweep\n--\nx")        # what launchd actually runs
    _drift(root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("LOADED definition" in r["detail"] for r in rows), rows
    assert not KILLERS & set(ld.verbs()) and ld.loaded()


def test_parse_launchd_definition_reads_program_and_arguments():
    out = "gui/501/x = {\n\tpath = /p\n\tprogram = /a\n\targuments = {\n\t\t/a\n\t\tx\n\t\t--\n\t}\n\tinherited environment = {\n\t\tK => v\n\t}\n}\n"
    assert S.parse_launchd_definition(out) == ("/a", ["/a", "x", "--"])
    assert S.parse_launchd_definition("gui/501/x = {\n\tstate = running\n}\n") == (None, None)


def test_wrapper_that_would_lock_elsewhere_defers(ld):
    # F2: the plist does not set ADE_JOBS_STATE_DIR, so the wrapper would lock under HOME, not under reconcile's state dir.
    root = _mini_catalog(ld.tmp)
    _wrap(root)                                                    # no state env in the plist
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    _drift(root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("would lock in" in r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"}


def test_failure_before_the_unload_defers_and_keeps_the_committed_row(ld, monkeypatch):
    # F3: a recovery-record write failure (ENOSPC, ...) happens before bootout: nothing changed, ownership must survive.
    root, catalog, plist = _installed_wrapped(ld)
    before, prior_entry = plist.read_bytes(), _entry(ld)
    _drift(root)

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(S, "write_recovery_record", boom)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and "bootout" not in ld.verbs() and plist.read_bytes() == before and ld.loaded(), rows
    assert _entry(ld) == prior_entry and _lock_is_free(ld)


def test_restore_never_overwrites_a_file_that_is_not_ours(ld):
    # F4: the new bytes were replaced by another writer before the rollback: the restore fails and the record stays.
    root, catalog, plist = _installed_wrapped(ld)
    _drift(root)
    ld.mark("fail_once", "bootstrap")
    orig = S._atomic_write_bytes

    def write_then_foreign(path, data, mode=0o600):
        orig(path, data, mode)
        if path == plist:
            path.write_bytes(b"<plist><!-- foreign --></plist>")   # someone else replaces our new bytes
    import unittest.mock as m
    with m.patch.object(S, "_atomic_write_bytes", write_then_foreign):
        rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and b"foreign" in plist.read_bytes() and not ld.loaded(), rows
    assert (ld.state / "admission" / f"{LABEL}.recovery.json").exists()


def test_recovery_ignores_a_label_the_ledger_does_not_own(ld):
    # F5: a stray record must not make reconcile load an arbitrary plist.
    root, catalog, plist = _installed_wrapped(ld)
    label = "com.djbclark.not-ours"
    other = ld.agents / f"{label}.plist"
    other.write_bytes(b"<plist/>")
    S.write_recovery_record(label, action="reload", plist=other, prior=b"<plist/>", new_sha=None, state_dir=ld.state, env=ld.env)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert any(r["action"] == "failed" and "no ADE ledger row" in r["detail"] for r in rows), rows
    assert "bootstrap" not in ld.verbs() and not ld.loaded(label)
    assert (ld.state / "admission" / f"{label}.recovery.json").exists()


def test_removal_interrupted_after_the_unlink_completes_its_ledger_row(ld):
    # F6: bootout + unlink done, record not cleared, ledger still pending-remove.
    root, catalog, label, plist = _wrapped_retired(ld, loaded=False)
    S.write_recovery_record(label, action="remove", plist=plist, prior=plist.read_bytes(), new_sha=None, state_dir=ld.state, env=ld.env)
    plist.unlink()
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["skillopt-sleep"]["status"] = "pending-remove"
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    rows, rc = _remove(ld, root, catalog, label)
    assert rc == 0 and any(r["action"] == "recover" and r["ok"] for r in rows), rows
    assert "skillopt-sleep" not in S.load_jobs_ledger(ld.state, env=ld.env)["entries"]
    assert not (ld.state / "admission" / f"{label}.recovery.json").exists() and "bootstrap" not in ld.verbs()


def test_killed_before_the_unload_leaves_a_pending_row_that_the_next_run_repairs(ld):
    # round 2, item 2: SIGTERM after the pending row is saved but before bootout; the old definition stays loaded.
    root, catalog, plist = _installed_wrapped(ld)
    prior_entry = _entry(ld)
    S.write_recovery_record(LABEL, action="reload", plist=plist, prior=plist.read_bytes(), new_sha="0" * 64, state_dir=ld.state, env=ld.env)
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"] = {**prior_entry, "status": "pending", "artifact_hash": "f" * 64}
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "recover" for r in rows), rows
    assert _entry(ld)["status"] == "committed" and _entry(ld)["artifact_hash"] == prior_entry["artifact_hash"]
    assert not (ld.state / "admission" / f"{LABEL}.recovery.json").exists() and ld.loaded()


def test_relative_state_dir_in_the_plist_never_matches_reconciles_lock_dir(tmp_path):
    import plistlib
    d = plistlib.dumps({"Label": LABEL, "EnvironmentVariables": {"ADE_JOBS_STATE_DIR": "rel/state"}})
    assert S.wrapper_lock_dir(d, os.getuid()) == Path("/nonexistent/relative-ADE_JOBS_STATE_DIR")


def test_ledger_artifact_is_rechecked_under_the_lock_before_the_unload(ld):
    root, catalog, plist = _installed_wrapped(ld)
    job = S.Job.from_plist(root / "config" / "launchd" / f"{LABEL}.plist", S.job_subst_from_row(
        next(j for j in catalog.jobs if j["name"] == "deadline-sweep"), root=root, env=ld.env, extra=None), ade=root)
    with pytest.raises(S.NativeDefer):
        S.reload_launchd_locked(job, "x", state_dir=ld.state, env=ld.env, expect_hash="0" * 64)
    assert "bootout" not in ld.verbs() and ld.loaded() and not list((ld.state / "admission").glob("*.recovery.json"))
