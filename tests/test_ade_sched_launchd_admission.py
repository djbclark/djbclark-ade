"""W21b: the native launchd admission for `ade-sched reconcile` (offline; a fake launchctl records argv).

The fake never touches the host: its "launchd" is a directory of marker files. A loaded job is never admitted (no launch
exclusion exists from outside it: `launchctl disable` does not stop a loaded StartInterval job, and an idle read followed
by `bootout` is two operations), so the tests assert zero bootout/bootstrap/disable/enable/kickstart calls on a loaded job.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_install as ai  # noqa: E402
import ade_sched as S  # noqa: E402
from test_ade_jobs_reconcile import _mini_catalog  # noqa: E402

LABEL = "com.djbclark.deadline-sweep"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "launchd"
NEVER = {"disable", "enable", "kickstart", "kill", "bootout", "bootstrap", "remove"}
KILLERS = NEVER - {"bootstrap"}  # an admitted install may bootstrap; nothing may ever boot out, disable or kill

FAKE_LAUNCHCTL = r"""#!/usr/bin/env python3
import json, os, sys
root = os.environ["FAKE_LD"]
argv = sys.argv[1:]
with open(os.path.join(root, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(argv) + "\n")
def flag(*p): return os.path.exists(os.path.join(root, *p))
def touch(*p):
    os.makedirs(os.path.join(root, p[0]), exist_ok=True)
    open(os.path.join(root, *p), "w").close()
def drop(*p):
    try: os.unlink(os.path.join(root, *p))
    except FileNotFoundError: pass
def read(*p):
    try: return open(os.path.join(root, *p)).read().strip()
    except FileNotFoundError: return None
def write(text, *p):
    os.makedirs(os.path.join(root, p[0]), exist_ok=True)
    open(os.path.join(root, *p), "w").write(text)
cmd = argv[0]
label = argv[1].rsplit("/", 1)[-1] if len(argv) > 1 else ""
if flag("fail", cmd):
    sys.stderr.write("fake failure\n"); sys.exit(int(read("fail", cmd) or 1))
if cmd == "print":
    if not flag("loaded", label):
        n = int(read("load_after_absent_print") or 0)   # "the Nth not-loaded answer is followed by an outside loader"
        if n:
            seen = int(read("absent_prints", "n") or 0) + 1
            write(str(seen), "absent_prints", "n")
            if seen == n:
                touch("loaded", label); write("running", "state", label); write("4242", "pid", label)
        sys.stderr.write("Could not find service\n"); sys.exit(113)
    if flag("garbage"):
        print("something unexpected"); sys.exit(0)
    print(f"{argv[1]} = {{")
    print("\tactive count = 1")
    print(f"\tstate = {read('state', label) or 'not running'}")
    if flag("pid", label): print(f"\tpid = {read('pid', label)}")
    print("\tresource coalition = {")
    print("\t\tstate = active")   # nested decoy: only the service block's own fields count
    print("\t}")
    print("}")
    if flag("start_work_after_print"):   # a launchd trigger fires right after the idle observation
        write("running", "state", label); write("4242", "pid", label)
elif cmd == "bootout":
    # killing running work is the one thing admission must never cause
    if read("pid", label):
        write("1", "killed", label)
    drop("loaded", label)
elif cmd == "bootstrap":
    base = os.path.basename(argv[2])[:-len(".plist")]
    if flag("loaded", base):
        sys.stderr.write("Bootstrap failed: 5: Input/output error\n"); sys.exit(5)
    touch("loaded", base)
sys.exit(0)
"""


@pytest.fixture
def ld(tmp_path):
    root = tmp_path / "ld"
    root.mkdir()
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(FAKE_LAUNCHCTL)
    launchctl.chmod(0o755)
    (tmp_path / "agents").mkdir()
    (tmp_path / "home").mkdir()
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "USER": "tester",
        "FAKE_LD": str(root),
        "ADE_TIMEZONE": "America/New_York",
        "ADE_SCHED_LAUNCHCTL": str(launchctl),
        "ADE_SCHED_LAUNCH_AGENTS": str(tmp_path / "agents"),
        "ADE_SCHED_LOCK": str(tmp_path / "lock" / "ade-sched.lock"),
        "ADE_JOBS_STATE_DIR": str(tmp_path / "jobs-state"),
    }
    env.pop("ADE_SCHED_BACKEND", None)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"  # no real paseo/launchctl/crontab: reconcile's live scan must stay offline

    class L:
        pass

    f = L()
    f.root, f.env, f.tmp = root, env, tmp_path
    f.launchctl = str(launchctl)
    f.agents = tmp_path / "agents"
    f.state = tmp_path / "jobs-state"
    f.uid = os.getuid()
    f.calls = lambda: [json.loads(x) for x in (root / "calls.jsonl").read_text().splitlines()] \
        if (root / "calls.jsonl").exists() else []
    f.verbs = lambda: [c[0] for c in f.calls()]
    f.reset = lambda: (root / "calls.jsonl").unlink(missing_ok=True)

    def mark(kind, label=LABEL, text=""):
        (root / kind).mkdir(exist_ok=True)
        (root / kind / label).write_text(text)

    def fail(cmd, rc="1"):
        (root / "fail").mkdir(exist_ok=True)
        (root / "fail" / cmd).write_text(rc)

    f.mark, f.fail = mark, fail
    f.flag = lambda name, text="1": (root / name).write_text(text)
    f.loaded = lambda label=LABEL: (root / "loaded" / label).exists()
    f.killed = lambda label=LABEL: (root / "killed" / label).exists()
    f.unload = lambda label=LABEL: (root / "loaded" / label).unlink()
    return f


def _adapter(ld, provenance=None):
    return S.launchd_admission(launchctl=ld.launchctl, uid=ld.uid, agents_dir=ld.agents, env=ld.env, provenance=provenance)


def _step(action="install", label=LABEL):
    return S.ReconcileStep("deadline-sweep", action, S.OWNER_ADE, "d", label, touch=True)


def _existing(ld, state="not running", pid=None, plist=True, loaded=True):
    if loaded:
        ld.mark("loaded")
        ld.mark("state", text=state)
    if pid is not None:
        ld.mark("pid", text=str(pid))
    if plist:
        (ld.agents / f"{LABEL}.plist").write_text("<plist/>")


# ---------------------------------------------------------------- parsing (real captured launchctl output)

@pytest.mark.parametrize("name,want", [("print_idle.txt", "idle"), ("print_running.txt", "busy")])
def test_parse_activity_on_real_launchctl_output(name, want):
    # The real output also carries nested `state = active` coalition lines (two tabs deep): they must not count.
    text = (FIXTURES / name).read_text()
    assert "\t\tstate = active" in text
    assert S.parse_launchd_activity(text) == want


@pytest.mark.parametrize("text,want", [
    ("gui/501/x = {\n\tactive count = 1\n\tstate = not running\n}\n", "idle"),
    ("gui/501/x = {\n\tstate = waiting\n}\n", "unknown"),   # never captured: fails closed
    ("gui/501/x = {\n\tstate = running\n\tpid = 42\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = running\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = spawn scheduled\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = 7\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = abc\n}\n", "unknown"),
    ("gui/501/x = {\n\tcoalition = {\n\t\tstate = running\n\t}\n\tstate = not running\n}\n", "idle"),
    ("gui/501/x = {\n\tactive count = 0\n}\n", "unknown"),
    ("something unexpected\n", "unknown"),
    ("", "unknown"),
])
def test_parse_activity(text, want):
    assert S.parse_launchd_activity(text) == want


# ---------------------------------------------------------------- the adapter alone

def test_absent_job_is_admitted(ld):
    with _adapter(ld)(_step()) as ev:
        assert ev.refusal() is None
    assert ld.verbs() == ["print"]


@pytest.mark.parametrize("kw", [dict(), dict(state="running", pid=4242), dict(state="running"), dict(pid=9)])
def test_loaded_job_in_any_state_defers_untouched(ld, kw):
    _existing(ld, **kw)
    with _adapter(ld, provenance=lambda step, plist: None)(_step("install")) as ev:
        assert "loaded" in (ev.refusal() or "")
    assert ld.loaded() and ld.verbs() == ["print"] and not ld.killed()


@pytest.mark.parametrize("state", ["absent", "unloaded", "loaded"])
def test_every_removal_defers_before_any_launchctl_call(ld, state):
    # An unlink cannot be compare-and-swap against other writers: no native removal, whatever the job's state.
    if state != "absent":
        _existing(ld, loaded=(state == "loaded"))
    with _adapter(ld, provenance=lambda step, plist: None)(_step("remove")) as ev:
        assert "removal" in (ev.refusal() or "")
    assert ld.verbs() == []


def test_loaded_job_with_unparseable_print_defers_untouched(ld):
    _existing(ld)
    ld.flag("garbage")
    with _adapter(ld)(_step()) as ev:
        assert ev.refusal() is not None
    assert ld.loaded() and ld.verbs() == ["print"]


def test_unreadable_print_defers(ld):
    _existing(ld)
    ld.fail("print", "5")
    with _adapter(ld)(_step()) as ev:
        assert "unreadable (rc=5)" in (ev.refusal() or "")  # not the pytest tmp dir name, which also says "unreadable"
    assert ld.loaded() and ld.verbs() == ["print"]


def test_updater_own_running_service_keeps_its_refusal(ld):
    label = "com.djbclark.ade-update-check"
    ld.mark("loaded", label)
    ld.mark("state", label, "running")
    ld.mark("pid", label, "9")
    (ld.agents / f"{label}.plist").write_text("<plist/>")
    with _adapter(ld)(_step(label=label)) as ev:
        assert ev.refusal() == "updater's own running service; next generation pending"
    assert ld.loaded(label) and ld.verbs() == ["print"]


def test_unloaded_plist_without_a_provenance_check_defers(ld):
    _existing(ld, loaded=False)
    with _adapter(ld)(_step()) as ev:
        assert "not provably ADE's" in (ev.refusal() or "")


@pytest.mark.parametrize("reason,admitted", [(None, True), ("foreign", False)])
def test_unloaded_plist_is_admitted_only_when_provenance_proves_it(ld, reason, admitted):
    _existing(ld, loaded=False)
    seen = []

    def prov(step, plist):
        seen.append((step.action, plist))
        return reason

    with _adapter(ld, prov)(_step("install")) as ev:
        assert (ev.refusal() is None) is admitted
    assert seen == [("install", ld.agents / f"{LABEL}.plist")] and ld.verbs() == ["print"]


def test_dangling_symlink_at_the_plist_path_is_not_absent(ld):
    (ld.agents / f"{LABEL}.plist").symlink_to(ld.tmp / "nowhere")
    with _adapter(ld, lambda step, plist: "not a regular file")(_step()) as ev:
        assert ev.refusal() is not None


def test_invalid_label_gets_the_conservative_default(ld):
    with _adapter(ld)(S.ReconcileStep("x", "install", S.OWNER_ADE, "d", None, touch=True)) as ev:
        assert ev.refusal() == S.JobAdmission().refusal()
    assert ld.verbs() == []


# ---------------------------------------------------------------- through reconcile

def _reconcile(ld, root, catalog, **kw):
    return S.reconcile(
        catalog.jobs, catalog.retired_jobs, dry_run=False, backend="launchd", root=root, ade=root,
        env=ld.env, state_dir=ld.state, names={"deadline-sweep"}, live=S.LiveScan("launchd", ()),
        platform_name="mac", native_admission=True, **kw,
    )


def _installed(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    return root, catalog


def _entries(ld):
    return S.load_jobs_ledger(ld.state, env=ld.env)["entries"]


def _deferral_reasons(ld):
    deferred = json.loads((ld.state / "jobs-deferred.json").read_text())
    return [v["reason"] for v in deferred["jobs"].values()]


def _drift(ld, text="<!-- drift -->\n"):
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text(plist.read_text() + text)
    return plist


def test_fresh_install_is_admitted_and_ledgered(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "installed" for r in rows)
    entry = _entries(ld)["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert ld.loaded() and not KILLERS & set(ld.verbs()) and "bootstrap" in ld.verbs()
    plist = ld.agents / f"{LABEL}.plist"
    assert stat.S_IMODE(plist.stat().st_mode) == 0o600
    assert [f.name for f in ld.agents.iterdir()] == [plist.name]  # the exclusive-create temp name is gone


def test_loaded_job_that_needs_a_reload_defers_and_is_never_unloaded(ld):
    root, catalog = _installed(ld)
    plist = _drift(ld)
    drifted = plist.read_text()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_text() == drifted and ld.loaded()
    assert not NEVER & set(ld.verbs())
    deferred = json.loads((ld.state / "jobs-deferred.json").read_text())
    assert any("loaded" in v["reason"] for v in deferred["jobs"].values())


def test_work_that_starts_after_the_idle_read_is_never_signalled(ld):
    # F1: the fake starts work the moment `print` has answered "not running". Admission must make no destructive call.
    root, catalog = _installed(ld)
    _drift(ld)
    ld.flag("start_work_after_print")
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert not NEVER & set(ld.verbs()) and not ld.killed() and ld.loaded()
    assert (ld.root / "pid" / LABEL).read_text() == "4242"  # the job that started is still running


def test_unloaded_job_with_the_ade_render_is_bootstrapped_without_any_write(ld):
    root, catalog = _installed(ld)
    plist = ld.agents / f"{LABEL}.plist"
    before = (plist.read_bytes(), plist.stat().st_ino, plist.stat().st_mtime_ns)
    ld.unload()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "installed" for r in rows), rows
    assert ld.loaded() and "bootstrap" in ld.verbs() and not KILLERS & set(ld.verbs())
    assert (plist.read_bytes(), plist.stat().st_ino, plist.stat().st_mtime_ns) == before  # no write, no replace


def test_unloaded_ade_owned_older_definition_is_deferred_not_overwritten(ld):
    # R2: even a ledger-owned file whose recorded hash matches is never overwritten: a hash read cannot make
    # check-and-overwrite atomic against another writer. Only a byte-match of the render is bootstrapped.
    root, catalog = _installed(ld)
    plist = _drift(ld)
    older = plist.read_bytes()
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"]["artifact_hash"] = S.artifact_hash({plist: plist.read_text()})
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    ld.unload()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_bytes() == older and not NEVER & set(ld.verbs())
    assert any("not provably ADE's" in r for r in _deferral_reasons(ld)), _deferral_reasons(ld)


def test_outside_loader_after_an_absent_print_is_never_booted_out(ld):
    # R1: `print` says "not loaded", then something loads the label and starts work. The install must not bootout.
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    # Fresh install reads: 2x plan-time status, then the adapter's own `print` (the 3rd not-loaded answer) before bootstrap.
    ld.flag("load_after_absent_print", "3")
    rows, rc = _reconcile(ld, root, catalog)
    assert (ld.root / "absent_prints" / "n").read_text() == "3" and "bootstrap" in ld.verbs()  # the race really happened
    assert rc == 1 and any(r["action"] == "failed" for r in rows), rows
    assert "bootout" not in ld.verbs() and not KILLERS & set(ld.verbs())
    assert not ld.killed() and ld.loaded() and (ld.root / "pid" / LABEL).read_text() == "4242"
    failed = next(r for r in rows if r["action"] == "failed")
    assert "left in place" in failed["detail"] and (ld.agents / f"{LABEL}.plist").exists()


def test_target_that_appears_between_admission_and_write_is_not_overwritten(ld, monkeypatch):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    plist = ld.agents / f"{LABEL}.plist"
    real = S._log_dirs  # runs after admission, before the existence check
    monkeypatch.setattr(S, "_log_dirs", lambda job: (real(job), plist.write_text("<plist>hand managed</plist>\n")))
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_text() == "<plist>hand managed</plist>\n" and not NEVER & set(ld.verbs())
    assert "deadline-sweep" not in _entries(ld)  # the pending intent was rolled back, not left as failed


def test_defer_after_a_hand_deletion_restores_the_existing_ledger_row(ld, monkeypatch):
    # The ledger holds a committed row (with a prior identity); the plist was deleted by hand; a writer re-creates the
    # path after admission. The rollback must put the whole row back, not drop it (that would lose removal authority).
    root, catalog = _installed(ld)
    plist = ld.agents / f"{LABEL}.plist"
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"]["prior_identity"] = {**ledger["entries"]["deadline-sweep"], "generation": 0}
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)  # (same label: no removal is planned, the row must still survive whole)
    before = _entries(ld)["deadline-sweep"]
    ld.unload()
    plist.unlink()
    ld.reset()
    real = S._log_dirs
    monkeypatch.setattr(S, "_log_dirs", lambda job: (real(job), plist.write_text("<plist>hand managed</plist>\n")))
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert plist.read_text() == "<plist>hand managed</plist>\n"  # the hook ran, so the NativeDefer path (not admission) decided
    assert any("exists and is not the ADE render" in r for r in _deferral_reasons(ld)), _deferral_reasons(ld)
    assert _entries(ld)["deadline-sweep"] == before and not NEVER & set(ld.verbs())


@pytest.mark.parametrize("exc", [PermissionError("denied"), OSError(45, "Operation not supported"), UnicodeEncodeError("ascii", "x", 0, 1, "bad")])
def test_unexpected_oserror_from_the_native_install_is_a_failed_row_not_a_traceback(ld, monkeypatch, exc):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)

    def boom(*a, **kw):
        raise exc

    monkeypatch.setattr(S, "create_exclusive", boom)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and any(r["action"] == "failed" for r in rows), rows
    assert not NEVER & set(ld.verbs()) and not (ld.agents / f"{LABEL}.plist").exists()
    assert _entries(ld)["deadline-sweep"]["status"] == "failed"  # reached the existing ledger-failed handling


def test_paseo_install_step_on_a_launchd_host_never_reaches_the_launchd_adapter(ld, monkeypatch):
    # An unrelated missing LaunchAgent file must not admit a paid-run paseo mutation.
    step = S.ReconcileStep("p", "install", S.OWNER_ADE, "paseo schedule create x", "x-schedule", touch=True)
    monkeypatch.setattr(S, "plan_reconcile", lambda *a, **kw: [step])

    def no_paseo(*a, **kw):
        pytest.fail("a paseo schedule must not be created through the launchd adapter")

    rows, rc = S.reconcile([{"name": "p", "kind": "paseo", "owner": S.OWNER_ADE}], [], dry_run=False, backend="launchd",
                           root=ld.tmp, env=ld.env, state_dir=ld.state, live=S.LiveScan("launchd", ()),
                           paseo_run=no_paseo, native_admission=True)
    assert rc == 6 and rows[0]["action"] == "deferred", rows
    assert ld.verbs() == []


def test_target_that_appears_during_the_exclusive_create_is_not_overwritten(ld, monkeypatch):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    plist = ld.agents / f"{LABEL}.plist"
    real = S.create_exclusive

    def racing(path, text, mode=0o600):
        path.write_text("<plist>hand managed</plist>\n")  # a writer wins right before our link
        return real(path, text, mode)

    monkeypatch.setattr(S, "create_exclusive", racing)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert plist.read_text() == "<plist>hand managed</plist>\n" and not NEVER & set(ld.verbs())
    assert [f.name for f in ld.agents.iterdir()] == [plist.name]


def test_create_exclusive_writes_utf8_bytes_whatever_the_locale(tmp_path):
    target = tmp_path / "u.plist"
    S.create_exclusive(target, "é\n")
    assert target.read_bytes() == "é\n".encode("utf-8") and stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [f.name for f in tmp_path.iterdir()] == ["u.plist"]


def test_a_temp_unlink_failure_after_a_successful_link_is_not_an_error(tmp_path, monkeypatch):
    target = tmp_path / "u.plist"
    real = Path.unlink

    def flaky(self, missing_ok=False):
        if self.name.endswith(".tmp"):
            raise PermissionError("busy")
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky)
    S.create_exclusive(target, "x")  # the definition exists; the leftover temp name is harmless (no .plist suffix)
    assert target.read_text() == "x"


@pytest.mark.parametrize("make", ["file", "dangling-symlink"])
def test_create_exclusive_never_replaces_anything(tmp_path, make):
    target = tmp_path / "x.plist"
    if make == "file":
        target.write_text("old")
    else:
        target.symlink_to(tmp_path / "nowhere")
    with pytest.raises(FileExistsError):
        S.create_exclusive(target, "new")
    assert (target.read_text() == "old") if make == "file" else target.is_symlink()
    assert [f.name for f in tmp_path.iterdir()] == ["x.plist"]


@pytest.mark.parametrize("loaded", [False, True])
def test_same_path_foreign_plist_without_ledger_is_never_overwritten(ld, loaded):
    # F2: a hand-managed plist at the conventional path, no ADE ledger entry.
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text("<plist>hand managed</plist>\n")
    if loaded:
        ld.mark("loaded")
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_text() == "<plist>hand managed</plist>\n"
    assert not NEVER & set(ld.verbs()) and "deadline-sweep" not in _entries(ld)
    # refused by admission itself (before any write), not only by the install-time byte compare
    assert any("loaded" in r if loaded else "not provably ADE's" in r for r in _deferral_reasons(ld)), _deferral_reasons(ld)


def test_plist_replaced_after_the_ledger_recorded_it_is_not_overwritten(ld):
    root, catalog = _installed(ld)
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text("<plist>replaced by someone else</plist>\n")
    ld.unload()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert plist.read_text() == "<plist>replaced by someone else</plist>\n" and not NEVER & set(ld.verbs())


def test_non_utf8_plist_defers_instead_of_crashing(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_bytes(b"bplist00\xff\xfe\x80")
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert plist.read_bytes() == b"bplist00\xff\xfe\x80" and not NEVER & set(ld.verbs())


@pytest.mark.parametrize("breakage", ["label-mismatch", "missing-source", "unrenderable-source"])
def test_blocked_row_keeps_its_installed_definition_and_ledger_row(ld, breakage):
    root, catalog = _installed(ld)
    plist = ld.agents / f"{LABEL}.plist"
    bytes_before = plist.read_bytes()
    entry_before = _entries(ld)["deadline-sweep"]
    ld.unload()
    source = root / "config" / "launchd" / f"{LABEL}.plist"
    if breakage == "label-mismatch":
        toml = root / "config" / "install.toml"
        toml.write_text(toml.read_text().replace(f'label = "{LABEL}"', 'label = "com.djbclark.other"'))
    elif breakage == "missing-source":
        source.unlink()
    else:
        source.write_text("<plist><dict><key>Label</key></dict>")  # not renderable
    catalog = ai.load_catalog(root=root)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and any(r["action"] == "blocked" for r in rows), rows
    assert not any(r["action"] in ("removed", "remove") for r in rows)
    assert plist.read_bytes() == bytes_before and not NEVER & set(ld.verbs())
    assert _entries(ld)["deadline-sweep"] == entry_before


@pytest.mark.parametrize("breakage", ["missing-source", "unrenderable-source"])
def test_planner_alone_suppresses_removal_for_a_blocked_row(ld, breakage):
    # Protects low-level callers too: no admission involved, only plan_reconcile.
    root, catalog = _installed(ld)
    source = root / "config" / "launchd" / f"{LABEL}.plist"
    if breakage == "missing-source":
        source.unlink()
    else:
        source.write_text("<plist><dict><key>Label</key></dict>")
    catalog = ai.load_catalog(root=root)
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"]["prior_identity"] = {**ledger["entries"]["deadline-sweep"],
                                                            "label": "com.djbclark.older"}
    steps = S.plan_reconcile(
        catalog.jobs, catalog.retired_jobs, ledger=ledger, live=S.LiveScan("launchd", ()), backend_name="launchd",
        root=root, ade=root, env=ld.env, names={"deadline-sweep"}, platform_name="mac",
    )
    assert [x.action for x in steps if x.name == "deadline-sweep"] == ["blocked"]
    assert not [x for x in steps if x.action == "remove"]


def test_fifo_at_the_plist_path_is_not_read(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    fifo = ld.agents / f"{LABEL}.plist"
    os.mkfifo(fifo)
    signal.signal(signal.SIGALRM, lambda *_: pytest.fail("reconcile blocked reading the FIFO"))
    signal.alarm(20)
    try:
        rows, rc = _reconcile(ld, root, catalog)  # a read of the FIFO would block forever
    finally:
        signal.alarm(0)
    assert rc != 0 and not NEVER & set(ld.verbs()), rows
    assert fifo.exists()


def _owned_retired_job(ld, label="com.djbclark.skillopt-sleep", loaded=False, ledger_hash=None):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    plist = ld.agents / f"{label}.plist"
    plist.write_text(
        f"# {S.GENERATED} from retired\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        f'<plist version="1.0"><dict><key>Label</key><string>{label}</string>'
        "<key>ProgramArguments</key><array><string>/bin/true</string></array></dict></plist>\n"
    )
    if loaded:
        ld.mark("loaded", label)
    ledger = S.empty_jobs_ledger(env=ld.env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep", "label": label, "owner": "djbclark-ade", "backend": "launchd",
        "scope": "user", "paths": [str(plist)], "generation": 1, "status": "committed",
        "artifact_hash": ledger_hash or S.artifact_hash({plist: plist.read_text()}),
    }
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    return root, catalog, label, plist


def _reconcile_removal(ld, root, catalog, label):
    return S.reconcile(
        catalog.jobs, catalog.retired_jobs, dry_run=False, backend="launchd", root=root, ade=root,
        env=ld.env, state_dir=ld.state, names={"skillopt-sleep"},
        live=S.LiveScan("launchd", (S.LiveJob(label, "launchd", "generated", True),)),
        platform_name="mac", native_admission=True,
    )


@pytest.mark.parametrize("hash_ok", [True, False])
@pytest.mark.parametrize("loaded", [False, True])
def test_every_native_removal_defers_and_keeps_file_and_ledger(ld, loaded, hash_ok):
    # An unlink cannot be compare-and-swap: even an unloaded, ledger-owned, hash-matching job is not removed.
    root, catalog, label, plist = _owned_retired_job(ld, loaded=loaded, ledger_hash=None if hash_ok else "deadbeef")
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.exists() and "skillopt-sleep" in _entries(ld)
    assert ld.loaded(label) is loaded and ld.verbs() == [] and not ld.killed(label)


def test_adopts_a_loaded_low_level_install_without_any_launchctl_mutation(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    job_row = next(j for j in catalog.jobs if j["name"] == "deadline-sweep")
    subst = S.job_subst_from_row(job_row, root=root, env=ld.env, extra=None)
    S.install(S.Job.from_plist(root / job_row["plist"], subst, ade=root), "launchd", env=ld.env)
    assert not (ld.state / "jobs.json").exists() and ld.loaded()  # loaded, and the ledger does not know the job
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "adopted" for r in rows)
    entry = _entries(ld)["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert not NEVER & set(ld.verbs()) and ld.loaded()


def test_label_mismatch_between_catalog_and_plist_is_blocked_before_any_launchctl_write(ld):
    root = _mini_catalog(ld.tmp)
    toml = root / "config" / "install.toml"
    toml.write_text(toml.read_text().replace(f'label = "{LABEL}"', 'label = "com.djbclark.other"'))
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and any(r["action"] == "blocked" and "differs" in r["detail"] for r in rows), rows
    assert not {"bootout", "bootstrap"} & set(ld.verbs())


def test_label_mismatch_at_execution_is_refused_before_install(ld, monkeypatch):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(S, "plan_reconcile", lambda *a, **kw: [
        S.ReconcileStep("deadline-sweep", "install", S.OWNER_ADE, "d", "com.djbclark.other", touch=True)])
    monkeypatch.setattr(S, "install", lambda *a, **kw: pytest.fail("install must not run for an unadmitted label"))
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 1 and rows[0]["action"] == "failed" and "differs" in rows[0]["detail"], rows


@pytest.mark.parametrize("backend", ["paseo", "systemd", "cron"])
def test_other_backends_keep_the_conservative_default(ld, monkeypatch, backend):
    label = "com.djbclark.old"
    old = dict(logical_id="old", label=label, owner=S.OWNER_ADE, backend=backend,
               scope="user", status="committed", paths=["old"], generation=1)
    ledger = S.empty_jobs_ledger(env=ld.env)
    ledger["entries"]["old"] = old
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    step = S.ReconcileStep("old", "remove", S.OWNER_ADE, "retired", label, touch=True, ledger_snapshot=old)
    monkeypatch.setattr(S, "plan_reconcile", lambda *a, **kw: [step])

    def no_effect(*a, **kw):
        pytest.fail("deferred work must never unload or stop paid runs")

    monkeypatch.setattr(S, "uninstall", no_effect)
    host = "launchd" if backend == "paseo" else backend
    rows, rc = S.reconcile([], [], dry_run=False, backend=host, root=ld.tmp, env=ld.env, state_dir=ld.state,
                           live=S.LiveScan(host, ()), paseo_run=no_effect, native_admission=True)
    assert rc == 6 and rows[0]["action"] == "deferred", rows
    assert ld.verbs() == []  # not one launchctl call for a non-launchd (or paseo) step


def test_explicit_admission_wins_over_the_native_adapter(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(
        ld, root, catalog, admission=lambda step: contextlib.nullcontext(S.JobAdmission()),
    )
    assert rc == 6 and not {"bootout", "bootstrap"} & set(ld.verbs())


def test_no_activate_keeps_the_conservative_default(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog, activate=False)
    assert rc == 6 and not {"bootout", "bootstrap"} & set(ld.verbs())


# ---------------------------------------------------------------- the production callers pass native_admission

def test_ade_install_apply_requests_the_native_adapter(ld, monkeypatch):
    seen = []

    def fake_reconcile(*a, **kw):
        seen.append(kw)
        return [], 0

    monkeypatch.setattr(S, "reconcile", fake_reconcile)
    monkeypatch.setattr(sys, "platform", "linux")  # CI runs on Linux: the backend must come from the env, not the host
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    env = {**ld.env, "ADE_SCHED_BACKEND": "launchd"}
    ai.apply_sched_reconcile(catalog, dry_run=False, names={"deadline-sweep"}, env=env, state_dir=ld.state)
    assert seen and seen[0].get("native_admission") is True


def test_ade_sched_cli_reconcile_yes_uses_the_native_adapter(ld):
    root = _mini_catalog(ld.tmp)
    proc = subprocess.run(
        [sys.executable, "-I", str(BIN / "ade-sched"), "--root", str(root), "--ade", str(root), "--backend", "launchd",
         "reconcile", "--yes", "--json", "--name", "deadline-sweep"],
        env=ld.env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert any(r["action"] == "installed" for r in out["results"]), out
    assert "print" in ld.verbs()  # the adapter read the label before installing
