"""ade-install catalog / plan / doctor / bounded apply."""
from __future__ import annotations

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
    assert by_id["sudo-secretspec"].get("system_argv") is None  # Linux tarball still UNKNOWN
    assert by_id["claude-code"].get("install_argv") == [
        "npm",
        "install",
        "-g",
        "@anthropic-ai/claude-code",
    ]
    assert by_id["codex"].get("install_argv") == ["npm", "install", "-g", "@openai/codex"]
    assert by_id["cursor-cli"].get("presence") == "agent"
    assert by_id["cursor-cli"].get("probe_argv") == ["agent", "--version"]
    assert by_id["cursor-cli"].get("update_argv") == ["agent", "update"]
    assert by_id["cursor-cli"].get("install_argv") is None  # curl|bash; no argv-list yet
    assert by_id["hermes"].get("chosen") is True
    assert by_id["hermes"].get("probe_argv") == ["hermes", "doctor"]
    assert by_id["hermes"].get("update_argv") == ["hermes", "update"]
    assert by_id["hermes"].get("install_argv") is None  # curl|bash; no argv-list yet
    proc = _run("check", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_fixture_doctor_missing_vs_unchosen(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    obs, rc = ai.doctor(catalog)
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
    obs, rc = ai.doctor(catalog, runner=runner)
    by_id = {o.id: o for o in obs if o.kind == "component"}
    assert by_id["tool-a"].status == "error"
    assert "boom" in by_id["tool-a"].detail
    assert rc == 1


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
    obs, rc = ai.doctor(catalog=ai.load_catalog(root=root), settings_path=tmp_path / "absent.json")
    assert not any(o.kind == "settings" for o in obs)
    assert rc == 1

    tmpl = root / ai.CLAUDE_SETTINGS_TMPL
    tmpl.parent.mkdir(parents=True)
    tmpl.write_text((REPO / ai.CLAUDE_SETTINGS_TMPL).read_text())
    live = tmp_path / "live-settings.json"
    live.write_text("{}")
    obs, rc = ai.doctor(catalog=ai.load_catalog(root=root), settings_path=live)
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
