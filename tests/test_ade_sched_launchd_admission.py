"""W21b: the native launchd admission adapter for `ade-sched reconcile` (offline; a fake launchctl records every argv).

The fake never touches the host: its "launchd" is a directory of marker files. Probe, macOS 27.2 (2026-11-12): a loaded job
that is `launchctl disable`d still runs its StartInterval trigger and answers `kickstart`, so the adapter excludes launches
by UNLOADING an idle job, never by disable/enable; the tests assert the adapter never calls them.
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
NEVER = {"disable", "enable", "kickstart", "kill"}

FAKE_LAUNCHCTL = r'''#!/usr/bin/env python3
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
elif cmd == "print-disabled":
    print("\tdisabled services = {")
    print('\t\t"com.apple.other" => enabled')
    if os.path.isdir(os.path.join(root, "disabled")):
        for name in sorted(os.listdir(os.path.join(root, "disabled"))):
            print(f'\t\t"{name}" => disabled')
    print("\t}")
elif cmd == "bootout":
    if not flag("bootout_noop"): drop("loaded", label)
elif cmd == "bootstrap":
    base = os.path.basename(argv[2])[:-len(".plist")]
    if flag("disabled", base):
        sys.stderr.write("Bootstrap failed: 5: Input/output error\n"); sys.exit(5)
    touch("loaded", base)
sys.exit(0)
'''


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
    return f


def _adapter(ld, err=None):
    return S.launchd_admission(launchctl=ld.launchctl, uid=ld.uid, agents_dir=ld.agents, env=ld.env, err=err)


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
    ("gui/501/x = {\n\tstate = waiting\n}\n", "idle"),
    ("gui/501/x = {\n\tstate = running\n\tpid = 42\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = running\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = spawn scheduled\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = 7\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = abc\n}\n", "unknown"),
    ("gui/501/x = {\n\tcoalition = {\n\t\tstate = running\n\t}\n\tstate = not running\n}\n", "idle"),
    ("gui/501/x = {\n\tactive count = 0\n}\n", "unknown"),
    ("gui/501/x = {\n\tstate = mystery\n}\n", "unknown"),
    ("something unexpected\n", "unknown"),
    ("", "unknown"),
])
def test_parse_activity(text, want):
    assert S.parse_launchd_activity(text) == want


def _disabled(*rows):
    return "\tdisabled services = {\n" + "".join(f"\t\t{r}\n" for r in rows) + "\t}\n"


@pytest.mark.parametrize("text,want", [
    (_disabled('"a.b" => disabled'), True),
    (_disabled('"a.b" => true'), True),
    (_disabled('"a.b" => enabled'), False),
    (_disabled('"a.b" => false'), False),
    (_disabled('"other" => disabled', '"a.b" => enabled'), False),
    (_disabled('"other" => enabled'), False),
    (_disabled(), False),
    (_disabled('"a.b" => odd'), None),
    (_disabled('"a.b" => disabled,'), None),       # format drift on the operator's row: unreadable, never "enabled"
    (_disabled('a.b => disabled'), None),
    ('\tdisabled services = {\n\t\t"a.b" => disabled\n', None),   # no closing brace
    ("garbage\n", None),
    ("", None),
])
def test_parse_disabled(text, want):
    assert S.parse_launchd_disabled(text, "a.b") is want


# ---------------------------------------------------------------- the adapter alone

def test_absent_job_is_admitted_without_touching_anything(ld):
    with _adapter(ld)(_step()) as ev:
        assert ev.refusal() is None
    assert ld.verbs() == ["print"]


def test_idle_job_is_unloaded_for_the_whole_context_then_reloaded_if_nothing_reloaded_it(ld):
    _existing(ld)
    with _adapter(ld)(_step("install")) as ev:
        assert ev.refusal() is None
        assert not ld.loaded()  # no launch path exists while the context is held
    assert ld.loaded()  # the mutation never ran: the prior state is restored
    assert ld.verbs().index("bootout") < ld.verbs().index("bootstrap")
    assert not NEVER & set(ld.verbs())


def test_mutation_that_loaded_the_job_is_not_bootstrapped_again(ld):
    _existing(ld)
    with _adapter(ld)(_step("install")):
        ld.mark("loaded")  # install()'s own bootstrap
    assert ld.verbs().count("bootstrap") == 0


def test_removed_job_is_not_reloaded(ld):
    _existing(ld)
    with _adapter(ld)(_step("remove")) as ev:
        assert ev.refusal() is None
        (ld.agents / f"{LABEL}.plist").unlink()  # uninstall()'s own plist removal
    assert not ld.loaded() and "bootstrap" not in ld.verbs()


@pytest.mark.parametrize("kw", [dict(state="running", pid=4242), dict(state="running"), dict(state="not running", pid=9)])
def test_busy_job_defers_without_touching_it(ld, kw):
    _existing(ld, **kw)
    with _adapter(ld)(_step()) as ev:
        assert "busy" in (ev.refusal() or "")
    assert ld.loaded()
    assert ld.verbs() == ["print"]  # no bootout, bootstrap, kill, disable, ...


def test_unknown_activity_defers_without_touching_it(ld):
    _existing(ld)
    ld.flag("garbage")
    with _adapter(ld)(_step()) as ev:
        assert "unknown" in (ev.refusal() or "")
    assert ld.loaded() and ld.verbs() == ["print"]


def test_unreadable_print_defers_without_touching_it(ld):
    _existing(ld)
    ld.fail("print", "5")
    with _adapter(ld)(_step()) as ev:
        assert "unreadable" in (ev.refusal() or "")
    assert ld.loaded() and ld.verbs() == ["print"]


def test_unloaded_job_with_a_plist_is_admitted_without_unloading(ld):
    _existing(ld, loaded=False)
    with _adapter(ld)(_step()) as ev:
        assert ev.refusal() is None
    assert not {"bootout", "bootstrap"} & set(ld.verbs())


def test_unload_that_did_not_take_defers(ld):
    _existing(ld)
    ld.flag("bootout_noop")
    with _adapter(ld)(_step()) as ev:
        assert "could not unload" in (ev.refusal() or "")
    assert "bootstrap" not in ld.verbs()  # nothing was unloaded, so nothing is reloaded


def test_operator_disabled_job_install_defers_and_removal_proceeds(ld):
    _existing(ld)
    ld.mark("disabled")
    with _adapter(ld)(_step("install")) as ev:
        assert "disabled by the operator" in (ev.refusal() or "")
    assert ld.loaded() and "bootout" not in ld.verbs()
    with _adapter(ld)(_step("remove")) as ev:
        assert ev.refusal() is None
    assert not NEVER & set(ld.verbs())  # the operator's disable is never touched


def test_unreadable_disabled_state_defers_an_install(ld):
    _existing(ld)
    ld.fail("print-disabled", "5")
    with _adapter(ld)(_step("install")) as ev:
        assert "unreadable" in (ev.refusal() or "")
    assert ld.loaded() and "bootout" not in ld.verbs()


def test_updater_own_running_service_keeps_its_refusal_and_is_untouched(ld):
    label = "com.djbclark.ade-update-check"
    ld.mark("loaded", label)
    ld.mark("state", label, "running")
    ld.mark("pid", label, "9")
    (ld.agents / f"{label}.plist").write_text("<plist/>")
    with _adapter(ld)(_step(label=label)) as ev:
        assert ev.refusal() == "updater's own running service; next generation pending"
    assert ld.loaded(label) and ld.verbs() == ["print"]  # no disable, no unload


def test_exception_inside_the_context_reloads_the_job(ld):
    _existing(ld)
    with pytest.raises(RuntimeError, match="boom"):
        with _adapter(ld)(_step()) as ev:
            assert ev.refusal() is None and not ld.loaded()
            raise RuntimeError("boom")
    assert ld.loaded()


def test_failed_reload_is_reported_with_the_command_and_does_not_raise(ld):
    _existing(ld)
    err = io.StringIO()
    with _adapter(ld, err=err)(_step()):
        ld.fail("bootstrap", "7")
    text = err.getvalue()
    assert "could not reload" in text and "launchctl bootstrap" in text and LABEL in text


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


def _drift(ld):
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text(plist.read_text() + "<!-- drift -->\n")  # a definition change forces install/reload
    return plist


def test_fresh_install_is_admitted_and_ledgered(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "installed" for r in rows)
    entry = S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert ld.loaded() and not NEVER & set(ld.verbs())


def test_reload_of_an_idle_job_unloads_it_first_and_loads_the_new_definition(ld):
    root, catalog = _installed(ld)
    plist = _drift(ld)
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "installed" for r in rows)
    verbs = ld.verbs()
    assert verbs.index("print") < verbs.index("bootout") < verbs.index("bootstrap")
    assert verbs.count("bootstrap") == 1  # the restore did not load it a second time
    assert ld.loaded() and "drift" not in plist.read_text() and not NEVER & set(verbs)


def test_busy_job_defers_with_exit_6_and_is_untouched(ld):
    root, catalog = _installed(ld)
    plist = _drift(ld)
    drifted = plist.read_text()
    ld.mark("state", text="running")
    ld.mark("pid", text="4242")
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_text() == drifted and ld.loaded()
    assert not ({"bootout", "bootstrap"} | NEVER) & set(ld.verbs())
    deferred = json.loads((ld.state / "jobs-deferred.json").read_text())
    assert any("busy" in v["reason"] for v in deferred["jobs"].values())


def test_exception_mid_mutation_reloads_the_job(ld, monkeypatch):
    root, catalog = _installed(ld)
    _drift(ld)

    def boom(*a, **kw):
        assert not ld.loaded()  # the exclusion is held while the mutation runs
        raise RuntimeError("boom")

    monkeypatch.setattr(S, "install", boom)
    with pytest.raises(RuntimeError, match="boom"):
        _reconcile(ld, root, catalog)
    assert ld.loaded()


def _owned_retired_job(ld, label="com.djbclark.skillopt-sleep"):
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
    ld.mark("loaded", label)
    ledger = S.empty_jobs_ledger(env=ld.env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep", "label": label, "owner": "djbclark-ade", "backend": "launchd",
        "scope": "user", "paths": [str(plist)], "artifact_hash": "deadbeef", "generation": 1, "status": "committed",
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


def test_removal_of_an_idle_job_goes_through_the_adapter(ld):
    root, catalog, label, plist = _owned_retired_job(ld)
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 0, rows
    assert any(r["action"] == "removed" for r in rows)
    verbs = ld.verbs()
    assert verbs.index("print") < verbs.index("bootout")
    assert "bootstrap" not in verbs and not NEVER & set(verbs)
    assert not plist.exists() and not ld.loaded(label)
    assert "skillopt-sleep" not in S.load_jobs_ledger(ld.state, env=ld.env)["entries"]


def test_removal_of_a_busy_job_defers_and_keeps_ownership(ld):
    root, catalog, label, plist = _owned_retired_job(ld)
    ld.mark("state", label, "running")
    ld.mark("pid", label, "77")
    rows, rc = _reconcile_removal(ld, root, catalog, label)
    assert rc == 6, rows
    assert plist.exists() and ld.loaded(label)
    assert "skillopt-sleep" in S.load_jobs_ledger(ld.state, env=ld.env)["entries"]
    assert "bootout" not in ld.verbs()


def test_adopts_a_low_level_install_without_a_reload(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    job_row = next(j for j in catalog.jobs if j["name"] == "deadline-sweep")
    subst = S.job_subst_from_row(job_row, root=root, env=ld.env, extra=None)
    S.install(S.Job.from_plist(root / job_row["plist"], subst, ade=root), "launchd", env=ld.env)
    assert not (ld.state / "jobs.json").exists()  # the ledger does not know the job
    ld.reset()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "adopted" for r in rows)
    entry = S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert not ({"bootout", "bootstrap"} | NEVER) & set(ld.verbs())


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
