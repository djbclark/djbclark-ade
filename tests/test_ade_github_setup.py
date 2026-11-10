"""ade-github-setup: check / observe / plan / apply / verify / argv secret refusal."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_github_setup as ags  # noqa: E402

# Fake PEM-looking blob used only to assert refuse paths never echo it.
_FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEfakePEMShouldNeverPrint\n-----END RSA PRIVATE KEY-----"


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-github-setup"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), check=False)


def _fixture_root(
    tmp_path: Path,
    *,
    mutate_manifest: dict | None = None,
    app_id: int | None = None,
) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / ".github").mkdir(parents=True)
    toml = (REPO / "config" / "github.toml").read_text()
    if app_id is not None:
        toml = toml.replace(
            "# app_id = 0\n",
            f"app_id = {app_id}\n",
        )
    (root / "config" / "github.toml").write_text(toml)
    (root / "config" / "github.schema.json").write_text(
        (REPO / "config" / "github.schema.json").read_text()
    )
    manifest = json.loads((REPO / ".github" / "app-manifest.json").read_text())
    if mutate_manifest:
        manifest.update(mutate_manifest)
    (root / ".github" / "app-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return root


def test_repo_github_toml_and_manifest_check_clean():
    cfg = ags.load_config(root=REPO)
    assert cfg.github["app_name"] == "ade-merge-gate"
    assert cfg.full_name == "djbclark/djbclark-ade"
    man = ags.load_manifest(cfg.manifest_path())
    assert ags.validate_manifest(man, path=cfg.manifest_path()) == []
    proc = _run("check", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["app_name"] == "ade-merge-gate"


def test_manifest_rejects_public_or_active_webhook(tmp_path):
    root = _fixture_root(tmp_path, mutate_manifest={"public": True})
    with pytest.raises(ags.GithubSetupError, match="public must be false"):
        ags.load_config(root=root)

    root2 = _fixture_root(tmp_path / "b")
    man_path = root2 / ".github" / "app-manifest.json"
    data = json.loads(man_path.read_text())
    data["hook_attributes"]["active"] = True
    man_path.write_text(json.dumps(data))
    with pytest.raises(ags.GithubSetupError, match="active must be false"):
        ags.load_config(root=root2)


def test_manifest_rejects_wrong_permissions(tmp_path):
    root = _fixture_root(
        tmp_path,
        mutate_manifest={
            "default_permissions": {
                "statuses": "read",
                "checks": "write",
                "pull_requests": "read",
                "metadata": "read",
            }
        },
    )
    with pytest.raises(ags.GithubSetupError, match="statuses"):
        ags.load_config(root=root)


def test_observe_local_ok(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)
    obs, rc = ags.observe(cfg, network=False)
    assert rc == 0
    by_id = {o.id: o for o in obs}
    assert by_id["manifest"].status == "ok"
    assert by_id["config"].status == "ok"
    assert by_id["network"].status == "deferred"
    proc = _run("observe", "--local", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["local_only"] is True


def test_plan_lists_browser_and_secret_steps(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)
    steps = ags.plan(cfg)
    by_id = {s.id: s for s in steps}
    assert by_id["app-create"].browser is True
    assert by_id["store-private-key"].secret_handling == "stdin-file-redirect"
    assert "stdin" in by_id["store-private-key"].reason
    assert by_id["hardening"].action == "deferred"
    proc = _run("plan", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload["steps"]) >= 6


def test_apply_dry_run_default(tmp_path):
    root = _fixture_root(tmp_path)
    proc = _run("apply", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "dry-run"
    ids = {r["id"] for r in payload["results"]}
    assert "ruleset-payload" in ids
    assert "manifest-create" in ids
    body = next(r["body"] for r in payload["results"] if r["id"] == "ruleset-payload")
    checks = body["rules"][0]["parameters"]["required_status_checks"]
    assert any(c["context"] == "adversary-marker" for c in checks)
    assert any(
        c["context"] == "pytest-linux" and c["integration_id"] == 15368 for c in checks
    )


def test_refuse_secret_argv_pem_and_flags():
    with pytest.raises(ags.GithubSetupError, match="secret material"):
        ags.refuse_secret_argv(["apply", "--yes", _FAKE_PEM])
    with pytest.raises(ags.GithubSetupError, match="secret flag"):
        ags.refuse_secret_argv(["apply", "--private-key", "/tmp/key.pem"])
    proc = _run("check", "--private-key", "/tmp/x.pem")
    assert proc.returncode == 2
    assert "refuse" in proc.stderr.lower()
    assert "MIIEfakePEMShouldNeverPrint" not in proc.stderr
    assert "MIIEfakePEMShouldNeverPrint" not in proc.stdout


def test_refuse_secret_argv_equals_form_redacts_value():
    secret = "super-leaky-token-value-9f3a"
    with pytest.raises(ags.GithubSetupError) as ei:
        ags.refuse_secret_argv([f"--token={secret}"])
    msg = str(ei.value)
    assert "--token" in msg
    assert secret not in msg
    assert f"--token={secret}" not in msg

    with pytest.raises(ags.GithubSetupError) as ei2:
        ags.refuse_secret_argv([f"--client-secret={secret}"])
    assert "--client-secret" in str(ei2.value)
    assert secret not in str(ei2.value)

    proc = _run("check", f"--token={secret}")
    assert proc.returncode == 2
    assert "refuse" in proc.stderr.lower()
    assert "--token" in proc.stderr
    assert secret not in proc.stderr
    assert secret not in proc.stdout


def test_observe_network_with_fake_runner(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations/" in joined and "repositories" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'["{cfg.full_name}"]\n',
                stderr="",
            )
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '[{"id":77,"app_id":4242,"app_slug":"ade-merge-gate",'
                    f'"account":"{cfg.owner}"}}]\n'
                ),
                stderr="",
            )
        if f"environments/{cfg.github['environment']}" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(argv, 0, stdout="{}\n", stderr="")
        if "deployment-branch-policies" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout='["master"]\n', stderr=""
            )
        if "secret" in argv and "list" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"name":"MERGE_GATE_PRIVATE_KEY"}]\n',
                stderr="",
            )
        if "variable" in argv and "list" in argv:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"name":"MERGE_GATE_CLIENT_ID"}]\n',
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"merge-gate","enforcement":"active"}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    obs, rc = ags.observe(cfg, network=True, runner=runner)
    assert rc == 0, obs
    by_id = {o.id: o for o in obs}
    assert by_id["app-install"].status == "ok"
    assert "4242" in by_id["app-install"].detail
    assert "user/installations" in by_id["app-install"].detail
    assert by_id["environment"].status == "ok"
    assert by_id["environment-branch"].status == "ok"
    assert by_id["private-key-secret"].status == "ok"
    assert "not read" in by_id["private-key-secret"].detail
    assert by_id["client-id-variable"].status == "ok"
    assert by_id["ruleset"].status == "ok"
    assert by_id["hardening"].status == "deferred"


def test_observe_missing_installation(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(argv, 0, stdout="[]\n", stderr="")
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="gh: Not Found (HTTP 404)\n"
        )

    obs, rc = ags.observe(cfg, network=True, runner=runner)
    assert rc == 1
    by_id = {o.id: o for o in obs}
    assert by_id["app-install"].status == "missing"
    assert "user/installations" in by_id["app-install"].detail


def test_observe_installation_unknown_when_list_fails(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations/" in joined and "repositories" in joined:
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="HTTP 403: Forbidden\n"
            )
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    '[{"id":77,"app_id":4242,"app_slug":"ade-merge-gate",'
                    f'"account":"{cfg.owner}"}}]\n'
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    obs, rc = ags.observe(cfg, network=True, runner=runner)
    by_id = {o.id: o for o in obs}
    assert by_id["app-install"].status == "unknown"
    # unknown install alone does not force exit 1; other probes may
    assert by_id["app-install"].status != "missing"


def test_ruleset_preview_placeholder_without_app_id(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)
    preview = ags.ruleset_preview(cfg)
    checks = preview["rules"][0]["parameters"]["required_status_checks"]
    adv = next(c for c in checks if c["context"] == "adversary-marker")
    assert adv["integration_id"] == "APP_ID"
    preview2 = ags.ruleset_preview(cfg, app_id=99)
    adv2 = next(
        c
        for c in preview2["rules"][0]["parameters"]["required_status_checks"]
        if c["context"] == "adversary-marker"
    )
    assert adv2["integration_id"] == 99


def _env_api_body(cfg: ags.GithubConfig) -> dict:
    """Environment GET/PUT body with the expected deployment_branch_policy."""
    body = ags.environment_payload(cfg)
    body["name"] = cfg.github["environment"]
    return body


def _apply_runner_ok(cfg: ags.GithubConfig, *, ruleset_exists: bool = False):
    """Fake gh runner for apply --yes / --verify (no network)."""
    env = cfg.github["environment"]
    want_rs = cfg.github["ruleset_name"]
    app_id = cfg.github.get("app_id") or 4242
    full_ruleset = ags.ruleset_preview(cfg, app_id=app_id)
    full_ruleset["id"] = 9
    env_body = _env_api_body(cfg)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        # --input <path> from _gh_json_body: body must not contain PEM.
        if "--input" in argv:
            idx = argv.index("--input")
            body_text = Path(argv[idx + 1]).read_text()
            assert "BEGIN" not in body_text
            assert "PRIVATE KEY" not in body_text
            assert "MIIEfake" not in body_text
        if "user/installations" in joined and "repositories" not in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=(
                    f'[{{"id":77,"app_id":{app_id},"app_slug":"ade-merge-gate"}}]\n'
                ),
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            if "-X" in argv and "PUT" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
                )
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            if "-X" in argv and "DELETE" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-X" in argv and "POST" in argv:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout='{"id":1,"name":"master","type":"branch"}\n',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":1,"name":"master","type":"branch"}]\n',
                stderr="",
            )
        if "rulesets/" in joined and joined.rstrip("/").split("rulesets/")[-1].isdigit():
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(full_ruleset) + "\n", stderr=""
            )
        if "rulesets" in joined:
            if "-X" in argv and "POST" in argv:
                body = dict(full_ruleset)
                body["id"] = 9
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps(body) + "\n", stderr=""
                )
            if "-X" in argv and "PUT" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, stdout=json.dumps(full_ruleset) + "\n", stderr=""
                )
            if ruleset_exists:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout=(
                        f'[{{"id":9,"name":"{want_rs}","enforcement":"active"}}]\n'
                    ),
                    stderr="",
                )
            return subprocess.CompletedProcess(argv, 0, stdout="[]\n", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    return runner


def test_apply_yes_api_env_ruleset_refuses_browser(tmp_path):
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    results, rc = ags.apply_yes(cfg, runner=_apply_runner_ok(cfg))
    assert rc == 0, results
    by_id = {r["id"]: r for r in results}
    assert by_id["manifest"]["action"] == "checked"
    assert by_id["app-create"]["action"] == "refuse-browser"
    assert "S7" in by_id["app-create"]["reason"]
    assert by_id["app-install"]["action"] == "refuse-browser"
    assert by_id["environment"]["ok"] is True
    assert by_id["environment-branch"]["ok"] is True
    assert by_id["ruleset"]["action"] == "applied"
    assert by_id["store-private-key"]["action"] == "refuse-operator-secret"
    assert "<" in by_id["store-private-key"]["reason"]
    assert by_id["store-private-key"].get("secret_handling") == "stdin-file-redirect"
    blob = json.dumps(results)
    assert "BEGIN" not in blob
    assert "PRIVATE KEY" not in blob
    assert "MIIEfake" not in blob


def test_apply_yes_refuses_ruleset_without_app_id(tmp_path):
    root = _fixture_root(tmp_path)  # no app_id
    cfg = ags.load_config(root=root)
    env_body = _env_api_body(cfg)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(argv, 0, stdout="[]\n", stderr="")
        if "environments/" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            if "-X" in argv and "DELETE" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-X" in argv and "POST" in argv:
                return subprocess.CompletedProcess(argv, 0, stdout="{}\n", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="[]\n", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.apply_yes(cfg, runner=runner)
    assert rc == 1
    by_id = {r["id"]: r for r in results}
    assert by_id["ruleset"]["action"] == "refused"
    assert by_id["ruleset"]["ok"] is False
    assert "App ID unknown" in by_id["ruleset"]["reason"]
    assert by_id["app-create"]["action"] == "refuse-browser"


def test_apply_yes_preserves_environment_put_failure(tmp_path):
    """PUT failure must not become success just because GET finds the env."""
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    env = cfg.github["environment"]
    # Stale env still readable after a permission-denied PUT.
    stale = {
        "name": env,
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
    }

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"app_id":4242,"app_slug":"ade-merge-gate"}]\n',
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            if "-X" in argv and "PUT" in argv:
                return subprocess.CompletedProcess(
                    argv,
                    1,
                    stdout="",
                    stderr="HTTP 403: Resource not accessible by integration\n",
                )
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(stale) + "\n", stderr=""
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.apply_yes(cfg, runner=runner)
    assert rc == 1
    by_id = {r["id"]: r for r in results}
    assert by_id["environment"]["ok"] is False
    assert by_id["environment"]["action"] == "failed"
    assert "403" in by_id["environment"]["reason"] or "not accessible" in by_id[
        "environment"
    ]["reason"]
    # Branch ensure is skipped once PUT failed (no false "applied" from GET).
    assert "environment-branch" not in by_id


def test_apply_yes_updates_existing_ruleset(tmp_path):
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    # Existing ruleset with wrong checks → PUT update.
    env = cfg.github["environment"]
    want_rs = cfg.github["ruleset_name"]
    stale = ags.ruleset_preview(cfg, app_id=4242)
    stale["id"] = 9
    stale["rules"][0]["parameters"]["required_status_checks"] = [
        {"context": "adversary-marker", "integration_id": 1}
    ]
    env_body = _env_api_body(cfg)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"app_id":4242,"app_slug":"ade-merge-gate"}]\n',
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout='["master"]\n', stderr=""
            )
        if "rulesets/9" in joined and "PUT" not in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(stale) + "\n", stderr=""
            )
        if "-X" in argv and "PUT" in argv and "rulesets/9" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(ags.ruleset_preview(cfg, app_id=4242)) + "\n",
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'[{{"id":9,"name":"{want_rs}","enforcement":"active"}}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.apply_yes(cfg, runner=runner)
    assert rc == 0, results
    by_id = {r["id"]: r for r in results}
    assert by_id["ruleset"]["action"] == "updated"
    assert by_id["environment-branch"]["action"] == "skipped"


def test_apply_yes_updates_ruleset_with_wrong_scope(tmp_path):
    """Wrong target/ref/bypass must not be treated as already reconciled."""
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    env = cfg.github["environment"]
    want_rs = cfg.github["ruleset_name"]
    stale = ags.ruleset_preview(cfg, app_id=4242)
    stale["id"] = 9
    # Checks + enforcement match, but scope targets a non-default branch.
    stale["conditions"] = {
        "ref_name": {"include": ["refs/heads/develop"], "exclude": []}
    }
    stale["bypass_actors"] = [
        {"actor_id": 1, "actor_type": "DeployKey", "bypass_mode": "always"}
    ]
    env_body = _env_api_body(cfg)
    put_seen = {"n": 0}

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"app_id":4242,"app_slug":"ade-merge-gate"}]\n',
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout='["master"]\n', stderr=""
            )
        if "rulesets/9" in joined and "PUT" not in argv:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(stale) + "\n", stderr=""
            )
        if "-X" in argv and "PUT" in argv and "rulesets/9" in joined:
            put_seen["n"] += 1
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(ags.ruleset_preview(cfg, app_id=4242)) + "\n",
                stderr="",
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'[{{"id":9,"name":"{want_rs}","enforcement":"active"}}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.apply_yes(cfg, runner=runner)
    assert rc == 0, results
    by_id = {r["id"]: r for r in results}
    assert by_id["ruleset"]["action"] == "updated"
    assert put_seen["n"] == 1
    assert "conditions.ref_name" in by_id["ruleset"]["reason"]


def test_verify_fails_ruleset_wrong_scope(tmp_path):
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    env = cfg.github["environment"]
    want_rs = cfg.github["ruleset_name"]
    wrong = ags.ruleset_preview(cfg, app_id=4242)
    wrong["id"] = 9
    wrong["target"] = "tag"
    env_body = _env_api_body(cfg)

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"app_id":4242,"app_slug":"ade-merge-gate"}]\n',
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout='["master"]\n', stderr=""
            )
        if "rulesets/9" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(wrong) + "\n", stderr=""
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'[{{"id":9,"name":"{want_rs}","enforcement":"active"}}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.verify(cfg, runner=runner)
    assert rc == 1
    by_id = {r["id"]: r for r in results}
    assert by_id["ruleset"]["action"] == "verify-fail"
    assert "target" in by_id["ruleset"]["reason"]


def test_verify_api_ok(tmp_path):
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    results, rc = ags.verify(cfg, runner=_apply_runner_ok(cfg, ruleset_exists=True))
    assert rc == 0, results
    by_id = {r["id"]: r for r in results}
    assert by_id["manifest"]["action"] == "verify-ok"
    assert by_id["environment"]["action"] == "verify-ok"
    assert by_id["environment-branch"]["action"] == "verify-ok"
    assert by_id["ruleset"]["action"] == "verify-ok"
    assert by_id["ruleset"]["app_id"] == 4242
    blob = json.dumps(results)
    assert "PRIVATE KEY" not in blob


def test_verify_fails_when_extra_branch_policies(tmp_path):
    """Membership of master is not enough — leftover policies must fail verify."""
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    env = cfg.github["environment"]
    want_rs = cfg.github["ruleset_name"]
    env_body = _env_api_body(cfg)
    full_ruleset = ags.ruleset_preview(cfg, app_id=4242)
    full_ruleset["id"] = 9
    extras = [
        {"id": 1, "name": "master", "type": "branch"},
        {"id": 2, "name": "develop", "type": "branch"},
    ]

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "user/installations" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='[{"id":77,"app_id":4242,"app_slug":"ade-merge-gate"}]\n',
                stderr="",
            )
        if f"environments/{env}" in joined and "deployment-branch" not in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(env_body) + "\n", stderr=""
            )
        if "deployment-branch-policies" in joined:
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(extras) + "\n", stderr=""
            )
        if "rulesets/" in joined and joined.rstrip("/").split("rulesets/")[-1].isdigit():
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(full_ruleset) + "\n", stderr=""
            )
        if "rulesets" in joined:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=f'[{{"id":9,"name":"{want_rs}","enforcement":"active"}}]\n',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected\n")

    results, rc = ags.verify(cfg, runner=runner)
    assert rc == 1
    by_id = {r["id"]: r for r in results}
    assert by_id["environment-branch"]["action"] == "verify-fail"
    assert "develop" in by_id["environment-branch"]["reason"]


def test_apply_yes_deletes_extra_branch_policies(tmp_path):
    """apply --yes must DELETE leftover policies, not skip on membership."""
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    env = cfg.github["environment"]
    deleted: list[str] = []
    base = _apply_runner_ok(cfg)
    extras = [
        {"id": 1, "name": "master", "type": "branch"},
        {"id": 99, "name": "hotfix", "type": "branch"},
    ]

    def runner(argv: list[str]) -> subprocess.CompletedProcess:
        joined = " ".join(argv)
        if "deployment-branch-policies" in joined:
            if "-X" in argv and "DELETE" in argv:
                deleted.append(argv[-1].rsplit("/", 1)[-1])
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
            if "-X" in argv and "POST" in argv:
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    stdout='{"id":1,"name":"master","type":"branch"}\n',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(extras) + "\n", stderr=""
            )
        return base(argv)

    results, rc = ags.apply_yes(cfg, runner=runner)
    assert rc == 0, results
    by_id = {r["id"]: r for r in results}
    assert by_id["environment-branch"]["ok"] is True
    assert by_id["environment-branch"]["action"] == "applied"
    assert "hotfix" in by_id["environment-branch"]["reason"]
    assert "99" in deleted


def test_cli_apply_verify_mode_json_shape(tmp_path, monkeypatch):
    """CLI --verify/--yes parse and emit mode= without needing live gh.

    Library paths are covered with fake runners; here we only assert the
    mutually exclusive flag wiring and that --dry-run still works end-to-end.
    """
    root = _fixture_root(tmp_path, app_id=4242)
    proc = _run("apply", "--dry-run", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["mode"] == "dry-run"
    # --verify without network: load_config ok, then real gh may fail/unknown;
    # ensure the flag is accepted (not argparse error / exit 2 from mutual excl).
    proc_v = _run("apply", "--verify", "--help")
    assert proc_v.returncode == 0
    assert "--verify" in proc_v.stdout
    assert "S7" in proc_v.stdout or "browser" in proc_v.stdout.lower() or "API" in proc_v.stdout


def test_verify_fails_when_ruleset_missing(tmp_path):
    root = _fixture_root(tmp_path, app_id=4242)
    cfg = ags.load_config(root=root)
    results, rc = ags.verify(cfg, runner=_apply_runner_ok(cfg, ruleset_exists=False))
    assert rc == 1
    by_id = {r["id"]: r for r in results}
    assert by_id["ruleset"]["action"] == "verify-fail"
    assert "not found" in by_id["ruleset"]["reason"]


def test_apply_mode_flags_mutually_exclusive(tmp_path):
    root = _fixture_root(tmp_path)
    proc = _run("apply", "--yes", "--verify", root=root)
    assert proc.returncode == 2
    text = (proc.stderr + proc.stdout).lower()
    assert "not allowed" in text or "refuse" in text


def test_plan_verify_step_is_api(tmp_path):
    root = _fixture_root(tmp_path)
    cfg = ags.load_config(root=root)
    by_id = {s.id: s for s in ags.plan(cfg)}
    assert by_id["verify"].action == "api"
    assert "T0-T3b" in by_id["verify"].reason or "throwaway" in by_id["verify"].reason
