"""S4b: ADE job reconcile + ownership ledger write path (launchd/systemd/cron/paseo, CI-testable)."""
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
    """Fake launchctl/systemctl/loginctl; agents + unit dirs + jobs ledger under tmp (never touch host)."""
    b = tmp_path / "fakebin"
    b.mkdir()
    log = tmp_path / "calls.log"
    loaded = tmp_path / "launchd-loaded"
    loaded.mkdir()
    _script(
        b / "launchctl",
        f'echo "launchctl $*" >> "{log}"\n'
        f'LOADED="{loaded}"\n'
        'if [ "$1" = bootstrap ]; then\n'
        '  if [ -n "$FAKE_BOOTSTRAP_FAIL" ]; then '
        'echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; fi\n'
        '  # bootstrap gui/UID PATH → mark basename(PATH) loaded (strip .plist)\n'
        '  base=$(basename "$3" .plist); touch "$LOADED/$base"; exit 0\n'
        'fi\n'
        'if [ "$1" = bootout ]; then\n'
        '  # bootout gui/UID/LABEL\n'
        '  lab="${2##*/}"; rm -f "$LOADED/$lab"; exit 0\n'
        'fi\n'
        'if [ "$1" = print ]; then\n'
        '  if [ -n "$FAKE_PRINT_RC" ]; then exit "$FAKE_PRINT_RC"; fi\n'
        '  lab="${2##*/}"\n'
        '  if [ -f "$LOADED/$lab" ]; then exit 0; fi\n'
        '  exit 1\n'
        'fi\n'
        "exit 0\n",
    )
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
        "ADE_TIMEZONE": "America/New_York",
        "ADE_SCHED_LAUNCHCTL": str(b / "launchctl"),
        "ADE_SCHED_SYSTEMCTL": str(b / "systemctl"),
        "ADE_SCHED_LOGINCTL": str(b / "loginctl"),
        "ADE_SCHED_CRONTAB": str(b / "crontab"),
        "ADE_SCHED_LAUNCH_AGENTS": str(tmp_path / "agents"),
        "ADE_SCHED_UNIT_DIR": str(tmp_path / "units"),
        "ADE_SCHED_LOCK": str(tmp_path / "lock" / "ade-sched.lock"),
        "ADE_JOBS_STATE_DIR": str(tmp_path / "jobs-state"),
    }
    env.pop("ADE_SCHED_BACKEND", None)
    (tmp_path / "home").mkdir()
    (tmp_path / "units").mkdir()
    (tmp_path / "agents").mkdir()

    class F:
        pass

    f = F()
    f.env, f.log, f.tmp = env, log, tmp_path
    f.units = tmp_path / "units"
    f.agents = tmp_path / "agents"
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
schedule = "50 3 * * *"
provider = "claude/test-model"
cwd = "__ADE__"
prompt = "Run __ADE__/bin/context-budget-check --instruction-lint. Report only."

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
    assert ("context-budget", "install") in by and by[("context-budget", "install")].touch
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


def test_yes_on_launchd_installs_and_ledgers(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("launchd", ()),
        platform_name="mac",
    )
    assert rc == 0, results
    assert any(r["action"] == "installed" and r["name"] == "deadline-sweep" for r in results)
    ledger = S.load_jobs_ledger(fake.state, env=fake.env)
    entry = ledger["entries"]["deadline-sweep"]
    assert entry["status"] == "committed"
    assert entry["backend"] == "launchd"
    assert entry["label"] == "com.djbclark.deadline-sweep"
    plist = fake.agents / "com.djbclark.deadline-sweep.plist"
    assert plist.is_file()
    assert S.GENERATED in plist.read_text(encoding="utf-8")
    st = S.status("com.djbclark.deadline-sweep", "launchd", env=fake.env)
    assert st.installed is True

    before = plist.read_text(encoding="utf-8")
    results2, rc2 = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan(
            "launchd",
            (S.LiveJob("com.djbclark.deadline-sweep", "launchd", "generated", True),),
        ),
        platform_name="mac",
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "skip" and r["name"] == "deadline-sweep" for r in results2)
    assert plist.read_text(encoding="utf-8") == before
    assert S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["deadline-sweep"]["artifact_hash"] == entry[
        "artifact_hash"
    ]


