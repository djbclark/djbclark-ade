"""ade-install catalog / plan / doctor / keys / linux-e2e / bounded apply."""
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


def _sched_backend(name: str, env: dict | None = None):
    import ade_sched as sched

    return sched.Backend(name, dict(env or {}), f"test-{name}")


def test_observe_sched_linger_launchd_and_cron_na():
    for name in ("launchd", "cron"):
        o = ai.observe_sched_linger(
            detect_fn=lambda env=None, **kw: _sched_backend(name),
            linger_fn=lambda env=None: "no",
            labels_fn=lambda backend, env=None: ["should-not-matter"],
        )
        assert o.kind == "sched" and o.id == "linger"
        assert o.status == "ok"
        assert f"linger: n/a (backend={name})" in o.detail
        assert "sudo" not in o.detail


def test_observe_sched_linger_systemd_jobs_no_is_warn():
    o = ai.observe_sched_linger(
        detect_fn=lambda env=None, **kw: _sched_backend("systemd", {"USER": "tester"}),
        linger_fn=lambda env=None: "no",
        labels_fn=lambda backend, env=None: ["com.djbclark.ade-update-check"],
    )
    assert o.status == "warn"
    assert "just linger" in o.detail
    assert "enable-linger" in o.detail
    assert "ade-update-check" in o.detail
    assert "sudo" not in o.detail.lower()


def test_observe_sched_linger_systemd_yes_or_no_jobs_ok():
    yes = ai.observe_sched_linger(
        detect_fn=lambda env=None, **kw: _sched_backend("systemd"),
        linger_fn=lambda env=None: "yes",
        labels_fn=lambda backend, env=None: ["com.djbclark.deadline-sweep"],
    )
    assert yes.status == "ok" and "linger: yes" in yes.detail
    idle = ai.observe_sched_linger(
        detect_fn=lambda env=None, **kw: _sched_backend("systemd"),
        linger_fn=lambda env=None: "no",
        labels_fn=lambda backend, env=None: [],
    )
    assert idle.status == "ok" and "no ade-sched systemd jobs" in idle.detail


def test_doctor_sched_linger_warn_fails_exit(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    # Skip live component probes' hard miss by forcing linger only: tool-c is missing,
    # so use skip path via injected ok components — inject sched linger warn directly.
    warn = ai.Observation(
        "sched", "linger", "warn",
        ai.linger_off_doctor_detail(["com.djbclark.ade-update-check"]),
    )
    # Count only linger: pass a catalog with no expected missing by observing with
    # skip_sched_linger false and sched_linger injected; fixture still has tool-c missing.
    # Use a hard-only-ok mini catalog instead.
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "tool-a"\n'
        'class = "hard"\n'
        'probe_argv = ["true"]\n'
        'presence = "true"\n'
    )
    catalog = ai.load_catalog(root=root)
    obs, rc = ai.doctor(catalog, sched_linger=warn)
    assert rc == 1
    linger = [o for o in obs if o.kind == "sched" and o.id == "linger"]
    assert len(linger) == 1 and linger[0].status == "warn"
    assert "sudo" not in linger[0].detail.lower()
    obs_ok, rc_ok = ai.doctor(
        catalog,
        sched_linger=ai.Observation("sched", "linger", "ok", "linger: n/a (backend=launchd)"),
    )
    assert rc_ok == 0
    assert any(o.detail.startswith("linger: n/a") for o in obs_ok if o.kind == "sched")


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
    assert len(json.loads(c.stdout)["component"]) == 5
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


def test_keys_observe_missing_binary_is_unknown(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    obs, rc = ai.keys_observe(catalog)
    assert rc == 0
    by = {(o.kind, o.id): o for o in obs}
    assert by[("secretspec", "check")].status == "unknown"
    assert "not on PATH" in by[("secretspec", "check")].detail
    assert any(o.kind == "key" for o in obs)


def test_keys_observe_check_fail_exits_1(tmp_path):
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)

    def runner(argv, cwd):
        assert argv[:2] == ["sudo-secretspec", "check"]
        assert "--reason" in argv
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="missing ANTHROPIC_API_KEY\n"
        )

    real_missing = ai._probe_executable_missing

    def not_missing(argv0: str) -> bool:
        if argv0 == "sudo-secretspec":
            return False
        return real_missing(argv0)

    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        obs, rc = ai.keys_observe(catalog, runner=runner)
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]
    assert rc == 1
    check = next(o for o in obs if o.kind == "secretspec")
    assert check.status == "missing"
    assert "missing ANTHROPIC_API_KEY" in check.detail


