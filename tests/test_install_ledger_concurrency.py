"""Separate apply processes share evidence and never overlap component effects."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai


WORKER = r'''
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ade_install as ai
state, events = Path(sys.argv[2]), Path(sys.argv[3])
name, cid, kind, mode = sys.argv[4:]
def flag(s): return events / s
def wait(s):
    end = time.monotonic() + 12
    while not flag(s).exists():
        if time.monotonic() > end: raise RuntimeError('barrier expired: ' + s)
        time.sleep(.01)
def observe(row, **kw):
    flag('planned-' + name).touch()
    status = 'ok' if flag('installed-' + cid).exists() else 'missing'
    return ai.Observation('component', cid, status, 'fixture')
ai.observe_component = observe
row = {'id': cid, 'class': 'hard', 'install_argv': ['fixture', cid]}
if kind == 'system':
    row.update(needs_system=True, system_argv=['fixture-system', cid])
catalog = ai.Catalog({'schema_version': 1, 'component': [row]}, events / 'catalog', root=events)
def run(argv, cwd):
    flag('entered-' + name).touch()
    if name == 'A': wait('release-A')
    if mode == 'runner-error': raise RuntimeError('injected runner failure')
    if mode == 'exec-error': raise OSError('injected exec failure')
    flag('installed-' + cid).touch()
    return subprocess.CompletedProcess(argv, 0, '', '')
if mode == 'save-error':
    original = ai.save_ledger
    calls = 0
    def save(*args):
        global calls
        calls += 1
        if calls == 2: raise OSError('injected terminal save failure')
        return original(*args)
    ai.save_ledger = save
flag('ready-' + name).touch()
wait('start-' + name)
try:
    rows, rc = ai.apply(catalog, dry_run=False, ids={cid}, state_dir=state,
                        runner=run, allow_system=kind == 'system',
                        apply_system=kind == 'system', reconcile_sched=False)
    output = {'rows': rows, 'rc': rc}
except (RuntimeError, OSError) as error:
    output, rc = {'exception': str(error)}, 17
if mode in {'runner-error', 'save-error', 'exec-error'}:
    flag('caught-' + name).touch()
    wait('finish-' + name)  # Remain alive: success by B proves finally released the lock.
print(json.dumps(output), flush=True)
sys.exit(rc)
'''


def wait_for(path, process, timeout=8):
    end = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"worker exited before {path.name}: {stdout}\n{stderr}")
        if time.monotonic() > end:
            pytest.fail(f"worker did not reach {path.name}")
        time.sleep(.01)


@pytest.fixture
def workers(tmp_path):
    events = tmp_path / "events"
    events.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    seed = {"status": "pending", "detail": "historical unknown evidence"}
    (state / "ledger.json").write_text(json.dumps({"schema_version": 1, "entries": {"historical": seed}}))
    script = tmp_path / "worker.py"
    script.write_text(WORKER)
    processes = []
    def start(name, cid, kind="user", mode="success"):
        process = subprocess.Popen([sys.executable, "-I", "-B", str(script), str(REPO / "bin"),
                                    str(state), str(events), name, cid, kind, mode],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**os.environ, "HOME": str(tmp_path / "home")})
        processes.append(process)
        wait_for(events / f"ready-{name}", process)
        (events / f"start-{name}").touch()
        return process
    yield state, events, start, seed
    for process in processes:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)


@pytest.mark.parametrize("kind,same_component", [("user", False), ("system", False), ("user", True)])
def test_two_apply_processes_preserve_both_operations_and_replan(workers, kind, same_component):
    state, events, start, seed = workers
    first = start("A", "first", kind)
    wait_for(events / "entered-A", first)
    second = start("B", "first" if same_component else "second")
    wait_for(events / "planned-B", second)
    # B has reached live planning while A is in its command. Without the shared
    # lifecycle lock B enters its runner and completes from a stale snapshot.
    end = time.monotonic() + .5
    while not (events / "entered-B").exists() and time.monotonic() < end:
        assert second.poll() is None
        time.sleep(.01)
    assert not (events / "entered-B").exists(), "component effects overlapped"
    pending = json.loads((state / "ledger.json").read_text())["entries"]
    assert pending["first"]["status"] == "pending"
    (events / "release-A").touch()
    out_a, err_a = first.communicate(timeout=8)
    out_b, err_b = second.communicate(timeout=8)
    assert first.returncode == second.returncode == 0, (out_a, err_a, out_b, err_b)
    entries = json.loads((state / "ledger.json").read_text())["entries"]
    assert entries["historical"] == seed
    assert entries["first"]["status"] == "installed"
    assert entries["first"]["kind"] == ("system_argv" if kind == "system" else "install_argv")
    if same_component:
        assert json.loads(out_b)["rows"][0]["action"] == "skip"
        assert not (events / "entered-B").exists()
        assert set(entries) == {"historical", "first"}
    else:
        assert entries["second"]["status"] == "installed"
        assert set(entries) == {"historical", "first", "second"}


@pytest.mark.parametrize("failure,status", [("runner-error", "pending"), ("save-error", "pending"),
                                            ("exec-error", "failed")])
def test_error_releases_lock_while_owner_alive_and_retains_uncertain_evidence(workers, failure, status):
    state, events, start, seed = workers
    first = start("A", "first", mode=failure)
    wait_for(events / "entered-A", first)
    second = start("B", "second")
    wait_for(events / "planned-B", second)
    (events / "release-A").touch()
    wait_for(events / "caught-A", first)
    wait_for(events / "entered-B", second)
    out_b, err_b = second.communicate(timeout=8)
    assert second.returncode == 0, (out_b, err_b)
    assert first.poll() is None, "the failed owner must still be alive for this release check"
    entries = json.loads((state / "ledger.json").read_text())["entries"]
    assert entries["historical"] == seed
    assert entries["first"]["status"] == status
    assert entries["second"]["status"] == "installed"
    (events / "finish-A").touch()
    first.communicate(timeout=8)
    assert first.returncode == (1 if failure == "exec-error" else 17)


def test_scheduler_reconcile_can_run_another_apply_after_component_lock_released(workers, monkeypatch):
    state, events, start, seed = workers
    monkeypatch.setattr(ai, "observe_component", lambda *a, **kw:
                        ai.Observation("component", "first", "missing", "fixture"))
    catalog = ai.Catalog({"component": [{"id": "first", "class": "hard", "install_argv": ["fixture"]}]},
                         events / "catalog", root=events)
    def reconcile(*args, **kwargs):
        child = start("B", "second")
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0, (stdout, stderr)
        return [], 0
    monkeypatch.setattr(ai, "apply_sched_reconcile", reconcile)
    _, rc = ai.apply(catalog, dry_run=False, ids={"first"}, state_dir=state, reconcile_sched=True,
                     runner=lambda argv, cwd: subprocess.CompletedProcess(argv, 0, "", ""))
    assert rc == 0
    entries = json.loads((state / "ledger.json").read_text())["entries"]
    assert entries["historical"] == seed
    assert entries["first"]["status"] == entries["second"]["status"] == "installed"


@pytest.mark.parametrize("case,dry_run,allow_system", [("ready", True, False), ("blocked", False, False),
                                                      ("system", False, True), ("skip", False, False)])
def test_nonexecuting_paths_create_no_state_or_lock(tmp_path, monkeypatch, case, dry_run, allow_system):
    row = {"id": "fixture", "class": "hard", "install_argv": ["never-run"]}
    if case == "blocked":
        row.pop("install_argv")
    if case == "system":
        row.update(needs_system=True, system_argv=["never-root"])
    monkeypatch.setattr(ai, "observe_component", lambda *a, **kw:
                        ai.Observation("component", "fixture", "ok" if case == "skip" else "missing", "fixture"))
    catalog = ai.Catalog({"component": [row]}, tmp_path / "catalog", root=tmp_path)
    state = tmp_path / "must-not-exist"
    runner = Mock(side_effect=AssertionError("nonexecuting request ran a command"))
    rows, rc = ai.apply(catalog, dry_run=dry_run, allow_system=allow_system,
                        state_dir=state, ids={"fixture"}, runner=runner, reconcile_sched=False)
    assert rows[0]["action"] == {"ready": "would-install", "blocked": "blocked",
                                 "system": "refuse-system-exec", "skip": "skip"}[case]
    assert rc == {"ready": 0, "blocked": 1, "system": 2, "skip": 0}[case]
    assert not state.exists()
    runner.assert_not_called()
