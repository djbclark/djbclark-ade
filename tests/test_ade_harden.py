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


def test_rejects_shell_metachar_interaction_limits_expiry(tmp_path):
    """Codex Security P2: attacker-controlled --root must not inject expiry."""
    import shlex

    evil = "six_months; touch /tmp/pwned #"
    root = _fixture_root(
        tmp_path,
        toml=f"""
schema_version = 1
[hardening.defaults]
pr_creation_policy = "collaborators_only"
[hardening.interaction_limits]
limit = "collaborators_only"
expiry = {evil!r}
""",
    )
    with pytest.raises(ah.HardenError, match="interaction_limits.expiry"):
        ah.load_config(root=root)
    # Belt-and-suspenders: remediation quotes even a bypassed loader value.
    rem = ah.interaction_limits_remediation(evil)
    cmd, _, note = rem.partition("  #")
    assert "auto-reapply deferred" in note
    parts = shlex.split(cmd)
    assert parts == [
        "just",
        "harden",
        "interaction_limits",
        "--expiry",
        evil,
    ]
    # Unquoted paste must not leave a bare semicolon command separator.
    assert f"--expiry {evil}" not in rem
    assert shlex.quote(evil) in rem


def test_interaction_limits_remediation_quotes_valid_expiry():
    rem = ah.interaction_limits_remediation("six_months")
    assert rem.startswith("just harden interaction_limits --expiry six_months")
    assert "auto-reapply deferred" in rem


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


def _is_gh_user_login(argv: list[str]) -> bool:
    """True for ``gh api … user`` (authenticated login), not user/repos."""
    return len(argv) >= 2 and argv[-1] == "user"


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
        if _is_gh_user_login(argv):
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"login":"djbclark"}\n', stderr=""
            )
        if "user/repos" in joined and "affiliation=owner" in joined:
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
        if _is_gh_user_login(argv):
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"login":"djbclark"}\n', stderr=""
            )
        if "user/repos" in joined and "affiliation=owner" in joined:
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
        if _is_gh_user_login(argv):
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"login":"djbclark"}\n', stderr=""
            )
        if "user/repos" in joined and "affiliation=owner" in joined:
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
    assert exp.remediation == ah.interaction_limits_remediation("six_months")
    # Only GET-style gh api / list probes — no mutation verbs in argv.
    assert all("api" in c for c in calls)


def test_observe_uncovered_non_fork_inventory(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ah.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if _is_gh_user_login(argv):
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"login":"djbclark"}\n', stderr=""
            )
        if "user/repos" in joined and "affiliation=owner" in joined:
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


def test_gh_json_prefers_complete_pretty_json_over_ndjson():
    """Pretty-printed multiline JSON must parse as one document (Codex P1)."""
    payload = {"limit": "collaborators_only", "expires_at": "2099-01-01T00:00:00Z"}

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        assert argv[0] == "gh"
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(payload, indent=2) + "\n", stderr=""
        )

    data, detail = ah._gh_json(
        runner, ["api", "user/interaction-limits"], api_version="2026-03-10"
    )
    assert detail == "ok"
    assert data == payload


def test_gh_json_ndjson_fallback_after_complete_fails():
    lines = (
        '{"full_name":"djbclark/a","fork":false,"name":"a","owner":"djbclark"}\n'
        '{"full_name":"djbclark/b","fork":true,"name":"b","owner":"djbclark"}\n'
    )

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, 0, stdout=lines, stderr="")

    data, detail = ah._gh_json(
        runner,
        ["api", "--paginate", "user/repos?affiliation=owner&per_page=100"],
        api_version="2026-03-10",
    )
    assert detail == "ok"
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["full_name"] == "djbclark/a"


def test_inventory_repos_path_user_vs_org():
    assert (
        ah._inventory_repos_path("djbclark", "djbclark")
        == "user/repos?affiliation=owner&per_page=100"
    )
    assert (
        ah._inventory_repos_path("FRDminc", "djbclark")
        == "orgs/FRDminc/repos?type=all&per_page=100"
    )


def test_observe_inventory_uses_org_endpoint_for_non_login_owner(tmp_path):
    root = _fixture_root(
        tmp_path,
        toml="""
schema_version = 1
[hardening]
owners = ["frdminc"]
check_user_interaction_limits = false
[hardening.defaults]
pr_creation_policy = "collaborators_only"
[hardening.forks]
pr_creation_policy = "disabled"
""",
    )
    cfg = ah.load_config(root=root)
    seen: list[str] = []

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        seen.append(joined)
        if _is_gh_user_login(argv):
            return subprocess.CompletedProcess(
                argv, 0, stdout='{"login":"djbclark"}\n', stderr=""
            )
        if "orgs/frdminc/repos" in joined and "type=all" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '{"full_name":"frdminc/secret","fork":false,'
                    '"name":"secret","owner":"frdminc"}\n'
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    findings = ah.observe_inventory(cfg, runner=runner)
    assert any("orgs/frdminc/repos" in s for s in seen)
    assert not any("users/frdminc/repos" in s for s in seen)
    unc = next(f for f in findings if f.setting == "inventory.uncovered")
    assert unc.status == "uncovered"
    assert "frdminc/secret" in unc.found
