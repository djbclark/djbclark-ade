"""W21c: the ade-job-run wrapper + per-label admission lock let reconcile reload/remove a LOADED launchd job safely.

Offline: the fake launchctl of the W21b tests (a directory of marker files), real flock, a real wrapper process. Contract:
no kill, no foreign write or delete, never leave a ledger-owned loaded job unloaded without a durable recovery record."""
from __future__ import annotations

import json
import os
import re
import signal
import shutil
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


def _wrap(root: Path, label: str = LABEL, state: Path | None = None, *, stub: bool = False, lock_dir: Path | None = None,
          wrapper: Path | None = None) -> None:
    """Route the mini catalog's plist through the wrapper, as config/launchd/ now does. The ADE root gets the REAL
    bin/ade-job-run (and the ade_sched.py it imports), so admission proves the real wrapper; `stub=True` installs an
    exit-0 shell script instead (negative cases only). The lock directory is an absolute argv value."""
    (root / "bin").mkdir(exist_ok=True)
    if stub:
        (root / "bin" / "ade-job-run").write_text("#!/bin/sh\nexit 0\n")
    else:
        shutil.copy2(WRAPPER, root / "bin" / "ade-job-run")
        shutil.copy2(BIN / "ade_sched.py", root / "bin" / "ade_sched.py")
    (root / "bin" / "ade-job-run").chmod(0o755)
    plist = root / "config" / "launchd" / f"{label}.plist"
    text = plist.read_text()
    old = "<string>__ADE__/bin/deadline</string>"
    assert old in text
    where = lock_dir if lock_dir is not None else (state / "admission" if state is not None else None)
    assert where is not None
    prog = str(wrapper) if wrapper is not None else "__ADE__/bin/ade-job-run"
    text = text.replace(old, f"<string>{prog}</string><string>--lock-dir</string><string>{where}</string>"
                             f"<string>{label}</string><string>--</string>{old}")
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
    p = subprocess.Popen([sys.executable, str(WRAPPER), "--lock-dir", str(ld.state / "admission"), LABEL, "--", "sleep", "60"], env=ld.env,
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
    cmd = [sys.executable, str(WRAPPER), "--lock-dir", str(ld.state / "admission"), LABEL, "--", "/usr/bin/touch", str(marker)]
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
    marker = tmp_path / "ran"
    r = subprocess.run([sys.executable, str(WRAPPER), "--lock-dir", str(blocker), LABEL, "--", "/usr/bin/touch", str(marker)],
                       env=ld.env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 75 and not marker.exists() and "not running" in r.stderr
    d = str(ld.state / "admission")
    for argv in ([LABEL], [LABEL, "/bin/true"], ["bad label", "--", "/bin/true"], [LABEL, "--", "/bin/true"],   # the old form
                 ["--lock-dir", "relative", LABEL, "--", "/bin/true"], ["--lock-dir", d, "bad label", "--", "/bin/true"]):
        r = subprocess.run([sys.executable, str(WRAPPER), *argv], env=ld.env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 2


@pytest.mark.parametrize("edit,why", [
    (lambda d: d.update(Program="/bin/sh"), "Program"),
    (lambda d: d.update(ProgramArguments=["/bin/true"]), "ProgramArguments"),
    (lambda d: d.update(Label="other"), "Label"),
    (lambda d: d["ProgramArguments"].__setitem__(3, "other"), "does not route"),
    (lambda d: d["ProgramArguments"].__setitem__(4, "-x"), "does not route"),
    (lambda d: d["ProgramArguments"].__setitem__(1, "-x"), "does not route"),
    (lambda d: d["ProgramArguments"].__setitem__(2, "rel/state"), "does not route"),   # a relative lock dir is never proof
    (lambda d: d["ProgramArguments"].__setitem__(2, "/elsewhere"), "would lock in"),
    (lambda d: d["ProgramArguments"].__setitem__(0, "/nonexistent/ade-job-run"), "not an executable"),
])
def test_wrapper_route_proof_is_read_from_the_installed_bytes(tmp_path, edit, why):
    import plistlib
    stub = tmp_path / "ade-job-run"
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)
    d = {"Label": LABEL, "ProgramArguments": [str(stub), "--lock-dir", "/state/admission", LABEL, "--", "/bin/true"]}
    assert S.wrapper_route_problem(plistlib.dumps(d), LABEL, lock_dir=Path("/state/admission")) is None
    edit(d)
    assert why in (S.wrapper_route_problem(plistlib.dumps(d), LABEL, lock_dir=Path("/state/admission")) or "")
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
    _wrap(root, state=ld.state)                       # the catalog moves to the wrapper: the render now differs
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
        "S.canonical_admission_dir = lambda: __import__('pathlib').Path(state) / 'admission'\n"
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
    pa = [str(root / "bin" / "ade-job-run"), "--lock-dir", str(ld.state / "admission"), label, "--", "/bin/true"]
    plist.write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": pa}))
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
    run = subprocess.Popen([sys.executable, str(WRAPPER), "--lock-dir", str(ld.state / "admission"), label, "--", "sleep", "60"], env=ld.env, stderr=subprocess.DEVNULL)
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
    (ld.root / "args" / LABEL).write_text("/old/ade/bin/deadline\nsweep\n--\nx\ny\nz")        # what launchd actually runs
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
    # F2: the plist's --lock-dir is not the directory reconcile would lock.
    root = _mini_catalog(ld.tmp)
    _wrap(root, lock_dir=ld.tmp / "elsewhere")
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
    # F4: the new bytes were edited by another writer before the rollback: the restore fails and the record stays.
    root, catalog, plist = _installed_wrapped(ld)
    _drift(root)
    ld.mark("fail_once", "bootstrap")
    orig, calls = S._guarded_replace, []

    def write_then_foreign(path, data, **k):
        r = orig(path, data, **k)
        if path == plist and not calls:
            calls.append(1)
            path.write_bytes(b"<plist><!-- foreign --></plist>")   # someone else edits our new bytes in place
        return r
    import unittest.mock as m
    with m.patch.object(S, "_guarded_replace", write_then_foreign):
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
    _drift(root)   # the render differs again, so only a repaired (committed, owned) row lets the reload go through
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "recover" for r in rows) and any(r["action"] == "installed" for r in rows), rows
    assert _entry(ld)["status"] == "committed" and _entry(ld)["artifact_hash"] != prior_entry["artifact_hash"]
    assert b"<integer>120</integer>" in plist.read_bytes()
    assert not (ld.state / "admission" / f"{LABEL}.recovery.json").exists() and ld.loaded()


def test_ledger_artifact_is_rechecked_under_the_lock_before_the_unload(ld):
    root, catalog, plist = _installed_wrapped(ld)
    job = S.Job.from_plist(root / "config" / "launchd" / f"{LABEL}.plist", S.job_subst_from_row(
        next(j for j in catalog.jobs if j["name"] == "deadline-sweep"), root=root, env=ld.env, extra=None), ade=root)
    with pytest.raises(S.NativeDefer):
        S.reload_launchd_locked(job, "x", state_dir=ld.state, env=ld.env, expect_hash="0" * 64)
    assert "bootout" not in ld.verbs() and ld.loaded() and not list((ld.state / "admission").glob("*.recovery.json"))


# ------------------------------------------------------------------------------------------------ round 2 (review of #622)

def _job_of(ld, root, catalog):
    return S.Job.from_plist(root / "config" / "launchd" / f"{LABEL}.plist", S.job_subst_from_row(
        next(j for j in catalog.jobs if j["name"] == "deadline-sweep"), root=root, env=ld.env, extra=None), ade=root)


def _set_loaded_args(ld, **repl):
    """Rewrite the LOADED definition the fake launchd printed (what launchd actually runs), index -> value."""
    f = ld.root / "args" / LABEL
    lines = f.read_text().splitlines()
    for i, v in repl.items():
        lines[int(i[1:])] = v
    f.write_text("\n".join(lines))


def test_f1_the_lock_dir_comes_from_the_loaded_argv_not_the_disk_plist(ld, tmp_path):
    # F1: disk says reconcile's lock dir A, but the LOADED job (and its running work) uses C. The disk plist and the ledger
    # hash both pass; only the loaded argv tells the truth. Work holds C's lock: nothing may be booted out.
    root, catalog, plist = _installed_wrapped(ld)
    other = tmp_path / "other-admission"
    _set_loaded_args(ld, a2=str(other))
    run = subprocess.Popen([sys.executable, str(WRAPPER), "--lock-dir", str(other), LABEL, "--", "sleep", "60"],
                           env=ld.env, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if (other / f"{LABEL}.lock").exists() and S.acquire_admission_lock(LABEL, exclusive=True, lock_dir=other) is None:
                break
            time.sleep(0.1)
        before = plist.read_bytes()
        _drift(root)
        rows, rc = _reconcile(ld, root, catalog)
        assert rc == 6 and any("LOADED definition" in r["detail"] for r in rows), rows
        assert not KILLERS & set(ld.verbs()) and plist.read_bytes() == before and ld.loaded() and run.poll() is None
    finally:
        run.terminate()
        run.wait(timeout=10)


def test_f1_a_loaded_lock_dir_that_differs_from_the_disk_one_defers_even_when_the_file_is_consistent(ld, tmp_path):
    # The loaded job's argv is internally consistent with the file except for the lock dir only in the loaded copy.
    root, catalog, plist = _installed_wrapped(ld)
    out = f"x = {{\n\tpath = {plist}\n\tprogram = /w\n\targuments = {{\n\t\t/w\n\t\t--lock-dir\n\t\t/elsewhere\n\t\t{LABEL}\n\t\t--\n\t\tcmd\n\t}}\n}}\n"
    import plistlib
    d = plistlib.loads(plist.read_bytes())
    d["ProgramArguments"][0] = "/w"
    d["ProgramArguments"][2] = "/elsewhere"
    assert "locks in" in (S.loaded_definition_problem(out, plistlib.dumps(d), LABEL, lock_dir=ld.state / "admission") or "")
    d["ProgramArguments"][2] = str(ld.state / "admission")
    assert S.loaded_definition_problem(out, plistlib.dumps(d), LABEL, lock_dir=ld.state / "admission") is not None


def test_f2_a_printed_program_is_required():
    out = f"x = {{\n\targuments = {{\n\t\t/w\n\t\t--lock-dir\n\t\t/d\n\t\t{LABEL}\n\t\t--\n\t\tcmd\n\t}}\n}}\n"
    import plistlib
    data = plistlib.dumps({"Label": LABEL, "ProgramArguments": ["/w", "--lock-dir", "/d", LABEL, "--", "cmd"]})
    assert "program" in (S.loaded_definition_problem(out, data, LABEL, lock_dir=Path("/d")) or "")
    assert S.wrapper_identity_problem(None, "/anywhere") is not None


def test_f2_identity_accepts_only_this_checkouts_real_wrapper(ld, tmp_path):
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state)
    prog = str(root / "bin" / "ade-job-run")
    assert S.wrapper_identity_problem(prog, root) is None                                   # the real one, copied into the root
    assert "is not" in S.wrapper_identity_problem(prog, tmp_path / "other-root")             # not the checkout reconcile runs from
    (root / "bin" / "ade-job-run").write_text("#!/bin/sh\nexec \"$@\"\n")                   # an old/custom wrapper: no shared lock
    assert "differs" in S.wrapper_identity_problem(prog, root)


def test_f2_a_wrapper_that_speaks_another_protocol_defers(ld, monkeypatch):
    root, catalog, plist = _installed_wrapped(ld)
    _drift(root)
    monkeypatch.setattr(S, "WRAPPER_PROTOCOL", "v2")
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("protocol" in r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"} and ld.loaded()


def test_f2_a_stub_wrapper_never_admits_a_reload(ld):
    # The old tests used an exit-0 shell stub as the "wrapper"; it must not pass.
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state, stub=True)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows                                       # the unloaded install needs no wrapper proof
    ld.reset()
    _drift(root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("differs from this checkout" in r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"}


def test_f2_a_wrapper_outside_the_ade_root_defers(ld, tmp_path):
    elsewhere = tmp_path / "elsewhere" / "bin"
    elsewhere.mkdir(parents=True)
    shutil.copy2(WRAPPER, elsewhere / "ade-job-run")
    shutil.copy2(BIN / "ade_sched.py", elsewhere / "ade_sched.py")
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state, wrapper=elsewhere / "ade-job-run")
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    ld.reset()
    _drift(root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any("ADE root" in r["detail"] for r in rows), rows
    assert set(ld.verbs()) <= {"print"}


# F3 ----------------------------------------------------------------------------------------------------------------

FOREIGN = b"<plist><!-- foreign --></plist>"


@pytest.mark.parametrize("how", ["rename", "edit"])
def test_f3_reload_never_replaces_a_plist_a_foreign_writer_changed_after_the_hash(ld, how):
    root, catalog, plist = _installed_wrapped(ld)
    _drift(root)
    ld.mark("foreign_on", "bootout", how)           # the foreign write lands during `bootout`: after the hash, before our replace
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1, rows
    assert plist.read_bytes().strip() == FOREIGN.strip() or b"foreign" in plist.read_bytes()   # their bytes survive
    assert b"<integer>120</integer>" not in plist.read_bytes()
    assert (ld.state / "admission" / f"{LABEL}.recovery.json").exists()    # the unloaded job keeps a recovery record
    assert "bootstrap" not in ld.verbs()


@pytest.mark.parametrize("how", ["rename", "edit"])
def test_f3_removal_never_unlinks_a_plist_a_foreign_writer_changed_after_the_hash(ld, how):
    root, catalog, label, plist = _wrapped_retired(ld)
    ld.mark("foreign_on", "bootout", how)
    rows, rc = _remove(ld, root, catalog, label)
    assert rc == 1, rows
    assert plist.exists() and b"foreign" in plist.read_bytes()             # not deleted
    assert (ld.state / "admission" / f"{label}.recovery.json").exists()


def test_f3_restore_never_replaces_a_plist_a_foreign_writer_renamed_in(ld):
    root, catalog, plist = _installed_wrapped(ld)
    _drift(root)
    ld.mark("fail_once", "bootstrap")
    ld.mark("foreign_on", "bootstrap", "rename")    # during our bootstrap, so our rollback finds another inode with other bytes
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and b"foreign" in plist.read_bytes() and not ld.loaded(), rows
    assert (ld.state / "admission" / f"{LABEL}.recovery.json").exists()


def test_f3_guarded_replace_and_unlink_see_a_swapped_inode_and_an_edit(tmp_path):
    f = tmp_path / "x.plist"
    f.write_bytes(b"prior")
    data, ident = S._read_identity(f)
    sha = {__import__("hashlib").sha256(data).hexdigest()}
    side = tmp_path / "side"
    side.write_bytes(b"prior")                      # same bytes, another inode: a foreign writer replaced the file
    os.replace(side, f)
    with pytest.raises(S.ForeignWrite):
        S._guarded_replace(f, b"new", expect_id=ident, allowed_sha=sha)
    with pytest.raises(S.ForeignWrite):
        S._guarded_unlink(f, expect_id=ident, allowed_sha=sha)
    assert f.read_bytes() == b"prior"
    data, ident = S._read_identity(f)
    f.write_bytes(b"edited")                        # same inode, other bytes
    with pytest.raises(S.ForeignWrite):
        S._guarded_replace(f, b"new", expect_id=ident, allowed_sha=sha)
    with pytest.raises(S.ForeignWrite):
        S._guarded_unlink(f, expect_id=ident, allowed_sha=sha)
    assert f.read_bytes() == b"edited"
    f.write_bytes(b"prior")
    data, ident = S._read_identity(f)
    S._guarded_replace(f, b"new", expect_id=ident, allowed_sha=sha)         # unchanged: replaced
    assert f.read_bytes() == b"new"
    data, ident = S._read_identity(f)
    S._guarded_unlink(f, expect_id=ident, allowed_sha={__import__("hashlib").sha256(b"new").hexdigest()})
    assert not f.exists()
    with pytest.raises(S.ForeignWrite):             # a vanished file is a refusal, not a create
        S._guarded_replace(f, b"x", expect_id=ident, allowed_sha=sha)


def _ade_writers(ld, root, catalog):
    """Every other ADE plist writer, as a callable: each must refuse while the label's admission lock is held."""
    job = _job_of(ld, root, catalog)
    return {
        "install": lambda: S.install(job, "launchd", env=ld.env),
        "uninstall": lambda: S.uninstall(LABEL, "launchd", env=ld.env, ade=root),
        "install_native": lambda: S.install_launchd_native(job, "x", env=ld.env, state_dir=ld.state),
    }


@pytest.mark.parametrize("who", ["install", "uninstall", "install_native"])
@pytest.mark.parametrize("holder", ["run", "reconcile"])
def test_f3_every_ade_writer_refuses_while_the_admission_lock_is_held(ld, who, holder):
    root, catalog, plist = _installed_wrapped(ld)
    before = plist.read_bytes()
    writers = _ade_writers(ld, root, catalog)
    if holder == "run":
        proc = _hold_a_run(ld)
        fd = None
    else:
        proc, fd = None, S.acquire_admission_lock(LABEL, exclusive=True, state_dir=ld.state)
        assert fd is not None
    try:
        with pytest.raises((S.SchedError, S.NativeDefer)):
            writers[who]()
    finally:
        S.release_admission_lock(fd)
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def test_f3_recovery_is_an_ade_writer_and_defers_while_a_run_holds_the_lock(ld):
    root, catalog, plist = _installed_wrapped(ld)
    S.write_recovery_record(LABEL, action="reload", plist=plist, prior=plist.read_bytes(), new_sha=None, state_dir=ld.state, env=ld.env)
    (ld.root / "loaded" / LABEL).unlink()   # the interrupted reload left the job unloaded
    ld.reset()
    run = _hold_a_run(ld)
    try:
        rows = S.recover_launchd_records(state_dir=ld.state, env=ld.env, owns=lambda _l: True)
    finally:
        run.terminate()
        run.wait(timeout=10)
    assert any(r["action"] == "failed" and "holds its admission lock" in r["detail"] for r in rows), rows
    assert "bootstrap" not in ld.verbs() and (ld.state / "admission" / f"{LABEL}.recovery.json").exists()


# ------------------------------------------------------------------------------------------------ round 2 adversary lows

@pytest.mark.parametrize("edit,why", [
    (lambda a: a.__setitem__(3, "com.djbclark.other"), "does not start with"),
    (lambda a: a.__setitem__(1, "--other-flag"), "does not start with"),
    (lambda a: a.__setitem__(4, "-x"), "does not start with"),
])
def test_loaded_head_must_equal_the_files_head(edit, why):
    import plistlib
    pa = ["/w", "--lock-dir", "/d", LABEL, "--", "cmd"]
    data = plistlib.dumps({"Label": LABEL, "ProgramArguments": pa})
    args = list(pa)
    edit(args)
    out = "x = {\n\tprogram = /w\n\targuments = {\n" + "".join(f"\t\t{a}\n" for a in args) + "\t}\n}\n"
    assert why in (S.loaded_definition_problem(out, data, LABEL, lock_dir=Path("/d")) or "")
    out = "x = {\n\tprogram = /other\n\targuments = {\n" + "".join(f"\t\t{a}\n" for a in pa) + "\t}\n}\n"
    assert "not the wrapper" in (S.loaded_definition_problem(out, data, LABEL, lock_dir=Path("/d")) or "")


def test_native_install_refuses_under_a_held_lock_and_succeeds_without_it(ld):
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state)
    catalog = ai.load_catalog(root=root)
    job = _job_of(ld, root, catalog)
    text = next(iter(S.render(job, "launchd", env=ld.env).files.values()))
    plist = ld.agents / f"{LABEL}.plist"
    fd = S.acquire_admission_lock(LABEL, exclusive=True, state_dir=ld.state)
    try:
        with pytest.raises(S.NativeDefer, match="holds its admission lock"):
            S.install_launchd_native(job, text, env=ld.env, state_dir=ld.state)
    finally:
        S.release_admission_lock(fd)
    assert not plist.exists() and "bootstrap" not in ld.verbs()
    assert S.install_launchd_native(job, text, env=ld.env, state_dir=ld.state) == "created"   # the same call, lock free


def test_removal_defers_when_the_label_was_loaded_after_admission(ld):
    root, catalog, label, plist = _wrapped_retired(ld, loaded=True)       # loaded now; the caller thinks it is not
    entry = S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["skillopt-sleep"]
    with pytest.raises(S.NativeDefer, match="loaded after admission"):
        S.remove_launchd_locked(label, expect_hash=entry["artifact_hash"], loaded=False, state_dir=ld.state, env=ld.env)
    assert plist.exists() and ld.loaded(label)


def test_an_interrupt_is_not_swallowed_when_the_restore_also_fails(ld, monkeypatch):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    _drift(root)
    text = next(iter(S.render(job, "launchd", env=ld.env).files.values()))

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    def restore_fails(*a, **k):
        raise S.SchedError(1, "restore failed")
    monkeypatch.setattr(S, "_guarded_replace", interrupted)
    monkeypatch.setattr(S, "_restore_prior_and_load", restore_fails)
    with pytest.raises(KeyboardInterrupt):
        S.reload_launchd_locked(job, text, state_dir=ld.state, env=ld.env)
    assert (ld.state / "admission" / f"{LABEL}.recovery.json").exists()    # the record stays


def test_low_level_uninstall_discards_an_interrupted_reloads_record(ld):
    root, catalog, plist = _installed_wrapped(ld)
    S.write_recovery_record(LABEL, action="reload", plist=plist, prior=plist.read_bytes(), new_sha=None, state_dir=ld.state, env=ld.env)
    assert S.uninstall(LABEL, "launchd", env=ld.env, ade=root)
    assert not plist.exists() and not list((ld.state / "admission").glob("*.recovery.json"))
    assert not list((ld.state / "admission").glob("*.prior.plist"))


# ------------------------------------------------------------------------------------------------ round 3 (F4: one canonical lock)

def _elsewhere_env(ld, tmp_path):
    """The caller's environment points everywhere except the canonical place: HOME, XDG_STATE_HOME and ADE_JOBS_STATE_DIR changed."""
    other = tmp_path / "other-home"
    return {**ld.env, "HOME": str(other), "XDG_STATE_HOME": str(other / "xdg"), "ADE_JOBS_STATE_DIR": str(other / "jobs")}


def test_f4_the_canonical_lock_dir_ignores_home_xdg_and_the_state_dir_env(tmp_path, monkeypatch):
    import pwd
    want = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state" / "djbclark-ade" / "admission"
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "x"))
    monkeypatch.setenv("ADE_JOBS_STATE_DIR", str(tmp_path / "j"))
    env = {"HOME": str(tmp_path / "h2"), "XDG_STATE_HOME": str(tmp_path / "x2"), "ADE_JOBS_STATE_DIR": str(tmp_path / "j2")}
    real = getattr(S.canonical_admission_dir, "real", S.canonical_admission_dir)   # conftest patches the function per test
    monkeypatch.setattr(S, "canonical_admission_dir", real)
    assert S.canonical_admission_dir() == want
    assert S.admission_dir(tmp_path / "s", env=env) == want
    assert S.default_subst(env=env)["__ADMISSION__"] == str(want)


