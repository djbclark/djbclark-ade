"""W21b: the native launchd admission adapter for `ade-sched reconcile` (offline; a fake launchctl records every argv).

The fake never touches the host: its "launchd" is a directory of marker files, and it models the one launchd rule the
design depends on: `bootstrap` of a disabled label fails with 119.
"""
from __future__ import annotations

import contextlib
import json
import os
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
    print("\tproperties = {")
    print("\t\tstate = running")   # nested decoy: only the service block's own fields count
    print("\t}")
    print(f"\tstate = {read('state', label) or 'not running'}")
    if flag("pid", label): print(f"\tpid = {read('pid', label)}")
    print("}")
elif cmd == "print-disabled":
    print("disabled services = {")
    print('\t"com.apple.other" => enabled')
    if os.path.isdir(os.path.join(root, "disabled")):
        for name in sorted(os.listdir(os.path.join(root, "disabled"))):
            print(f'\t"{name}" => disabled')
    print("}")
elif cmd == "disable":
    if not flag("disable_noop"): touch("disabled", label)
elif cmd == "enable":
    drop("disabled", label)
elif cmd == "bootout":
    drop("loaded", label)
elif cmd == "bootstrap":
    base = os.path.basename(argv[2])[:-len(".plist")]
    if flag("disabled", base):
        sys.stderr.write("Bootstrap failed: 119: Service is disabled\n"); sys.exit(119)
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
    f.mark = lambda kind, label=LABEL, text="": (root / kind).mkdir(exist_ok=True) or (root / kind / label).write_text(text)
    f.flag = lambda name, text="1": (root / name).write_text(text) if name == "garbage" else (
        (root / "fail").mkdir(exist_ok=True) or (root / "fail" / name).write_text(text))
    f.loaded = lambda label=LABEL: (root / "loaded" / label).exists()
    f.disabled = lambda label=LABEL: (root / "disabled" / label).exists()
    return f


def _adapter(ld):
    return S.launchd_admission(launchctl=ld.launchctl, uid=ld.uid, agents_dir=ld.agents, env=ld.env)


def _step(action="install", label=LABEL):
    return S.ReconcileStep("deadline-sweep", action, S.OWNER_ADE, "d", label, touch=True)


def _existing(ld, state="not running", pid=None, plist=True):
    ld.mark("loaded")
    ld.mark("state", text=state)
    if pid is not None:
        ld.mark("pid", text=str(pid))
    if plist:
        (ld.agents / f"{LABEL}.plist").write_text("<plist/>")


# ---------------------------------------------------------------- parsing

PRINT_IDLE = "gui/501/x = {\n\tactive count = 1\n\tstate = not running\n}\n"


@pytest.mark.parametrize("text,want", [
    (PRINT_IDLE, "idle"),
    ("gui/501/x = {\n\tstate = waiting\n}\n", "idle"),
    ("gui/501/x = {\n\tstate = running\n\tpid = 42\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = running\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = spawn scheduled\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = 7\n}\n", "busy"),
    ("gui/501/x = {\n\tstate = not running\n\tpid = abc\n}\n", "unknown"),
    ("gui/501/x = {\n\tproperties = {\n\t\tstate = running\n\t}\n\tstate = not running\n}\n", "idle"),
    ("gui/501/x = {\n\tactive count = 0\n}\n", "unknown"),
    ("gui/501/x = {\n\tstate = mystery\n}\n", "unknown"),
    ("something unexpected\n", "unknown"),
    ("", "unknown"),
])
def test_parse_activity(text, want):
    assert S.parse_launchd_activity(text) == want


@pytest.mark.parametrize("text,want", [
    ('disabled services = {\n\t"a.b" => disabled\n}\n', True),
    ('disabled services = {\n\t"a.b" => true\n}\n', True),
    ('disabled services = {\n\t"a.b" => enabled\n}\n', False),
    ('disabled services = {\n\t"a.b" => false\n}\n', False),
    ('disabled services = {\n\t"other" => disabled\n}\n', False),
    ('disabled services = {\n\t"a.b" => odd\n}\n', None),
    ("garbage\n", None),
])
def test_parse_disabled(text, want):
    assert S.parse_launchd_disabled(text, "a.b") is want


# ---------------------------------------------------------------- the adapter alone

def test_absent_job_is_admitted_without_disabling(ld):
    with _adapter(ld)(_step()) as ev:
        assert ev.refusal() is None
        assert ev.before_bootstrap is None
    assert ld.verbs() == ["print"]  # nothing was disabled or enabled


def test_idle_existing_job_is_excluded_then_restored(ld):
    _existing(ld)
    with _adapter(ld)(_step("remove")) as ev:
        assert ev.refusal() is None
        assert ld.disabled()  # launches are excluded for the whole context
        assert "bootout" not in ld.verbs()
    assert not ld.disabled()
    assert ld.calls()[-1] == ["enable", f"gui/{ld.uid}/{LABEL}"]
    assert "disable" in ld.verbs()


def test_busy_job_defers_without_killing_and_reenables(ld):
    _existing(ld, state="running", pid=4242)
    with _adapter(ld)(_step()) as ev:
        assert "busy" in (ev.refusal() or "")
    assert not ld.disabled()
    assert not {"bootout", "bootstrap", "kickstart", "kill", "remove"} & set(ld.verbs())


def test_unknown_activity_defers_and_reenables(ld):
    _existing(ld)
    ld.flag("garbage")
    with _adapter(ld)(_step()) as ev:
        assert "unknown" in (ev.refusal() or "")
    assert not ld.disabled()


def test_unreadable_print_defers_before_touching_anything(ld):
    _existing(ld)
    ld.flag("print", "5")
    with _adapter(ld)(_step()) as ev:
        assert "unreadable" in (ev.refusal() or "")
    assert not {"disable", "enable"} & set(ld.verbs())


