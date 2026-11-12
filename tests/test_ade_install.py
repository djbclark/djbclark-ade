"""ade-install catalog / plan / doctor / bounded apply."""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
FIX = REPO / "tests" / "fixtures" / "install_catalog"
sys.path.insert(0, str(BIN))
import ade_install as ai  # noqa: E402
import ade_user_install as aui  # noqa: E402


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-install"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO), check=False)


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    return root


def test_repo_install_toml_checks_clean():
    catalog = ai.load_catalog(root=REPO)
    assert catalog.data["schema_version"] == 1
    assert len(catalog.components) >= 20
    assert len(catalog.keys) >= 6
    assert len(catalog.logins) >= 4
    ids = [c["id"] for c in catalog.components]
    assert len(ids) == len(set(ids))
    assert "pi" in ids and "sudo-secretspec" in ids
    by_id = {c["id"]: c for c in catalog.components}
    assert by_id["just"].get("install_argv")
    assert by_id["uv"].get("install_argv")
    assert by_id["git"].get("needs_system") is True
    assert by_id["git"].get("system_argv")
    assert by_id["git"].get("system_argv_darwin") == ["brew", "install", "git"]
    assert by_id["aiuse"].get("install_argv")
    assert by_id["sudo-secretspec"].get("needs_system") is True
    assert by_id["sudo-secretspec"].get("system_argv_darwin") == [
        "brew",
        "install",
        "frdminc/sudo-secretspec/sudo-secretspec",
    ]
    assert by_id["sudo-secretspec"].get("probe_argv") == ["sudo-secretspec", "doctor"]
    # Linux: multi-step helper via install_argv; no single system_argv / no pinned URL.
    assert by_id["sudo-secretspec"].get("system_argv") is None
    assert by_id["sudo-secretspec"].get("install_argv") == [
        "{bin}/ade-user-install",
        "sudo-secretspec",
        "--prefix",
        "{prefix}",
    ]
    assert "ade-user-install" in (by_id["sudo-secretspec"].get("install") or "")
    assert by_id["claude-code"].get("install_argv") == [
        "npm",
        "install",
        "-g",
        "@anthropic-ai/claude-code",
    ]
    assert by_id["codex"].get("install_argv") == ["npm", "install", "-g", "@openai/codex"]
    assert by_id["node"].get("probe_argv") == ["node", "--version"]
    assert by_id["node"].get("system_argv") == ["apt-get", "install", "-y", "nodejs", "npm"]
    assert by_id["npm"].get("needs_system") is True
    assert by_id["npm"].get("system_argv") == ["apt-get", "install", "-y", "nodejs", "npm"]
    assert by_id["npm"].get("system_argv_darwin") == ["brew", "install", "node"]
    assert by_id["npm"].get("probe_argv") == ["npm", "--version"]
    assert by_id["npm"].get("presence") == "npm"
    assert by_id["cursor-cli"].get("presence") == "agent"
    assert by_id["cursor-cli"].get("probe_argv") == ["agent", "--version"]
    assert by_id["cursor-cli"].get("update_argv") == ["agent", "update"]
    assert by_id["cursor-cli"].get("install_argv") == [
        "{bin}/ade-user-install",
        "cursor-cli",
        "--prefix",
        "{prefix}",
    ]
    assert by_id["hermes"].get("chosen") is True
    assert by_id["hermes"].get("probe_argv") == ["hermes", "doctor"]
    assert by_id["hermes"].get("update_argv") == ["hermes", "update"]
    assert by_id["hermes"].get("install_argv") == ["{bin}/ade-user-install", "hermes"]
    assert by_id["peer-link"].get("install_argv") is None  # private; prose only
    assert by_id["litellm"].get("install_argv") is None  # fork/role; prose only
    assert by_id["grok-bot-setup"].get("install_argv") == [
        "npm",
        "install",
        "-g",
        "--ignore-scripts",
        "grok-bot-setup",
    ]
    assert by_id["grok-bot-setup"].get("probe_argv") == ["adapters", "help"]
    assert by_id["1password"].get("needs_system") is True
    assert by_id["1password"].get("system_argv_darwin") == [
        "brew",
        "install",
        "--cask",
        "1password",
        "1password-cli",
    ]
    assert by_id["omp"]["class"] == "never"
    assert by_id["opencode"]["class"] == "never"
    assert by_id["crush"]["class"] == "never"
    assert by_id["paseo-plugin-session-guard"]["class"] == "offered"
    assert by_id["paseo-plugin-session-guard"]["chosen"] is True
    assert by_id["paseo-plugin-tell-agent"]["chosen"] is True

    assert by_id["graft"]["class"] == "hard"
    assert by_id["graft"].get("probe_argv") == ["graft", "--version"]
    assert by_id["ade-claim"].get("paseo_plugin") == "ade-claim"
    assert by_id["ade-claim"].get("chosen") is False
    assert by_id["ade-claim"].get("install_argv") is None
    assert by_id["ade-yolo"].get("paseo_plugin") == "ade-yolo"
    assert by_id["ade-yolo"].get("chosen") is False
    assert by_id["ade-yolo"].get("install_argv") is None
    proc = _run("check", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def _paseo_plugin_catalog(tmp_path: Path, *, chosen: bool = False) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "ade-claim"\n'
        'class = "optional"\n'
        f"chosen = {'true' if chosen else 'false'}\n"
        'paseo_plugin = "ade-claim"\n'
        'install = "operator paseo plugin install only"\n'
    )
    return root


def test_paseo_plugin_missing_when_paseo_absent(tmp_path, monkeypatch):
    root = _paseo_plugin_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(ai.shutil, "which", lambda name: None)
    o = ai.observe_component(catalog.components[0], root=catalog.root)
    assert o.status == "missing"
    assert "paseo not on PATH" in o.detail
    assert "never install" in o.detail
    obs, rc = ai.doctor(catalog)
    by_id = {x.id: x for x in obs if x.kind == "component"}
    assert by_id["ade-claim"].status == "missing"
    assert rc == 0  # unchosen: visible, not a doctor failure


def test_paseo_plugin_disabled_and_ok(tmp_path, monkeypatch):
    root = _paseo_plugin_catalog(tmp_path)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(
        ai.shutil, "which",
        lambda name: "/usr/bin/paseo" if name == "paseo" else None,
    )

    def runner_disabled(argv, cwd):
        assert argv == ["paseo", "plugin", "ls", "--json"]
        body = json.dumps([
            {"id": "other", "status": "running", "enabled": True},
            {"id": "ade-claim", "status": "disabled", "enabled": False},
        ])
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")

    o = ai.observe_component(catalog.components[0], root=catalog.root, runner=runner_disabled)
    assert o.status == "disabled"
    assert "never enable" in o.detail

    def runner_ok(argv, cwd):
        body = json.dumps({"plugins": [{"id": "ade-claim", "status": "running", "enabled": True}]})
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")

    o = ai.observe_component(catalog.components[0], root=catalog.root, runner=runner_ok)
    assert o.status == "ok"
    assert "running" in o.detail

    def runner_absent(argv, cwd):
        body = json.dumps([{"id": "session-guard", "status": "running"}])
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")

    o = ai.observe_component(catalog.components[0], root=catalog.root, runner=runner_absent)
    assert o.status == "missing"
    assert "not installed" in o.detail


def test_paseo_plugin_chosen_disabled_fails_doctor(tmp_path, monkeypatch):
    root = _paseo_plugin_catalog(tmp_path, chosen=True)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(
        ai.shutil, "which",
        lambda name: "/usr/bin/paseo" if name == "paseo" else None,
    )

    def runner(argv, cwd):
        body = json.dumps([{"id": "ade-claim", "enabled": False, "status": "disabled"}])
        return subprocess.CompletedProcess(argv, 0, stdout=body, stderr="")

    obs, rc = ai.doctor(catalog, runner=runner)
    by_id = {x.id: x for x in obs if x.kind == "component"}
    assert by_id["ade-claim"].status == "disabled"
    assert rc == 1


def test_paseo_plugin_apply_never_installs(tmp_path):
    root = _paseo_plugin_catalog(tmp_path, chosen=True)
    catalog = ai.load_catalog(root=root)
    results, rc = ai.apply(catalog, dry_run=True, ids={"ade-claim"})
    assert results[0]["action"] == "blocked"
    assert "never installs or enables" in results[0]["reason"]
    assert rc == 1
    # unchosen → skip
    root2 = _paseo_plugin_catalog(tmp_path / "unchosen", chosen=False)
    catalog2 = ai.load_catalog(root=root2)
    results, rc = ai.apply(catalog2, dry_run=True, ids={"ade-claim"})
    assert results[0]["action"] == "skip"
    assert rc == 0


