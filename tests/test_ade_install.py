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
    assert catalog.provenance["source"] == "ade.toml"
    assert catalog.provenance["ade_toml_has_install"] is True
    assert str(catalog.path).endswith("config/ade.toml")
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


def test_folded_catalog_matches_legacy_install_toml():
    """Folded [install] and transitional install.toml are the same catalog body."""
    import tomllib

    folded = ai.load_catalog(root=REPO)
    legacy = ai.load_catalog(
        root=REPO, install_path=REPO / "config" / "install.toml"
    )
    assert folded.provenance["source"] == "ade.toml"
    assert legacy.provenance["source"] == "install.toml"
    assert folded.data == legacy.data


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


def test_loads_install_while_ade_toml_present_without_install_fold(tmp_path):
    """ade.toml without [install] falls through to transitional install.toml."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "ade.toml").write_text("schema_version = 1\n")
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    catalog = ai.load_catalog(root=root)
    assert catalog.provenance["ade_toml_present"] is True
    assert catalog.provenance["ade_toml_has_install"] is False
    assert catalog.provenance["source"] == "install.toml"
    assert len(catalog.components) >= 1


def test_prefers_folded_install_when_ade_toml_carries_catalog(tmp_path):
    """When both exist, prefer folded [install]; legacy file stays for fallthrough."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    folded = (
        "schema_version = 1\n"
        "[install]\n"
        "schema_version = 1\n"
        "[[install.component]]\n"
        'id = "folded-tool"\n'
        'class = "hard"\n'
        'presence = "true"\n'
        'probe_argv = ["true"]\n'
    )
    (root / "config" / "ade.toml").write_text(folded)
    (root / "config" / "install.toml").write_text((FIX / "minimal.toml").read_text())
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    catalog = ai.load_catalog(root=root)
    assert catalog.provenance["source"] == "ade.toml"
    assert catalog.provenance["legacy_install_present"] is True
    assert [c["id"] for c in catalog.components] == ["folded-tool"]
    # Explicit legacy path still loads install.toml (tooling / parity checks).
    legacy = ai.load_catalog(root=root, install_path=root / "config" / "install.toml")
    assert legacy.provenance["source"] == "install.toml"
    assert [c["id"] for c in legacy.components] != ["folded-tool"]


def test_doctor_same_folded_vs_legacy(tmp_path):
    """Doctor observations match for the same catalog body from either source."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    minimal = (FIX / "minimal.toml").read_text()
    (root / "config" / "install.toml").write_text(minimal)
    (root / "config" / "install.schema.json").write_text(
        (REPO / "config" / "install.schema.json").read_text()
    )
    # Build ade.toml with only [install] from the same body.
    import tomllib

    body = tomllib.loads(minimal)
    lines = ["schema_version = 1", "", "[install]", "schema_version = 1", ""]
    for row in body["component"]:
        lines.append("[[install.component]]")
        for k, v in row.items():
            if isinstance(v, bool):
                lines.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, list):
                inner = ", ".join(json.dumps(x) for x in v)
                lines.append(f"{k} = [ {inner} ]")
            else:
                lines.append(f"{k} = {json.dumps(v)}")
        lines.append("")
    for section in ("key", "login"):
        for row in body.get(section) or []:
            lines.append(f"[[install.{section}]]")
            for k, v in row.items():
                if isinstance(v, list):
                    inner = ", ".join(json.dumps(x) for x in v)
                    lines.append(f"{k} = [ {inner} ]")
                else:
                    lines.append(f"{k} = {json.dumps(v)}")
            lines.append("")
    (root / "config" / "ade.toml").write_text("\n".join(lines) + "\n")
    folded = ai.load_catalog(root=root)
    legacy = ai.load_catalog(root=root, install_path=root / "config" / "install.toml")
    assert folded.data == legacy.data
    obs_f, rc_f = ai.doctor(folded)
    obs_l, rc_l = ai.doctor(legacy)
    assert rc_f == rc_l
    # Catalog observation ids name the source path; component/key/login probes match.
    assert [(o.kind, o.id, o.status, o.detail) for o in obs_f if o.kind != "catalog"] == [
        (o.kind, o.id, o.status, o.detail) for o in obs_l if o.kind != "catalog"
    ]
    assert [o.status for o in obs_f if o.kind == "catalog"] == ["ok"]
    assert [o.status for o in obs_l if o.kind == "catalog"] == ["ok"]


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
