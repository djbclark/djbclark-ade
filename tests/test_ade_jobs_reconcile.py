"""S4b: first ADE job reconcile + ownership ledger write path (systemd, CI-testable)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_install as ai  # noqa: E402
import ade_sched as S  # noqa: E402


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


@pytest.fixture
def fake(tmp_path):
    """Fake systemctl/loginctl; unit dir + jobs ledger under tmp (never touch host systemd)."""
    b = tmp_path / "fakebin"
    b.mkdir()
    log = tmp_path / "calls.log"
    _script(
        b / "systemctl",
        f'echo "systemctl $*" >> "{log}"\n'
        'case "$*" in\n'
        '  --version) echo "systemd ${FAKE_SD_VERSION:-255} (255.4)"; echo "+PAM";;\n'
        '  *is-system-running*) echo "${FAKE_SD_STATE:-running}"; '
        '[ "${FAKE_SD_STATE:-running}" = running ] || exit 1;;\n'
        '  *is-active*) echo active;;\n'
        '  *NextElapseUSecRealtime*) echo "Thu 2026-11-10 03:50:00 UTC";;\n'
        'esac\nexit 0\n',
    )
    _script(b / "loginctl", f'echo "loginctl $*" >> "{log}"\necho "${{FAKE_LINGER:-yes}}"\n')
    _script(b / "crontab", f'echo "crontab $*" >> "{log}"\necho "no crontab for tester" >&2; exit 1\n')
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "USER": "tester",
        "ADE_SCHED_SYSTEMCTL": str(b / "systemctl"),
        "ADE_SCHED_LOGINCTL": str(b / "loginctl"),
        "ADE_SCHED_CRONTAB": str(b / "crontab"),
        "ADE_SCHED_UNIT_DIR": str(tmp_path / "units"),
        "ADE_SCHED_LOCK": str(tmp_path / "lock" / "ade-sched.lock"),
        "ADE_JOBS_STATE_DIR": str(tmp_path / "jobs-state"),
    }
    env.pop("ADE_SCHED_BACKEND", None)
    (tmp_path / "home").mkdir()
    (tmp_path / "units").mkdir()

    class F:
        pass

    f = F()
    f.env, f.log, f.tmp = env, log, tmp_path
    f.units = tmp_path / "units"
    f.state = tmp_path / "jobs-state"
    f.calls = lambda: log.read_text().splitlines() if log.exists() else []
    return f


def _mini_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config" / "launchd").mkdir(parents=True)
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "deadline").write_text("#!/bin/sh\nexit 0\n")
    (root / "bin" / "deadline").chmod(0o755)
    # Minimal plist (placeholders match deadline-sweep shape).
    (root / "config" / "launchd" / "com.djbclark.deadline-sweep.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.djbclark.deadline-sweep</string>
  <key>ProgramArguments</key><array>
    <string>__ADE__/bin/deadline</string><string>sweep</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>__HOME__/.local/bin:/usr/bin:/bin</string>
    <key>DEADLINE_STATE_DIR</key><string>__STATE__</string>
  </dict>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>__STATE__/sweep.log</string>
  <key>StandardErrorPath</key><string>__STATE__/sweep.log</string>
</dict></plist>
""",
        encoding="utf-8",
    )
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "config" / "install.toml").write_text(
        """
schema_version = 1

[[component]]
id = "tool-a"
class = "hard"
presence = "python3"
probe_argv = ["python3", "--version"]

[[install.jobs]]
name = "deadline-sweep"
kind = "ade-sched"
owner = "djbclark-ade"
class = "hard"
label = "com.djbclark.deadline-sweep"
plist = "config/launchd/com.djbclark.deadline-sweep.plist"
set = ["__STATE__={home}/.local/state/deadlines"]
platforms = ["mac", "linux"]

[[install.jobs]]
name = "planned-job"
kind = "ade-sched"
owner = "djbclark-ade"
class = "hard"
schedule = "pending"
command = "just update --auto"
notes = "plist pending"

[[install.jobs]]
name = "context-budget"
kind = "paseo"
owner = "djbclark-ade"
class = "hard"
label = "context-budget"
mode = "auto"

[[install.jobs]]
name = "dep-svc"
kind = "service"
owner = "dependency"
class = "hard"
label = "paseo"

[[install.retired_jobs]]
name = "skillopt-sleep"
kind = "ade-sched"
owner = "djbclark-ade"
label = "com.djbclark.skillopt-sleep"
""",
        encoding="utf-8",
    )
    return root