def test_cli_keys_json(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    proc = _run("keys", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert "no get/export" in payload["note"]
    kinds = {o["kind"] for o in payload["observations"]}
    assert "secretspec" in kinds


def test_linux_e2e_proves_harddeps_keys_linger(tmp_path, monkeypatch):
    """Hermetic Linux path: hard install_argv dry-run + keys + linger WARN (no Mac)."""
    root = _fixture_root(tmp_path)
    catalog = ai.load_catalog(root=root)
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)

    warn = ai.Observation(
        "sched",
        "linger",
        "warn",
        ai.linger_off_doctor_detail(["com.djbclark.ade-update-check"]),
    )

    def secretspec_ok(argv, cwd):
        assert argv[:2] == ["sudo-secretspec", "check"]
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    real_missing = ai._probe_executable_missing

    def not_missing(argv0: str) -> bool:
        if argv0 == "sudo-secretspec":
            return False
        return real_missing(argv0)

    ai._probe_executable_missing = not_missing  # type: ignore[assignment]
    try:
        report, rc = ai.linux_e2e(
            catalog,
            sched_linger=warn,
            secretspec_runner=secretspec_ok,
        )
    finally:
        ai._probe_executable_missing = real_missing  # type: ignore[assignment]

    # Doctor fails on linger WARN + missing hard components; e2e rc mirrors that.
    assert rc == 1
    assert report["mode"] == "linux-e2e-dry-run"
    assert report["linger"]["status"] == "warn"
    assert "just linger" in report["linger"]["detail"]
    assert "sudo" not in report["linger"]["detail"].lower()
    assert report["secretspec_check"]["status"] == "ok"
    assert "tool-a" in report["hard_ids"]
    assert "tool-d" in report["hard_ids"]
    assert "tool-e" in report["hard_ids"]
    assert "tool-c" not in report["hard_ids"]  # optional, not hard

    apply_rows = {
        r["id"]: r for r in report["stages"]["apply_hard_dry_run"]["results"]
    }
    assert apply_rows["tool-e"]["action"] == "would-install"
    assert apply_rows["tool-e"]["argv"] == ["true"]
    assert apply_rows["tool-d"]["action"] == "would-system-install"
    assert apply_rows["tool-d"]["argv"][:2] == ["apt-get", "install"]
    # No Darwin brew argv required for the Linux prove path.
    assert all("brew" not in " ".join(r.get("argv") or []) for r in apply_rows.values())


def test_linux_e2e_empty_hard_selection_does_not_apply_all(tmp_path, monkeypatch):
    """Empty hard_ids must pass an empty set (not None) so apply selects nothing.

    None would tell build_apply_steps to process every component, so a catalog
    with only offered/optional rows would dry-run those instead of hard-only.
    """
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "opt"\n'
        'class = "optional"\n'
        "chosen = true\n"
        'probe_argv = ["true"]\n'
        'presence = "definitely-not-on-path-opt-empty-hard"\n'
        # no install_argv → would be blocked if selected via ids=None
        "[[component]]\n"
        'id = "off"\n'
        'class = "offered"\n'
        "chosen = false\n"
        'presence = "definitely-not-on-path-off-empty-hard"\n'
    )
    catalog = ai.load_catalog(root=root)
    assert ai.hard_component_ids(catalog) == set()
    linger_ok = ai.Observation(
        "sched", "linger", "ok", "linger: n/a (backend=cron)"
    )
    _report, _rc = ai.linux_e2e(catalog, sched_linger=linger_ok)
    assert _report["hard_ids"] == []
    assert _report["stages"]["apply_hard_dry_run"]["results"] == []
    assert _report["stages"]["apply_hard_dry_run"]["rc"] == 0


def test_linux_e2e_ok_when_hard_present_linger_na(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    (root / "config" / "install.toml").write_text(
        "schema_version = 1\n"
        "[[component]]\n"
        'id = "py"\n'
        'class = "hard"\n'
        'probe_argv = ["python3", "--version"]\n'
        'presence = "python3"\n'
        'install_argv = ["true"]\n'
        "[[key]]\n"
        'name = "K"\n'
        'components = ["py"]\n'
        'create_url = "UNKNOWN"\n'
        'verify = "UNKNOWN"\n'
        'expiry = "unknown"\n'
    )
    catalog = ai.load_catalog(root=root)
    real_which = ai.shutil.which
    monkeypatch.setattr(
        ai.shutil,
        "which",
        lambda name: None if name == "sudo-secretspec" else real_which(name),
    )
    linger_ok = ai.Observation(
        "sched", "linger", "ok", "linger: n/a (backend=launchd)"
    )
    report, rc = ai.linux_e2e(
        catalog,
        sched_linger=linger_ok,
        # secretspec absent → unknown, keys rc 0
    )
    assert rc == 0, report
    assert report["ok"] is True
    assert report["linger"]["status"] == "ok"
    assert report["secretspec_check"]["status"] == "unknown"
    rows = report["stages"]["apply_hard_dry_run"]["results"]
    assert rows[0]["id"] == "py"
    # present → skip on dry-run (python3 is on PATH in CI)
    assert rows[0]["action"] == "skip"


def test_cli_linux_e2e_json(tmp_path, monkeypatch):
    root = _fixture_root(tmp_path)
    monkeypatch.setattr(ai.shutil, "which", lambda _name: None)
    # Inject via env-free path: monkeypatch linux_e2e to force linger n/a by
    # patching observe_sched_linger used inside doctor when not injected — CLI
    # has no inject hooks, so patch observe_sched_linger for hermetic CI.
    monkeypatch.setattr(
        ai,
        "observe_sched_linger",
        lambda **_kw: ai.Observation(
            "sched", "linger", "ok", "linger: n/a (backend=cron)"
        ),
    )
    proc = _run("linux-e2e", "--json", root=root)
    # Fixture has missing hard tool-d/tool-e → doctor fails → e2e rc 1, still JSON.
    assert proc.returncode == 1, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "linux-e2e-dry-run"
    assert "tool-e" in payload["hard_ids"]
    actions = {
        r["id"]: r["action"]
        for r in payload["stages"]["apply_hard_dry_run"]["results"]
    }
    assert actions["tool-e"] == "would-install"
    assert actions["tool-d"] == "would-system-install"