@pytest.mark.parametrize("who", ["install", "uninstall", "install_native"])
def test_f4_a_run_holding_the_canonical_lock_stops_a_writer_whose_env_points_elsewhere(ld, tmp_path, who):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    env = _elsewhere_env(ld, tmp_path)
    run = _hold_a_run(ld)
    ld.reset()
    try:
        with pytest.raises((S.SchedError, S.NativeDefer), match="admission lock"):
            {"install": lambda: S.install(job, "launchd", env=env),
             "uninstall": lambda: S.uninstall(LABEL, "launchd", env=env, ade=root),
             "install_native": lambda: S.install_launchd_native(job, "x", env=env)}[who]()
        assert run.poll() is None and not KILLERS & set(ld.verbs()) and not ld.killed()
    finally:
        run.terminate()
        run.wait(timeout=10)


@pytest.mark.parametrize("who", ["install", "uninstall"])
def test_f4_reconcile_and_a_low_level_writer_exclude_each_other_whatever_the_env(ld, tmp_path, who):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    before = plist.read_bytes()
    fd = S.acquire_admission_lock(LABEL, exclusive=True)          # what reconcile holds across its transaction
    assert fd is not None
    try:
        env = _elsewhere_env(ld, tmp_path)
        with pytest.raises(S.SchedError, match="admission lock"):
            S.install(job, "launchd", env=env) if who == "install" else S.uninstall(LABEL, "launchd", env=env, ade=root)
    finally:
        S.release_admission_lock(fd)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


