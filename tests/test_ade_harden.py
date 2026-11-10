"""ade-harden: check / observe / apply refusal / drift findings."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_harden as ah  # noqa: E402


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-harden"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(REPO), check=False
    )


def _fixture_root(tmp_path: Path, *, toml: str | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    text = toml if toml is not None else (REPO / "config" / "hardening.toml").read_text()
    (root / "config" / "hardening.toml").write_text(text)
    (root / "config" / "hardening.schema.json").write_text(
        (REPO / "config" / "hardening.schema.json").read_text()
    )
    return root


def test_repo_hardening_toml_check_clean():
    cfg = ah.load_config(root=REPO)
    assert cfg.owners == ["djbclark"]
    assert any(
        r["owner"] == "djbclark" and r["name"] == "djbclark-ade" for r in cfg.repos
    )
    proc = _run("check", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert "djbclark/djbclark-ade" in payload["summary"]["repos"]


def test_rejects_bad_pr_policy(tmp_path):
    root = _fixture_root(
        tmp_path,
        toml="""
schema_version = 1
[hardening.defaults]
pr_creation_policy = "nope"
""",
    )
    with pytest.raises(ah.HardenError, match="pr_creation_policy"):
        ah.load_config(root=root)


def test_rejects_duplicate_repo(tmp_path):
    root = _fixture_root(
        tmp_path,
        toml="""