def test_paseo_plugin_rejects_install_argv(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "ade-claim"\n'
        'class = "optional"\n'
        "chosen = false\n"
        'paseo_plugin = "ade-claim"\n'
        'install_argv = ["paseo", "plugin", "install", "x"]\n'
    )
    with pytest.raises(ai.InstallError, match="install_argv"):
        ai.load_catalog(root=root)


def _hermes_catalog(root):
    catalog = ai.load_catalog(root=root)
    catalog.data["component"].append({
        "id": "hermes", "class": "offered", "chosen": True,
        "probe_argv": ["hermes", "doctor"], "install_argv": ["true"],
    })
    return catalog


def _hermes_ok_runner(argv, cwd):
    return subprocess.CompletedProcess(argv, 0, stdout="hermes healthy\n", stderr="")


def test_hermes_choice_skip_keeps_doctor_quiet(tmp_path):
    """A recorded skip overrides catalog chosen=true: no probe, exit 0."""
    root = _fixture_root(tmp_path)
    catalog = _hermes_catalog(root)
    record = {"choice": "skip"}
    obs, rc = ai.doctor(
        catalog, component_ids=["hermes"], hermes_choice=record,
        runner=_hermes_ok_runner, skip_credential_bak=True,
    )
    hermes = [o for o in obs if o.id == "hermes"]
    assert len(hermes) == 1
    assert hermes[0].status == "unchosen"
    assert not any(o.kind == "hermes-item" for o in obs)
    assert rc == 0


def test_hermes_choice_self_runs_checklist(tmp_path, monkeypatch):
    """self expects Hermes; a passing catalog probe then checks the checklist."""
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: False)
    root = _fixture_root(tmp_path)
    catalog = _hermes_catalog(root)
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)
    (home / ".hermes" / "config.yaml").write_text("model: local\n")
    skills = home / ".local" / "share" / "skill-everywhere" / "skills"
    skills.mkdir(parents=True)
    collab = home / ".hermes" / "skills" / "autonomous-ai-agents" / "claude-collaboration"
    collab.mkdir(parents=True)
    (collab / "SKILL.md").write_text("# claude-collaboration\n")

    def runner(argv, cwd):
        if argv[:2] == ["claude", "mcp"]:
            return subprocess.CompletedProcess(argv, 0, stdout="hermes: connected\n", stderr="")
        return _hermes_ok_runner(argv, cwd)

    obs, rc = ai.doctor(
        catalog, component_ids=["hermes"], hermes_choice={"choice": "self"},
        runner=runner, hermes_home=home, skip_credential_bak=True,
    )
    by_id = {o.id: o for o in obs}
    assert by_id["hermes"].status == "ok"
    for item in (
        "hermes-config", "hermes-skills-root", "hermes-claude-collaboration", "hermes-mcp-bridge",
    ):
        assert by_id[item].status == "ok", item
    # tell_chief_of_staff is optional: absent still ok, and never fails doctor.
    assert by_id["hermes-tell-chief"].status == "ok"
    assert "optional" in by_id["hermes-tell-chief"].detail
    assert rc == 0


def test_hermes_checklist_missing_item_fails_scoped_doctor(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: False)
    root = _fixture_root(tmp_path)
    catalog = _hermes_catalog(root)
    obs, rc = ai.doctor(
        catalog, component_ids=["hermes"], hermes_choice={"choice": "ai"},
        runner=_hermes_ok_runner, hermes_home=tmp_path / "empty-home",
        skip_credential_bak=True,
    )
    by_id = {o.id: o for o in obs}
    assert by_id["hermes"].status == "ok"
    assert by_id["hermes-config"].status == "missing"
    assert rc == 1


def test_hermes_choice_roundtrip_and_refuse(tmp_path):
    path = ai.save_hermes_choice("skip", state_dir=tmp_path)
    assert path == tmp_path / "hermes-choice.json"
    assert ai.load_hermes_choice(tmp_path)["choice"] == "skip"
    with pytest.raises(ai.InstallError):
        ai.save_hermes_choice("later", state_dir=tmp_path)
    path.write_text("{not json")
    with pytest.raises(ai.InstallError):
        ai.load_hermes_choice(tmp_path)


@pytest.mark.parametrize("choice,chosen", [("skip", True), ("self", False), ("ai", False)])
def test_hermes_choice_controls_apply(tmp_path, monkeypatch, choice, chosen):
    root = _fixture_root(tmp_path)
    catalog = _hermes_catalog(root)
    hermes = next(row for row in catalog.components if row["id"] == "hermes")
    hermes["chosen"] = chosen
    hermes["install_argv"] = ["true"]
    ai.save_hermes_choice(choice, state_dir=tmp_path / "state")
    monkeypatch.setattr(ai, "observe_component", lambda *a, **k: ai.Observation("component", "hermes", "missing", "fixture"))
    results, rc = ai.apply(catalog, ids={"hermes"}, state_dir=tmp_path / "state")
    assert rc == 0
    assert results[0]["action"] == ("skip" if choice == "skip" else "would-install")
    assert hermes["chosen"] == chosen  # overlay must not mutate catalog metadata


def test_hermes_choice_enables_unchosen_doctor(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    catalog = _hermes_catalog(root)
    next(row for row in catalog.components if row["id"] == "hermes")["chosen"] = False
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: True)
    obs, rc = ai.doctor(catalog, component_ids=["hermes"], hermes_choice={"choice": "self"})
    assert next(o for o in obs if o.id == "hermes").status == "missing"
    assert rc == 1


def test_hermes_choice_cli_records_without_install(tmp_path):
    proc = _run("hermes-choice", "ai", "--state-dir", str(tmp_path), "--json")
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    assert body["choice"] == "ai"
    assert "hermes-setup" in body["next"]
    assert ai.load_hermes_choice(tmp_path)["choice"] == "ai"