@pytest.mark.parametrize("who", ["install", "uninstall"])
def test_f4_a_loaded_job_with_a_non_canonical_lock_dir_is_refused_untouched(ld, tmp_path, who):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    _set_loaded_args(ld, a2=str(tmp_path / "somewhere-else"))
    ld.reset()
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="migrate-wrapper") as e:
        S.install(job, "launchd", env=ld.env) if who == "install" else S.uninstall(LABEL, "launchd", env=ld.env, ade=root)
    assert "canonical" in str(e.value) and plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


@pytest.mark.parametrize("who", ["install", "uninstall"])
def test_f4_a_loaded_pre_wrapper_job_is_refused_by_low_level_install_and_uninstall(ld, who):
    root = _mini_catalog(ld.tmp)                          # installed with the OLD bytes: no wrapper
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    plist = ld.agents / f"{LABEL}.plist"
    old = plist.read_bytes()
    job = _job_of(ld, root, catalog)
    ld.reset()
    with pytest.raises(S.SchedError, match="migrate-wrapper"):
        S.install(job, "launchd", env=ld.env) if who == "install" else S.uninstall(LABEL, "launchd", env=ld.env, ade=root)
    assert plist.read_bytes() == old and ld.loaded() and not KILLERS & set(ld.verbs())