def test_launchd_reconcile_refuses_cross_backend_ledger_remove(fake, tmp_path):
    """A systemd ledger row must not be cleared by launchd --yes."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    label = "com.djbclark.skillopt-sleep"
    (fake.units / f"{label}.service").write_text(
        f"# {S.GENERATED} from retired\n[Service]\nExecStart=/bin/true\n",
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
        "paths": [str(fake.units / f"{label}.service")],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)

    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=S.LiveScan("launchd", ()),
        backend_name="launchd",
        root=root,
        ade=root,
        env=fake.env,
        names={"skillopt-sleep"},
        platform_name="mac",
    )
    assert not any(s.action == "remove" for s in steps)
    assert any(
        s.action == "report" and "ledger backend='systemd'" in s.detail for s in steps
    )

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("launchd", ()),
        platform_name="mac",
    )
    assert rc == 0, results
    assert not any(r["action"] == "removed" for r in results)
    assert "skillopt-sleep" in S.load_jobs_ledger(fake.state, env=fake.env)["entries"]
    assert (fake.units / f"{label}.service").is_file()


def test_yes_on_launchd_removes_ledger_owned(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    label = "com.djbclark.skillopt-sleep"
    plist = fake.agents / f"{label}.plist"
    plist.write_text(
        f"# {S.GENERATED} from retired\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        "<plist version=\"1.0\"><dict>"
        f"<key>Label</key><string>{label}</string>"
        "<key>ProgramArguments</key><array><string>/bin/true</string></array>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    # Mark loaded so bootout has something to clear (Codex P2 unload verify).
    (tmp_path / "launchd-loaded" / label).write_text("")
    ledger = S.empty_jobs_ledger(env=fake.env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "launchd",
        "scope": "user",
        "paths": [str(plist)],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("launchd", (S.LiveJob(label, "launchd", "generated", True),)),
        platform_name="mac",
    )
    assert rc == 0, results
    assert any(r["action"] == "removed" and r["name"] == "skillopt-sleep" for r in results)
    assert "skillopt-sleep" not in S.load_jobs_ledger(fake.state, env=fake.env)["entries"]
    assert not plist.exists()


def test_launchd_plan_loads_when_plist_matches_but_unloaded(fake, tmp_path):
    """Matching plist that is not loaded must install/load, not skip (Codex P2 on #514)."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Install once (loads), then unload while leaving the plist + ledger.
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("launchd", ()),
        platform_name="mac",
    )
    assert rc == 0, results
    label = "com.djbclark.deadline-sweep"
    loaded = tmp_path / "launchd-loaded" / label
    assert loaded.is_file()
    loaded.unlink()
    assert S.status(label, "launchd", env=fake.env).active is False

    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=S.LiveScan("launchd", ()),
        backend_name="launchd",
        root=root,
        ade=root,
        env=fake.env,
        names={"deadline-sweep"},
        platform_name="mac",
    )
    assert any(
        s.action == "install" and s.name == "deadline-sweep" and "load inactive" in s.detail
        for s in steps
    )


