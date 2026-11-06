"""Bulk skill discovery and reconciliation, with isolated HOME and no live clients."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "skill-everywhere"


@pytest.fixture
def catalog(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    public = tmp_path / "public skills"
    private = tmp_path / "private skills"
    public.mkdir()
    private.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    codex = bindir / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"),
               BASH_ENV="/dev/null", SKILL_EVERYWHERE_ADE=str(public),
               SKILL_EVERYWHERE_PRIVATE=str(private), SKILL_EVERYWHERE_ONLY="codex",
               PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    env.pop("ENV", None)
    return home, public, private, env


def skill(root, name):
    path = root / name
    path.mkdir()
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test skill\n---\n")
    return path


def run(catalog, *args):
    return subprocess.run([str(SCRIPT), *args], env=catalog[3], capture_output=True,
                          text=True, timeout=30)


def test_all_discovers_both_roots_and_linked_skills_once(catalog, tmp_path):
    home, public, private, _ = catalog
    source = skill(public, "steps")
    skill(private, "1password")
    skill(private, "steps")
    external = skill(tmp_path, "external")
    (public / "linked").symlink_to(external, target_is_directory=True)
    skill(public, ".hidden")
    (public / "helpers").mkdir()
    before = run(catalog, "--check", "--all")
    assert before.returncode == 1
    assert not (home / ".agents").exists()
    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    assert applied.stdout.count("== steps\n") == 1
    links = home / ".agents" / "skills"
    assert sorted(p.name for p in links.iterdir()) == ["1password", "linked", "steps"]
    assert (links / "steps").readlink() == source
    assert (links / "1password").readlink() == private / "1password"
    assert (links / "linked" / "SKILL.md").is_file()
    checked = run(catalog, "--check", "--all")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked.stdout.rstrip().endswith("== end")
    assert "already linked" in run(catalog, "--all").stdout


def test_site_root_is_a_third_root_after_public_and_private(catalog, tmp_path):
    home, public, private, env = catalog
    site = tmp_path / "site skills"
    site.mkdir()
    env["SKILL_EVERYWHERE_SITE"] = str(site)
    moved = skill(site, "report")
    skill(site, "steps")
    source = skill(public, "steps")
    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    links = home / ".agents" / "skills"
    assert sorted(p.name for p in links.iterdir()) == ["report", "steps"]
    assert (links / "report").readlink() == moved
    assert (links / "steps").readlink() == source
    named = run(catalog, "--check", "report")
    assert named.returncode == 0 and "linked" in named.stdout
    missing = run(catalog, "--check", "nowhere")
    assert missing.returncode == 1 and str(site / "nowhere") in missing.stderr


def test_pi_only_links_shared_directory_without_native_duplicates(catalog):
    home, public, _, env = catalog
    source = skill(public, "steps")
    pi = Path(env["PATH"].split(os.pathsep)[0]) / "pi"
    pi.write_text("#!/bin/sh\nexit 0\n")
    pi.chmod(0o755)
    env["SKILL_EVERYWHERE_ONLY"] = "pi"
    assert run(catalog, "--check", "--all").returncode == 1
    result = run(catalog, "--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".agents/skills/steps").readlink() == source
    assert not (home / ".pi").exists()
    assert run(catalog, "--check", "--all").returncode == 0


def test_all_dry_run_is_read_only(catalog):
    home, public, _, _ = catalog
    skill(public, "steps")
    result = run(catalog, "--dry-run", "--all")
    assert result.returncode == 0 and "would link" in result.stdout
    assert not (home / ".agents").exists()


def test_foreign_content_is_preserved_and_all_check_fails(catalog):
    home, public, _, _ = catalog
    skill(public, "steps")
    foreign = home / ".agents" / "skills" / "steps"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("foreign skill")
    assert run(catalog, "--all").returncode == 1
    result = run(catalog, "--check", "--all")
    assert result.returncode == 1 and "not ours" in result.stdout
    assert (foreign / "SKILL.md").read_text() == "foreign skill"
    # Named checks retain the existing reporting contract used by ade-update.
    assert run(catalog, "--check", "steps").returncode == 0


def test_all_repairs_chained_and_dangling_links(catalog, tmp_path):
    home, public, _, _ = catalog
    source = skill(public, "steps")
    skill(public, "baton")
    hub = tmp_path / "hub"
    hub.symlink_to(source, target_is_directory=True)
    links = home / ".agents" / "skills"
    links.mkdir(parents=True)
    (links / "steps").symlink_to(hub, target_is_directory=True)
    (links / "baton").symlink_to(tmp_path / "gone")
    assert run(catalog, "--check", "--all").returncode == 1
    assert run(catalog, "--all").returncode == 0
    assert (links / "steps").readlink() == source
    assert (links / "baton").readlink() == public / "baton"
    assert run(catalog, "--check", "--all").returncode == 0


@pytest.mark.parametrize("args", [("--all", "steps"), ("--all", "--remove"), ("--remove", "--all")])
def test_all_rejects_names_or_bulk_removal_before_writing(catalog, args):
    home, public, _, _ = catalog
    skill(public, "steps")
    result = run(catalog, *args)
    assert result.returncode == 2
    assert not (home / ".agents").exists()


def test_all_empty_inventory_is_not_success(catalog):
    assert run(catalog, "--check", "--all").returncode == 2


def test_unsafe_discovered_name_fails_before_any_links(catalog):
    home, public, _, _ = catalog
    skill(public, "alpha")
    skill(public, "unsafe name")
    result = run(catalog, "--all")
    assert result.returncode == 2 and "unsafe skill directory" in result.stderr
    assert not (home / ".agents").exists()