def test_f4_a_loaded_canonical_wrapped_idle_job_can_be_reinstalled_low_level(ld):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    ld.reset()
    S.install(job, "launchd", env=ld.env)                 # the real wrapper, canonical lock dir, idle: the proof passes
    assert ld.verbs().count("bootout") == 1 and ld.verbs().count("bootstrap") == 1 and ld.loaded()


def _pre_wrapper_install(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    _wrap(root, state=ld.state)                           # the catalog moves to the wrapper
    job = _job_of(ld, root, catalog)
    text = next(iter(S.render(job, "launchd", env=ld.env).files.values()))
    ld.reset()
    return root, job, text, ld.agents / f"{LABEL}.plist"


def test_f4_migrate_wrapper_moves_an_idle_pre_wrapper_job_under_the_canonical_lock(ld):
    root, job, text, plist = _pre_wrapper_install(ld)
    assert S.migrate_wrapper_launchd(job, text, env=ld.env) == "migrated"
    assert plist.read_text() == text and ld.loaded() and ld.verbs().count("bootout") == 1
    assert S.loaded_wrapper_problem(S._launchctl_print(S._ctx("launchd", ld.env, {}), LABEL)[1], LABEL, S.canonical_admission_dir(), root) is None
    assert _lock_is_free(ld) and not list((ld.state / "admission").glob("*.recovery.json"))
    with pytest.raises(S.SchedError, match="already runs through"):
        S.migrate_wrapper_launchd(job, text, env=ld.env)


def test_f4_migrate_wrapper_refuses_a_running_pre_wrapper_job(ld):
    root, job, text, plist = _pre_wrapper_install(ld)
    before = plist.read_bytes()
    ld.mark("state", LABEL, "running")
    ld.mark("pid", LABEL, "4242")
    with pytest.raises(S.SchedError, match="quiet time"):
        S.migrate_wrapper_launchd(job, text, env=ld.env)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def test_f4_migrate_wrapper_restores_the_prior_bytes_when_the_bootstrap_fails(ld):
    root, job, text, plist = _pre_wrapper_install(ld)
    before = plist.read_bytes()
    ld.mark("fail_once", "bootstrap")
    with pytest.raises(S.SchedError):
        S.migrate_wrapper_launchd(job, text, env=ld.env)
    assert plist.read_bytes() == before and ld.loaded()


# ------------------------------------------------------------------------------------------------ round 3 review of fc9fad08 (B2-B5)

def test_b2_a_loaded_canonical_install_that_cannot_bootstrap_restores_the_prior_definition(ld):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    before = plist.read_bytes()
    ld.reset()
    ld.mark("fail_once", "bootstrap")                     # the new definition fails to load; the restore succeeds
    with pytest.raises(S.ReloadRolledBack):
        S.install(job, "launchd", env=ld.env)
    assert plist.read_bytes() == before and ld.loaded() and _lock_is_free(ld)
    assert not list((ld.state / "admission").glob("*.recovery.json"))


def test_b2_a_loaded_canonical_install_whose_restore_also_fails_keeps_a_recovery_record(ld):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    before = plist.read_bytes()
    ld.reset()
    ld.fail("bootstrap")                                  # nothing can be bootstrapped
    with pytest.raises(S.SchedError, match="recovery record kept"):
        S.install(job, "launchd", env=ld.env)
    rec = S.recovery_record_path(LABEL)
    assert rec.exists() and S.recovery_prior_path(LABEL).read_bytes() == before and not ld.loaded()


def _unwrapped_text(plist):
    import plistlib
    d = plistlib.loads(plist.read_bytes())
    d["ProgramArguments"] = d["ProgramArguments"][S._WRAP_HEAD:]
    return plistlib.dumps(d).decode()


def test_b3_install_over_a_loaded_wrapped_job_refuses_a_definition_that_leaves_the_wrapper(ld, monkeypatch):
    import dataclasses
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    before = plist.read_bytes()
    ld.reset()
    real = S._render
    unwrapped = _unwrapped_text(plist)
    monkeypatch.setattr(S, "_render", lambda *a, **k: (lambda r: dataclasses.replace(r, files={p: unwrapped for p in r.files}))(real(*a, **k)))
    with pytest.raises(S.SchedError, match="would leave the canonical wrapper"):
        S.install(job, "launchd", env=ld.env)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def test_b3_migrate_wrapper_refuses_a_definition_that_is_not_wrapped(ld):
    root, job, text, plist = _pre_wrapper_install(ld)
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="does not route through the canonical wrapper"):
        S.migrate_wrapper_launchd(job, plist.read_text(), env=ld.env)    # the old, unwrapped bytes again
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def test_b4_the_admission_placeholder_cannot_be_set(ld, tmp_path):
    root = _mini_catalog(ld.tmp)
    _wrap(root, state=ld.state)
    catalog = ai.load_catalog(root=root)
    row = next(j for j in catalog.jobs if j["name"] == "deadline-sweep")
    plist = root / "config" / "launchd" / f"{LABEL}.plist"
    with pytest.raises(S.SchedError, match="__ADMISSION__"):
        S.Job.from_plist(plist, {"__ADMISSION__": str(tmp_path / "x")}, ade=root)
    with pytest.raises(S.SchedError, match="__ADMISSION__"):
        S.job_subst_from_row(row, root=root, env=ld.env, extra={"__ADMISSION__": str(tmp_path / "x")})
    with pytest.raises(S.SchedError, match="__ADMISSION__"):
        S.job_subst_from_row({**row, "set": [f"__ADMISSION__={tmp_path / 'x'}"]}, root=root, env=ld.env)
    assert S.job_subst_from_row(row, root=root, env=ld.env)["__ADMISSION__"] == str(S.canonical_admission_dir())