def _run_sched(*args: str, env: dict[str, str], root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-sched"), "--backend", "systemd", *args]
    if root is not None:
        argv[4:4] = ["--root", str(root), "--ade", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), env=env, check=False)


def test_ade_sched_cli_defers_catalog_import_including_reconcile():
    src = (BIN / "ade-sched").read_text(encoding="utf-8")
    head, _, rest = src.partition("\ndef ")
    assert "import ade_install" not in head
    assert src.count("import ade_install as ai") >= 3  # list, diff, reconcile


def test_ledger_roundtrip_and_fail_closed(fake, tmp_path):
    empty = S.load_jobs_ledger(fake.state, env=fake.env)
    assert empty["entries"] == {}
    assert empty["schema_version"] == S.JOBS_LEDGER_SCHEMA_VERSION
    empty["entries"]["deadline-sweep"] = {
        "logical_id": "deadline-sweep",
        "label": "com.djbclark.deadline-sweep",
        "owner": "djbclark-ade",
        "backend": "systemd",
        "status": "committed",
        "paths": [],
        "artifact_hash": "abc",
        "generation": 1,
    }
    empty["generation"] = 1
    path = S.save_jobs_ledger(empty, fake.state, env=fake.env)
    assert path == fake.state / "jobs.json"
    loaded = S.load_jobs_ledger(fake.state, env=fake.env)
    assert loaded["entries"]["deadline-sweep"]["status"] == "committed"

    bad = fake.state / "jobs.json"
    bad.write_text("[]\n", encoding="utf-8")
    with pytest.raises(S.SchedError, match="root must be an object"):
        S.load_jobs_ledger(fake.state, env=fake.env)


def test_plan_never_unloads_foreign_or_unledgered_retired(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan(
        "systemd",
        (
            S.LiveJob("com.djbclark.skillopt-sleep", "systemd", "file", True),
            S.LiveJob("com.djbclark.mystery", "systemd", "generated", True),
            S.LiveJob("dev.herdr.server", "systemd", "file", True),
        ),
    )
    ledger = S.empty_jobs_ledger(env=fake.env)
    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=ledger,
        live=live,
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        platform_name="linux",
    )
    by = {(s.name, s.action): s for s in steps}
    assert ("deadline-sweep", "install") in by and by[("deadline-sweep", "install")].touch
    assert ("planned-job", "planned") in by
    assert ("context-budget", "report") in by  # paseo later
    assert ("dep-svc", "report") in by
    # Retired live without ledger ownership: report only.
    assert any(s.category == "retired" and s.action == "report" and not s.touch for s in steps)
    assert any(s.category == "foreign" and s.action == "report" and not s.touch for s in steps)
    assert not any(s.action == "remove" for s in steps)
    assert not any("herdr" in (s.name or "") for s in steps)


def test_reconcile_yes_installs_and_writes_committed_ledger(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("systemd", ()),
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc == 0, results
    installed = [r for r in results if r["action"] == "installed"]
    assert len(installed) == 1 and installed[0]["name"] == "deadline-sweep"
    assert (fake.units / "com.djbclark.deadline-sweep.service").is_file()
    assert (fake.units / "com.djbclark.deadline-sweep.timer").is_file()
    ledger = S.load_jobs_ledger(fake.state, env=fake.env)
    entry = ledger["entries"]["deadline-sweep"]
    assert entry["status"] == "committed"
    assert entry["owner"] == "djbclark-ade"
    assert entry["backend"] == "systemd"
    assert entry["label"] == "com.djbclark.deadline-sweep"
    assert entry["artifact_hash"]
    assert ledger["generation"] >= 1

    # Idempotent second pass: skip (hash match), no reload noise required.
    results2, rc2 = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan(
            "systemd",
            (S.LiveJob("com.djbclark.deadline-sweep", "systemd", "generated", True),),
        ),
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "skip" and r["name"] == "deadline-sweep" for r in results2)


