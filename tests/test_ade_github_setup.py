"""ade-github-setup: check / observe / plan / dry-run / argv secret refusal."""
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


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-github-setup"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), check=False)


def _fixture_root(tmp_path: Path, *, mutate_manifest: dict | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / ".github").mkdir(parents=True)
    (root / "config" / "github.toml").write_text(
        (REPO / "config" / "github.toml").read_text()
    )
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


def test_apply_dry_run_default_and_yes_refused(tmp_path):
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

    proc_yes = _run("apply", "--yes", root=root)
    assert proc_yes.returncode == 2
    assert "refused" in (proc_yes.stderr + proc_yes.stdout).lower()


def test_refuse_secret_argv_pem_and_flags():
    with pytest.raises(ags.GithubSetupError, match="secret material"):
        ags.refuse_secret_argv(
            ["apply", "--yes", "-----BEGIN RSA PRIVATE KEY-----\nMII"]
        )
    with pytest.raises(ags.GithubSetupError, match="secret flag"):
        ags.refuse_secret_argv(["apply", "--private-key", "/tmp/key.pem"])
    proc = _run("check", "--private-key", "/tmp/x.pem")
    assert proc.returncode == 2
    assert "refuse" in proc.stderr.lower()


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