@pytest.mark.parametrize("who", ["install", "uninstall"])
def test_b5_the_low_level_proof_checks_the_loaded_wrapper_bytes(ld, who):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    ld.reset()
    (root / "bin" / "ade-job-run").write_text("#!/bin/sh\nexit 0\n")      # canonical argv, but not this checkout's wrapper
    with pytest.raises(S.SchedError, match="migrate-wrapper"):
        S.install(job, "launchd", env=ld.env) if who == "install" else S.uninstall(LABEL, "launchd", env=ld.env, ade=root)
    assert ld.loaded() and not KILLERS & set(ld.verbs())


# ------------------------------------------------------------------------------------------------ round 4 (F5: bind the root)

def test_r4_a_present_but_different_program_is_rejected_by_both_proof_paths(tmp_path):
    import plistlib
    pa = ["/w/ade-job-run", "--lock-dir", "/d", LABEL, "--", "cmd"]
    out = "x = {\n\tprogram = /other\n\targuments = {\n" + "".join(f"\t\t{a}\n" for a in pa) + "\t}\n}\n"
    data = plistlib.dumps({"Label": LABEL, "ProgramArguments": pa})
    assert "not the wrapper" in (S.loaded_definition_problem(out, data, LABEL, lock_dir=Path("/d")) or "")      # reconcile's proof
    assert "not the wrapper" in (S.loaded_wrapper_problem(out, LABEL, Path("/d"), tmp_path) or "")              # the low-level proof


def _foreign_checkout(tmp_path):
    """A second ADE checkout: an IDENTICAL ade-job-run with a DIFFERENT adjacent ade_sched.py (what the wrapper imports)."""
    other = tmp_path / "other-checkout"
    (other / "bin").mkdir(parents=True)
    shutil.copy2(WRAPPER, other / "bin" / "ade-job-run")
    (other / "bin" / "ade_sched.py").write_text((BIN / "ade_sched.py").read_text() + "\n# stale or custom copy\n")
    (other / "bin" / "ade-job-run").chmod(0o755)
    return other


@pytest.mark.parametrize("who", ["install", "uninstall"])
def test_r4_a_loaded_wrapper_in_another_checkout_is_refused_by_the_low_level_writers(ld, tmp_path, who):
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    other = _foreign_checkout(tmp_path)
    foreign = str(other / "bin" / "ade-job-run")
    _set_loaded_args(ld, a0=foreign)                  # canonical lock dir, identical wrapper bytes, protocol v1, another checkout
    ld.reset()
    assert S.wrapper_identity_problem(foreign, tmp_path / "nowhere") is not None
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="migrate-wrapper") as e:
        S.install(job, "launchd", env=ld.env) if who == "install" else S.uninstall(LABEL, "launchd", env=ld.env, ade=root)
    assert "ADE root" in str(e.value) and plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs()) and not ld.killed()