def test_reconcile_removes_only_ledger_owned_retired(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Seed a ledger-owned retired label and write fake units.
    label = "com.djbclark.skillopt-sleep"
    (fake.units / f"{label}.service").write_text(
        f"# {S.GENERATED} from retired\n[Service]\nExecStart=/bin/true\n",
        encoding="utf-8",
    )
    (fake.units / f"{label}.timer").write_text(
        f"# {S.GENERATED} from retired\n[Timer]\nOnUnitActiveSec=60s\n",
        encoding="utf-8",
    )
    ledger = S.empty_jobs_ledger(env=fake.env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "systemd",
        "scope": "user",
        "paths": [str(fake.units / f"{label}.service"), str(fake.units / f"{label}.timer")],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("systemd", (S.LiveJob(label, "systemd", "generated", True),)),
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc == 0, results
    assert any(r["action"] == "removed" and r["name"] == "skillopt-sleep" for r in results)
    assert not (fake.units / f"{label}.service").exists()
    assert "skillopt-sleep" not in S.load_jobs_ledger(fake.state, env=fake.env)["entries"]


def test_pending_intent_is_not_removal_authority(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    label = "com.djbclark.skillopt-sleep"
    (fake.units / f"{label}.service").write_text(f"# {S.GENERATED}\n", encoding="utf-8")
    ledger = S.empty_jobs_ledger(env=fake.env)
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "systemd",
        "status": "pending",  # install intent only — never remove
        "paths": [],
        "artifact_hash": "x",
        "generation": 1,
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)
    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=S.LiveScan("systemd", (S.LiveJob(label, "systemd", "file", True),)),
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        names={"skillopt-sleep"},
        platform_name="linux",
    )
    assert not any(s.action == "remove" for s in steps)
    assert any(s.action == "report" and "not removal authority" in s.detail for s in steps)
    # Unit file must remain.
    assert (fake.units / f"{label}.service").is_file()


def test_yes_on_non_systemd_refuses(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="cron",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("cron", ()),
        platform_name="linux",
    )
    assert rc == S.EX_USAGE
    assert all(r["action"] == "refuse-backend" for r in results)
    assert not (fake.state / "jobs.json").exists() or S.load_jobs_ledger(fake.state, env=fake.env)["entries"] == {}


def test_cli_reconcile_dry_run_and_yes(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    env = {**fake.env}
    proc = _run_sched("reconcile", "--json", "--name", "deadline-sweep", env=env, root=root)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["mode"] == "dry-run"
    assert data["write_backend"] == "systemd"
    assert any(r["action"] == "would-install" and r["name"] == "deadline-sweep" for r in data["results"])
    assert not (fake.units / "com.djbclark.deadline-sweep.service").exists()

    proc = _run_sched(
        "reconcile", "--yes", "--json", "--name", "deadline-sweep", "--allow-no-linger",
        env=env, root=root,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["mode"] == "yes" and data["ok"] is True
    assert (fake.units / "com.djbclark.deadline-sweep.service").is_file()
    ledger = json.loads((fake.state / "jobs.json").read_text(encoding="utf-8"))
    assert ledger["entries"]["deadline-sweep"]["status"] == "committed"


def test_cli_refuse_yes_and_dry_run(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    proc = _run_sched("reconcile", "--yes", "--dry-run", env=fake.env, root=root)
    assert proc.returncode == 2
    assert "refuse both" in proc.stderr