def test_unreadable_disabled_state_defers_before_touching_anything(ld):
    _existing(ld)
    ld.flag("print-disabled", "5")
    with _adapter(ld)(_step()) as ev:
        assert "unreadable" in (ev.refusal() or "")
    assert not {"disable", "enable"} & set(ld.verbs())


def test_exclusion_that_did_not_take_defers(ld):
    _existing(ld)
    (ld.root / "disable_noop").write_text("1")  # `disable` exits 0 but the label stays enabled
    with _adapter(ld)(_step()) as ev:
        assert "could not disable" in (ev.refusal() or "")


def test_operator_disabled_job_stays_disabled(ld):
    _existing(ld)
    ld.mark("disabled")
    with _adapter(ld)(_step("remove")) as ev:
        assert ev.refusal() is None
    assert ld.disabled()
    assert not {"disable", "enable"} & set(ld.verbs())
    with _adapter(ld)(_step("install")) as ev:  # a new definition would need an enable: never done unasked
        assert "disabled by the operator" in (ev.refusal() or "")
    assert ld.disabled()
    assert not {"disable", "enable"} & set(ld.verbs())


def test_updater_own_running_service_keeps_its_refusal(ld):
    label = "com.djbclark.ade-update-check"
    ld.mark("loaded", label)
    ld.mark("state", label, "running")
    ld.mark("pid", label, "9")
    (ld.agents / f"{label}.plist").write_text("<plist/>")
    with _adapter(ld)(_step(label=label)) as ev:
        assert ev.refusal() == "updater's own running service; next generation pending"
    assert not ld.disabled(label)


def test_exception_inside_the_context_reenables(ld):
    _existing(ld)
    with pytest.raises(RuntimeError, match="boom"):
        with _adapter(ld)(_step()) as ev:
            assert ev.refusal() is None and ld.disabled()
            raise RuntimeError("boom")
    assert not ld.disabled()


def test_failed_restore_is_loud_and_names_the_command(ld):
    _existing(ld)
    with pytest.raises(S.SchedError, match=r"run: launchctl enable gui/\d+/com\.djbclark\.deadline-sweep"):
        with _adapter(ld)(_step()):
            ld.flag("enable", "3")  # the restore will fail
    assert ld.verbs().count("enable") == 2  # retried once


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


def test_fresh_install_is_admitted_and_ledgered(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "installed" for r in rows)
    entry = S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert ld.loaded() and "disable" not in ld.verbs()


def test_reload_of_an_idle_job_is_admitted_and_reenabled(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    assert _reconcile(ld, root, catalog)[1] == 0
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text(plist.read_text() + "<!-- drift -->\n")  # a definition change forces install/reload
    (ld.root / "calls.jsonl").unlink()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "installed" for r in rows)
    verbs = ld.verbs()
    assert verbs.index("disable") < verbs.index("bootout") < verbs.index("enable") < verbs.index("bootstrap")
    assert verbs[-1] == "enable" and not ld.disabled() and ld.loaded()
    assert "drift" not in plist.read_text()


def test_busy_job_defers_with_exit_6_and_is_untouched(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    assert _reconcile(ld, root, catalog)[1] == 0
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text(plist.read_text() + "<!-- drift -->\n")
    drifted = plist.read_text()
    ld.mark("state", text="running")
    ld.mark("pid", text="4242")
    (ld.root / "calls.jsonl").unlink()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 6 and any(r["action"] == "deferred" for r in rows), rows
    assert plist.read_text() == drifted and ld.loaded() and not ld.disabled()
    assert not {"bootout", "bootstrap"} & set(ld.verbs())
    deferred = json.loads((ld.state / "jobs-deferred.json").read_text())
    assert any("busy" in v["reason"] for v in deferred["jobs"].values())


def test_exception_mid_mutation_reenables(ld, monkeypatch):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    assert _reconcile(ld, root, catalog)[1] == 0
    plist = ld.agents / f"{LABEL}.plist"
    plist.write_text(plist.read_text() + "<!-- drift -->\n")

    def boom(*a, **kw):
        assert ld.disabled()  # the exclusion is held while the mutation runs
        raise RuntimeError("boom")

    monkeypatch.setattr(S, "install", boom)
    with pytest.raises(RuntimeError, match="boom"):
        _reconcile(ld, root, catalog)
    assert not ld.disabled()


def test_adopts_a_low_level_install_without_a_reload(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    job_row = next(j for j in catalog.jobs if j["name"] == "deadline-sweep")
    subst = S.job_subst_from_row(job_row, root=root, env=ld.env, extra=None)
    S.install(S.Job.from_plist(root / job_row["plist"], subst, ade=root), "launchd", env=ld.env)
    assert not (ld.state / "jobs.json").exists()  # the ledger does not know the job
    (ld.root / "calls.jsonl").unlink()
    rows, rc = _reconcile(ld, root, catalog)
    assert rc == 0, rows
    assert any(r["action"] == "adopted" for r in rows)
    entry = S.load_jobs_ledger(ld.state, env=ld.env)["entries"]["deadline-sweep"]
    assert entry["status"] == "committed" and entry["backend"] == "launchd"
    assert not {"bootout", "bootstrap", "disable", "enable"} & set(ld.verbs())


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
    assert rc == 6 and not {"disable", "enable", "bootout", "bootstrap"} & set(ld.verbs())


def test_no_activate_keeps_the_conservative_default(ld):
    root = _mini_catalog(ld.tmp)
    catalog = ai.load_catalog(root=root)
    rows, rc = _reconcile(ld, root, catalog, activate=False)
    assert rc == 6 and not {"disable", "enable", "bootout", "bootstrap"} & set(ld.verbs())