def test_r4_the_low_level_root_defaults_to_the_checkout_beside_the_scheduler(ld, tmp_path):
    # no --ade and no job root: the root is REPO (never None), so a wrapper in a tmp root is not this scheduler's own
    root, catalog, plist = _installed_wrapped(ld)
    ld.reset()
    with pytest.raises(S.SchedError, match="ADE root"):
        S.uninstall(LABEL, "launchd", env=ld.env)
    assert plist.exists() and ld.loaded() and not KILLERS & set(ld.verbs())
    assert S.ade_root_of(None) == str(S.REPO) and S.ade_root_of(root) == os.path.realpath(root)


def test_r4_a_loaded_canonical_idle_job_is_uninstalled_when_the_selected_root_holds_its_wrapper(ld):
    root, catalog, plist = _installed_wrapped(ld)
    ld.reset()
    assert S.uninstall(LABEL, "launchd", env=ld.env, ade=root) is True        # --ade names the root the wrapper lives in
    assert not plist.exists() and not ld.loaded()


def test_r4_an_empty_ade_is_no_selection_not_the_current_directory(ld, tmp_path, monkeypatch):
    root, catalog, plist = _installed_wrapped(ld)
    other = _foreign_checkout(tmp_path)
    d = {"Label": LABEL, "ProgramArguments": ["/x/ade-job-run", "--lock-dir", "/d", LABEL, "--", "c"]}
    monkeypatch.chdir(other)                          # the operator happens to stand inside the other checkout
    monkeypatch.setattr(S, "is_linked_worktree", lambda path: False)   # this suite runs in a worktree; production REPO is the primary checkout
    assert S.Job.from_dict(d, ade="").ade_root is None and S.ade_root_of("") == str(S.REPO)
    job = S.Job.from_plist(root / "config" / "launchd" / f"{LABEL}.plist",
                           S.job_subst_from_row(next(j for j in catalog.jobs if j["name"] == "deadline-sweep"), root=root, env=ld.env, extra=None), ade="")
    _set_loaded_args(ld, a0=str(other / "bin" / "ade-job-run"))
    ld.reset()
    with pytest.raises(S.SchedError, match="ADE root"):
        S.install(job, "launchd", env=ld.env)
    with pytest.raises(S.SchedError, match="ADE root"):
        S.uninstall(LABEL, "launchd", env=ld.env, ade="")
    assert ld.loaded() and not KILLERS & set(ld.verbs())


# ------------------------------------------------------------------------------------------------ W21d (follow-ups to #622)
# Item 7 (a): load-watch's plist is wrapped; (b) --restart-service. B7: migrate-wrapper takes the OLD wrapper's lock too.

LW_LABEL = "com.djbclark.load-watch"
HERDR = "dev.herdr.server"


def _lw_root(ld):
    """A tmp ADE root holding the REAL wrapper, scheduler and the checked-in load-watch plist."""
    root = ld.tmp / "lw-root"
    (root / "bin").mkdir(parents=True)
    (root / "launchd").mkdir()
    shutil.copy2(WRAPPER, root / "bin" / "ade-job-run")
    shutil.copy2(BIN / "ade_sched.py", root / "bin" / "ade_sched.py")
    (root / "bin" / "load-watch").write_text("#!/bin/sh\nexit 0\n")
    shutil.copy2(REPO / "launchd" / f"{LW_LABEL}.plist", root / "launchd" / f"{LW_LABEL}.plist")
    return root


def _lw_job(ld, root):
    return S.Job.from_plist(root / "launchd" / f"{LW_LABEL}.plist", {"__HOME__": str(ld.tmp / "home")}, ade=root)


def _hold_label_run(ld, label, lock_dir=None):
    p = subprocess.Popen([sys.executable, str(WRAPPER), "--lock-dir", str(lock_dir or (ld.state / "admission")), label, "--", "sleep", "60"],
                         env=ld.env, stderr=subprocess.DEVNULL)
    for _ in range(100):
        fd = S.acquire_admission_lock(label, exclusive=True, lock_dir=lock_dir)
        if fd is None:
            return p
        S.release_admission_lock(fd)
        time.sleep(0.1)
    p.kill()
    raise AssertionError("the wrapped run never took its shared lock")


def _stop(p):
    p.terminate()
    p.wait(timeout=10)


def test_w21d_the_checked_in_load_watch_plist_routes_through_the_canonical_wrapper(ld):
    import plistlib
    raw = plistlib.loads(re.sub(rb"<!--.*?-->", b"", (REPO / "launchd" / f"{LW_LABEL}.plist").read_bytes(), flags=re.DOTALL))
    assert raw["ProgramArguments"] == ["__ADE__/bin/ade-job-run", "--lock-dir", "__ADMISSION__", LW_LABEL, "--",
                                       "__ADE__/bin/load-watch", "sample"]
    root = _lw_root(ld)
    text = next(iter(S.render(_lw_job(ld, root), "launchd", env=ld.env).files.values()))
    assert S.wrapper_route_problem(text.encode(), LW_LABEL, lock_dir=S.canonical_admission_dir()) is None
    real = os.path.realpath(root)
    assert plistlib.loads(text.encode())["ProgramArguments"] == [
        f"{real}/bin/ade-job-run", "--lock-dir", str(S.canonical_admission_dir()), LW_LABEL, "--", f"{real}/bin/load-watch", "sample"]


def test_w21d_a_loaded_wrapped_load_watch_installs_and_uninstalls_through_the_locked_path(ld, monkeypatch):
    root = _lw_root(ld)
    job = _lw_job(ld, root)
    S.install(job, "launchd", env=ld.env)                                     # first install: nothing loaded yet
    plist = ld.agents / f"{LW_LABEL}.plist"
    assert ld.loaded(LW_LABEL) and S.wrapper_route_problem(plist.read_bytes(), LW_LABEL, lock_dir=S.canonical_admission_dir()) is None
    ld.reset()
    run = _hold_label_run(ld, LW_LABEL)                                       # a sample in flight holds the canonical lock shared
    try:
        for op in (lambda: S.install(job, "launchd", env=ld.env), lambda: S.uninstall(LW_LABEL, "launchd", env=ld.env, ade=root)):
            with pytest.raises(S.SchedError, match="admission lock"):
                op()
        assert run.poll() is None and not KILLERS & set(ld.verbs()) and not ld.killed(LW_LABEL) and ld.loaded(LW_LABEL)
    finally:
        _stop(run)
    ld.reset()
    seen, real = [], S.write_recovery_record
    monkeypatch.setattr(S, "write_recovery_record", lambda *a, **k: (seen.append(list(ld.verbs())), real(*a, **k))[1])
    S.install(job, "launchd", env=ld.env)                                     # idle: the record-first reload of a LOADED job
    assert seen and "bootout" not in seen[0] and ld.verbs().count("bootout") == 1 and ld.loaded(LW_LABEL)
    assert not list((ld.state / "admission").glob("*.recovery.json"))
    assert S.uninstall(LW_LABEL, "launchd", env=ld.env, ade=root) is True
    assert not plist.exists() and not ld.loaded(LW_LABEL)


