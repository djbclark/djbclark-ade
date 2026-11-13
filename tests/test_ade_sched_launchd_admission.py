"""W21b: the read-only native launchd admission adapter for `ade-sched reconcile` (offline; a fake launchctl records argv).

The fake never touches the host: its "launchd" is a directory of marker files. A loaded job is never admitted (no launch
exclusion exists from outside it: `launchctl disable` does not stop a loaded StartInterval job, and an idle read followed
by `bootout` is two operations), so the tests assert zero bootout/bootstrap/disable/enable/kickstart calls on a loaded job.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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
    f.flag = lambda name: (root / name).write_text("1")
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
@pytest.mark.parametrize("action", ["install", "remove"])
def test_loaded_job_in_any_state_defers_untouched(ld, kw, action):
    _existing(ld, **kw)
    with _adapter(ld, provenance=lambda step, plist: None)(_step(action)) as ev:
        assert "loaded" in (ev.refusal() or "")
    assert ld.loaded() and ld.verbs() == ["print"] and not ld.killed()


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

    with _adapter(ld, prov)(_step("remove")) as ev:
        assert (ev.refusal() is None) is admitted
    assert seen == [("remove", ld.agents / f"{LABEL}.plist")] and ld.verbs() == ["print"]


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
    assert ld.loaded() and not {"disable", "enable", "kickstart", "kill"} & set(ld.verbs())


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


def test_unloaded_job_with_the_ade_render_is_loaded(ld):
    root, catalog = _installed(ld)
    ld.unload()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "installed" for r in rows), rows
    assert ld.loaded() and "bootstrap" in ld.verbs()


def test_unloaded_ade_owned_older_definition_is_replaced(ld):
    # The ledger owns the file and its recorded hash equals the file's hash: ADE's own older definition.
    root, catalog = _installed(ld)
    plist = _drift(ld)
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"]["artifact_hash"] = S.artifact_hash({plist: plist.read_text()})
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    ld.unload()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0 and any(r["action"] == "installed" for r in rows), rows
    assert "drift" not in plist.read_text() and ld.loaded()


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


def test_plist_replaced_after_the_ledger_recorded_it_is_not_overwritten(ld):
    root, catalog = _installed(ld)
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text("<plist>replaced by someone else</plist>\n")
    ld.unload()
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert plist.read_text() == "<plist>replaced by someone else</plist>\n" and not NEVER & set(ld.verbs())


def test_ledger_row_of_another_backend_does_not_prove_ownership(ld, monkeypatch):
    # plan_reconcile already defers a backend migration; force the install step so the adapter's own check is what refuses.
    root, catalog = _installed(ld)
    plist = _drift(ld)
    ledger = S.load_jobs_ledger(ld.state, env=ld.env)
    ledger["entries"]["deadline-sweep"]["artifact_hash"] = S.artifact_hash({plist: plist.read_text()})
    ledger["entries"]["deadline-sweep"]["backend"] = "systemd"
    S.save_jobs_ledger(ledger, ld.state, env=ld.env)
    ld.unload()
    ld.reset()
    monkeypatch.setattr(S, "plan_reconcile", lambda *a, **kw: [_step()])
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6, rows
    assert "drift" in plist.read_text() and not NEVER & set(ld.verbs())


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


def test_removal_of_an_unloaded_ade_owned_job_with_matching_hash_proceeds(ld):
    root, catalog, label, plist = _owned_retired_job(ld)
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 0 and any(r["action"] == "removed" for r in rows), rows
    assert not plist.exists() and "skillopt-sleep" not in _entries(ld)


@pytest.mark.parametrize("snapshot_hash_ok", [True, False])
def test_removal_authority_from_the_planned_snapshot_is_hash_checked_too(ld, monkeypatch, snapshot_hash_ok):
    # The ledger row is gone but the plan carries the prior identity (removal authority, `_removal_entry`): the artifact
    # hash that identity recorded must still match the file before the removal is admitted.
    root, catalog, label, plist = _owned_retired_job(ld, ledger_hash=None if snapshot_hash_ok else "deadbeef")
    snapshot = _entries(ld)["skillopt-sleep"]
    S.save_jobs_ledger(S.empty_jobs_ledger(env=ld.env), ld.state, env=ld.env)
    step = S.ReconcileStep("skillopt-sleep", "remove", S.OWNER_ADE, "retired", label, touch=True, ledger_snapshot=snapshot)
    monkeypatch.setattr(S, "plan_reconcile", lambda *a, **kw: [step])
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert (rc == 0) is snapshot_hash_ok, rows
    assert plist.exists() is (not snapshot_hash_ok)


def test_removal_authorized_by_a_stale_ledger_hash_defers(ld):
    root, catalog, label, plist = _owned_retired_job(ld, ledger_hash="deadbeef")
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 6, rows
    assert plist.exists() and "skillopt-sleep" in _entries(ld)


def test_removal_of_a_loaded_job_defers_and_keeps_ownership(ld):
    root, catalog, label, plist = _owned_retired_job(ld, loaded=True)
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 6, rows
    assert plist.exists() and ld.loaded(label) and "skillopt-sleep" in _entries(ld)
    assert not NEVER & set(ld.verbs())


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
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    ai.apply_sched_reconcile(catalog, dry_run=False, names={"deadline-sweep"}, env=ld.env, state_dir=ld.state)
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