def test_launchd_remove_keeps_ledger_when_still_loaded(fake, tmp_path):
    """Failed unload (still loaded) must not clear ownership (Codex P2 on #514)."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    label = "com.djbclark.skillopt-sleep"
    plist = fake.agents / f"{label}.plist"
    plist.write_text(
        f"# {S.GENERATED} from retired\n"
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<plist version=\"1.0\"><dict>"
        f"<key>Label</key><string>{label}</string>"
        "<key>ProgramArguments</key><array><string>/bin/true</string></array>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    (tmp_path / "launchd-loaded" / label).write_text("")
    # Force print to keep reporting loaded even after bootout.
    env = {**fake.env, "FAKE_PRINT_RC": "0"}
    ledger = S.empty_jobs_ledger(env=env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "launchd",
        "scope": "user",
        "paths": [str(plist)],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=env)

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("launchd", (S.LiveJob(label, "launchd", "generated", True),)),
        platform_name="mac",
    )
    assert rc == 1, results
    assert any(r["action"] == "failed" and r["name"] == "skillopt-sleep" for r in results)
    entry = S.load_jobs_ledger(fake.state, env=env)["entries"]["skillopt-sleep"]
    assert entry["status"] == "failed"
    assert "still loaded" in entry.get("detail", "")
    assert plist.is_file()  # uninstall refuses to unlink while loaded


def _cron_store_scripts(tmp_path: Path, log: Path) -> Path:
    """Writable fake crontab: -l reads store; - replaces store from stdin."""
    b = tmp_path / "cronbin"
    b.mkdir(exist_ok=True)
    store = tmp_path / "crontab.txt"
    store.write_text("")
    _script(
        b / "crontab",
        f'echo "crontab $*" >> "{log}"\n'
        f'store="{store}"\n'
        'case "$*" in\n'
        '  -l)\n'
        '    if [ ! -s "$store" ]; then echo "no crontab for tester" >&2; exit 1; fi\n'
        '    cat "$store"; exit 0;;\n'
        '  -)\n'
        '    cat > "$store"; exit 0;;\n'
        'esac\n'
        'echo "unexpected crontab $*" >&2; exit 2\n',
    )
    return b / "crontab"


def test_yes_on_cron_installs_and_ledgers(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    crontab = _cron_store_scripts(tmp_path, fake.log)
    env = {**fake.env, "ADE_SCHED_CRONTAB": str(crontab)}
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="cron",
        root=root,
        ade=root,
        env=env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("cron", ()),
        platform_name="linux",
    )
    assert rc == 0, results
    assert any(r["action"] == "installed" and r["name"] == "deadline-sweep" for r in results)
    ledger = S.load_jobs_ledger(fake.state, env=env)
    entry = ledger["entries"]["deadline-sweep"]
    assert entry["status"] == "committed"
    assert entry["backend"] == "cron"
    assert entry["label"] == "com.djbclark.deadline-sweep"
    store = (tmp_path / "crontab.txt").read_text()
    assert "# BEGIN ade-sched:com.djbclark.deadline-sweep" in store
    st = S.status("com.djbclark.deadline-sweep", "cron", env=env)
    assert st.installed is True

    # Idempotent second pass: compare the installed crontab block (not Path("crontab").is_file()).
    before = (tmp_path / "crontab.txt").read_text()
    results2, rc2 = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="cron",
        root=root,
        ade=root,
        env=env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan(
            "cron",
            (S.LiveJob("com.djbclark.deadline-sweep", "cron", "crontab", True),),
        ),
        platform_name="linux",
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "skip" and r["name"] == "deadline-sweep" for r in results2)
    assert (tmp_path / "crontab.txt").read_text() == before
    assert S.load_jobs_ledger(fake.state, env=env)["entries"]["deadline-sweep"]["artifact_hash"] == entry["artifact_hash"]


def test_cron_reconcile_refuses_cross_backend_ledger_remove(fake, tmp_path):
    """A systemd ledger row must not be cleared by cron --yes (Codex P2 on #511)."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    crontab = _cron_store_scripts(tmp_path, fake.log)
    env = {**fake.env, "ADE_SCHED_CRONTAB": str(crontab)}
    label = "com.djbclark.skillopt-sleep"
    (fake.units / f"{label}.service").write_text(
        f"# {S.GENERATED} from retired\n[Service]\nExecStart=/bin/true\n",
        encoding="utf-8",
    )
    ledger = S.empty_jobs_ledger(env=env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "systemd",
        "scope": "user",
        "paths": [str(fake.units / f"{label}.service")],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=env)

    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=env),
        live=S.LiveScan("cron", ()),
        backend_name="cron",
        root=root,
        ade=root,
        env=env,
        names={"skillopt-sleep"},
        platform_name="linux",
    )
    assert not any(s.action == "remove" for s in steps)
    assert any(
        s.action == "report" and "ledger backend='systemd'" in s.detail for s in steps
    )

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="cron",
        root=root,
        ade=root,
        env=env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("cron", ()),
        platform_name="linux",
    )
    assert rc == 0, results
    assert not any(r["action"] == "removed" for r in results)
    assert "skillopt-sleep" in S.load_jobs_ledger(fake.state, env=env)["entries"]
    assert (fake.units / f"{label}.service").is_file()