def _service(ld, *, label=HERDR, tag="alpha", keep_alive=True):
    """A herdr-like service definition (an absolute program, no wrapper): KeepAlive or a plain StartInterval job."""
    import plistlib
    d = {"Label": label, "ProgramArguments": ["/usr/bin/true", tag], "RunAtLoad": True}
    if keep_alive:
        d["KeepAlive"] = {"SuccessfulExit": False}
    else:
        d["StartInterval"] = 300
    src = ld.tmp / "svc-src"
    src.mkdir(exist_ok=True)
    path = src / f"{label}-{tag}.plist"
    path.write_bytes(plistlib.dumps(d))
    return S.Job.from_plist(path)


def _loaded_service(ld, **kw):
    job = _service(ld, **kw)
    S.install(job, "launchd", env=ld.env)                                     # absent: written + bootstrapped, loaded UNWRAPPED
    plist = ld.agents / f"{job.label}.plist"
    assert ld.loaded(job.label) and plist.exists() and S.loaded_wrapper_problem(
        S._launchctl_print(S._ctx("launchd", ld.env, {}), job.label)[1], job.label, S.canonical_admission_dir(), ld.tmp) is not None
    ld.reset()
    return job, plist


def test_w21d_a_loaded_unwrapped_keepalive_install_is_refused_without_the_flag(ld):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="--restart-service"):
        S.install(_service(ld, tag="bravo"), "launchd", env=ld.env)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not KILLERS & set(ld.verbs())


def test_w21d_restart_service_replaces_a_loaded_unwrapped_keepalive_service_record_first(ld, monkeypatch):
    job, plist = _loaded_service(ld)
    new = _service(ld, tag="bravo")
    seen, real = [], S.write_recovery_record
    monkeypatch.setattr(S, "write_recovery_record", lambda *a, **k: (seen.append(list(ld.verbs())), real(*a, **k))[1])
    S.install(new, "launchd", env=ld.env, restart_service=True)
    assert seen and "bootout" not in seen[0]                                  # the record + prior copy exist BEFORE the service is stopped
    assert ld.verbs().count("bootout") == 1 and ld.verbs().count("bootstrap") == 1 and ld.loaded(HERDR)
    assert b"bravo" in plist.read_bytes() and b"alpha" not in plist.read_bytes() and _lock_is_free(ld, HERDR)
    assert not list((ld.state / "admission").glob("*.recovery.json"))


def test_w21d_restart_service_restores_the_prior_definition_when_the_new_one_fails_to_load(ld):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    ld.mark("fail_once", "bootstrap")
    with pytest.raises(S.ReloadRolledBack):
        S.install(_service(ld, tag="bravo"), "launchd", env=ld.env, restart_service=True)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not list((ld.state / "admission").glob("*.recovery.json"))


def test_w21d_restart_service_keeps_the_recovery_record_when_the_restore_also_fails(ld):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    ld.fail("bootstrap")
    with pytest.raises(S.SchedError, match="recovery record kept"):
        S.install(_service(ld, tag="bravo"), "launchd", env=ld.env, restart_service=True)
    assert S.recovery_record_path(HERDR).exists() and S.recovery_prior_path(HERDR).read_bytes() == before and not ld.loaded(HERDR)


def test_w21d_restart_service_never_restarts_a_job_that_is_not_a_keepalive_service(ld):
    # (a) the NEW definition is not KeepAlive; (b) the loaded pre-wrapper job is not a KeepAlive service either
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="not a KeepAlive"):
        S.install(_service(ld, tag="bravo", keep_alive=False), "launchd", env=ld.env, restart_service=True)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not KILLERS & set(ld.verbs())
    root, job2, text, plist2 = _pre_wrapper_install(ld)
    before2 = plist2.read_bytes()
    with pytest.raises(S.SchedError, match="not a KeepAlive"):
        S.install(job2, "launchd", env=ld.env, restart_service=True)
    assert plist2.read_bytes() == before2 and ld.loaded() and not KILLERS & set(ld.verbs())


def test_w21d_restart_service_without_activation_is_refused_it_is_a_bootout(ld):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="needs activation") as e:
        S.install(_service(ld, tag="bravo"), "launchd", env=ld.env, restart_service=True, activate=False)
    assert e.value.code == S.EX_USAGE
    with pytest.raises(S.SchedError, match="needs activation"):
        S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True, activate=False)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not KILLERS & set(ld.verbs())


def test_w21d_a_busy_canonical_lock_refuses_even_with_restart_service(ld):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    fd = S.acquire_admission_lock(HERDR, exclusive=False)
    try:
        with pytest.raises(S.SchedError, match="admission lock"):
            S.install(_service(ld, tag="bravo"), "launchd", env=ld.env, restart_service=True)
        with pytest.raises(S.SchedError, match="admission lock"):
            S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True)
    finally:
        S.release_admission_lock(fd)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not KILLERS & set(ld.verbs())


def test_w21d_restart_service_has_no_effect_on_a_canonical_wrapped_job(ld, monkeypatch):
    import dataclasses
    root, catalog, plist = _installed_wrapped(ld)
    job = _job_of(ld, root, catalog)
    before = plist.read_bytes()
    ld.reset()
    real = S._render
    unwrapped = _unwrapped_text(plist)
    monkeypatch.setattr(S, "_render", lambda *a, **k: (lambda r: dataclasses.replace(r, files={p: unwrapped for p in r.files}))(real(*a, **k)))
    with pytest.raises(S.SchedError, match="would leave the canonical wrapper"):      # the normal path's wrapper check still applies
        S.install(job, "launchd", env=ld.env, restart_service=True)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def test_w21d_a_loaded_unwrapped_keepalive_uninstall_is_refused_without_the_flag(ld):
    job, plist = _loaded_service(ld)
    with pytest.raises(S.SchedError, match="--restart-service"):
        S.uninstall(HERDR, "launchd", env=ld.env)
    assert plist.exists() and ld.loaded(HERDR) and not KILLERS & set(ld.verbs())


def test_w21d_restart_service_uninstalls_a_loaded_unwrapped_keepalive_service_record_first(ld, monkeypatch):
    job, plist = _loaded_service(ld)
    seen, real = [], S.write_recovery_record
    monkeypatch.setattr(S, "write_recovery_record", lambda *a, **k: (seen.append(list(ld.verbs())), real(*a, **k))[1])
    assert S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True) is True
    assert seen and "bootout" not in seen[0] and ld.verbs().count("bootout") == 1
    assert not plist.exists() and not ld.loaded(HERDR) and not list((ld.state / "admission").glob("*.recovery.json"))


