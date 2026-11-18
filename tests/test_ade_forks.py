"""Fork policy validation and actual installer execution containment."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
import ade_forks as forks
import ade_install as install


@pytest.fixture
def policy(tmp_path, monkeypatch):
    path = tmp_path / "forks.toml"
    path.write_text('''schema_version = 1
[[component]]
id = "pilot"
owner = "djbclark-ade"
upstream = "https://github.com/upstream/pilot"
fork = "https://github.com/djbclark/pilot"
channel = "stable"
strategy = "merge"
compatibility_group = "pilot"
catalog_ids = ["pilot"]
required_features = ["retains-feature"]
''')
    monkeypatch.setattr(forks, "POLICY_PATH", path)
    return path


def catalog(tmp_path, cid="pilot", *, system=False):
    row = {
        "id": cid, "class": "hard", "install_argv": ["install-command"],
        "update_argv": ["update-command"], "probe_argv": ["probe-command"],
    }
    if system:
        row.update(needs_system=True, system_argv=["system-install-command"])
    return install.Catalog({"component": [row]}, tmp_path / "catalog.toml", root=tmp_path)


def test_repo_policy_and_observation_do_not_claim_qualification():
    rows = forks.load_policy()
    report = forks.inspect_policy(rows, [])
    assert {row["id"] for row in rows} >= {"paseo", "ade-plugins", "cfengine-libntech"}
    assert report["policy_valid"] is True
    assert all(not row["eligible"] and not row["authorized"] for row in report["components"])
    assert all(row["running_revision"] is None for row in report["components"])


@pytest.mark.parametrize("change", [
    lambda s: s.replace("schema_version = 1", "schema_version = 2"),
    lambda s: s.replace("schema_version = 1", "schema_version = true"),
    lambda s: s.replace('strategy = "merge"', 'strategy = "reset"'),
    lambda s: s.replace('strategy = "merge"', 'strategy = ["merge"]'),
    lambda s: s.replace('strategy = "merge"', 'strategy = { name = "merge" }'),
    lambda s: s.replace('strategy = "merge"', 'strategy = "patch-queue"'),
    lambda s: s.replace('required_features = ["retains-feature"]', 'required_features = []'),
    lambda s: s.replace('catalog_ids = ["pilot"]', 'catalog_ids = ["pilot", "pilot"]'),
    lambda s: s.replace('https://github.com/upstream/pilot', 'https://token@github.com/upstream/pilot'),
    lambda s: s.replace('https://github.com/upstream/pilot', 'https://github.com/upstream/pilot?token=x'),
    lambda s: s.replace('https://github.com/upstream/pilot', 'file:///upstream/pilot'),
    lambda s: s + '\npatch_manifest = "../outside.json"\n',
    lambda s: s + '\nallow_updates = true\n',
    lambda s: s + s[s.index("[[component]]"):],
    lambda s: s + s[s.index("[[component]]"):].replace('id = "pilot"', 'id = "second"'),
])
def test_invalid_policy_fails_closed(policy, change):
    policy.write_text(change(policy.read_text()))
    with pytest.raises(forks.PolicyError):
        forks.load_policy()
    assert forks.installer_hold("unmanaged").startswith("fork_policy_unavailable")


@pytest.mark.parametrize("contents", [None, "", "schema_version = 1\ncomponent = []\n", "bad = ["])
def test_missing_empty_or_broken_policy_holds_all_execution(policy, contents):
    if contents is None:
        policy.unlink()
    else:
        policy.write_text(contents)
    assert forks.installer_hold("pilot")
    assert forks.installer_hold("unmanaged")


@pytest.mark.parametrize("force,system", [(False, False), (True, False), (True, True)])
def test_install_force_and_system_hold_without_probe_or_runner(policy, tmp_path, monkeypatch, force, system):
    def forbidden(*args, **kwargs):
        pytest.fail("managed component reached a probe or install runner")
    monkeypatch.setattr(install, "observe_component", forbidden)
    state = tmp_path / "state"
    rows, rc = install.apply(
        catalog(tmp_path, system=system), dry_run=False, force=force,
        allow_system=system, apply_system=system, state_dir=state, runner=forbidden,
    )
    assert rc == 1 and rows[0]["action"] == "blocked"
    assert not state.exists()


@pytest.mark.parametrize("dry_run", [True, False])
def test_update_explicit_id_is_blocked_not_unknown(policy, tmp_path, dry_run):
    def forbidden(*args, **kwargs):
        pytest.fail("managed component reached update or doctor")
    path = tmp_path / "state" / "updates.json"
    report, rc = install.apply_updates(
        catalog(tmp_path), dry_run=dry_run, ids={"pilot"},
        run=forbidden, doctor_fn=forbidden, state_path=path,
    )
    assert rc == 1 and report["components"][0]["action"] == "blocked"
    assert report["doctor"]["retried"] == []
    assert path.exists() is not dry_run


def test_stale_install_step_is_rechecked_at_execution(policy, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("stale prepared install executed")
    row = {}
    failed = install._run_install_argv(
        step=install.ApplyStep("pilot", "would-install", ["stock-updater"], "ready"),
        row=row, ledger={}, state_dir=tmp_path / "state", cwd=tmp_path,
        run=forbidden, timeout_s=1, kind="install_argv", completed_reason="installed",
    )
    assert failed and row["action"] == "blocked"
    assert not (tmp_path / "state").exists()


def test_update_retry_rechecks_new_enrollment(policy, tmp_path, monkeypatch):
    c = catalog(tmp_path, cid="other")
    monkeypatch.setattr(install, "observe_component", lambda *a, **kw: install.Observation("component", "other", "ok", "present"))
    calls = []
    def run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    def doctor(*args, **kwargs):
        # A new enrollment arrives between initial execution and repair retry.
        policy.write_text(policy.read_text().replace('catalog_ids = ["pilot"]', 'catalog_ids = ["other"]'))
        return [install.Observation("component", "other", "error", "broken")], 1
    report, rc = install.apply_updates(c, dry_run=False, run=run, doctor_fn=doctor, state_path=tmp_path / "updates.json")
    assert rc == 1 and calls == [["update-command"]]
    assert "fork_managed" in report["components"][0]["retry_reason"]


def test_catalog_root_and_changed_source_do_not_override_enrollment(policy, tmp_path):
    c = catalog(tmp_path)
    c.data["component"][0].update(source="https://github.com/upstream/stock", update_argv=["stock-updater"])
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "forks.toml").write_text("schema_version=1\ncomponent=[]")
    assert install.update_plan(c)[0]["action"] == "blocked"


def test_unmanaged_command_retains_update_behavior(policy):
    calls = []
    def run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    assert install._run_update_argv(run, "other", ["updater"])["action"] == "updated"
    assert calls == [["updater"]]


def test_status_and_check_cli_do_not_create_files(policy, tmp_path):
    before = copy.deepcopy(sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")))
    for command, code in (("status", 0), ("check", 1)):
        proc = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "bin" / "ade-fork"), command, "--policy", str(policy), "--id", "pilot", "--json"], capture_output=True, text=True)
        assert proc.returncode == code, proc.stderr
        row = json.loads(proc.stdout)["components"][0]
        assert row["eligible"] is False and row["installed_revision"] is None
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before


def test_unknown_id_and_malformed_policy_cli_exit_two(policy):
    assert forks.main(["status", "--id", "absent", "--json"]) == 2
    policy.write_text("bad=[")
    assert forks.main(["check", "--json"]) == 2
