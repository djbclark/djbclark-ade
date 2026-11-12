"""W18: crash/orphan recovery. Workers are really SIGKILLed at each install phase."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai
import ade_install_recovery as rec

@pytest.fixture(autouse=True)
def _alarm_fails_the_test_not_pytest():
    previous = signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(TimeoutError("state-file hang")))
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)


PHASES = ("pre-pending", "in-command", "pre-terminal-save", "mid-atomic-write", "post-terminal-save")

WORKER = r'''
import os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ade_install as ai
state, flag, phase = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
def park():
    flag.touch()
    time.sleep(120)
row = {'id': 'tool', 'class': 'hard', 'install_argv': ['fixture', 'tool']}
catalog = ai.Catalog({'schema_version': 1, 'component': [row]}, state / 'catalog', root=state)
ai.observe_component = lambda row, **kw: ai.Observation('component', 'tool', 'missing', 'fixture')
saves = 0
original_save = ai.save_ledger
def save(sd, ledger):
    global saves
    saves += 1
    if phase == 'pre-pending' and saves == 1:
        park()
    if phase == 'pre-terminal-save' and saves == 2:
        park()
    out = original_save(sd, ledger)
    if phase == 'post-terminal-save' and saves == 2:
        park()
    return out
ai.save_ledger = save
if phase == 'mid-atomic-write':
    real_replace, calls = os.replace, 0
    def replace(a, b, *args, **kw):
        global calls
        calls += 1
        if calls == 2:  # temp fully written, not yet swapped in
            park()
        return real_replace(a, b, *args, **kw)
    ai.os.replace = replace
def run(argv, cwd):
    if phase == 'in-command':
        park()
    return subprocess.CompletedProcess(argv, 0, '', '')
ai.apply(catalog, dry_run=False, ids={'tool'}, state_dir=state, runner=run, reconcile_sched=False)
'''


def kill_at(tmp_path, phase):
    state = tmp_path / "state"
    state.mkdir()
    script = tmp_path / "worker.py"
    script.write_text(WORKER)
    flag = tmp_path / "parked"
    proc = subprocess.Popen([sys.executable, "-I", "-B", str(script), str(REPO / "bin"), str(state), str(flag), phase],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, "HOME": str(tmp_path / "home")})
    end = time.monotonic() + 15
    while not flag.exists():
        if proc.poll() is not None:
            pytest.fail("worker exited early: " + str(proc.communicate()))
        assert time.monotonic() < end, "worker never parked"
        time.sleep(.02)
    os.kill(proc.pid, signal.SIGKILL)
    proc.communicate(timeout=10)
    return state, proc.pid


def kinds(findings):
    return {(f.kind, f.status) for f in findings}


@pytest.mark.parametrize("phase", PHASES)
def test_kill_at_each_phase_is_detected_then_repaired_idempotently(tmp_path, phase):
    state, pid = kill_at(tmp_path, phase)
    found = rec.scan(state)
    ledger_present = (state / "ledger.json").is_file()
    expected = {
        "pre-pending": {("lock-holder", "orphaned")},
        "in-command": {("lock-holder", "orphaned"), ("ledger-entry", "orphaned")},
        "pre-terminal-save": {("lock-holder", "orphaned"), ("ledger-entry", "orphaned")},
        "mid-atomic-write": {("lock-holder", "orphaned"), ("ledger-entry", "orphaned"), ("temp-file", "orphaned")},
        "post-terminal-save": {("lock-holder", "orphaned")},
    }[phase]
    assert kinds(found) == expected, [f.__dict__ for f in found]
    # observe-only: scanning changed nothing
    before = sorted(p.name for p in state.iterdir())
    rec.scan(state)
    assert sorted(p.name for p in state.iterdir()) == before
    # dry-run names the repair but writes nothing
    report, rc = rec.recover(state, yes=False)
    assert rc == 0 and report["status"] == "dry-run" and sorted(p.name for p in state.iterdir()) == before
    # explicit repair
    report, rc = rec.recover(state, yes=True)
    assert rc == 0 and report["status"] == "recovered", report
    assert rec.scan(state) == []
    if "ledger-entry" in {k for k, _ in expected}:
        entry = ai.load_ledger(state)["entries"]["tool"]
        assert entry["status"] == "interrupted" and entry["previous_status"] == "pending"
        assert entry["argv"] == ["fixture", "tool"] and entry["owner"]["pid"] == pid  # evidence kept
    if ledger_present and phase == "post-terminal-save":
        assert ai.load_ledger(state)["entries"]["tool"]["status"] == "installed"
    evidence = [json.loads(line) for line in (state / ai.RECOVERY_EVIDENCE).read_text().splitlines()]
    assert evidence, "recovery wrote no evidence"
    if phase == "mid-atomic-write":
        assert len(list((state / rec.QUARANTINE_DIR).iterdir())) == 1
        assert not [p for p in state.iterdir() if p.name.endswith(".tmp")]
    # idempotent
    report, rc = rec.recover(state, yes=True)
    assert rc == 0 and report["status"] == "nothing-to-recover"


def test_recovery_never_runs_at_the_next_apply(tmp_path):
    state, _ = kill_at(tmp_path, "in-command")
    row = {"id": "tool", "class": "hard", "install_argv": ["fixture", "tool"]}
    catalog = ai.Catalog({"schema_version": 1, "component": [row]}, state / "catalog", root=state)
    ran = []
    import unittest.mock as mock
    with mock.patch.object(ai, "observe_component", lambda r, **k: ai.Observation("component", "tool", "missing", "fx")):
        ai.apply(catalog, dry_run=False, ids={"tool"}, state_dir=state, runner=lambda a, c: ran.append(a) or subprocess.CompletedProcess(a, 0, "", ""), reconcile_sched=False)
    # the new apply replaced the entry itself; no orphan repair was performed behind its back
    assert ran and not (state / rec.QUARANTINE_DIR).exists()
    events = [json.loads(line)["event"] for line in (state / ai.RECOVERY_EVIDENCE).read_text().splitlines()]
    assert events == ["stale-lock-holder-superseded"]  # evidence kept of the killed holder; nothing was repaired


def test_pid_reuse_is_an_orphan_and_same_start_is_active(tmp_path, monkeypatch):
    state = tmp_path / "state"
    me = os.getpid()
    mine = ai.process_start_time(me)
    if mine is None:
        pytest.skip("process start time unreadable here")
    state.mkdir()
    ai.save_ledger(state, {"entries": {
        "reused": {"status": "pending", "owner": {"pid": me, "start": mine - 1000}},
        "live": {"status": "pending", "owner": {"pid": me, "start": mine}},
    }})
    got = {f.id: f.status for f in rec.scan(state) if f.kind == "ledger-entry"}
    assert got == {"reused": "orphaned", "live": "active"}
    monkeypatch.setattr(ai, "process_start_time", lambda pid: None)  # unreadable start counts as live
    assert {f.id: f.status for f in rec.scan(state) if f.kind == "ledger-entry"} == {"reused": "active", "live": "active"}


def test_legacy_entry_without_owner_needs_a_free_lock(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ai.save_ledger(state, {"entries": {"old": {"status": "pending", "at": "2026-01-01T00:00:00Z"}}})
    assert [(f.status) for f in rec.scan(state)] == ["orphaned"]
    with ai.install_ledger_lock(state):
        pass  # lock file exists, free
    assert [(f.status) for f in rec.scan(state) if f.kind == "ledger-entry"] == ["orphaned"]
    holder = subprocess.Popen([sys.executable, "-I", "-c",
        "import fcntl,os,sys,time\nfd=os.open(sys.argv[1],os.O_RDWR)\nfcntl.flock(fd,fcntl.LOCK_EX)\nprint('ready',flush=True)\ntime.sleep(60)",
        str(state / "ledger.lock")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "ready"
        assert [f.status for f in rec.scan(state) if f.kind == "ledger-entry"] == ["unverifiable"]
        report, rc = rec.recover(state, yes=True)  # a running installer: never waits, never breaks the lock
        assert rc == 1 and report["status"] == "lock-busy"
        assert ai.load_ledger(state)["entries"]["old"]["status"] == "pending"
    finally:
        holder.kill()
        holder.wait()


def test_python_sentinel_is_reported_but_repaired_only_by_python_recover(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / ai.PYTHON_PENDING).write_text("pid=999999999\nstarted=2026-11-12T00:00:00Z\nargv=[]\n")
    ai.save_ledger(state, {"entries": {"python": {"status": "pending", "owner": {"pid": 999999999, "start": 1}}}})
    found = rec.scan(state)
    assert kinds(found) == {("python-pending", "orphaned")}  # the ledger python row is not double-reported
    assert found[0].repair == rec.PYTHON_RECOVER_COMMAND
    report, rc = rec.recover(state, yes=True)
    assert rc == 0 and report["status"] == "nothing-to-recover" and report["deferred"]
    assert (state / ai.PYTHON_PENDING).exists()
    assert ai.load_ledger(state)["entries"]["python"]["status"] == "pending"


def test_sentinel_with_reused_pid_no_longer_blocks_as_owner_active(tmp_path):
    me = os.getpid()
    start = ai.process_start_time(me)
    if start is None:
        pytest.skip("process start time unreadable here")
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start - 3600))
    assert ai.sentinel_owner_status({"pid": str(me), "started": old}) == "reused"
    new = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))
    assert ai.sentinel_owner_status({"pid": str(me), "started": new}) == "alive"
    assert ai.sentinel_owner_status({"pid": str(me)}) == "unverifiable"  # no evidence counts as live


def test_root_never_repairs_and_unreadable_ledger_is_untouched(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    ai.save_ledger(state, {"entries": {"x": {"status": "pending", "owner": {"pid": 999999999, "start": 1}}}})
    report, rc = rec.recover(state, yes=True, euid=0)
    assert rc == 1 and report["status"] == "refused-root"
    assert ai.load_ledger(state)["entries"]["x"]["status"] == "pending"
    (state / "ledger.json").write_text("{not json")
    found = rec.scan(state)
    assert ("ledger", "corrupt") in kinds(found)
    report, rc = rec.recover(state, yes=True)
    assert (state / "ledger.json").read_text() == "{not json"


def test_live_writer_temp_is_not_orphaned_and_legacy_temp_needs_age(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    me = os.getpid()
    live = state / f"ledger.json.{me}.{ai._start_token(ai.process_start_time(me))}.abc.tmp"
    live.write_text("{}")
    recent = state / "ledger.json.abcd1234"
    recent.write_text("{}")
    old = state / f"{ai.HERMES_CHOICE_FILE}.wxyz9876"
    old.write_text("{}")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    got = {f.id: f.status for f in rec.scan(state) if f.kind == "temp-file"}
    assert got == {live.name: "active", recent.name: "active", old.name: "orphaned"}
    unrelated = state / "notes.abcd1234"
    unrelated.write_text("x")
    assert unrelated.name not in {f.id for f in rec.scan(state)}


def test_doctor_reports_install_state_and_fails_only_on_leftovers(tmp_path):
    state, _ = kill_at(tmp_path, "in-command")
    catalog = ai.Catalog({"schema_version": 1, "component": []}, tmp_path / "catalog", root=tmp_path)
    kw = dict(skip_jobs=True, skip_credential_bak=True, pi_pool_acceptance_path=tmp_path / "none.toml")
    obs, rc = ai.doctor(catalog, install_state_dir=state, **kw)
    rows = [o for o in obs if o.kind == "install-state"]
    assert rc == 1 and {o.status for o in rows} == {"orphaned"} and all("recover --yes" in o.detail for o in rows)
    assert (state / "ledger.json").is_file() and not (state / rec.QUARANTINE_DIR).exists()  # doctor never repairs
    rec.recover(state, yes=True)
    obs, rc = ai.doctor(catalog, install_state_dir=state, **kw)
    assert [o.status for o in obs if o.kind == "install-state"] == ["ok"]
    # scoped doctor and a doctor given no state dir skip installation-wide state
    assert not [o for o in ai.doctor(catalog, **kw)[0] if o.kind == "install-state"]


def test_cli_recover_dry_run_then_yes(tmp_path):
    state, _ = kill_at(tmp_path, "pre-terminal-save")
    cmd = [sys.executable, "-I", "-B", str(REPO / "bin" / "ade-install"), "recover", "--json", "--state-dir", str(state)]
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    dry = json.loads(subprocess.run(cmd, capture_output=True, text=True, env=env, check=True).stdout)
    assert dry["status"] == "dry-run" and "ledger-entry/tool" in dry["would_repair"]
    live = subprocess.run(cmd + ["--yes"], capture_output=True, text=True, env=env)
    assert live.returncode == 0 and json.loads(live.stdout)["status"] == "recovered"


def test_symlinked_lock_and_evidence_never_redirect_a_write(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("precious\n")
    (state / "ledger.lock").symlink_to(victim)
    with pytest.raises(ai.InstallError):
        with ai.install_ledger_lock(state):
            pass
    assert victim.read_text() == "precious\n"
    assert rec.lock_state(state) == "held"  # a link is unverifiable, never "free"
    (state / "ledger.lock").unlink()
    (state / ai.RECOVERY_EVIDENCE).symlink_to(victim)
    with pytest.raises(ai.InstallError):
        ai.append_recovery_evidence(state, {"event": "x"})
    # a hostile stale holder plus a linked evidence log: the lock still works and writes nothing through the link
    (state / "ledger.lock").write_text(json.dumps({"pid": 999999999, "start": 1}))
    with ai.install_ledger_lock(state):
        pass
    assert victim.read_text() == "precious\n"
    report, rc = rec.recover(state, yes=True)  # write-ahead evidence refused: no repair attempted
    assert victim.read_text() == "precious\n"


def test_hostile_state_dir_data_cannot_crash_lock_doctor_or_recover(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "ledger.lock").write_text(json.dumps({"pid": 10**12, "start": 1}))
    with ai.install_ledger_lock(state):  # OverflowError in the advisory holder swap must not fail the lock
        pass
    (state / f"ledger.json.{10**12}.unknown.x.tmp").write_text("{}")
    assert {f.status for f in rec.scan(state)} == {"orphaned"}
    assert rec.recover(state, yes=True)[1] == 0
    assert ai.owner_status({"pid": 10**12, "start": 1}) == "unknown"
    assert ai.owner_status({"pid": True and "x"}) == "unknown"


def test_non_regular_lock_file_does_not_hang_the_scan(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    os.mkfifo(state / "ledger.lock")
    signal.alarm(10)
    try:
        assert [(f.kind, f.status) for f in rec.scan(state)] == [("state-file", "corrupt")] and rec.lock_state(state) == "held"
    finally:
        signal.alarm(0)


def test_start_time_jitter_is_tolerated_and_young_reuse_verdicts_wait(tmp_path):
    me = os.getpid()
    start = ai.process_start_time(me)
    if start is None:
        pytest.skip("process start time unreadable here")
    assert ai.owner_status({"pid": me, "start": start + 1}) == "alive"
    assert ai.owner_status({"pid": me, "start": start - 1000}) == "reused"
    state = tmp_path / "state"
    state.mkdir()
    temp = state / f"ledger.json.{me}.00000000.abc.tmp"  # live pid, different start token
    temp.write_text("{}")
    assert [f.status for f in rec.scan(state)] == ["active"]  # young: a lock-free writer may be mid-write
    os.utime(temp, (time.time() - 3600, time.time() - 3600))
    assert [f.status for f in rec.scan(state)] == ["orphaned"]
    late = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 30))
    assert ai.sentinel_owner_status({"pid": str(me), "started": late}) == "alive"  # bridge clock step: not reused


def test_hostile_file_names_are_escaped_in_reports(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "ledger.json.99999999.unknown.\x1b[31m.tmp").write_text("{}")
    rows = rec.observations(state)
    assert rows and all("\x1b" not in r.id + r.detail for r in rows)


def test_start_time_does_not_depend_on_the_callers_tz(tmp_path, monkeypatch):
    spawned = time.time()
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
    try:
        got = set()
        for tz in ("UTC", "America/Los_Angeles", "Asia/Kolkata", None):
            if tz is None:
                monkeypatch.delenv("TZ", raising=False)
            else:
                monkeypatch.setenv("TZ", tz)
            time.tzset()
            got.add(ai.process_start_time(child.pid))
        assert len(got) == 1 and None not in got
        assert abs(next(iter(got)) - spawned) < 10  # a consistent zone offset would still pass the equality
    finally:
        child.kill()
        child.wait()
        monkeypatch.undo()
        time.tzset()


def test_refused_evidence_log_keeps_the_stale_holder_record(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    victim = tmp_path / "log-target"
    victim.write_text("")
    (state / ai.RECOVERY_EVIDENCE).symlink_to(victim)
    stale = json.dumps({"pid": 999999999, "start": 1})
    (state / "ledger.lock").write_text(stale)
    with ai.install_ledger_lock(state):
        pass
    assert (state / "ledger.lock").read_text() == stale and victim.read_text() == ""  # nothing erased unlogged
    report, rc = rec.recover(state, yes=True)
    assert rc == 1 and report["status"] == "refused"
    assert any(f["kind"] == "state-file" for f in report["findings"])  # doctor sees the unsafe log too


def test_doctor_reports_unsafe_state_files_and_fifo_evidence_does_not_hang(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "t").write_text("")
    (state / "ledger.lock").symlink_to(tmp_path / "t")
    obs = rec.observations(state)
    assert [(o.status, o.id) for o in obs] == [("corrupt", "state-file/ledger.lock")] and rec.failing(obs) == 1
    (state / "ledger.lock").unlink()
    os.mkfifo(state / ai.RECOVERY_EVIDENCE)
    (state / "ledger.lock").write_text(json.dumps({"pid": 999999999, "start": 1}))
    signal.alarm(10)
    try:
        with ai.install_ledger_lock(state):  # a reader-less FIFO would block an O_WRONLY open forever
            pass
        assert rec.recover(state, yes=True)[1] == 1
    finally:
        signal.alarm(0)


def test_root_refuses_the_lock_in_a_user_owned_state_dir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(ai.InstallError, match="as root"):
        with ai.install_ledger_lock(state):
            pass
    assert not (state / "ledger.lock").exists()


def test_dry_run_output_escapes_hostile_names(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "ledger.json.99999999.unknown.\x1b[31m.tmp").write_text("{}")  # APFS rejects invalid UTF-8 names, so no surrogates here
    out = subprocess.run([sys.executable, "-I", "-B", str(REPO / "bin" / "ade-install"), "recover", "--state-dir", str(state)],
                         capture_output=True, text=True, env={**os.environ, "HOME": str(tmp_path / "home")})
    assert out.returncode == 0 and "\x1b" not in out.stdout and "Traceback" not in out.stderr


def test_root_guard_runs_before_any_mkdir_and_judges_every_ancestor(tmp_path, monkeypatch):
    fresh = tmp_path / "a" / "b" / "state"  # does not exist yet; ancestors are user-owned
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    with pytest.raises(ai.InstallError, match="as root|root does not own"):
        with ai.install_ledger_lock(fresh):
            pass
    assert not (tmp_path / "a").exists()  # nothing was created before the refusal