def test_fixture_doctor_missing_vs_unchosen(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    obs, rc = ai.doctor(catalog, skip_credential_bak=True)
    by_id = {o.id: o for o in obs if o.kind == "component"}
    assert by_id["tool-a"].status == "ok"
    assert "probe ok" in by_id["tool-a"].detail
    assert by_id["tool-b"].status == "unchosen"
    assert by_id["tool-c"].status == "missing"
    assert rc == 1  # chosen optional missing counts
    key_obs = [o for o in obs if o.kind == "key"]
    assert key_obs and key_obs[0].status == "unknown"


def test_doctor_probe_argv_fail_is_error(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Force tool-a probe to fail via injected runner.
    def runner(argv, cwd):
        return subprocess.CompletedProcess(argv, 7, stdout="", stderr="boom\n")

    # Replace tool-a's observation path by applying runner to all probes.
    # tool-c has no probe_argv → still missing via presence.
    obs, rc = ai.doctor(catalog, runner=runner, skip_credential_bak=True)
    by_id = {o.id: o for o in obs if o.kind == "component"}
    assert by_id["tool-a"].status == "error"
    assert "boom" in by_id["tool-a"].detail
    assert rc == 1


def test_observe_credential_bak_absent_ok(tmp_path):
    vault = tmp_path / "credential-bak"
    o = ai.observe_credential_bak(
        today=datetime.date(2026, 11, 25),
        path=vault,
        exists_fn=lambda p: False,
    )
    assert o.kind == "vault" and o.id == "credential-bak"
    assert o.status == "ok"
    assert "absent" in o.detail
    assert "never deletes" in o.detail
    assert "2026-11-19" in o.detail


def test_observe_credential_bak_early_present_ok(tmp_path):
    vault = tmp_path / "credential-bak"
    vault.mkdir()
    o = ai.observe_credential_bak(
        today=datetime.date(2026, 10, 20),
        path=vault,
    )
    assert o.status == "ok"
    assert "present" in o.detail
    assert "never deletes" in o.detail


def test_observe_credential_bak_approaching_is_warn(tmp_path):
    vault = tmp_path / "credential-bak"
    vault.mkdir()
    # 9 days before delete-after (within 14-day lead).
    o = ai.observe_credential_bak(
        today=datetime.date(2026, 11, 10),
        path=vault,
    )
    assert o.status == "warn"
    assert "in 9 day(s)" in o.detail
    assert "never deletes" in o.detail
    assert "rm" not in o.detail.lower()
    assert "unlink" not in o.detail.lower()


def test_observe_credential_bak_past_is_error(tmp_path):
    vault = tmp_path / "credential-bak"
    vault.mkdir()
    o = ai.observe_credential_bak(
        today=datetime.date(2026, 11, 19),
        path=vault,
    )
    assert o.status == "error"
    assert "on/after delete-after" in o.detail
    assert "operator yes" in o.detail
    assert "never deletes" in o.detail


def test_observe_credential_bak_never_calls_delete(tmp_path):
    """Guard: injected exists_fn must be the only filesystem touch for presence."""
    vault = tmp_path / "credential-bak"
    vault.mkdir()
    marker = tmp_path / "secret.txt"
    marker.write_text("do-not-read", encoding="utf-8")
    calls: list[Path] = []

    def exists_fn(p: Path) -> bool:
        calls.append(p)
        return True

    o = ai.observe_credential_bak(
        today=datetime.date(2026, 11, 20),
        path=vault,
        exists_fn=exists_fn,
    )
    assert o.status == "error"
    assert calls == [vault]
    # Vault and marker untouched.
    assert vault.is_dir()
    assert marker.read_text(encoding="utf-8") == "do-not-read"


def test_doctor_credential_bak_warn_fails_exit(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'probe_argv = ["true"]\n'
        'presence = "true"\n'
    )
    catalog = ai.load_catalog(root=root)
    warn = ai.Observation(
        "vault",
        "credential-bak",
        "warn",
        "credential-bak still present; doctor never deletes",
    )
    obs, rc = ai.doctor(catalog, credential_bak=warn)
    assert rc == 1
    bak = [o for o in obs if o.kind == "vault" and o.id == "credential-bak"]
    assert len(bak) == 1 and bak[0].status == "warn"
    obs_ok, rc_ok = ai.doctor(
        catalog,
        credential_bak=ai.Observation(
            "vault",
            "credential-bak",
            "ok",
            "credential-bak absent; doctor never deletes",
        ),
    )
    assert rc_ok == 0
    assert any(o.status == "ok" for o in obs_ok if o.kind == "vault")


def test_doctor_credential_bak_error_fails_exit(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'probe_argv = ["true"]\n'
        'presence = "true"\n'
    )
    catalog = ai.load_catalog(root=root)
    err = ai.Observation(
        "vault",
        "credential-bak",
        "error",
        "credential-bak still present on/after delete-after; doctor never deletes",
    )
    obs, rc = ai.doctor(catalog, credential_bak=err)
    assert rc == 1
    bak = [o for o in obs if o.kind == "vault" and o.id == "credential-bak"]
    assert len(bak) == 1 and bak[0].status == "error"


def test_doctor_probe_binary_missing(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "gone"\n'
        'class = "hard"\n'
        'probe_argv = ["definitely-not-a-real-bin-xyz", "--version"]\n'
        'presence = "definitely-not-a-real-bin-xyz"\n'
    )
    catalog = ai.load_catalog(root=root)
    o = ai.observe_component(catalog.components[0], root=catalog.root)
    assert o.status == "missing"
    assert "probe binary not found" in o.detail


def test_plan_blocks_unknown_install(tmp_path):
    root = _fixture_root(tmp_path)
    steps = ai.plan(ai.load_catalog(root=root))
    by_id = {s["id"]: s for s in steps}
    assert by_id["tool-a"]["action"] == "blocked"
    assert by_id["tool-b"]["action"] == "skip"
    assert by_id["tool-c"]["action"] == "would-install"
    assert by_id["tool-c"]["argv"] == ["true"]
    assert by_id["tool-d"]["action"] == "needs-system"
    assert by_id["tool-d"]["needs_system"] is True


def test_refuses_when_ade_toml_present(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "ade.toml").write_text("schema_version = 1\n")
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    with pytest.raises(ai.InstallError, match="refuse transitional"):
        ai.load_catalog(root=root)


def test_duplicate_component_id_rejected(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\nid = \"x\"\nclass = \"hard\"\n"
        "[[component]]\nid = \"x\"\nclass = \"hard\"\n"
    )
    with pytest.raises(ai.InstallError, match="duplicate"):
        ai.load_catalog(root=root)


def test_offered_requires_chosen(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n[[component]]\nid = \"h\"\nclass = \"offered\"\n"
    )
    with pytest.raises(ai.InstallError, match="chosen"):
        ai.load_catalog(root=root)


def test_cli_catalog_and_plan_json(tmp_path):
    root = _fixture_root(tmp_path)
    c = _run("catalog", "--json", root=root)
    assert c.returncode == 0, c.stderr
    assert len(json.loads(c.stdout)["component"]) == 4
    p = _run("plan", "--json", root=root)
    assert p.returncode == 0, p.stderr
    assert "apply" in json.loads(p.stdout)["note"]


def test_commands_make_no_writes(tmp_path):
    root = _fixture_root(tmp_path)
    dest = root / "config" / "install.toml"
    before = dest.read_bytes()
    mtime = dest.stat().st_mtime_ns
    for cmd in ("check", "catalog", "plan", "doctor"):
        _run(cmd, "--json", root=root)
    # dry-run apply also must not mutate the catalog
    _run("apply", "--dry-run", "--json", root=root)
    assert dest.read_bytes() == before
    assert dest.stat().st_mtime_ns == mtime


def test_expand_argv_tokens(tmp_path):
    root = tmp_path / "repo"
    prefix = tmp_path / "prefix"
    out = ai.expand_argv(
        ["{bin}/ade-user-install", "just", "--prefix", "{prefix}"],
        root=root,
        prefix=prefix,
    )
    assert out[0] == str(root.resolve() / "bin" / "ade-user-install")
    assert out[-1] == str(prefix.resolve())
    with pytest.raises(ai.InstallError, match="braces"):
        ai.expand_argv(["{unknown}/x"], root=root)


def test_pick_system_argv_darwin_vs_linux():
    row = {
        "system_argv": ["apt-get", "install", "-y", "git"],
        "system_argv_darwin": ["brew", "install", "git"],
    }
    assert ai.pick_system_argv(row, system="Linux") == ["apt-get", "install", "-y", "git"]
    assert ai.pick_system_argv(row, system="Darwin") == ["brew", "install", "git"]
    assert ai.pick_system_argv({"system_argv": ["apt-get", "x"]}, system="Darwin") == ["apt-get", "x"]
    assert ai.pick_system_argv({}, system="Linux") is None


def test_apply_dry_run_default_and_system_preview(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-c"})
    assert rc == 0
    assert results[0]["action"] == "would-install"
    assert results[0]["argv"] == ["true"]

    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-d"})
    assert results[0]["action"] == "refuse-system"
    assert rc == 1

    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-d"}, allow_system=True)
    assert rc == 0
    assert results[0]["action"] == "would-system-install"
    assert results[0]["argv"] == ["apt-get", "install", "-y", "tool-d"]

    results, rc = ai.apply(catalog, dry_run=False, ids={"tool-d"}, allow_system=True)
    assert rc == 2
    assert results[0]["action"] == "refuse-system-exec"


def test_apply_yes_runs_argv_and_writes_ledger(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "state"
    calls: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        calls.append(list(argv))
        assert cwd == catalog.root
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    results, rc = ai.apply(
        catalog,
        dry_run=False,
        ids={"tool-c"},
        state_dir=state,
        runner=runner,
    )
    assert rc == 0, results
    assert results[0]["action"] == "installed"
    assert calls == [["true"]]
    ledger = json.loads((state / "ledger.json").read_text())
    assert ledger["schema_version"] == 1
    assert ledger["entries"]["tool-c"]["status"] == "installed"


def test_apply_skips_present_unless_force(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-a"})
    assert rc == 0
    assert results[0]["action"] == "skip"
    # force with blocked (no argv) still blocked
    results, _ = ai.apply(catalog, dry_run=True, ids={"tool-a"}, force=True)
    assert results[0]["action"] == "blocked"


def test_cli_apply_dry_run_json(tmp_path):
    root = _fixture_root(tmp_path)
    proc = _run("apply", "--dry-run", "--json", "--id", "tool-c", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["results"][0]["action"] == "would-install"


def test_cli_apply_system_dry_run_and_yes_refused(tmp_path):
    root = _fixture_root(tmp_path)
    dry = _run("apply", "--dry-run", "--system", "--json", "--id", "tool-d", root=root)
    assert dry.returncode == 0, dry.stderr
    payload = json.loads(dry.stdout)
    assert payload["results"][0]["action"] == "would-system-install"
    yes = _run("apply", "--yes", "--system", "--json", "--id", "tool-d", root=root)
    assert yes.returncode == 2
    assert json.loads(yes.stdout)["results"][0]["action"] == "refuse-system-exec"


def test_collect_and_cli_print_system_argv(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    rows = ai.collect_system_argv(catalog, ids={"tool-d"})
    assert len(rows) == 1
    assert rows[0]["ok"] is True
    assert rows[0]["action"] == "print-system-argv"
    assert rows[0]["argv"] == ["apt-get", "install", "-y", "tool-d"]

    missing = ai.collect_system_argv(catalog, ids={"tool-c"})
    assert missing[0]["ok"] is False
    assert missing[0]["action"] == "skip"

    proc = _run("apply", "--print-system-argv", "--json", "--id", "tool-d", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "print-system-argv"
    assert payload["results"][0]["argv"] == ["apt-get", "install", "-y", "tool-d"]

    bad = _run(
        "apply", "--print-system-argv", "--yes", "--json", "--id", "tool-d", root=root,
    )
    assert bad.returncode == 2


def test_apply_system_opt_in_runs_with_mock_runner(tmp_path):
    """Live system_argv only with apply_system; runner is injected — never real apt."""
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "state"
    calls: list[list[str]] = []

    def runner(argv: list[str], cwd: Path):
        calls.append(list(argv))
        # Refuse accidental real package managers in tests.
        assert argv[0] not in ("apt-get", "brew", "sudo")
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    # Without apply_system: still refuse (and never call runner).
    results, rc = ai.apply(
        catalog,
        dry_run=False,
        ids={"tool-d"},
        allow_system=True,
        apply_system=False,
        state_dir=state,
        runner=runner,
    )
    assert rc == 2
    assert results[0]["action"] == "refuse-system-exec"
    assert calls == []

    # apply_system without allow_system refused at API.
    with pytest.raises(ai.InstallError, match="requires --system"):
        ai.apply(
            catalog,
            dry_run=False,
            ids={"tool-d"},
            allow_system=False,
            apply_system=True,
            state_dir=state,
            runner=runner,
        )

    # Opt-in path: rewrite fixture argv through expand is apt-get — use a custom
    # catalog row by monkeypatching pick via a runner that accepts the argv list
    # but we assert argv is a list and shell is never used (runner contract).
    def system_runner(argv: list[str], cwd: Path):
        calls.append(list(argv))
        assert isinstance(argv, list) and all(isinstance(x, str) for x in argv)
        assert cwd == catalog.root
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    calls.clear()
    results, rc = ai.apply(
        catalog,
        dry_run=False,
        ids={"tool-d"},
        allow_system=True,
        apply_system=True,
        state_dir=state,
        runner=system_runner,
    )
    assert rc == 0, results
    assert results[0]["action"] == "installed"
    assert results[0]["reason"] == "system_argv completed"
    assert calls == [["apt-get", "install", "-y", "tool-d"]]
    ledger = json.loads((state / "ledger.json").read_text())
    assert ledger["entries"]["tool-d"]["status"] == "installed"
    assert ledger["entries"]["tool-d"]["kind"] == "system_argv"


def test_cli_apply_system_requires_yes_and_opt_in(tmp_path):
    root = _fixture_root(tmp_path)
    no_yes = _run(
        "apply", "--apply-system", "--system", "--json", "--id", "tool-d", root=root,
    )
    assert no_yes.returncode == 2
    assert "--apply-system requires --yes" in no_yes.stderr

    # --yes --system without --apply-system still refused (no mock needed: no exec).
    refused = _run(
        "apply", "--yes", "--system", "--json", "--id", "tool-d", root=root,
    )
    assert refused.returncode == 2
    assert json.loads(refused.stdout)["results"][0]["action"] == "refuse-system-exec"


def test_user_install_link_dry_run(tmp_path):
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    tool = root / "bin" / "demo-tool"
    tool.write_text("#!/bin/sh\necho ok\n")
    tool.chmod(0o755)
    prefix = tmp_path / "prefix"
    result = aui.link_repo_bin("demo-tool", root=root, prefix=prefix, dry_run=True)
    assert result["action"] == "would-link"
    assert not prefix.exists()
    result = aui.link_repo_bin("demo-tool", root=root, prefix=prefix, dry_run=False)
    assert result["action"] == "linked"
    assert (prefix / "demo-tool").resolve() == tool.resolve()


def test_user_install_uv_url_linux_x86():
    # Pure URL construction; no network.
    url = aui.uv_download_url("linux", "x86_64")
    assert url.endswith("uv-x86_64-unknown-linux-gnu.tar.gz")
    jurl = aui.just_download_url("linux", "x86_64", "1.40.0")
    assert "just-1.40.0-x86_64-unknown-linux-musl.tar.gz" in jurl


def _nudge_settings(*, events: dict[str, str]) -> dict:
    """Minimal Claude settings with context_size_nudge under the named events."""
    hooks: dict = {}
    for event, cmd in events.items():
        hooks[event] = [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]
    return {"hooks": hooks}


def test_observe_context_size_nudge_skips_without_template(tmp_path):
    assert ai.observe_context_size_nudge(root=tmp_path) is None


def test_observe_context_size_nudge_ok_and_missing(tmp_path):
    root = tmp_path / "repo"
    tmpl = root / ai.CLAUDE_SETTINGS_TMPL
    tmpl.parent.mkdir(parents=True)
    # Real template has PostToolUse + UserPromptSubmit; copy it so expectations match.
    real = REPO / ai.CLAUDE_SETTINGS_TMPL
    tmpl.write_text(real.read_text())
    live = tmp_path / "settings.json"

    missing = ai.observe_context_size_nudge(root=root, settings_path=live)
    assert missing is not None
    assert missing.kind == "settings"
    assert missing.id == "context_size_nudge"
    assert missing.status == "missing"
    assert "PostToolUse" in missing.detail
    assert "UserPromptSubmit" in missing.detail
    assert "Apply by hand" in missing.detail
    assert "never mutates" in missing.detail

    live.write_text(json.dumps(_nudge_settings(events={
        "PostToolUse": f'hook-deadline 2 "$HOME"/.claude/hooks/{ai.CONTEXT_SIZE_NUDGE}',
    })))
    partial = ai.observe_context_size_nudge(root=root, settings_path=live)
    assert partial is not None and partial.status == "missing"
    assert "UserPromptSubmit" in partial.detail
    assert "PostToolUse" in partial.detail  # expected set still named

    live.write_text(json.dumps(_nudge_settings(events={
        "PostToolUse": f'hook-deadline 2 "$HOME"/.claude/hooks/{ai.CONTEXT_SIZE_NUDGE}',
        "UserPromptSubmit": f'hook-deadline 4 "$HOME"/.claude/hooks/{ai.CONTEXT_SIZE_NUDGE}',
    })))
    ok = ai.observe_context_size_nudge(root=root, settings_path=live)
    assert ok is not None and ok.status == "ok"
    assert "PostToolUse" in ok.detail and "UserPromptSubmit" in ok.detail


def test_doctor_includes_context_size_nudge_check(tmp_path):
    root = _fixture_root(tmp_path)
    # No template beside the fixture catalog → nudge skipped; doctor still fails on tool-c.
    obs, rc = ai.doctor(catalog=ai.load_catalog(root=root), settings_path=tmp_path / "absent.json", skip_credential_bak=True)
    assert not any(o.kind == "settings" for o in obs)
    assert rc == 1

    tmpl = root / ai.CLAUDE_SETTINGS_TMPL
    tmpl.parent.mkdir(parents=True)
    tmpl.write_text((REPO / ai.CLAUDE_SETTINGS_TMPL).read_text())
    live = tmp_path / "live-settings.json"
    live.write_text("{}")
    obs, rc = ai.doctor(catalog=ai.load_catalog(root=root), settings_path=live, skip_credential_bak=True)
    nudge = [o for o in obs if o.kind == "settings" and o.id == "context_size_nudge"]
    assert len(nudge) == 1 and nudge[0].status == "missing"
    assert rc == 1

    live.write_text(json.dumps(_nudge_settings(events={
        "PostToolUse": f".../{ai.CONTEXT_SIZE_NUDGE}",
        "UserPromptSubmit": f".../{ai.CONTEXT_SIZE_NUDGE}",
    })))
    # Force components healthy so only the settings check could fail; tool-c is still missing.
    # Assert the nudge itself is ok when both events are registered.
    nudge_only = ai.observe_context_size_nudge(root=root, settings_path=live)
    assert nudge_only is not None and nudge_only.status == "ok"


def test_repo_template_registers_context_size_nudge_events():
    events = ai._hook_events_registering(
        ai.load_claude_settings_json(REPO / ai.CLAUDE_SETTINGS_TMPL, template=True),
        ai.CONTEXT_SIZE_NUDGE,
    )
    assert events == {"PostToolUse", "UserPromptSubmit"}


def _force_secretspec_present():
    real_missing = ai._probe_executable_missing

    def not_missing(argv0: str) -> bool:
        if argv0 == "sudo-secretspec":
            return False
        return real_missing(argv0)

    return real_missing, not_missing


def test_keys_observe_missing_binary_is_unknown(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "keys.json"
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    obs, rc = ai.keys_observe(catalog, keys_state_path=state)
    assert rc == 0
    by = {(o.kind, o.id): o for o in obs}
    assert by[("secretspec", "check")].status == "unknown"
    assert "not on PATH" in by[("secretspec", "check")].detail
    assert any(o.kind == "key" for o in obs)
    assert state.is_file()
    saved = json.loads(state.read_text())
    assert "values" not in saved
    assert "hash" not in json.dumps(saved).lower()
    for entry in saved["keys"].values():
        assert set(entry) <= {"status", "detail"}
    assert saved["keys"]["EXAMPLE_API_KEY"]["status"] == "unknown"


def test_keys_observe_check_fail_exits_1(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "keys.json"

    def runner(argv, cwd):
        assert argv[:2] == ["sudo-secretspec", "check"]
        assert "--reason" in argv
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="missing ANTHROPIC_API_KEY\n")

    real_missing, not_missing = _force_secretspec_present()
    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        obs, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]
    assert rc == 1
    check = next(o for o in obs if o.kind == "secretspec")
    assert check.status == "missing"
    assert "missing ANTHROPIC_API_KEY" in check.detail


def test_keys_verify_under_secretspec_run_ok(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'presence = "python3"\n'
        "[[key]]\n"
        'name = "EXAMPLE_API_KEY"\n'
        'verify = "fixture"\n'
        'verify_argv = ["true"]\n'
    )
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "keys.json"
    seen: list[list[str]] = []

    def runner(argv, cwd):
        seen.append(list(argv))
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        assert argv[:2] == ["sudo-secretspec", "run"]
        assert "--reason" in argv
        reason = argv[argv.index("--reason") + 1]
        assert reason == "ade-install keys verify EXAMPLE_API_KEY"
        assert "--" in argv
        assert argv[argv.index("--") + 1 :] == ["true"]
        # Deliberate fake secret in stdout: must never appear in observations.
        return subprocess.CompletedProcess(
            argv, 0, stdout="SECRET_VALUE_SHOULD_NOT_LEAK\n", stderr=""
        )

    real_missing, not_missing = _force_secretspec_present()
    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        obs, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]
    assert rc == 0
    key = next(o for o in obs if o.kind == "key")
    assert key.status == "ok"
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in key.detail
    assert "no value read" in key.detail
    blob = state.read_text()
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in blob
    saved = json.loads(blob)
    assert saved["keys"]["EXAMPLE_API_KEY"]["status"] == "ok"
    assert any(a[:2] == ["sudo-secretspec", "run"] for a in seen)


def test_keys_verify_invalid_exits_1_and_hides_bodies(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'presence = "python3"\n'
        "[[key]]\n"
        'name = "EXAMPLE_API_KEY"\n'
        'verify_argv = ["probe-bin"]\n'
    )
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "keys.json"

    def runner(argv, cwd):
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            argv,
            ai.VERIFY_EXIT_INVALID,
            stdout="token=sk-leak-me\n",
            stderr="ADE_KEY_VERIFY:invalid\nbad body sk-leak-me\n",
        )

    real_missing, not_missing = _force_secretspec_present()
    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        obs, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]
    assert rc == 1
    key = next(o for o in obs if o.kind == "key")
    assert key.status == "invalid"
    assert "sk-leak-me" not in key.detail
    assert "sk-leak-me" not in state.read_text()


def test_keys_verify_expiring_marker(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'presence = "python3"\n'
        "[[key]]\n"
        'name = "EXAMPLE_API_KEY"\n'
        'verify_argv = ["probe-bin"]\n'
    )
    catalog = ai.load_catalog(root=root)
    state = tmp_path / "keys.json"

    def runner(argv, cwd):
        if argv[:2] == ["sudo-secretspec", "check"]:
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            argv,
            ai.VERIFY_EXIT_EXPIRING,
            stdout="",
            stderr="ADE_KEY_VERIFY:expiring:2026-12-01\n",
        )

    real_missing, not_missing = _force_secretspec_present()
    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        obs, rc = ai.keys_observe(catalog, runner=runner, keys_state_path=state)
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]
    assert rc == 0  # expiring is advisory, not VERIFY_FAIL_STATUSES
    key = next(o for o in obs if o.kind == "key")
    assert key.status == "expiring"
    assert "2026-12-01" in key.detail


def test_classify_verify_expiring_date_must_be_iso_calendar_day():
    status, detail = ai.classify_verify_result(
        ai.VERIFY_EXIT_OK,
        stderr="ADE_KEY_VERIFY:expiring:sk-leakMe1234567890abcdef\n",
    )
    assert status == "expiring"
    assert "sk-leakMe" not in detail
    assert "leak" not in detail
    assert detail == "verify expiring (no value read)"

    status, detail = ai.classify_verify_result(
        ai.VERIFY_EXIT_OK,
        stderr="ADE_KEY_VERIFY:expiring:2026-12-01T00:00:00Z\n",
    )
    assert status == "expiring"
    assert "2026-12-01T" not in detail
    assert detail == "verify expiring (no value read)"

    status, detail = ai.classify_verify_result(
        ai.VERIFY_EXIT_OK,
        stderr="ADE_KEY_VERIFY:expiring:2026-12-01\n",
    )
    assert status == "expiring"
    assert detail == "verify expiring 2026-12-01 (no value read)"


def test_classify_verify_keeps_failure_when_expiring_marker_present():
    for code, want in (
        (ai.VERIFY_EXIT_INVALID, "invalid"),
        (ai.VERIFY_EXIT_NO_QUOTA, "no-quota"),
        (ai.VERIFY_EXIT_UNREACHABLE, "unreachable"),
        (ai.VERIFY_EXIT_MISSING, "missing"),
    ):
        status, detail = ai.classify_verify_result(
            code,
            stderr="ADE_KEY_VERIFY:expiring:2026-12-01\n",
        )
        assert status == want, (code, status, detail)
        assert "expiring" not in status
        assert "2026-12-01" not in detail


def test_keys_verify_argv_validated(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'presence = "python3"\n'
        "[[key]]\n"
        'name = "BAD"\n'
        "verify_argv = []\n"
    )
    try:
        ai.load_catalog(root=root)
        raise AssertionError("expected InstallError")
    except ai.InstallError as e:
        assert "verify_argv" in str(e)


def test_cli_keys_json(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    state = tmp_path / "keys-cli.json"
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    proc = _run("keys", "--json", "--keys-state", str(state), root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert "no get/export" in payload["note"]
    assert "verify_argv" in payload["note"]
    kinds = {o["kind"] for o in payload["observations"]}
    assert "secretspec" in kinds
    assert state.is_file()


def test_graft_hard_dep_missing_probe_fails_doctor(tmp_path):
    """Hard-dep graft: missing ``graft --version`` binary fails doctor (exit 1)."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "graft"\n'
        'class = "hard"\n'
        'probe_argv = ["definitely-not-graft-xyz", "--version"]\n'
        'presence = "definitely-not-graft-xyz"\n'
    )
    catalog = ai.load_catalog(root=root)
    obs, rc = ai.doctor(catalog)
    by_id = {o.id: o for o in obs if o.kind == "component"}
    assert by_id["graft"].status == "missing"
    assert "probe binary not found" in by_id["graft"].detail
    assert rc == 1
    # No acceptance file under fixture root → no pools advisory.
    assert not any(o.kind == "pools" for o in obs)


def test_observe_pi_pools_skips_without_acceptance_file(tmp_path):
    assert ai.observe_pi_pools(root=tmp_path) is None


def test_observe_pi_pools_warns_unaccepted_quiet_on_accepted(tmp_path):
    """WARN names UNACCEPTED pools; accepted Cursor/Z.ai stay out of the detail."""
    root = tmp_path / "repo"
    path = root / "config" / "pi-pool-acceptance.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[pools.cursor]\naccepted = true\n"
        "[pools.zai]\naccepted = true\n"
        "[pools.grok]\naccepted = false\n"
        "[pools.go]\naccepted = false\n"
    )
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    o = ai.observe_pi_pools(root=root, acceptance_path=path)
    assert o is not None
    assert o.kind == "pools" and o.id == "ade-pi-pools"
    assert o.status == "warn"
    assert "grok" in o.detail and "go" in o.detail
    assert "UNACCEPTED" in o.detail
    assert "never writes accepted=true" in o.detail
    # Accepted shortlist stays quiet in the warn text.
    assert "cursor" not in o.detail.lower()
    assert "zai" not in o.detail.lower()
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime


def test_observe_pi_pools_ok_when_all_accepted(tmp_path):
    root = tmp_path / "repo"
    path = root / "config" / "pi-pool-acceptance.toml"
    path.parent.mkdir(parents=True)
    # Cover every routing Pi service so status_rows has no unaccepted routing gap.
    path.write_text(
        "[pools.cursor]\naccepted = true\n"
        "[pools.zai]\naccepted = true\n"
    )
    o = ai.observe_pi_pools(root=root, acceptance_path=path)
    assert o is not None and o.status == "ok"
    assert "accepted" in o.detail


def test_doctor_pi_pools_advisory_warn_keeps_exit_zero(tmp_path):
    """Pools warn is advisory: exit 0 when hard components are healthy."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'probe_argv = ["true"]\n'
        'presence = "true"\n'
    )
    accept = root / "config" / "pi-pool-acceptance.toml"
    accept.write_text(
        "[pools.cursor]\naccepted = true\n"
        "[pools.zai]\naccepted = true\n"
        "[pools.grok]\naccepted = false\n"
    )
    before = accept.read_bytes()

    def runner(argv, cwd):
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    obs, rc = ai.doctor(
        ai.load_catalog(root=root),
        runner=runner,
        pi_pool_acceptance_path=accept,
    )
    pools = [o for o in obs if o.kind == "pools" and o.id == "ade-pi-pools"]
    assert len(pools) == 1 and pools[0].status == "warn"
    assert "grok" in pools[0].detail
    assert rc == 0  # advisory only
    assert accept.read_bytes() == before


def test_shipped_acceptance_warns_checklist_quiet_on_cursor_zai():
    path = REPO / "config" / "pi-pool-acceptance.toml"
    before = path.read_bytes()
    o = ai.observe_pi_pools(root=REPO, acceptance_path=path)
    assert o is not None and o.status == "warn"
    for name in ("grok", "antigravity", "sipb", "go"):
        assert name in o.detail
    assert "cursor" not in o.detail.lower()
    assert "zai" not in o.detail.lower()
    assert path.read_bytes() == before

def test_secretspec_linux_urls_are_versioned_not_pinned():
    meta = aui.secretspec_linux_download_urls("0.21.1-sudo.5")
    assert meta["tag"] == "v0.21.1-sudo.5"
    assert meta["tarball_name"] == (
        "sudo-secretspec-0.21.1-sudo.5-x86_64-unknown-linux-gnu.tar.gz"
    )
    assert meta["tarball_url"].endswith(
        "/releases/download/v0.21.1-sudo.5/"
        "sudo-secretspec-0.21.1-sudo.5-x86_64-unknown-linux-gnu.tar.gz"
    )
    assert meta["sha256_url"].endswith(".tar.gz.sha256")
    assert meta["latest_page"].endswith("/releases/latest")
    # Must not invent a fixed tag in the download path without a resolved version.
    assert "/download/latest/" not in meta["tarball_url"]


def test_secretspec_linux_dry_run_uses_fake_resolver(monkeypatch, tmp_path):
    monkeypatch.setattr(aui, "host_triplet", lambda: ("linux", "x86_64"))
    prefix = tmp_path / "bin"
    result = aui.install_sudo_secretspec(
        prefix=prefix,
        dry_run=True,
        resolve_tag=lambda owner, repo: "0.21.1-sudo.5",
    )
    assert result["action"] == "would-fetch-extract"
    assert result["version"] == "0.21.1-sudo.5"
    assert "0.21.1-sudo.5" in result["tarball_url"]
    assert result["libexec_install_argv"][0] == "sudo"
    assert result["libexec_install_argv"][2:4] == ["install", "--declarations"]
    # Placeholder path only — never a secret value.
    assert result["libexec_install_argv"][-1] == "/path/secretspec.toml"
    assert not any("sk-" in a or "secret=" in a.lower() for a in result["libexec_install_argv"])
    assert not (tmp_path / "lib").exists()


def _fake_secretspec_media_blobs(version: str = "0.21.1-sudo.5"):
    import hashlib
    import io
    import tarfile

    root_name = f"sudo-secretspec-{version}-x86_64-unknown-linux-gnu"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # libexec installer stub
        data = b"#!/bin/sh\necho staged\n"
        info = tarfile.TarInfo(name=f"{root_name}/libexec/sudo-secretspec")
        info.size = len(data)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(data))
        readme = b"media\n"
        rinfo = tarfile.TarInfo(name=f"{root_name}/README.md")
        rinfo.size = len(readme)
        tar.addfile(rinfo, io.BytesIO(readme))
    blob = buf.getvalue()
    digest = hashlib.sha256(blob).hexdigest()
    tarball = f"{root_name}.tar.gz"
    sha_text = f"{digest}  {tarball}\n".encode()
    return blob, sha_text, tarball


def test_secretspec_linux_stage_with_fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(aui, "host_triplet", lambda: ("linux", "x86_64"))
    blob, sha_text, tarball = _fake_secretspec_media_blobs()
    urls = aui.secretspec_linux_download_urls("0.21.1-sudo.5")

    def fake_urlopen(url: str) -> bytes:
        if url == urls["tarball_url"]:
            return blob
        if url == urls["sha256_url"]:
            return sha_text
        raise AssertionError(f"unexpected URL {url!r} (tests must not hit network)")

    prefix = tmp_path / "bin"
    prefix.mkdir()
    result = aui.install_sudo_secretspec(
        prefix=prefix,
        dry_run=False,
        resolve_tag=lambda o, r: "0.21.1-sudo.5",
        urlopen=fake_urlopen,
    )
    assert result["action"] == "staged"
    assert result["run_install"] is False
    media = Path(result["media_dir"])
    assert (media / "libexec" / "sudo-secretspec").is_file()
    assert result["libexec_install_argv"][0] == "sudo"
    assert "--declarations" in result["libexec_install_argv"]
    # No secret-looking argv tokens.
    joined = " ".join(result["libexec_install_argv"])
    assert "API_KEY" not in joined and "password" not in joined.lower()


def test_secretspec_run_install_opt_in_with_fake_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(aui, "host_triplet", lambda: ("linux", "x86_64"))
    blob, sha_text, _ = _fake_secretspec_media_blobs()
    urls = aui.secretspec_linux_download_urls("0.21.1-sudo.5")

    def fake_urlopen(url: str) -> bytes:
        if url.endswith(".sha256"):
            return sha_text
        if url.endswith(".tar.gz"):
            return blob
        raise AssertionError(url)

    decl = tmp_path / "secretspec.toml"
    decl.write_text("[protocols]\n")
    seen: list[list[str]] = []

    def fake_runner(argv, cwd):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    result = aui.install_sudo_secretspec(
        prefix=tmp_path / "bin",
        dry_run=False,
        declarations=decl,
        run_install=True,
        resolve_tag=lambda o, r: "0.21.1-sudo.5",
        urlopen=fake_urlopen,
        runner=fake_runner,
    )
    assert result["action"] == "installed"
    assert len(seen) == 1
    assert seen[0][0] == "sudo"
    assert seen[0][2:] == ["install", "--declarations", str(decl.resolve())]
    assert all(a != "" for a in seen[0])


def test_plan_and_apply_linux_secretspec_uses_install_argv(monkeypatch, tmp_path):
    # On Linux (no brew system_argv), needs_system rows with install_argv fall through.
    monkeypatch.setattr(ai.platform, "system", lambda: "Linux")
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "bin" / "ade-user-install").write_text("#!/bin/sh\n")
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "sudo-secretspec"\n'
        'class = "hard"\n'
        "needs_system = true\n"
        "install_argv = "
        '["{bin}/ade-user-install", "sudo-secretspec", "--prefix", "{prefix}"]\n'
        'system_argv_darwin = ["brew", "install", "frdminc/sudo-secretspec/sudo-secretspec"]\n'
        'probe_argv = ["true"]\n'
        'presence = "true"\n'
    )
    catalog = ai.load_catalog(root=root)
    steps = ai.plan(catalog)
    by_id = {s["id"]: s for s in steps}
    assert by_id["sudo-secretspec"]["action"] == "would-install"
    assert by_id["sudo-secretspec"]["argv"][1] == "sudo-secretspec"
    assert by_id["sudo-secretspec"]["needs_system"] is True

    apply_steps = ai.build_apply_steps(catalog, force=True, allow_system=False)
    assert apply_steps[0].action == "would-install"
    assert apply_steps[0].argv is not None
    assert apply_steps[0].argv[1] == "sudo-secretspec"

    # Darwin still prefers brew system_argv when --system is set.
    monkeypatch.setattr(ai.platform, "system", lambda: "Darwin")
    darwin_steps = ai.build_apply_steps(catalog, force=True, allow_system=True)
    assert darwin_steps[0].action == "would-system-install"
    assert darwin_steps[0].argv[:2] == ["brew", "install"]


def test_safe_extract_refuses_path_traversal(tmp_path):
    import io
    import tarfile

    bad = io.BytesIO()
    with tarfile.open(fileobj=bad, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../escape")
        payload = b"x"
        info.size = 1
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(aui.UserInstallError, match="unsafe|escapes"):
        aui._safe_extract_tar_gz(bad.getvalue(), tmp_path / "bad")


def test_hermes_and_cursor_dry_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        aui,
        "_resolve_cursor_version",
        lambda: "2026.11.05-86047df",
    )
    prefix = tmp_path / "bin"
    result = aui.install_cursor_cli(prefix=prefix, share=tmp_path / "share", dry_run=True)
    assert result["action"] == "would-fetch"
    assert "2026.11.05-86047df" in result["url"]
    assert result["dest"] == str(prefix / "agent")
    assert result["trust"] == aui.VENDOR_TRUST_ENV
    assert not prefix.exists()

    h = aui.install_hermes(dry_run=True)
    assert h["action"] == "would-run-script"
    assert h["url"] == aui.HERMES_INSTALL_SCRIPT
    assert h["argv"][-1] == "--non-interactive"
    assert h["trust"] == aui.VENDOR_TRUST_ENV


def test_vendor_install_refuses_without_trust_env(monkeypatch, tmp_path):
    monkeypatch.delenv(aui.VENDOR_TRUST_ENV, raising=False)
    monkeypatch.setattr(aui, "_resolve_cursor_version", lambda: "2026.11.05-86047df")
    with pytest.raises(aui.UserInstallError, match=aui.VENDOR_TRUST_ENV):
        aui.install_cursor_cli(prefix=tmp_path / "bin", share=tmp_path / "share", dry_run=False)
    with pytest.raises(aui.UserInstallError, match=aui.VENDOR_TRUST_ENV):
        aui.install_hermes(dry_run=False)


def test_labeled_ade_sched_job_names_from_repo():
    catalog = ai.load_catalog(root=REPO)
    names = ai.labeled_ade_sched_job_names(catalog)
    assert "keys-check" in names
    assert "harden-check" in names
    assert "ade-update-check" in names
    assert "deadline-sweep" in names
    assert "update-auto" not in names  # no plist yet


def test_apply_skips_reconcile_when_id_filter(monkeypatch, tmp_path):
    called: list[int] = []

    def boom(*_a, **_k):
        called.append(1)
        return [], 0

    monkeypatch.setattr(ai, "apply_sched_reconcile", boom)
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-c"})
    assert rc == 0
    assert called == []
    assert not any(r.get("category") == "sched" for r in results)


def test_apply_full_runs_reconcile_sched(monkeypatch, tmp_path):
    called: list[bool] = []

    def fake(_catalog, *, dry_run=True, **_k):
        called.append(dry_run)
        return ([{
            "id": "keys-check",
            "action": "would-install",
            "reason": "plan",
            "ok": True,
            "category": "sched",
        }], 0)

    monkeypatch.setattr(ai, "apply_sched_reconcile", fake)
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Force reconcile even with --id (default would skip when ids is set).
    results, rc = ai.apply(catalog, dry_run=True, ids={"tool-c"}, reconcile_sched=True)
    assert rc == 0, results
    assert called == [True]
    assert any(r.get("category") == "sched" and r["id"] == "keys-check" for r in results)


def test_apply_sched_reconcile_skips_non_write_backend(monkeypatch, tmp_path):
    import ade_sched as sched

    class B:
        # Host backend outside RECONCILE_WRITE_BACKENDS (launchd/cron/systemd write; paseo is orthogonal).
        name = "paseo"

    monkeypatch.setattr(sched, "detect", lambda *_a, **_k: B())
    root = _fixture_root(tmp_path)
    # Point catalog jobs at a labeled ADE row.
    (root / "config" / "install.toml").write_text(
        (REPO / "config" / "install.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    catalog = ai.load_catalog(root=root)
    rows, rc = ai.apply_sched_reconcile(catalog, dry_run=False, names={"keys-check"})
    assert rc == 0
    assert rows and rows[0]["action"] == "skip-reconcile-backend"
    assert rows[0]["ok"] is True


def test_apply_sched_reconcile_refuses_linked_worktree_root(monkeypatch, tmp_path):
    """Full apply must not pin timers at an ephemeral linked worktree (Codex P1 on #516)."""
    import ade_sched as sched

    class B:
        name = "systemd"

    monkeypatch.setattr(sched, "detect", lambda *_a, **_k: B())
    monkeypatch.setattr(sched, "RECONCILE_WRITE_BACKEND", "systemd", raising=False)
    monkeypatch.setattr(sched, "RECONCILE_WRITE_BACKENDS", frozenset({"systemd"}), raising=False)
    monkeypatch.setattr(sched, "is_linked_worktree", lambda _p: True)
    called: list[dict] = []

    def fake_reconcile(*_a, **kwargs):
        called.append(kwargs)
        return [], 0

    monkeypatch.setattr(sched, "reconcile", fake_reconcile)
    root = _fixture_root(tmp_path)
    (root / "config" / "install.toml").write_text(
        (REPO / "config" / "install.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    catalog = ai.load_catalog(root=root)
    for dry_run in (False, True):
        called.clear()
        rows, rc = ai.apply_sched_reconcile(
            catalog, dry_run=dry_run, names={"keys-check"},
        )
        assert rc == 1, dry_run
        assert not called, dry_run
        assert rows and rows[0]["action"] == "blocked", dry_run
        assert "worktree" in rows[0]["reason"], dry_run
        assert rows[0]["ok"] is False, dry_run


def test_apply_sched_reconcile_passes_implicit_ade(monkeypatch, tmp_path):
    """ade=None keeps Job.from_* worktree refuse; ade=root would bypass it."""
    import ade_sched as sched

    class B:
        name = "systemd"

    monkeypatch.setattr(sched, "detect", lambda *_a, **_k: B())
    monkeypatch.setattr(sched, "RECONCILE_WRITE_BACKEND", "systemd", raising=False)
    monkeypatch.setattr(sched, "RECONCILE_WRITE_BACKENDS", frozenset({"systemd"}), raising=False)
    monkeypatch.setattr(sched, "is_linked_worktree", lambda _p: False)
    seen: list[object] = []

    def fake_reconcile(*_a, **kwargs):
        seen.append(kwargs.get("ade"))
        return [{"name": "keys-check", "action": "unchanged", "ok": True}], 0

    monkeypatch.setattr(sched, "reconcile", fake_reconcile)
    root = _fixture_root(tmp_path)
    (root / "config" / "install.toml").write_text(
        (REPO / "config" / "install.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    catalog = ai.load_catalog(root=root)
    rows, rc = ai.apply_sched_reconcile(catalog, dry_run=False, names={"keys-check"})
    assert rc == 0
    assert seen == [None]
    assert rows and rows[0]["id"] == "keys-check"



# --- S4: ade-install update (execute dependency update_argv with evidence) ---


def _update_run_spy(rc_by_call: list[int] | None = None):
    """Fake run callable: records argv calls, returns CompletedProcess per rc list."""
    calls: list[list[str]] = []

    def run(argv):
        calls.append([str(a) for a in argv])
        rc = 0
        if rc_by_call:
            rc = rc_by_call.pop(0) if len(rc_by_call) > 1 else rc_by_call[0]
        return subprocess.CompletedProcess(argv, rc, stdout=f"out {len(calls)}\n", stderr="")

    return run, calls


def test_update_dry_run_runs_nothing_writes_nothing(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy()
    report, rc = ai.apply_updates(
        catalog, dry_run=True, run=run, state_path=tmp_path / "state" / "updates.json",
    )
    assert rc == 0
    assert calls == []
    assert report["mode"] == "dry-run"
    entries = {e["id"]: e for e in report["components"]}
    assert entries["tool-a"]["action"] == "would-update"
    assert entries["tool-a"]["argv"] == ["true"]
    assert entries["tool-a"]["pre"]["status"] == "ok"
    assert not (tmp_path / "state" / "updates.json").exists()
    # unchosen/blocked rows never become candidates
    assert set(entries) == {"tool-a"}


def test_update_yes_executes_and_writes_evidence(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy()
    state = tmp_path / "state" / "updates.json"
    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, state_path=state,
    )
    assert rc == 0
    assert calls == [["true"]]
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["action"] == "updated"
    assert entry["rc"] == 0
    assert entry["doctor"] == "ok"
    assert entry["retried"] is False
    saved = json.loads(state.read_text())
    assert saved["mode"] == "apply"
    assert saved["exit"] == 0
    assert saved["components"][0]["id"] == "tool-a"


def test_update_yes_skips_missing_prestate(tmp_path):
    root = _fixture_root(tmp_path)
    # Make tool-a's probe binary absent so pre-observation is missing.
    catalog = ai.load_catalog(root=root)
    row = {c["id"]: c for c in catalog.components}["tool-a"]
    row["probe_argv"] = ["definitely-not-a-binary-xyz", "--version"]
    run, calls = _update_run_spy()
    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, state_path=tmp_path / "updates.json",
    )
    assert rc == 0
    assert calls == []  # never ran the update for an absent binary
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["action"] == "skip-not-installed"
    assert "doctor" not in entry


def test_update_doctor_fail_retries_once_then_reports(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy()

    obs_fail = ai.Observation("component", "tool-a", "missing", "doctor: absent after update")
    obs_ok = ai.Observation("component", "tool-a", "ok", "doctor: probe ok")
    doctor_calls: list[list[str]] = []

    def doctor_fn(_catalog, *, component_ids=None, probe_timeout_s=15.0):
        doctor_calls.append(list(component_ids or []))
        # first scoped doctor fails; after the retry it passes
        if len(doctor_calls) == 1:
            return [obs_fail], 1
        return [obs_ok], 0

    state = tmp_path / "updates.json"
    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, doctor_fn=doctor_fn, state_path=state,
    )
    assert rc == 0  # healthy after the one retry
    assert calls == [["true"], ["true"]]  # initial run + exactly one retry
    assert doctor_calls == [["tool-a"], ["tool-a"]]
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["retried"] is True
    assert entry["retry_rc"] == 0
    assert entry["doctor"] == "ok"
    assert report["doctor"]["before_fail"] == ["tool-a"]
    assert report["doctor"]["retried"] == ["tool-a"]
    assert report["doctor"]["after_fail"] == []


def test_update_doctor_still_failing_after_retry_exits_1_no_rollback(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy()

    obs_fail = ai.Observation("component", "tool-a", "error", "doctor: still broken")
    doctor_calls: list[list[str]] = []

    def doctor_fn(_catalog, *, component_ids=None, probe_timeout_s=15.0):
        doctor_calls.append(list(component_ids or []))
        return [obs_fail], 1

    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, doctor_fn=doctor_fn, state_path=tmp_path / "updates.json",
    )
    assert rc == 1
    assert calls == [["true"], ["true"]]  # one retry, then reported
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["doctor"] == "fail"
    assert entry["action"] == "updated"  # evidence recorded; never rolled back
    assert report["doctor"]["after_fail"] == ["tool-a"]


def test_update_failed_update_command_exits_1(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy(rc_by_call=[3])

    obs_ok = ai.Observation("component", "tool-a", "ok", "doctor: probe ok")

    def doctor_fn(_catalog, *, component_ids=None, probe_timeout_s=15.0):
        return [obs_ok], 0

    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, doctor_fn=doctor_fn, state_path=tmp_path / "updates.json",
    )
    assert rc == 1  # update_argv exited 3; doctor ok does not hide it
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["action"] == "update-failed"
    assert entry["rc"] == 3
    assert entry["doctor"] == "ok"


def test_update_id_filter_and_unknown_id(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    run, calls = _update_run_spy()
    report, rc = ai.apply_updates(
        catalog, dry_run=True, ids={"tool-a"}, run=run, state_path=tmp_path / "u.json",
    )
    assert rc == 0
    assert [e["id"] for e in report["components"]] == ["tool-a"]
    with pytest.raises(ai.InstallError, match="unknown update component"):
        ai.apply_updates(catalog, dry_run=True, ids={"no-such"}, run=run)


def test_update_cli_dry_run_and_yes(tmp_path):
    root = _fixture_root(tmp_path)
    dry = _run("update", root=root)
    assert dry.returncode == 0
    assert "would-update" in dry.stdout
    state = tmp_path / "state"
    yes = _run("update", "--yes", "--state", str(state / "updates.json"), root=root)
    assert yes.returncode == 0
    assert "updated" in yes.stdout
    assert "evidence:" in yes.stdout
    saved = json.loads((state / "updates.json").read_text())
    assert saved["exit"] == 0
    # refuse both flags
    both = _run("update", "--yes", "--dry-run", root=root)
    assert both.returncode == 2


def test_update_cli_json_reports_state(tmp_path):
    root = _fixture_root(tmp_path)
    state = tmp_path / "updates.json"
    out = _run("update", "--yes", "--json", "--state", str(state), root=root)
    assert out.returncode == 0
    payload = json.loads(out.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "apply"
    assert payload["exit"] == 0


def test_update_timeout_is_failed_even_when_doctor_ok(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)

    def run(_argv):
        raise subprocess.TimeoutExpired(_argv, 1)

    obs_ok = ai.Observation("component", "tool-a", "ok", "doctor: probe ok")

    def doctor_fn(_catalog, *, component_ids=None, probe_timeout_s=15.0):
        return [obs_ok], 0

    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, doctor_fn=doctor_fn, state_path=tmp_path / "updates.json",
    )
    assert rc == 1
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["action"] == "update-failed"
    assert entry["rc"] is None
    assert entry["doctor"] == "ok"


def test_update_retry_timeout_is_failed_even_when_doctor_ok(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    calls = {"n": 0}

    def run(_argv):
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(_argv, 0, stdout="first\n", stderr="")
        raise subprocess.TimeoutExpired(_argv, 1)

    obs_fail = ai.Observation("component", "tool-a", "missing", "doctor: absent")
    obs_ok = ai.Observation("component", "tool-a", "ok", "doctor: probe ok")
    doctor_calls = {"n": 0}

    def doctor_fn(_catalog, *, component_ids=None, probe_timeout_s=15.0):
        doctor_calls["n"] += 1
        if doctor_calls["n"] == 1:
            return [obs_fail], 1
        return [obs_ok], 0

    report, rc = ai.apply_updates(
        catalog, dry_run=False, run=run, doctor_fn=doctor_fn, state_path=tmp_path / "updates.json",
    )
    assert rc == 1
    assert calls["n"] == 2
    entry = {e["id"]: e for e in report["components"]}["tool-a"]
    assert entry["retried"] is True
    assert entry["rc"] == 0
    assert entry["retry_rc"] is None
    assert entry["doctor"] == "ok"



@pytest.mark.parametrize("choice", [None, "skip", "self", "ai"])
def test_hermes_choice_never_stays_unselected(choice):
    record = None if choice is None else {"choice": choice}
    assert ai.hermes_choice_effective({"id": "hermes", "class": "never"}, record) is False


def test_hermes_checklist_test_has_docstring():
    assert test_hermes_choice_self_runs_checklist.__doc__