def test_yes_on_cron_removes_ledger_owned(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    crontab = _cron_store_scripts(tmp_path, fake.log)
    env = {**fake.env, "ADE_SCHED_CRONTAB": str(crontab)}
    label = "com.djbclark.skillopt-sleep"
    # Seed an ADE-owned cron block + ledger authority (retired inventory name).
    (tmp_path / "crontab.txt").write_text(
        f"# BEGIN ade-sched:{label}\n"
        f"# generated by ade-sched\n"
        f"* * * * * /bin/true\n"
        f"# END ade-sched:{label}\n",
        encoding="utf-8",
    )
    ledger = S.empty_jobs_ledger(env=env)
    ledger["generation"] = 1
    ledger["entries"]["skillopt-sleep"] = {
        "logical_id": "skillopt-sleep",
        "label": label,
        "owner": "djbclark-ade",
        "backend": "cron",
        "scope": "user",
        "paths": ["crontab"],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=env)

    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="cron",
        root=root,
        ade=root,
        env=env,
        state_dir=fake.state,
        names={"skillopt-sleep"},
        live=S.LiveScan("cron", (S.LiveJob(label, "cron", "crontab", True),)),
        platform_name="linux",
    )
    assert rc == 0, results
    assert any(r["action"] == "removed" and r["name"] == "skillopt-sleep" for r in results)
    assert "skillopt-sleep" not in S.load_jobs_ledger(fake.state, env=env)["entries"]
    store = (tmp_path / "crontab.txt").read_text()
    assert f"# BEGIN ade-sched:{label}" not in store


