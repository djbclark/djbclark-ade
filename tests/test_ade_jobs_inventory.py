"""S4b: install.jobs / retired_jobs inventory, ade-sched list/diff, doctor drift (never unload)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_install as ai  # noqa: E402
import ade_sched as S  # noqa: E402


def test_ade_sched_cli_defers_catalog_import():
    """Module body must not import ade_install (tomllib/3.11); only list/diff may."""
    src = (BIN / "ade-sched").read_text(encoding="utf-8")
    head, _, rest = src.partition("\ndef ")
    assert "import ade_install" not in head
    assert "import ade_install as ai" in rest


def _run_sched(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-sched"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), check=False)


def _mini_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
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
command = "bin/context-budget-check"

[[install.jobs]]
name = "optional-up"
kind = "paseo"
owner = "djbclark-ade"
class = "optional"
chosen = false
label = "paseo-upstream-pending"
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

[[install.retired_jobs]]
name = "cpu-watch-family"
kind = "ade-sched"
owner = "djbclark-ade"
label = "com.djbclark.*-cpu-watch"
""".lstrip(),
        encoding="utf-8",
    )
    return root


def test_repo_jobs_inventory_loads():
    catalog = ai.load_catalog(root=REPO)
    names = [j["name"] for j in catalog.jobs]
    assert "deadline-sweep" in names
    assert "load-watch" in names
    assert "ade-update-check" in names
    assert "harden-check" in names
    assert "keys-check" in names
    assert "context-budget" in names
    assert "routing-recalibrate" in names
    retired = {r["name"]: r["label"] for r in catalog.retired_jobs}
    assert retired["skillopt-sleep"] == "com.djbclark.skillopt-sleep"
    assert "*" in retired["cpu-watch-family"]
    assert retired["routing-recalibrate-launchd"] == "com.djbclark.routing-recalibrate"
    assert "routing-recalibrate" not in retired
    by_name = {j["name"]: j for j in catalog.jobs}
    assert by_name["harden-check"]["label"] == "com.djbclark.harden-check"
    assert by_name["harden-check"]["plist"].endswith("com.djbclark.harden-check.plist")
    assert by_name["harden-check"]["command"] == "bin/ade-harden observe"
    assert by_name["keys-check"]["label"] == "com.djbclark.keys-check"
    assert by_name["keys-check"]["plist"].endswith("com.djbclark.keys-check.plist")
    assert by_name["keys-check"]["command"] == "bin/ade-install keys"
    assert by_name["context-budget"]["mode"] == "auto"
    assert by_name["paseo-upstream-pending"]["chosen"] is False
    assert by_name["routing-recalibrate"]["kind"] == "paseo"
    assert by_name["routing-recalibrate"]["mode"] == "auto"
    assert by_name["routing-recalibrate"]["chosen"] is False
    assert by_name["routing-recalibrate"]["schedule"] == "0 9 1 * *"
    summary = ai.catalog_summary(catalog)
    assert summary["jobs"] >= 8
    assert summary["retired_jobs"] >= 10
    assert summary["jobs_by_owner"].get("djbclark-ade", 0) >= 1