schema_version = 1
[hardening.defaults]
pr_creation_policy = "collaborators_only"
[[hardening.repo]]
owner = "djbclark"
name = "djbclark-ade"
[[hardening.repo]]
owner = "djbclark"
name = "djbclark-ade"
""",
    )
    with pytest.raises(ah.HardenError, match="duplicate"):
        ah.load_config(root=root)


def test_observe_local_ok(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)
    findings, rc = ah.observe(cfg, network=False)
    assert rc == 0
    by = {(f.target, f.setting): f for f in findings}
    assert by[("config", "hardening.toml")].status == "ok"
    assert by[("network", "probes")].status == "deferred"
    proc = _run("observe", "--local", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["local_only"] is True
    assert payload["writes"] is False
    assert payload["auto_reapply"] is False


def test_apply_refused(tmp_path):
    root = _fixture_root(tmp_path)
    for args in (
        ("apply",),
        ("apply", "--yes"),
        ("apply", "--dry-run"),
    ):
        proc = _run(*args, root=root)
        assert proc.returncode == 2, (args, proc.stderr)
        assert "refused" in (proc.stderr + proc.stdout).lower()


def test_refuse_mutate_flags():
    with pytest.raises(ah.HardenError, match="refused"):
        ah.refuse_mutate_argv(["observe", "--reapply"])
    with pytest.raises(ah.HardenError, match="refused"):
        ah.refuse_mutate_argv(["--renew"])
    proc = _run("observe", "--yes", root=REPO)
    assert proc.returncode == 2
    assert "refused" in proc.stderr.lower()


def test_resolve_policy_merges_overrides(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)
    row = {
        "owner": "djbclark",
        "name": "djbclark-ade",
        "profile": "active",
        "merge_gate_ruleset": True,
        "disable_wiki": False,
    }
    pol = ah.resolve_policy(cfg, row)
    assert pol["pr_creation_policy"] == "collaborators_only"
    assert pol["merge_gate_ruleset"] is True
    assert pol["disable_wiki"] is False
    fork_pol = ah.resolve_policy(
        cfg, {"owner": "djbclark", "name": "paseo", "profile": "fork"}
    )
    assert fork_pol["pr_creation_policy"] == "disabled"


def _ok_repo_payload(**overrides: object) -> dict:
    base = {
        "full_name": "djbclark/djbclark-ade",
        "fork": False,
        "archived": False,
        "has_pull_requests": True,
        "pull_request_creation_policy": "collaborators_only",
        "has_issues": True,
        "has_wiki": False,
        "has_projects": False,
        "has_discussions": False,
        "security_and_analysis": {
            "secret_scanning": {"status": "disabled"},
            "secret_scanning_push_protection": {"status": "disabled"},
        },
    }
    base.update(overrides)
    return base


def test_observe_network_clean_with_fake_runner(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)
    future = (datetime.now(timezone.utc) + timedelta(days=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        assert "X-GitHub-Api-Version: 2026-03-10" in joined or "api" not in argv
        if "repos/djbclark/djbclark-ade/actions/permissions/fork-pr" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"approval_policy":"all_external_contributors"}\n',
                stderr="",
            )
        if "repos/djbclark/djbclark-ade/actions/permissions/workflow" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"default_workflow_permissions":"read",'
                    '"can_approve_pull_request_reviews":false}\n'
                ),
                stderr="",
            )
        if "repos/djbclark/djbclark-ade/rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"merge-gate","enforcement":"active","bypass_actors":[]}]\n',
                stderr="",
            )
        if "repos/djbclark/djbclark-ade" in joined and "actions" not in joined and "rulesets" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(_ok_repo_payload()) + "\n", stderr=""
            )
        if "user/interaction-limits" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"limit": "collaborators_only", "expires_at": future}
                )
                + "\n",
                stderr="",
            )
        if "users/djbclark/repos" in joined:
            # Only the configured repo → no uncovered.
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"full_name":"djbclark/djbclark-ade","fork":false,'
                    '"name":"djbclark-ade","owner":"djbclark"}\n'
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    findings, rc = ah.observe(cfg, network=True, runner=runner)
    assert rc == 0, findings
    statuses = {f.status for f in findings}
    assert "drift" not in statuses
    assert "missing" not in statuses
    assert "uncovered" not in statuses
    by = {(f.target, f.setting): f for f in findings}
    assert by[("djbclark/djbclark-ade", "pull_request_creation_policy")].status == "ok"
    assert by[("djbclark/djbclark-ade", "fork_pr_workflows_approval")].status == "ok"
    assert by[("user", "interaction_limits.limit")].status == "ok"
    assert by[("forgejo", "forgejo")].status == "deferred"


def test_observe_reports_pr_policy_drift(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "repos/djbclark/djbclark-ade" in joined and "actions" not in joined and "rulesets" not in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    _ok_repo_payload(pull_request_creation_policy="all")
                )
                + "\n",
                stderr="",
            )
        if "fork-pr" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"approval_policy":"all_external_contributors"}\n',
                stderr="",
            )
        if "permissions/workflow" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"default_workflow_permissions":"read",'
                    '"can_approve_pull_request_reviews":false}\n'
                ),
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"merge-gate","enforcement":"active","bypass_actors":[]}]\n',
                stderr="",
            )
        if "interaction-limits" in joined:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if "users/djbclark/repos" in joined:
            return subprocess.CompletedProcess(argv, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    findings, rc = ah.observe(cfg, network=True, runner=runner)
    assert rc == 1
    drift = [
        f
        for f in findings
        if f.setting == "pull_request_creation_policy" and f.status == "drift"
    ]
    assert len(drift) == 1
    assert drift[0].wanted == "collaborators_only"
    assert drift[0].found == "all"
    assert drift[0].remediation is not None
    assert "just harden" in drift[0].remediation
    assert "djbclark/djbclark-ade" in drift[0].remediation


def test_observe_interaction_limit_expiry_drift_no_reapply(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)
    soon = (datetime.now(timezone.utc) + timedelta(days=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    calls: list[list[str]] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        calls.append(list(argv))
        joined = " ".join(argv)
        # Fail closed if any write verb sneaks in.
        assert "PUT" not in joined and "PATCH" not in joined and "POST" not in joined
        if "interaction-limits" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"limit": "collaborators_only", "expires_at": soon}
                )
                + "\n",
                stderr="",
            )
        if "repos/djbclark/djbclark-ade" in joined and "actions" not in joined and "rulesets" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(_ok_repo_payload()) + "\n", stderr=""
            )
        if "fork-pr" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"approval_policy":"all_external_contributors"}\n',
                stderr="",
            )
        if "permissions/workflow" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"default_workflow_permissions":"read",'
                    '"can_approve_pull_request_reviews":false}\n'
                ),
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"merge-gate","enforcement":"active","bypass_actors":[]}]\n',
                stderr="",
            )
        if "users/djbclark/repos" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"full_name":"djbclark/djbclark-ade","fork":false,'
                    '"name":"djbclark-ade","owner":"djbclark"}\n'
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    findings, rc = ah.observe(cfg, network=True, runner=runner)
    assert rc == 1
    exp = next(
        f for f in findings if f.setting == "interaction_limits.expires_at"
    )
    assert exp.status == "drift"
    assert exp.remediation is not None
    assert "auto-reapply deferred" in exp.remediation
    # Only GET-style gh api / list probes — no mutation verbs in argv.
    assert all("api" in c for c in calls)


def test_observe_uncovered_non_fork_inventory(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "users/djbclark/repos" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"full_name":"djbclark/djbclark-ade","fork":false,'
                    '"name":"djbclark-ade","owner":"djbclark"}\n'
                    '{"full_name":"djbclark/other","fork":false,'
                    '"name":"other","owner":"djbclark"}\n'
                    '{"full_name":"djbclark/paseo","fork":true,'
                    '"name":"paseo","owner":"djbclark"}\n'
                ),
                stderr="",
            )
        if "interaction-limits" in joined:
            future = (datetime.now(timezone.utc) + timedelta(days=90)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {"limit": "collaborators_only", "expires_at": future}
                )
                + "\n",
                stderr="",
            )
        if "repos/djbclark/djbclark-ade" in joined and "actions" not in joined and "rulesets" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(_ok_repo_payload()) + "\n", stderr=""
            )
        if "fork-pr" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"approval_policy":"all_external_contributors"}\n',
                stderr="",
            )
        if "permissions/workflow" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"default_workflow_permissions":"read",'
                    '"can_approve_pull_request_reviews":false}\n'
                ),
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"merge-gate","enforcement":"active","bypass_actors":[]}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    findings, rc = ah.observe(cfg, network=True, runner=runner)
    assert rc == 1
    unc = next(f for f in findings if f.setting == "inventory.uncovered")
    assert unc.status == "uncovered"
    assert "djbclark/other" in unc.found
    forks = next(f for f in findings if f.setting == "inventory.forks")
    assert forks.status == "ok"
    assert "djbclark/paseo" in forks.found


def test_ade_toml_dual_source_refused(tmp_path):
    root = _fixture_root(tmp_path)
    (root / "config" / "ade.toml").write_text("schema_version = 1\n")
    with pytest.raises(ah.HardenError, match="ade.toml"):
        ah.load_config(root=root)