def test_cli_reconcile_dry_run_and_yes(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    env = {**fake.env}
    proc = _run_sched("reconcile", "--json", "--name", "deadline-sweep", env=env, root=root)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["mode"] == "dry-run"
    assert data["write_backend"] == "systemd"
    assert data["write_backends"] == ["cron", "launchd", "systemd"]
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


def _fake_paseo_run(store: Path):
    """Injectable paseo CLI: schedule ls/create/delete mutate a tmp JSON list of names."""

    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        assert argv and argv[0] == "paseo"
        names: list[str] = []
        if store.is_file():
            names = json.loads(store.read_text(encoding="utf-8"))
        if argv[1:4] == ["schedule", "ls", "--json"]:
            body = json.dumps([{"name": n} for n in names])
            return subprocess.CompletedProcess(argv, 0, body, "")
        if argv[1:3] == ["schedule", "create"]:
            # --name LABEL somewhere before the prompt positional
            try:
                ni = argv.index("--name")
                label = argv[ni + 1]
            except (ValueError, IndexError):
                return subprocess.CompletedProcess(argv, 2, "", "missing --name")
            if "--mode" not in argv:
                return subprocess.CompletedProcess(argv, 2, "", "missing --mode")
            if label not in names:
                names.append(label)
                store.write_text(json.dumps(names), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:3] == ["schedule", "delete"]:
            try:
                ni = argv.index("--name")
                label = argv[ni + 1]
            except (ValueError, IndexError):
                return subprocess.CompletedProcess(argv, 2, "", "missing --name")
            names = [n for n in names if n != label]
            store.write_text(json.dumps(names), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 2, "", f"unexpected {argv}")

    return run


def test_paseo_create_argv_shape_and_timezone_refuse(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    row = next(j for j in catalog.jobs if j["name"] == "context-budget")
    argv = S.paseo_schedule_create_argv(row, ade=root, env=fake.env)
    assert argv[:3] == ["paseo", "schedule", "create"]
    assert "--cron" in argv and argv[argv.index("--cron") + 1] == "50 3 * * *"
    assert "--timezone" in argv and argv[argv.index("--timezone") + 1] == "America/New_York"
    assert "--name" in argv and argv[argv.index("--name") + 1] == "context-budget"
    assert "--mode" in argv and argv[argv.index("--mode") + 1] == "auto"
    assert "--provider" in argv and argv[argv.index("--provider") + 1] == "claude/test-model"
    assert "--cwd" in argv and argv[argv.index("--cwd") + 1] == str(root.resolve())
    assert argv[-1].startswith("Run ") and "context-budget-check" in argv[-1]
    assert S.paseo_schedule_delete_argv("context-budget") == [
        "paseo", "schedule", "delete", "--name", "context-budget",
    ]
    env_no_tz = {k: v for k, v in fake.env.items() if k != "ADE_TIMEZONE"}
    with pytest.raises(S.SchedError, match="timezone"):
        S.paseo_schedule_create_argv(row, ade=root, env=env_no_tz)


def test_paseo_missing_mode_blocked(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    jobs = []
    for j in catalog.jobs:
        if j["name"] == "context-budget":
            j = dict(j)
            j.pop("mode", None)
        jobs.append(j)
    steps = S.plan_reconcile(
        jobs,
        catalog.retired_jobs,
        ledger=S.empty_jobs_ledger(env=fake.env),
        live=S.LiveScan("systemd", ()),
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        names={"context-budget"},
        platform_name="linux",
    )
    assert any(s.action == "blocked" and s.name == "context-budget" and "--mode" in s.detail for s in steps)


def test_paseo_reconcile_creates_and_ledgers(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text("[]", encoding="utf-8")
    run = _fake_paseo_run(store)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=S.LiveScan("systemd", ()),
        platform_name="linux",
        paseo_run=run,
    )
    assert rc == 0, results
    assert any(r["action"] == "installed" and r["name"] == "context-budget" for r in results)
    assert "context-budget" in json.loads(store.read_text(encoding="utf-8"))
    entry = S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["context-budget"]
    assert entry["backend"] == "paseo"
    assert entry["status"] == "committed"
    assert entry["label"] == "context-budget"

    # Idempotent: live + ledger → skip (no second create).
    live = S.LiveScan(
        "systemd",
        (S.LiveJob("context-budget", "paseo", "paseo", True),),
    )
    results2, rc2 = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=live,
        platform_name="linux",
        paseo_run=run,
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "skip" and r["name"] == "context-budget" for r in results2)


def test_paseo_adopt_ledger_without_create(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text(json.dumps(["context-budget"]), encoding="utf-8")
    run = _fake_paseo_run(store)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=S.LiveScan(
            "systemd",
            (S.LiveJob("context-budget", "paseo", "paseo", True),),
        ),
        platform_name="linux",
        paseo_run=run,
    )
    assert rc == 0, results
    assert any(r["action"] == "adopted" and r["name"] == "context-budget" for r in results)
    assert json.loads(store.read_text(encoding="utf-8")) == ["context-budget"]
    entry = S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["context-budget"]
    assert entry["backend"] == "paseo" and entry["status"] == "committed"


def test_paseo_remove_ledger_owned_never_foreign(fake, tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text(json.dumps(["context-budget", "mystery-agent"]), encoding="utf-8")
    run = _fake_paseo_run(store)
    # Drop context-budget from expected inventory so ledger-owned remove fires.
    jobs = [j for j in catalog.jobs if j["name"] != "context-budget"]
    ledger = S.empty_jobs_ledger(env=fake.env)
    ledger["generation"] = 1
    ledger["entries"]["context-budget"] = {
        "logical_id": "context-budget",
        "label": "context-budget",
        "owner": "djbclark-ade",
        "backend": "paseo",
        "scope": "user",
        "paths": ["paseo-schedule:context-budget"],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)
    live = S.LiveScan(
        "systemd",
        (
            S.LiveJob("context-budget", "paseo", "paseo", True),
            S.LiveJob("mystery-agent", "paseo", "paseo", True),
        ),
    )
    results, rc = S.reconcile(
        jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=live,
        platform_name="linux",
        paseo_run=run,
    )
    assert rc == 0, results
    assert any(r["action"] == "removed" and r["name"] == "context-budget" for r in results)
    assert "context-budget" not in S.load_jobs_ledger(fake.state, env=fake.env)["entries"]
    assert json.loads(store.read_text(encoding="utf-8")) == ["mystery-agent"]

    # Foreign live paseo without ledger: report only (never delete) when in plan scope.
    steps = S.plan_reconcile(
        jobs,
        catalog.retired_jobs,
        ledger=S.empty_jobs_ledger(env=fake.env),
        live=live,
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        platform_name="linux",
    )
    assert not any(s.action == "remove" and s.label == "mystery-agent" for s in steps)


def test_paseo_yes_works_on_launchd_host_backend(fake, tmp_path):
    """Paseo writes are orthogonal: --yes on launchd may still create paseo schedules."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text("[]", encoding="utf-8")
    run = _fake_paseo_run(store)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=S.LiveScan("launchd", ()),
        platform_name="mac",
        paseo_run=run,
    )
    assert rc == 0, results
    assert any(r["action"] == "installed" and r["name"] == "context-budget" for r in results)
    assert S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["context-budget"]["backend"] == "paseo"

    # Idempotent second pass: skip must not exit 2 (Codex P2 on #513).
    live = S.LiveScan(
        "launchd",
        (S.LiveJob("context-budget", "paseo", "paseo", True),),
    )
    results2, rc2 = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=live,
        platform_name="mac",
        paseo_run=run,
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "skip" and r["name"] == "context-budget" for r in results2)


def test_paseo_yes_mixed_with_host_refuse_exits_2(fake, tmp_path, monkeypatch):
    """Paseo create plus planned host refuse still exits 2 (Codex P2 on #513).

    After launchd joined RECONCILE_WRITE_BACKENDS (#514), pin a non-write host set so
    the refuse-counting path stays covered.
    """
    monkeypatch.setattr(S, "RECONCILE_WRITE_BACKENDS", frozenset({"systemd", "cron"}))
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text("[]", encoding="utf-8")
    run = _fake_paseo_run(store)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="launchd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget", "deadline-sweep"},
        live=S.LiveScan("launchd", ()),
        platform_name="mac",
        paseo_run=run,
    )
    assert rc == S.EX_USAGE, results
    assert any(r["action"] == "installed" and r["name"] == "context-budget" for r in results)
    assert any(r["action"] == "refuse-backend" and r["name"] == "deadline-sweep" for r in results)
    assert any(r["action"] == "refuse-backend" and r.get("ok") is False for r in results)


def test_paseo_delete_readback_probe_failure_keeps_ledger(fake, tmp_path):
    """Failed post-delete ls must not clear ownership (Codex P2 on #513)."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    store = tmp_path / "paseo-schedules.json"
    store.write_text(json.dumps(["context-budget"]), encoding="utf-8")
    base = _fake_paseo_run(store)
    jobs = [j for j in catalog.jobs if j["name"] != "context-budget"]
    ledger = S.empty_jobs_ledger(env=fake.env)
    ledger["generation"] = 1
    ledger["entries"]["context-budget"] = {
        "logical_id": "context-budget",
        "label": "context-budget",
        "owner": "djbclark-ade",
        "backend": "paseo",
        "scope": "user",
        "paths": ["paseo-schedule:context-budget"],
        "artifact_hash": "deadbeef",
        "generation": 1,
        "status": "committed",
    }
    S.save_jobs_ledger(ledger, fake.state, env=fake.env)

    def run_fail_after_delete(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ["schedule", "delete"]:
            return base(argv)
        if argv[1:4] == ["schedule", "ls", "--json"]:
            names = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else []
            if "context-budget" not in names:
                return subprocess.CompletedProcess(argv, 1, "", "ls failed")
        return base(argv)

    results, rc = S.reconcile(
        jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"context-budget"},
        live=S.LiveScan(
            "systemd",
            (S.LiveJob("context-budget", "paseo", "paseo", True),),
        ),
        platform_name="linux",
        paseo_run=run_fail_after_delete,
    )
    assert rc == 1, results
    assert any(r["action"] == "failed" and r["name"] == "context-budget" for r in results)
    entry = S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["context-budget"]
    assert entry["status"] == "failed"
    assert "ls failed" in entry.get("detail", "")


def test_plan_activates_inactive_timer_even_when_hashes_match(fake, tmp_path):
    """P1: matching unit files are not skip/adopt while the timer is inactive."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Install once so artifacts exist, then force is-active -> inactive.
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
    label = "com.djbclark.deadline-sweep"
    assert (fake.units / f"{label}.timer").is_file()

    inactive_bin = fake.tmp / "fakebin" / "systemctl"
    inactive_bin.write_text(
        inactive_bin.read_text().replace(
            '  *is-active*) echo active;;\n',
            '  *is-active*) echo inactive; exit 3;;\n',
        )
    )
    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=S.LiveScan("systemd", (S.LiveJob(label, "systemd", "generated", False),)),
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        names={"deadline-sweep"},
        platform_name="linux",
    )
    by = {(s.name, s.action): s for s in steps}
    assert ("deadline-sweep", "install") in by
    assert ("deadline-sweep", "skip") not in by
    assert "inactive timer" in by[("deadline-sweep", "install")].detail


def test_plan_skips_inactive_oneshot_without_timer(fake, tmp_path):
    """Completed oneshot services (no timer) may remain inactive and still skip/adopt."""
    root = tmp_path / "repo-oneshot"
    (root / "config" / "launchd").mkdir(parents=True)
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "tool").write_text("#!/bin/sh\nexit 0\n")
    (root / "bin" / "tool").chmod(0o755)
    (root / "config" / "launchd" / "com.djbclark.oneshot.plist").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.djbclark.oneshot</string>
  <key>ProgramArguments</key><array>
    <string>__ADE__/bin/tool</string>
  </array>
  <key>RunAtLoad</key><true/>
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
name = "oneshot-job"
kind = "ade-sched"
owner = "djbclark-ade"
class = "hard"
label = "com.djbclark.oneshot"
plist = "config/launchd/com.djbclark.oneshot.plist"
platforms = ["linux"]
""",
        encoding="utf-8",
    )
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
        names={"oneshot-job"},
        live=S.LiveScan("systemd", ()),
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc == 0, results
    assert (fake.units / "com.djbclark.oneshot.service").is_file()
    assert not (fake.units / "com.djbclark.oneshot.timer").exists()

    inactive_bin = fake.tmp / "fakebin" / "systemctl"
    inactive_bin.write_text(
        inactive_bin.read_text().replace(
            '  *is-active*) echo active;;\n',
            '  *is-active*) echo inactive; exit 3;;\n',
        )
    )
    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=S.LiveScan(
            "systemd",
            (S.LiveJob("com.djbclark.oneshot", "systemd", "generated", False),),
        ),
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        names={"oneshot-job"},
        platform_name="linux",
    )
    assert any(s.action == "skip" and s.name == "oneshot-job" for s in steps)


def test_reconcile_preserves_implicit_ade_worktree_refuse(fake, tmp_path, monkeypatch):
    """P1: ade=ade or root must not turn an implicit ADE into an explicit override."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    wt, common = tmp_path / "wt", tmp_path / "main.git" / "worktrees" / "wt"
    common.mkdir(parents=True)
    (common / "commondir").write_text("../..\n")
    (wt).mkdir()
    (wt / ".git").write_text(f"gitdir: {common}\n")
    assert S.is_linked_worktree(wt)

    # Point REPO at the linked worktree and call with ade=None (CLI without --ade).
    monkeypatch.setattr(S, "REPO", wt.resolve())
    # Catalog plists live under root; copy the ADE path into subst via explicit root files that use __ADE__.
    job = next(j for j in catalog.jobs if j["name"] == "deadline-sweep")
    subst = S.job_subst_from_row(job, root=root, env=fake.env)
    built = S.Job.from_plist(root / job["plist"], subst, ade=None)
    assert built.worktree == str(wt.resolve())

    steps = S.plan_reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        ledger=S.empty_jobs_ledger(env=fake.env),
        live=S.LiveScan("systemd", ()),
        backend_name="systemd",
        root=root,
        ade=None,  # implicit — must keep worktree refuse on install
        env=fake.env,
        names={"deadline-sweep"},
        platform_name="linux",
    )
    # Plan may still emit install; execute must refuse via job.worktree.
    assert any(s.action == "install" and s.name == "deadline-sweep" for s in steps)
    results, rc = S.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=None,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=S.LiveScan("systemd", ()),
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc == 1
    failed = [r for r in results if r["name"] == "deadline-sweep"]
    assert failed and failed[0]["action"] == "failed"
    assert "worktree" in failed[0]["detail"]
    # Explicit --ade still bypasses the refuse (operator choice).
    built_explicit = S.Job.from_plist(root / job["plist"], subst, ade=wt)
    assert built_explicit.worktree is None


def test_label_change_keeps_old_identity_until_remove(fake, tmp_path):
    """P2: renaming a label for the same logical name must remove the old timer."""
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
    old_label = "com.djbclark.deadline-sweep"
    new_label = "com.djbclark.deadline-sweep-v2"
    assert (fake.units / f"{old_label}.timer").is_file()

    # Rewrite catalog label + plist Label to the new identity.
    plist = root / "config" / "launchd" / "com.djbclark.deadline-sweep.plist"
    plist.write_text(
        plist.read_text(encoding="utf-8").replace(old_label, new_label),
        encoding="utf-8",
    )
    install_toml = root / "config" / "install.toml"
    install_toml.write_text(
        install_toml.read_text(encoding="utf-8").replace(
            f'label = "{old_label}"',
            f'label = "{new_label}"',
            1,
        ),
        encoding="utf-8",
    )
    catalog2 = ai.load_catalog(root=root)
    live = S.LiveScan(
        "systemd",
        (S.LiveJob(old_label, "systemd", "generated", True),),
    )
    steps = S.plan_reconcile(
        catalog2.jobs,
        catalog2.retired_jobs,
        ledger=S.load_jobs_ledger(fake.state, env=fake.env),
        live=live,
        backend_name="systemd",
        root=root,
        ade=root,
        env=fake.env,
        names={"deadline-sweep"},
        platform_name="linux",
    )
    assert any(s.action == "install" and s.label == new_label for s in steps)
    assert any(s.action == "remove" and s.label == old_label for s in steps)

    results2, rc2 = S.reconcile(
        catalog2.jobs,
        catalog2.retired_jobs,
        dry_run=False,
        backend="systemd",
        root=root,
        ade=root,
        env=fake.env,
        state_dir=fake.state,
        names={"deadline-sweep"},
        live=live,
        platform_name="linux",
        allow_no_linger=True,
    )
    assert rc2 == 0, results2
    assert any(r["action"] == "removed" and r["label"] == old_label for r in results2)
    assert any(r["action"] == "installed" and r["label"] == new_label for r in results2)
    assert not (fake.units / f"{old_label}.service").exists()
    assert (fake.units / f"{new_label}.service").is_file()
    entry = S.load_jobs_ledger(fake.state, env=fake.env)["entries"]["deadline-sweep"]
    assert entry["label"] == new_label
    assert entry["status"] == "committed"
    assert "prior_identity" not in entry