def test_paseo_job_requires_mode(tmp_path):
    root = _mini_catalog(tmp_path)
    text = (root / "config" / "install.toml").read_text(encoding="utf-8")
    text = text.replace('mode = "auto"\nschedule = "50 3 * * *"\ncommand = "bin/context-budget-check"\n', "")
    (root / "config" / "install.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ai.InstallError, match="paseo jobs require mode"):
        ai.load_catalog(root=root)


def test_diff_ok_missing_retired_foreign_never_unload(tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan(
        "systemd",
        (
            S.LiveJob("com.djbclark.deadline-sweep", "systemd", "generated", True),
            S.LiveJob("context-budget", "paseo", "paseo", True),
            S.LiveJob("com.djbclark.skillopt-sleep", "systemd", "file", True),
            S.LiveJob("com.djbclark.opencode-cpu-watch", "systemd", "file", True),
            S.LiveJob("com.djbclark.mystery", "systemd", "generated", True),
            S.LiveJob("dev.herdr.server", "systemd", "file", True),
        ),
    )
    rows = S.diff_jobs(catalog.jobs, catalog.retired_jobs, live, unload=True)
    assert all(r.action == "report" for r in rows)
    by = {r.name: r for r in rows}
    assert by["deadline-sweep"].status == "ok" and not by["deadline-sweep"].fail
    assert by["planned-job"].status == "planned" and not by["planned-job"].fail
    assert by["context-budget"].status == "ok"
    assert by["optional-up"].status == "unchosen"
    assert by["dep-svc"].status == "unknown" and not by["dep-svc"].fail
    assert by["skillopt-sleep"].status == "present" and by["skillopt-sleep"].fail
    assert by["cpu-watch-family"].status == "present" and by["cpu-watch-family"].fail
    assert by["com.djbclark.mystery"].status == "foreign" and not by["com.djbclark.mystery"].fail
    assert "dev.herdr.server" not in by  # not a foreign candidate prefix for ADE


def test_diff_unprobeable_scheduler_is_unknown_not_fail(tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan("none", (), ("backend detect: no scheduler", "paseo not on PATH; paseo schedules not probed"))
    rows = S.diff_jobs(catalog.jobs, catalog.retired_jobs, live)
    by = {r.name: r for r in rows}
    assert by["deadline-sweep"].status == "unknown" and not by["deadline-sweep"].fail
    assert by["context-budget"].status == "unknown" and not by["context-budget"].fail
    assert by["skillopt-sleep"].status == "unknown" and not by["skillopt-sleep"].fail
    assert not any(r.fail for r in rows)


def test_diff_failed_backend_scan_is_unknown_not_empty_missing(tmp_path):
    """Detection ok + enumeration fail must not report every ADE job missing."""
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan(
        "cron",
        (),
        ("backend scan: crontab read for scan: boom", "paseo not on PATH; paseo schedules not probed"),
    )
    rows = S.diff_jobs(catalog.jobs, catalog.retired_jobs, live)
    by = {r.name: r for r in rows}
    assert by["deadline-sweep"].status == "unknown" and not by["deadline-sweep"].fail
    assert "not probed" in by["deadline-sweep"].detail
    assert by["skillopt-sleep"].status == "unknown" and not by["skillopt-sleep"].fail
    assert by["context-budget"].status == "unknown"
    assert not any(r.status == "missing" for r in rows)
    assert not any(r.fail for r in rows)


def test_paseo_schedule_names_timeout_and_launch_are_unavailable():
    def boom_timeout(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(argv, 30)

    jobs, notes = S.paseo_schedule_names(run=boom_timeout)
    assert jobs == []
    assert any("timeout" in n for n in notes)
    assert any("paseo schedule ls failed" in n for n in notes)

    def boom_launch(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("paseo")

    jobs, notes = S.paseo_schedule_names(run=boom_launch)
    assert jobs == []
    assert any("launch:" in n for n in notes)

    # diff must treat those notes as unprobeable, not missing.
    live = S.LiveScan("systemd", (), notes)
    rows = S.diff_jobs(
        [{"name": "cb", "kind": "paseo", "owner": "djbclark-ade", "class": "hard",
          "label": "context-budget", "mode": "auto"}],
        [],
        live,
    )
    assert rows[-1].status == "unknown" and not rows[-1].fail


def test_doctor_includes_job_drift(tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan(
        "launchd",
        (S.LiveJob("com.djbclark.deadline-sweep", "launchd", "generated", True),),
        ("paseo not on PATH; paseo schedules not probed",),
    )
    obs, rc = ai.doctor(catalog, jobs_live=live)
    kinds = {(o.kind, o.id, o.status) for o in obs}
    assert ("job", "deadline-sweep", "ok") in kinds
    assert ("job", "planned-job", "planned") in kinds
    assert ("job", "context-budget", "unknown") in kinds  # paseo unavailable
    assert rc == 0


def test_doctor_fails_on_retired_present(tmp_path):
    root = _mini_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    live = S.LiveScan(
        "cron",
        (
            S.LiveJob("com.djbclark.deadline-sweep", "cron", "crontab", True),
            S.LiveJob("context-budget", "paseo", "paseo", True),
            S.LiveJob("com.djbclark.skillopt-sleep", "cron", "crontab", True),
        ),
    )
    obs, rc = ai.doctor(catalog, jobs_live=live)
    assert rc == 1
    retired = [o for o in obs if o.kind == "retired-job" and o.id == "skillopt-sleep"]
    assert retired and retired[0].status == "present"


def test_cli_list_and_diff_json(tmp_path):
    root = _mini_catalog(tmp_path)
    proc = _run_sched("list", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert any(j["name"] == "deadline-sweep" for j in payload["jobs"])
    assert any(r["name"] == "skillopt-sleep" for r in payload["retired_jobs"])

    # conftest pins ADE_SCHED_CRONTAB=/usr/bin/true → empty crontab; missing ADE jobs → exit 1.
    proc = _run_sched("--backend", "cron", "diff", "--json", root=root)
    assert proc.returncode == 1, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    assert data["backend"] == "cron"
    assert data["ok"] is False
    assert all(row["action"] == "report" for row in data["drift"])
    assert any(row["name"] == "deadline-sweep" and row["status"] == "missing" for row in data["drift"])


def test_cli_list_repo():
    proc = _run_sched("list", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload["jobs"]) >= 8
    assert len(payload["retired_jobs"]) >= 10