def test_w21d_a_failed_restart_uninstall_restores_the_service_and_keeps_the_record_when_it_cannot(ld, monkeypatch):
    job, plist = _loaded_service(ld)
    before = plist.read_bytes()
    monkeypatch.setattr(S, "_guarded_unlink", lambda *a, **k: (_ for _ in ()).throw(S.SchedError(S.EX_ACTIVATE, "unlink failed")))
    with pytest.raises(S.ReloadRolledBack):                                    # unloaded, then put back
        S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True)
    assert plist.read_bytes() == before and ld.loaded(HERDR) and not S.recovery_record_path(HERDR).exists()
    ld.fail("bootstrap")
    with pytest.raises(S.SchedError, match="recovery record kept"):            # unloaded and the restore fails too
        S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True)
    assert S.recovery_record_path(HERDR).exists() and S.recovery_prior_path(HERDR).read_bytes() == before and not ld.loaded(HERDR)


@pytest.mark.parametrize("how", ["not-keepalive", "unparseable", "missing"])
def test_w21d_restart_service_uninstall_needs_a_keepalive_installed_plist(ld, how):
    if how == "not-keepalive":
        job, plist = _loaded_service(ld, keep_alive=False)
    else:
        job, plist = _loaded_service(ld)
        plist.write_bytes(b"not a plist") if how == "unparseable" else plist.unlink()
    with pytest.raises(S.SchedError, match="refused even with --restart-service"):
        S.uninstall(HERDR, "launchd", env=ld.env, restart_service=True)
    assert ld.loaded(HERDR) and not KILLERS & set(ld.verbs()) and (how == "missing" or plist.exists())


def test_w21d_restart_service_uninstall_refuses_a_loaded_pre_wrapper_non_keepalive_job(ld):
    root, job, text, plist = _pre_wrapper_install(ld)
    before = plist.read_bytes()
    with pytest.raises(S.SchedError, match="not a KeepAlive"):
        S.uninstall(LABEL, "launchd", env=ld.env, restart_service=True, ade=root)
    assert plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs())


def _child_cli(ld, *argv):
    """Run bin/ade-sched in a child that first points the canonical lock directory at the test's tmp dir."""
    child = (
        "import runpy, sys, pathlib; sys.path[:0] = [sys.argv[1]]\n"
        "import ade_sched as S\n"
        "d = pathlib.Path(sys.argv[2])\n"   # read BEFORE sys.argv is rewritten below
        "S.canonical_admission_dir = lambda: d\n"
        "script = sys.argv[3]; sys.argv = ['ade-sched'] + sys.argv[4:]\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    return subprocess.run([sys.executable, "-c", child, str(BIN), str(ld.state / "admission"), str(BIN / "ade-sched"), "--backend", "launchd", *argv],
                          env=ld.env, capture_output=True, text=True, timeout=120)


def test_w21d_the_ade_sched_cli_forwards_restart_service_to_install_and_uninstall(ld):
    job, plist = _loaded_service(ld)
    bravo = ld.tmp / "svc-src" / f"{HERDR}-bravo.plist"
    _service(ld, tag="bravo")
    r = _child_cli(ld, "install", str(bravo))
    assert r.returncode == 1 and "--restart-service" in r.stderr and b"bravo" not in plist.read_bytes()
    r = _child_cli(ld, "install", str(bravo), "--restart-service")
    assert r.returncode == 0, r.stderr
    assert b"bravo" in plist.read_bytes() and ld.loaded(HERDR)
    r = _child_cli(ld, "uninstall", HERDR)
    assert r.returncode == 1 and plist.exists() and ld.loaded(HERDR)
    r = _child_cli(ld, "uninstall", HERDR, "--restart-service")
    assert r.returncode == 0, r.stderr
    assert not plist.exists() and not ld.loaded(HERDR)


# -- B7: migrate-wrapper also takes the OLD wrapper's lock

def _old_wrapped_noncanonical(ld, tmp_path):
    """LABEL loaded from a wrapped plist whose --lock-dir is NOT the canonical one; returns what migrate-wrapper needs."""
    root = _mini_catalog(ld.tmp)
    orig = (root / "config" / "launchd" / f"{LABEL}.plist").read_text()
    old_dir = tmp_path / "old-admission"
    _wrap(root, lock_dir=old_dir)
    catalog = ai.load_catalog(root=root)
    S.install(_job_of(ld, root, catalog), "launchd", env=ld.env)                       # absent: loaded with the OLD lock directory
    (root / "config" / "launchd" / f"{LABEL}.plist").write_text(orig)
    _wrap(root, state=ld.state)                                                       # the catalog moves to the canonical lock directory
    job = _job_of(ld, root, catalog)
    text = next(iter(S.render(job, "launchd", env=ld.env).files.values()))
    ld.reset()
    assert S.loaded_wrapper_problem(S._launchctl_print(S._ctx("launchd", ld.env, {}), LABEL)[1], LABEL, S.canonical_admission_dir(), root) is not None
    return root, job, text, ld.agents / f"{LABEL}.plist", old_dir


def test_b7_migrate_wrapper_refuses_while_a_run_of_the_old_wrapper_holds_its_lock(ld, tmp_path):
    root, job, text, plist, old_dir = _old_wrapped_noncanonical(ld, tmp_path)
    before = plist.read_bytes()
    run = _hold_label_run(ld, LABEL, old_dir)
    try:
        with pytest.raises(S.SchedError, match="old wrapper"):
            S.migrate_wrapper_launchd(job, text, env=ld.env)
        assert run.poll() is None and plist.read_bytes() == before and ld.loaded() and not KILLERS & set(ld.verbs()) and not ld.killed()
        assert _lock_is_free(ld)                                                     # the canonical lock was released again
    finally:
        _stop(run)


def test_b7_migrate_wrapper_holds_the_old_lock_for_the_whole_migration_and_then_releases_it(ld, tmp_path, monkeypatch):
    root, job, text, plist, old_dir = _old_wrapped_noncanonical(ld, tmp_path)
    probes, real = [], S.reload_launchd_locked

    def probe(*a, **k):
        fd = S.acquire_admission_lock(LABEL, exclusive=False, lock_dir=old_dir)     # a run of the old wrapper trying to start
        probes.append(fd is None)
        S.release_admission_lock(fd)
        return real(*a, **k)

    monkeypatch.setattr(S, "reload_launchd_locked", probe)
    assert S.migrate_wrapper_launchd(job, text, env=ld.env) == "migrated"
    assert probes == [True] and plist.read_text() == text and ld.verbs().count("bootout") == 1
    fd = S.acquire_admission_lock(LABEL, exclusive=True, lock_dir=old_dir)
    assert fd is not None                                                            # released in the finally
    S.release_admission_lock(fd)
    assert _lock_is_free(ld)


def test_b7_an_old_lock_directory_that_is_the_canonical_one_under_another_name_is_not_locked_twice(ld, tmp_path):
    root, job, text, plist, old_dir = _old_wrapped_noncanonical(ld, tmp_path)
    canon = S.canonical_admission_dir()
    alias = tmp_path / "alias-admission"
    alias.symlink_to(canon)
    _set_loaded_args(ld, a2=str(alias))                                              # a different spelling of the SAME directory
    assert S.migrate_wrapper_launchd(job, text, env=ld.env) == "migrated"
