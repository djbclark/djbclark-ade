"""Bulk skill discovery and reconciliation, with isolated HOME and no live clients."""
import os
import shutil
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
    site = tmp_path / "site root"  # empty: a real OPS_ROOT must not leak the operator's site skills in
    site.mkdir()
    chrome = tmp_path / "chrome skills"
    chrome.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    codex = bindir / "codex"
    codex.write_text("#!/bin/sh\nexit 0\n")
    codex.chmod(0o755)
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"),
               BASH_ENV="/dev/null", SKILL_EVERYWHERE_ADE=str(public),
               SKILL_EVERYWHERE_PRIVATE=str(private), SKILL_EVERYWHERE_SITE=str(site),
               SKILL_EVERYWHERE_CHROME=str(chrome),
               SKILL_EVERYWHERE_ONLY="codex",
               SKILL_EVERYWHERE_BIN_DIR=str(bindir))
    env.pop("ENV", None)
    paseo_skill(home)  # a live client always has the Paseo-synced copy
    return home, public, private, env


def paseo_skill(home):
    """The Paseo daemon's synced copy and its marker, as in the real ~/.agents/skills/paseo."""
    path = home / ".agents" / "skills" / "paseo"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: paseo\ndescription: Paseo\n---\n")
    (path / ".paseo-managed-files.json").write_text('{"version": 1, "files": {}}\n')
    return path


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
    assert sorted(p.name for p in (home / ".agents" / "skills").iterdir()) == ["paseo"]
    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    assert applied.stdout.count("== steps\n") == 1
    links = home / ".agents" / "skills"
    assert sorted(p.name for p in links.iterdir()) == ["1password", "linked", "paseo", "steps"]
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
    assert sorted(p.name for p in links.iterdir()) == ["paseo", "report", "steps"]
    assert (links / "report").readlink() == moved
    assert (links / "steps").readlink() == source
    named = run(catalog, "--check", "report")
    assert named.returncode == 0 and "linked" in named.stdout
    missing = run(catalog, "--check", "nowhere")
    assert missing.returncode == 1 and str(site / "nowhere") in missing.stderr


def test_chrome_root_is_a_fourth_root_after_site(catalog):
    home, public, _, env = catalog
    chrome = Path(env["SKILL_EVERYWHERE_CHROME"])
    moved = skill(chrome, "real-chrome")
    source = skill(public, "real-chrome")
    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stderr + applied.stdout
    links = home / ".agents" / "skills"
    assert (links / "real-chrome").readlink() == source
    only = skill(chrome, "core")
    assert run(catalog, "--all").returncode == 0
    assert (links / "core").readlink() == only


def test_site_root_defaults_to_the_site_public_checkout(catalog):
    home, public, _, env = catalog
    env.pop("SKILL_EVERYWHERE_SITE", None)
    env.pop("OPS_ROOT", None)
    site = home / "ops" / "site-public-djbclark" / "skills"
    site.mkdir(parents=True)
    moved = skill(site, "report")
    assert run(catalog, "--all").returncode == 0
    assert (home / ".agents/skills/report").readlink() == moved


def test_check_all_warns_once_for_each_absent_root(catalog, tmp_path):
    _, public, _, env = catalog
    env["SKILL_EVERYWHERE_SITE"] = str(tmp_path / "no such root")
    skill(public, "steps")
    run(catalog, "--all")
    checked = run(catalog, "--check", "--all")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    warnings = [l for l in checked.stderr.splitlines() if l.startswith("warning: skill root")]
    assert warnings == [f"warning: skill root {tmp_path / 'no such root'} does not exist; its skills are not checked"]
    assert "warning: skill root" not in run(catalog, "--all").stderr


def test_remove_of_a_gone_site_skill_unlinks_the_site_link(catalog, tmp_path):
    home, _, _, env = catalog
    site = tmp_path / "site skills"
    site.mkdir()
    env["SKILL_EVERYWHERE_SITE"] = str(site)
    moved = skill(site, "report")
    assert run(catalog, "report").returncode == 0
    link = home / ".agents/skills/report"
    assert link.readlink() == moved
    (moved / "SKILL.md").unlink()
    moved.rmdir()
    result = run(catalog, "--remove", "report")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not link.is_symlink()


def test_grokbot_copy_names_the_root_it_came_from(catalog, tmp_path):
    home, public, _, env = catalog
    site = tmp_path / "site skills"
    site.mkdir()
    env["SKILL_EVERYWHERE_SITE"] = str(site)
    env["SKILL_EVERYWHERE_ONLY"] = "grokbot"
    (home / "agent-data" / "workflows").mkdir(parents=True)
    skill(site, "report")
    skill(public, "steps")
    assert run(catalog, "report", "steps").returncode == 0
    out = home / "agent-data" / "workflows"
    assert (out / "ade-report/.skill-everywhere").read_text().startswith("source=site-djbclark/skills/report\n")
    assert "djbclark/site-djbclark/tree/master/skills/report" in (out / "ade-report/SKILL.md").read_text()
    assert (out / "ade-steps/.skill-everywhere").read_text().startswith("source=djbclark-ade/skills/steps\n")
    assert "djbclark/djbclark-ade/tree/master/skills/steps" in (out / "ade-steps/SKILL.md").read_text()
    assert run(catalog, "--check", "report", "steps").stdout.count("copied (") == 2


STANDING = (
    "**On Grok Bot (Daniel, 2026-11-11):** do all AI work, coding included, in Grok Bot itself; "
    "ignore any routing here to agy/Gemini, Claude, OpenAI/Codex or acp-run TUIs unless Chief of Staff "
    "says Grok Bot usage is over pace."
)


def test_grokbot_banner_carries_standing_vendor_note_once(catalog, tmp_path):
    home, public, _, env = catalog
    env["SKILL_EVERYWHERE_ONLY"] = "grokbot"
    env["SKILL_EVERYWHERE_GROKBOT_NOTE"] = "Per-skill extra note."
    (home / "agent-data" / "workflows").mkdir(parents=True)
    skill(public, "steps")
    assert run(catalog, "steps").returncode == 0
    body = (home / "agent-data" / "workflows" / "ade-steps" / "SKILL.md").read_text()
    assert body.count(STANDING) == 1
    assert body.index(STANDING) < body.index("Per-skill extra note.")
    # Re-render is idempotent: a second run leaves the copy unchanged and reports already copied.
    again = run(catalog, "steps")
    assert again.returncode == 0 and "already copied" in again.stdout
    assert (home / "agent-data" / "workflows" / "ade-steps" / "SKILL.md").read_text() == body
    # Other targets are unaffected: a Codex link is the source file, which has no banner or note.
    env["SKILL_EVERYWHERE_ONLY"] = "codex"
    env.pop("SKILL_EVERYWHERE_GROKBOT_NOTE", None)
    assert run(catalog, "steps").returncode == 0
    source = (public / "steps" / "SKILL.md").read_text()
    linked = (home / ".agents" / "skills" / "steps" / "SKILL.md").read_text()
    assert STANDING not in source and STANDING not in linked
    assert linked == source


def test_grokbot_check_removes_mktemp_when_render_fails(catalog, tmp_path):  # PR 20 LOW e
    home, public, _, env = catalog
    env["SKILL_EVERYWHERE_ONLY"] = "grokbot"
    (home / "agent-data" / "workflows").mkdir(parents=True)
    skill(public, "steps")
    assert run(catalog, "steps").returncode == 0  # managed copy present so --check renders to compare
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    mktemp_log = tmp_path / "mktemp.log"
    real_mktemp = subprocess.check_output(["bash", "-lc", "command -v mktemp"], text=True).strip()
    (bindir / "mktemp").write_text(
        f"#!/bin/sh\nd=$({real_mktemp} -d)\nprintf '%s\\n' \"$d\" >>{mktemp_log}\nprintf '%s\\n' \"$d\"\n"
    )
    (bindir / "mktemp").chmod(0o755)
    # render_copy must fail after cp. A fake gawk on PATH does not do it on a Mac: bin/skill-everywhere prepends /opt/homebrew/bin,
    # so the real Homebrew gawk wins and the render succeeds (the Linux CI has no such directory). A directory named SKILL.md.new in
    # the source makes the script's own `>"$2/SKILL.md.new"` redirect fail, on any platform and for root too.
    (public / "steps" / "SKILL.md.new").mkdir()
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    result = run(catalog, "--check", "steps")
    # Named --check stays exit 0 for a stale/failed render (only --all raises rc); the leak fix is the mktemp rm.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stale copy" in result.stdout and "render for" in result.stderr
    dirs = [Path(line) for line in mktemp_log.read_text().splitlines() if line]
    assert dirs and all(not d.exists() for d in dirs), dirs


def test_all_dry_run_is_read_only(catalog):
    home, public, _, _ = catalog
    skill(public, "steps")
    result = run(catalog, "--dry-run", "--all")
    assert result.returncode == 0 and "would link" in result.stdout
    assert sorted(p.name for p in (home / ".agents" / "skills").iterdir()) == ["paseo"]


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
    assert sorted(p.name for p in (home / ".agents" / "skills").iterdir()) == ["paseo"]


def test_all_empty_inventory_is_not_success(catalog):
    assert run(catalog, "--check", "--all").returncode == 2


def test_unsafe_discovered_name_fails_before_any_links(catalog):
    home, public, _, _ = catalog
    skill(public, "alpha")
    skill(public, "unsafe name")
    result = run(catalog, "--all")
    assert result.returncode == 2 and "unsafe skill directory" in result.stderr
    assert sorted(p.name for p in (home / ".agents" / "skills").iterdir()) == ["paseo"]


def _default_root_env(home: Path, tmp_path: Path) -> dict:
    """HOME isolated; no SKILL_EVERYWHERE_ADE; private/site roots cannot leak the operator's."""
    env = dict(os.environ, HOME=str(home), BASH_ENV="/dev/null",
               SKILL_EVERYWHERE_PRIVATE=str(tmp_path / "none-private"),
               SKILL_EVERYWHERE_SITE=str(tmp_path / "none-site"),
               SKILL_EVERYWHERE_CHROME=str(tmp_path / "none-chrome"),
               SKILL_EVERYWHERE_ONLY="nonesuch")
    env.pop("SKILL_EVERYWHERE_ADE", None)
    env.pop("ENV", None)
    return env


def test_default_root_resolves_from_symlinked_script(tmp_path):
    """No SKILL_EVERYWHERE_ADE and no ~/src/djbclark-ade: the repo of the script's real path is used."""
    home = tmp_path / "home"
    home.mkdir()
    link = tmp_path / "linkdir" / "skill-everywhere"
    link.parent.mkdir()
    link.symlink_to(SCRIPT)
    r = subprocess.run([str(link), "--check", "no-such-skill-xyz"], env=_default_root_env(home, tmp_path),
                       capture_output=True, text=True, timeout=30)
    root = SCRIPT.resolve().parents[1]
    common = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    if common.endswith("/.git") and Path(common).parent != root and (Path(common).parent / "bin/skill-everywhere").is_file():
        root = Path(common).parent        # the suite runs from a linked worktree: the script resolves its primary checkout
    expected = root / "skills" / "no-such-skill-xyz"
    assert str(expected.parent) in r.stderr, r.stderr
    assert str(home) not in r.stderr


def test_default_root_from_linked_worktree_uses_primary_checkout(tmp_path):
    """Run from a linked worktree, the default root is the primary checkout's skills/ (a worktree is removed after
    its merge, so links into it would dangle)."""
    primary = tmp_path / "primary"
    (primary / "bin").mkdir(parents=True)
    (primary / "skills").mkdir()
    (primary / "skills" / ".keep").write_text("")
    shutil.copy2(SCRIPT, primary / "bin" / "skill-everywhere")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "init"],
                 ["worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt"]):
        subprocess.run([*git, *argv], cwd=primary, check=True, capture_output=True)
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run([str(tmp_path / "wt" / "bin" / "skill-everywhere"), "--check", "no-such-skill-xyz"],
                       env=_default_root_env(home, tmp_path), capture_output=True, text=True, timeout=30)
    assert str(primary.resolve() / "skills") in r.stderr, r.stderr
    assert str(tmp_path / "wt" / "skills") not in r.stderr


def test_canonical_checkout_wins_when_it_exists(tmp_path):
    """With ~/src/djbclark-ade present, its skills/ is the default even when the script runs from another checkout
    (a second clone must not report false gaps or link into a removable copy; adversary on PR 292)."""
    home = tmp_path / "home"
    canon = home / "src" / "djbclark-ade"
    (canon / "bin").mkdir(parents=True)
    (canon / "skills").mkdir()
    (canon / "bin" / "skill-everywhere").write_text("")
    r = subprocess.run([str(SCRIPT), "--check", "no-such-skill-xyz"], env=_default_root_env(home, tmp_path),
                       capture_output=True, text=True, timeout=30)
    assert str(canon / "skills") in r.stderr, r.stderr


# --- Paseo's skill in Hermes (2026-11-21) and foreign dirs of third-party skills ---------------------------------

def hermes_env(catalog, tmp_path, installed=True):
    """Target only Hermes; SKILL_EVERYWHERE_BIN_DIR isolates client binary lookup without rewriting PATH."""
    env = catalog[3]
    bindir = tmp_path / "bin"
    env["SKILL_EVERYWHERE_ONLY"] = "hermes"
    env["SKILL_EVERYWHERE_BIN_DIR"] = str(bindir)
    if installed:
        fake = bindir / "hermes"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
    return catalog[0] / ".local" / "share" / "skill-everywhere" / "skills"


def snapshot(path):
    return {p.relative_to(path): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_paseo_skill_is_linked_into_hermes_and_paseo_files_are_untouched(catalog, tmp_path):
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    source = home / ".agents" / "skills" / "paseo"
    before = snapshot(source)
    result = run(catalog, "steps")
    assert result.returncode == 0, result.stderr + result.stdout
    assert (hermes / "paseo").is_symlink() and (hermes / "paseo").readlink() == source
    assert (hermes / "paseo" / "SKILL.md").is_file()
    assert snapshot(source) == before and not source.is_symlink()


def test_paseo_link_is_idempotent(catalog, tmp_path):
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    assert run(catalog, "steps").returncode == 0
    again = run(catalog, "steps")
    assert again.returncode == 0, again.stderr + again.stdout
    assert "== paseo" in again.stdout and again.stdout.split("== paseo", 1)[1].count("already linked") == 1
    assert "linked\n" not in again.stdout.split("== paseo", 1)[1].replace("already linked", "")
    assert (hermes / "paseo").readlink() == home / ".agents" / "skills" / "paseo"


def test_paseo_foreign_real_dir_at_the_hermes_target_is_left_alone(catalog, tmp_path):
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    foreign = hermes / "paseo"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("someone else's paseo")
    result = run(catalog, "steps")
    assert result.returncode == 1
    assert "not ours" in result.stdout and "left alone" in result.stdout
    assert not foreign.is_symlink() and (foreign / "SKILL.md").read_text() == "someone else's paseo"
    assert snapshot(foreign) == {Path("SKILL.md"): b"someone else's paseo"}


def test_paseo_missing_source_makes_no_dangling_link(catalog, tmp_path):
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    shutil.rmtree(home / ".agents" / "skills" / "paseo")
    result = run(catalog, "steps")
    assert result.returncode == 1
    assert "paseo skill source" in result.stderr and "missing" in result.stderr
    assert not os.path.lexists(hermes / "paseo")


def test_check_fails_loudly_when_paseo_is_missing_from_a_live_target(catalog, tmp_path):
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    failed = run(catalog, "--check", "steps")
    assert failed.returncode == 1
    assert "error: paseo skill is missing on hermes" in failed.stderr
    assert failed.stdout.rstrip().endswith("== end")
    assert run(catalog, "steps").returncode == 0
    assert run(catalog, "--check", "steps").returncode == 0
    # a dangling link counts as missing too
    shutil.rmtree(home / ".agents" / "skills" / "paseo")
    dangling = run(catalog, "--check", "steps")
    assert dangling.returncode == 1 and "dangling" in dangling.stderr
    # the Codex/Pi target, which Paseo's own daemon fills, fails the same way
    catalog[3]["SKILL_EVERYWHERE_ONLY"] = "codex"
    codex = run(catalog, "--check", "steps")
    assert codex.returncode == 1 and "error: paseo skill is missing on codex" in codex.stderr


def test_check_ignores_paseo_for_a_client_that_is_not_installed(catalog, tmp_path):
    hermes_env(catalog, tmp_path, installed=False)
    skill(catalog[1], "steps")
    result = run(catalog, "--check", "steps")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "error:" not in result.stderr


def test_foreign_dir_of_a_third_party_skill_is_a_note_not_an_error(catalog):
    home, public, _, env = catalog
    chrome = Path(env["SKILL_EVERYWHERE_CHROME"])
    skill(chrome, "canvas")
    skill(public, "steps")
    foreign = home / ".agents" / "skills" / "canvas"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("installed by another tool")
    result = run(catalog, "--all")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "third-party skill: a note, not an error" in result.stdout
    assert not foreign.is_symlink() and (foreign / "SKILL.md").read_text() == "installed by another tool"
    assert (home / ".agents" / "skills" / "steps").is_symlink()  # the rest of the run still links
    checked = run(catalog, "--check", "--all")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "not ours; third-party skill, left alone" in checked.stdout


def test_foreign_dir_at_the_name_of_our_own_skill_stays_an_error(catalog):
    home, public, _, env = catalog
    chrome = Path(env["SKILL_EVERYWHERE_CHROME"])
    skill(chrome, "canvas")
    skill(public, "steps")
    foreign = home / ".agents" / "skills" / "steps"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("foreign")
    foreign_canvas = home / ".agents" / "skills" / "canvas"
    foreign_canvas.mkdir()
    result = run(catalog, "--all")
    assert result.returncode == 1  # steps collides; canvas alone would not
    assert (foreign / "SKILL.md").read_text() == "foreign"


def test_paseo_as_a_name_runs_only_the_paseo_step(catalog, tmp_path):  # ade-update's fix command for a missing hermes link
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    failed = run(catalog, "--check", "paseo")
    assert failed.returncode == 1 and "error: paseo skill is missing on hermes" in failed.stderr
    assert failed.stdout.strip().splitlines() == ["== end"]
    linked = run(catalog, "paseo")
    assert linked.returncode == 0, linked.stdout + linked.stderr
    assert "no SKILL.md" not in linked.stderr and "== steps" not in linked.stdout
    assert (hermes / "paseo").readlink() == home / ".agents" / "skills" / "paseo"
    assert not (hermes / "steps").exists()  # only the paseo step ran
    assert run(catalog, "--check", "paseo").returncode == 0


def test_remove_paseo_removes_only_our_hermes_link_and_other_removes_leave_it(catalog, tmp_path):  # PR 874 adversary low
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    source = home / ".agents" / "skills" / "paseo"
    before = snapshot(source)
    assert run(catalog, "steps").returncode == 0 and (hermes / "paseo").is_symlink()
    other = run(catalog, "--remove", "steps")
    assert other.returncode == 0 and (hermes / "paseo").is_symlink() and "== paseo" not in other.stdout
    dry = run(catalog, "--dry-run", "--remove", "paseo")
    assert dry.returncode == 0 and "would remove" in dry.stdout and (hermes / "paseo").is_symlink()
    removed = run(catalog, "--remove", "paseo")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "removed" in removed.stdout and not os.path.lexists(hermes / "paseo")
    assert snapshot(source) == before  # the Paseo-managed copy is never touched
    again = run(catalog, "--remove", "paseo")
    assert again.returncode == 0 and "left alone" in again.stdout
    foreign = hermes / "paseo"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("foreign")
    kept = run(catalog, "--remove", "paseo")
    assert kept.returncode == 0 and "left alone" in kept.stdout and (foreign / "SKILL.md").read_text() == "foreign"


def test_remove_paseo_removes_our_link_even_when_it_dangles(catalog, tmp_path):  # PR 878 adversary low 1
    home, public, _, _ = catalog
    hermes = hermes_env(catalog, tmp_path)
    skill(public, "steps")
    assert run(catalog, "steps").returncode == 0
    shutil.rmtree(home / ".agents" / "skills" / "paseo")  # Paseo's copy is gone: the link now dangles
    assert (hermes / "paseo").is_symlink() and not (hermes / "paseo").exists()
    removed = run(catalog, "--remove", "paseo")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "removed" in removed.stdout and "left alone" not in removed.stdout
    assert not os.path.lexists(hermes / "paseo")
    # a dangling link that is NOT ours (another target) stays
    (hermes / "paseo").symlink_to(tmp_path / "elsewhere")
    kept = run(catalog, "--remove", "paseo")
    assert kept.returncode == 0 and "left alone" in kept.stdout and (hermes / "paseo").is_symlink()


# --- Retired skill cleanup and /self-handoff split (2026-11-24) -------------------------------------------------

def test_retired_handoff_skills_cleaned_across_targets_and_gemini(catalog, tmp_path):
    """Link mode removes stale symlinks (and Grok Bot managed copies) for retired skills while preserving foreign entries."""
    home, public, _, env = catalog
    bindir = tmp_path / "bin"
    for cli in ("claude", "hermes"):
        fake = bindir / cli
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
    env["SKILL_EVERYWHERE_ONLY"] = ""
    env["SKILL_EVERYWHERE_BIN_DIR"] = str(bindir)
    # Paseo skill must exist for claude and hermes too so --check --all can go green after cleanup.
    for pdir in (home / ".claude" / "skills" / "paseo",):
        pdir.mkdir(parents=True)
        (pdir / "SKILL.md").write_text("---\nname: paseo\ndescription: Paseo\n---\n")

    skill(public, "self-handoff")
    skill(public, "handoff")
    skill(public, "hand")

    claude_dir = home / ".claude" / "skills"
    agents_dir = home / ".agents" / "skills"
    hermes_dir = home / ".local" / "share" / "skill-everywhere" / "skills"
    gemini_dir = home / ".gemini" / "skills"
    grok_dir = home / "agent-data" / "workflows"
    for d in (claude_dir, agents_dir, hermes_dir, gemini_dir, grok_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Stale symlinks pointing into our public root (now gone) across all dirs.
    for d in (claude_dir, agents_dir, hermes_dir, gemini_dir):
        (d / "old-handoff-use-paseo-handoff").symlink_to(public / "old-handoff-use-paseo-handoff")
        (d / "old-hand-use-paseo-handoff").symlink_to(public / "old-hand-use-paseo-handoff")

    # Managed Grok Bot copy of a retired skill should also be removed.
    grok_copy = grok_dir / "ade-old-handoff-use-paseo-handoff"
    grok_copy.mkdir()
    (grok_copy / ".skill-everywhere").write_text("source=djbclark-ade/skills/old-handoff-use-paseo-handoff\n")
    (grok_copy / "SKILL.md").write_text("---\nname: old-handoff-use-paseo-handoff\n---\n")

    # Foreign Grok Bot dir without .skill-everywhere marker must stay untouched.
    foreign_grok = grok_dir / "ade-old-hand-use-paseo-handoff"
    foreign_grok.mkdir()
    (foreign_grok / "SKILL.md").write_text("foreign copy")

    # paseo-only invocation must NOT touch retired links (F5).
    paseo_only = run(catalog, "paseo")
    assert paseo_only.returncode == 0, paseo_only.stdout + paseo_only.stderr
    assert "== retired skills" not in paseo_only.stdout
    assert (claude_dir / "old-handoff-use-paseo-handoff").is_symlink()
    assert (gemini_dir / "old-handoff-use-paseo-handoff").is_symlink()

    # Named --check (used by bin/ade-update) must NOT emit retired-link warnings or set exit 1 (F5).
    named_chk = run(catalog, "--check", "self-handoff")
    assert named_chk.returncode == 0, named_chk.stdout + named_chk.stderr
    assert "retired skill" not in named_chk.stderr
    assert named_chk.stdout.rstrip().endswith("== end")

    # --dry-run --all previews removal without deleting anything.
    dry = run(catalog, "--dry-run", "--all")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "would remove retired" in dry.stdout
    assert (gemini_dir / "old-handoff-use-paseo-handoff").is_symlink()
    assert grok_copy.is_dir()

    # --check --all fails with warnings while retired links remain (no duplicate scan of ~/.gemini/skills).
    chk_before = run(catalog, "--check", "--all")
    assert chk_before.returncode == 1
    assert "retired skill link still present" in chk_before.stderr
    assert "retired skill copy still present" in chk_before.stderr
    assert chk_before.stderr.count(str(gemini_dir / "old-handoff-use-paseo-handoff")) == 1
    assert chk_before.stderr.count(str(gemini_dir / "old-hand-use-paseo-handoff")) == 1

    # Link mode installs self-handoff/handoff/hand (including into ~/.gemini/skills) and removes all our retired links + managed copy.
    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "== retired skills" in applied.stdout
    assert applied.stdout.count(str(gemini_dir / "old-handoff-use-paseo-handoff")) == 1
    assert applied.stdout.count(str(gemini_dir / "old-hand-use-paseo-handoff")) == 1
    for d in (claude_dir, agents_dir, hermes_dir, gemini_dir):
        assert (d / "self-handoff").readlink() == public / "self-handoff"
        assert (d / "handoff").readlink() == public / "handoff"
        assert (d / "hand").readlink() == public / "hand"
    for d in (claude_dir, agents_dir, hermes_dir, gemini_dir):
        assert not os.path.lexists(d / "old-handoff-use-paseo-handoff")
        assert not os.path.lexists(d / "old-hand-use-paseo-handoff")
    assert not grok_copy.exists()
    assert (foreign_grok / "SKILL.md").read_text() == "foreign copy"

    # Subsequent --check --all passes and rerun --all is quiet/idempotent on retired skills.
    chk_after = run(catalog, "--check", "--all")
    assert chk_after.returncode == 0, chk_after.stdout + chk_after.stderr
    rerun = run(catalog, "--all")
    assert rerun.returncode == 0 and "== retired skills" not in rerun.stdout


def test_retired_grokbot_symlinked_marker_is_never_removed(catalog, tmp_path):
    """F2: a real dir whose .skill-everywhere is a symlink to a regular file is ignored and never rm -rf'd."""
    home, public, _, env = catalog
    env["SKILL_EVERYWHERE_ONLY"] = "grokbot"
    grok_dir = home / "agent-data" / "workflows"
    grok_dir.mkdir(parents=True)
    skill(public, "steps")
    assert run(catalog, "steps").returncode == 0

    real_file = tmp_path / "regular-sentinel.txt"
    real_file.write_text("not a marker\n")
    tricked = grok_dir / "ade-old-handoff-use-paseo-handoff"
    tricked.mkdir()
    (tricked / ".skill-everywhere").symlink_to(real_file)
    (tricked / "keep.txt").write_text("preserve me")

    chk = run(catalog, "--check", "--all")
    assert chk.returncode == 0, chk.stdout + chk.stderr
    assert "retired skill copy" not in chk.stderr

    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "== retired skills" not in applied.stdout
    assert tricked.is_dir() and (tricked / "keep.txt").read_text() == "preserve me"
    assert real_file.read_text() == "not a marker\n"


def test_retired_cleanup_leaves_foreign_links_real_dirs_and_live_root_skills(catalog, tmp_path):
    """Foreign symlinks, real directories, and names still present in a root are never removed."""
    home, public, _, _ = catalog
    skill(public, "steps")
    agents_dir = home / ".agents" / "skills"
    foreign_link = agents_dir / "old-handoff-use-paseo-handoff"
    foreign_link.symlink_to(tmp_path / "someone-else")
    foreign_dir = agents_dir / "old-hand-use-paseo-handoff"
    foreign_dir.mkdir()
    (foreign_dir / "SKILL.md").write_text("foreign real dir")

    res = run(catalog, "--all")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "== retired skills" not in res.stdout
    assert foreign_link.is_symlink() and foreign_link.readlink() == tmp_path / "someone-else"
    assert foreign_dir.is_dir() and not foreign_dir.is_symlink()

    # If a root still ships a live SKILL.md under a retired name, it is linked, never removed.
    foreign_link.unlink()
    live = skill(public, "old-handoff-use-paseo-handoff")
    res2 = run(catalog, "--all")
    assert res2.returncode == 0, res2.stdout + res2.stderr
    assert (agents_dir / "old-handoff-use-paseo-handoff").readlink() == live


def test_repo_self_handoff_split_and_deprecation_aliases(catalog):
    """Real repo layout: self-handoff exists, old-* retired and cleaned, handoff/hand alias paseo-handoff."""
    repo = SCRIPT.resolve().parents[1]
    skills_dir = repo / "skills"
    assert (skills_dir / "self-handoff" / "SKILL.md").is_file()
    assert not (skills_dir / "old-handoff-use-paseo-handoff").exists()
    assert not (skills_dir / "old-hand-use-paseo-handoff").exists()

    for alias in ("handoff", "hand"):
        p = skills_dir / alias / "SKILL.md"
        assert p.is_file() and not p.is_symlink() and not p.parent.is_symlink()
        text = p.read_text(encoding="utf-8")
        assert f"name: {alias}\n" in text
        assert "paseo-handoff" in text
        assert "/self-handoff" in text
        assert "old-handoff-use-paseo-handoff" not in text
        assert "old-hand-use-paseo-handoff" not in text

    loose_text = (skills_dir / "loose" / "SKILL.md").read_text(encoding="utf-8")
    assert "self-handoff" in loose_text
    assert "the `handoff` skill" not in loose_text

    # Run bin/skill-everywhere --all against the real repo skills/ into isolated HOME.
    home, _, _, env = catalog
    env["SKILL_EVERYWHERE_ADE"] = str(skills_dir)
    agents_dir = home / ".agents" / "skills"
    gemini_dir = home / ".gemini" / "skills"
    gemini_dir.mkdir(parents=True)
    for d in (agents_dir, gemini_dir):
        (d / "old-handoff-use-paseo-handoff").symlink_to(skills_dir / "old-handoff-use-paseo-handoff")
        (d / "old-hand-use-paseo-handoff").symlink_to(skills_dir / "old-hand-use-paseo-handoff")
    env["SKILL_EVERYWHERE_ONLY"] = "codex,gemini"
    res = run(catalog, "--all")
    assert res.returncode == 0, res.stdout + res.stderr
    for d in (agents_dir, gemini_dir):
        assert (d / "self-handoff").readlink() == skills_dir / "self-handoff"
        assert (d / "handoff").readlink() == skills_dir / "handoff"
        assert (d / "hand").readlink() == skills_dir / "hand"
        assert not os.path.lexists(d / "old-handoff-use-paseo-handoff")
        assert not os.path.lexists(d / "old-hand-use-paseo-handoff")


# --- First-class gemini (~/.gemini/skills) target (2026-11-24) --------------------------------------------------

def test_gemini_target_detected_via_dot_gemini_dir_without_cli(catalog, tmp_path):
    """Antigravity runs without a gemini/antigravity binary on PATH: ~/.gemini dir enables linking/checking/removal."""
    home, public, _, env = catalog
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env["SKILL_EVERYWHERE_ONLY"] = "gemini"
    env["SKILL_EVERYWHERE_BIN_DIR"] = str(empty_bin)
    src = skill(public, "self-handoff")

    # Neither ~/.gemini dir nor CLI binary: treated as not installed; link mode creates nothing.
    chk_absent = run(catalog, "--check", "--all")
    assert chk_absent.returncode == 0, chk_absent.stdout + chk_absent.stderr
    assert "gemini" in chk_absent.stdout and "not installed" in chk_absent.stdout
    assert chk_absent.stdout.rstrip().endswith("== end")
    assert run(catalog, "--all").returncode == 0
    assert not (home / ".gemini").exists()

    # A plain file at ~/.gemini is not a directory: still not installed.
    (home / ".gemini").write_text("not a dir\n")
    chk_file = run(catalog, "--check", "--all")
    assert chk_file.returncode == 0 and "not installed" in chk_file.stdout
    (home / ".gemini").unlink()

    # Creating ~/.gemini enables the target even with no binary in SKILL_EVERYWHERE_BIN_DIR.
    (home / ".gemini").mkdir()
    chk_missing = run(catalog, "--check", "--all")
    assert chk_missing.returncode == 1
    assert "gemini" in chk_missing.stdout and "missing" in chk_missing.stdout
    assert "paseo skill is" not in chk_missing.stderr  # Paseo syncs ~/.gemini/config/skills/paseo, not ~/.gemini/skills/paseo

    linked = run(catalog, "--all")
    assert linked.returncode == 0, linked.stdout + linked.stderr
    link = home / ".gemini" / "skills" / "self-handoff"
    assert link.is_symlink() and link.readlink() == src

    chk_ok = run(catalog, "--check", "--all")
    assert chk_ok.returncode == 0, chk_ok.stdout + chk_ok.stderr
    assert "linked" in chk_ok.stdout and chk_ok.stdout.rstrip().endswith("== end")

    again = run(catalog, "--all")
    assert again.returncode == 0 and "already linked" in again.stdout

    removed = run(catalog, "--remove", "self-handoff")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "removed" in removed.stdout and not os.path.lexists(link)


@pytest.mark.parametrize("cli_name", ["gemini", "antigravity"])
def test_gemini_target_detected_via_cli_binary_in_bin_dir(catalog, tmp_path, cli_name):
    """A gemini or antigravity binary in SKILL_EVERYWHERE_BIN_DIR enables linking even before ~/.gemini exists."""
    home, public, _, env = catalog
    bindir = tmp_path / f"bin-{cli_name}"
    bindir.mkdir()
    fake = bindir / cli_name
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    env["SKILL_EVERYWHERE_ONLY"] = "gemini"
    env["SKILL_EVERYWHERE_BIN_DIR"] = str(bindir)
    src = skill(public, "steps")
    assert not (home / ".gemini").exists()

    chk = run(catalog, "--check", "--all")
    assert chk.returncode == 1 and "missing" in chk.stdout

    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    link = home / ".gemini" / "skills" / "steps"
    assert link.is_symlink() and link.readlink() == src
    assert run(catalog, "--check", "--all").returncode == 0


def test_gemini_only_retired_cleanup_runs_once_without_duplicates(catalog, tmp_path):
    """SKILL_EVERYWHERE_ONLY=gemini scans ~/.gemini/skills once for retired links and preserves foreign entries."""
    home, public, _, env = catalog
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    env["SKILL_EVERYWHERE_ONLY"] = "gemini"
    env["SKILL_EVERYWHERE_BIN_DIR"] = str(empty_bin)
    src = skill(public, "self-handoff")

    gemini_dir = home / ".gemini" / "skills"
    gemini_dir.mkdir(parents=True)
    retired_link = gemini_dir / "old-handoff-use-paseo-handoff"
    retired_link.symlink_to(public / "old-handoff-use-paseo-handoff")
    foreign_link = gemini_dir / "old-hand-use-paseo-handoff"
    foreign_link.symlink_to(tmp_path / "someone-else")

    chk = run(catalog, "--check", "--all")
    assert chk.returncode == 1
    assert chk.stderr.count(str(retired_link)) == 1
    assert str(foreign_link) not in chk.stderr

    applied = run(catalog, "--all")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert applied.stdout.count(str(retired_link)) == 1
    assert not os.path.lexists(retired_link)
    assert foreign_link.is_symlink() and foreign_link.readlink() == tmp_path / "someone-else"
    assert (gemini_dir / "self-handoff").readlink() == src
    assert run(catalog, "--check", "--all").returncode == 0


def test_tendcf_stage0_dual_read_skill_roots_and_fail_closed_fallback(catalog, tmp_path):
    """Queue #123 / Finding 2: dual-read active tendcf site pair, fail-closed fallback, and bidirectional transition reconciliation."""
    home, public, _, env = catalog
    env.pop("SKILL_EVERYWHERE_PRIVATE", None)
    env.pop("SKILL_EVERYWHERE_SITE", None)
    env.pop("OPS_ROOT", None)
    env.pop("TENDCF_SITE", None)
    env.pop("TENDCF_OPS_ROOT", None)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["SKILL_EVERYWHERE_ONLY"] = "codex,grokbot"
    grok_dir = home / "agent-data" / "workflows"
    grok_dir.mkdir(parents=True)

    troot = home / "tendcf-ops"
    tpriv = troot / "tendcf-private-acme" / "skills"
    tpub = troot / "tendcf-public-acme" / "skills"
    tpriv.mkdir(parents=True)
    tpub.mkdir(parents=True)
    tpriv_skill = skill(tpriv, "priv-tendcf")
    tpub_skill = skill(tpub, "pub-tendcf")
    tshared_skill = skill(tpub, "shared-site")

    lpriv = home / "ops" / "site-private" / "skills"
    lsite = home / "ops" / "site-public-djbclark" / "skills"
    lpriv.mkdir(parents=True)
    lsite.mkdir(parents=True)
    lpriv_skill = skill(lpriv, "legacy-priv")
    lsite_skill = skill(lsite, "legacy-site")
    lshared_skill = skill(lsite, "shared-site")

    # Truly foreign entries must NEVER be touched across transitions.
    links = home / ".agents" / "skills"
    foreign_target = tmp_path / "outside-foreign" / "foreign-skill"
    foreign_target.mkdir(parents=True)
    (links / "foreign-skill").symlink_to(foreign_target)
    foreign_grok = grok_dir / "ade-foreign-only"
    foreign_grok.mkdir()
    (foreign_grok / "SKILL.md").write_text("foreign grok skill\n")

    # 1. Without selector, sole tendcf-ops pair is NOT globbed -> legacy ~/ops roots win.
    r_legacy = run(catalog, "--all")
    assert r_legacy.returncode == 0, r_legacy.stdout + r_legacy.stderr
    assert (links / "legacy-priv").readlink() == lpriv_skill
    assert (links / "legacy-site").readlink() == lsite_skill
    assert (links / "shared-site").readlink() == lshared_skill
    assert not (links / "priv-tendcf").exists()
    assert not (links / "pub-tendcf").exists()
    assert (grok_dir / "ade-legacy-site" / ".skill-everywhere").read_text().startswith("source=site-djbclark/skills/legacy-site\n")
    assert (grok_dir / "ade-shared-site" / ".skill-everywhere").read_text().startswith("source=site-djbclark/skills/shared-site\n")
    assert run(catalog, "--check", "--all").returncode == 0

    # 2. Transition legacy -> tendcf via XDG active-site:
    #    --check --all MUST fail (migrating same-name + stale old-site-only links & Grok Bot copies).
    active_cfg = tmp_path / "xdg" / "tendcf" / "active-site"
    active_cfg.parent.mkdir(parents=True)
    active_cfg.write_text("acme\n", encoding="utf-8")
    chk_to_tendcf = run(catalog, "--check", "--all")
    assert chk_to_tendcf.returncode == 1
    assert "migrating from" in chk_to_tendcf.stdout
    assert "stale site skill link still present" in chk_to_tendcf.stderr
    assert "stale site skill copy still present" in chk_to_tendcf.stderr
    assert "foreign-skill" not in chk_to_tendcf.stderr

    #    --all relinks same-name, installs tendcf-only, removes legacy-only links & copies, preserves foreign.
    r_tendcf = run(catalog, "--all")
    assert r_tendcf.returncode == 0, r_tendcf.stdout + r_tendcf.stderr
    assert (links / "priv-tendcf").readlink() == tpriv_skill.resolve()
    assert (links / "pub-tendcf").readlink() == tpub_skill.resolve()
    assert (links / "shared-site").readlink() == tshared_skill.resolve()
    assert not os.path.lexists(links / "legacy-priv")
    assert not os.path.lexists(links / "legacy-site")
    assert not (grok_dir / "ade-legacy-priv").exists()
    assert not (grok_dir / "ade-legacy-site").exists()
    assert (grok_dir / "ade-pub-tendcf" / ".skill-everywhere").read_text().startswith("source=tendcf-public-acme/skills/pub-tendcf\n")
    assert (grok_dir / "ade-shared-site" / ".skill-everywhere").read_text().startswith("source=tendcf-public-acme/skills/shared-site\n")
    assert (links / "foreign-skill").readlink() == foreign_target
    assert (foreign_grok / "SKILL.md").read_text() == "foreign grok skill\n"
    assert run(catalog, "--check", "--all").returncode == 0

    # 3. Transition tendcf -> legacy (remove active-site):
    #    --check --all MUST fail again on migrating same-name + stale tendcf-only links & copies.
    active_cfg.unlink()
    chk_to_legacy = run(catalog, "--check", "--all")
    assert chk_to_legacy.returncode == 1
    assert "migrating from" in chk_to_legacy.stdout
    assert "stale site skill link still present" in chk_to_legacy.stderr
    assert "stale site skill copy still present" in chk_to_legacy.stderr

    r_back = run(catalog, "--all")
    assert r_back.returncode == 0, r_back.stdout + r_back.stderr
    assert (links / "legacy-priv").readlink() == lpriv_skill
    assert (links / "legacy-site").readlink() == lsite_skill
    assert (links / "shared-site").readlink() == lshared_skill
    assert not os.path.lexists(links / "priv-tendcf")
    assert not os.path.lexists(links / "pub-tendcf")
    assert not (grok_dir / "ade-priv-tendcf").exists()
    assert not (grok_dir / "ade-pub-tendcf").exists()
    assert (grok_dir / "ade-shared-site" / ".skill-everywhere").read_text().startswith("source=site-djbclark/skills/shared-site\n")
    assert (links / "foreign-skill").readlink() == foreign_target
    assert (foreign_grok / "SKILL.md").read_text() == "foreign grok skill\n"
    assert run(catalog, "--check", "--all").returncode == 0


def test_manually_installed_link_to_inactive_valid_site_layout_is_preserved(catalog, tmp_path):
    """Round 3 MEDIUM #2: a manually installed link to another syntactically valid inactive site is never removed or replaced."""
    home, public, _, env = catalog
    env.pop("SKILL_EVERYWHERE_PRIVATE", None)
    env.pop("SKILL_EVERYWHERE_SITE", None)
    env.pop("OPS_ROOT", None)
    env.pop("TENDCF_SITE", None)
    env.pop("TENDCF_OPS_ROOT", None)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["SKILL_EVERYWHERE_ONLY"] = "codex"

    # Active legacy roots.
    lpriv = home / "ops" / "site-private" / "skills"
    lsite = home / "ops" / "site-public-djbclark" / "skills"
    lpriv.mkdir(parents=True)
    lsite.mkdir(parents=True)
    skill(lpriv, "legacy-priv")
    skill(lsite, "active-site-skill")

    # Another syntactically valid inactive tendcf site that skill-everywhere never managed.
    inactive_pub = home / "tendcf-ops" / "tendcf-public-other" / "skills"
    inactive_pub.mkdir(parents=True)
    manual_only_src = skill(inactive_pub, "manual-inactive-skill")
    manual_collide_src = skill(inactive_pub, "active-site-skill")

    links = home / ".agents" / "skills"
    # 1. Manually installed link to an inactive-site-only skill: routine --all and --check --all MUST preserve it silently.
    (links / "manual-inactive-skill").symlink_to(manual_only_src)
    r_all = run(catalog, "--all")
    assert r_all.returncode == 0, r_all.stdout + r_all.stderr
    assert (links / "manual-inactive-skill").readlink() == manual_only_src
    r_chk = run(catalog, "--check", "--all")
    assert r_chk.returncode == 0, r_chk.stdout + r_chk.stderr
    assert "manual-inactive-skill" not in r_chk.stderr

    # 2. Manually installed link to an inactive site with the SAME name as an active skill:
    #    MUST be treated as a foreign link (`other link -> ...`, left alone, exit 1), NEVER silently replaced!
    (links / "active-site-skill").unlink()
    (links / "active-site-skill").symlink_to(manual_collide_src)
    r_collide = run(catalog, "--all")
    assert r_collide.returncode == 1
    assert "other link ->" in r_collide.stdout
    assert "migrating from" not in r_collide.stdout
    assert (links / "active-site-skill").readlink() == manual_collide_src


def test_named_ade_run_and_manual_links_under_previously_selected_root_are_preserved(catalog, tmp_path):
    """Round 4 MEDIUM #2: per-link provenance prevents ADE-only runs or root selection from claiming manual links."""
    home, public, _, env = catalog
    env.pop("SKILL_EVERYWHERE_PRIVATE", None)
    env.pop("SKILL_EVERYWHERE_SITE", None)
    env.pop("OPS_ROOT", None)
    env.pop("TENDCF_SITE", None)
    env.pop("TENDCF_OPS_ROOT", None)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["SKILL_EVERYWHERE_ONLY"] = "codex"

    skill(public, "ade-only")
    lpriv = home / "ops" / "site-private" / "skills"
    lpriv.mkdir(parents=True)
    manual_before_src = skill(lpriv, "manual-before-switch")
    manual_collide_src = skill(lpriv, "shared-manual")
    managed_legacy_src = skill(lpriv, "managed-legacy")

    tpriv = home / "tendcf-ops" / "tendcf-private-acme" / "skills"
    tpriv.mkdir(parents=True)
    skill(tpriv, "shared-manual")
    tpriv_only = skill(tpriv, "acme-only")

    links = home / ".agents" / "skills"
    # Pre-existing manual links under legacy site-private root BEFORE any site install.
    (links / "manual-before-switch").symlink_to(manual_before_src)
    (links / "shared-manual").symlink_to(manual_collide_src)

    # 1. Named ADE-only run MUST NOT claim ownership of legacy site roots or manual links under them.
    r_ade = run(catalog, "ade-only")
    assert r_ade.returncode == 0, r_ade.stdout + r_ade.stderr

    # 2. Named install of ONE legacy site skill records ONLY that skill (not manual siblings under the same root).
    r_one = run(catalog, "managed-legacy")
    assert r_one.returncode == 0, r_one.stdout + r_one.stderr
    assert (links / "managed-legacy").readlink() == managed_legacy_src

    # 3. Switch to acme:
    #    - `managed-legacy` (in ledger) IS flagged/removed;
    #    - `manual-before-switch` (under same legacy root, NOT in ledger) IS preserved silently;
    #    - `shared-manual` (same name as acme skill, NOT in ledger) stays `other link -> ...`, left alone!
    active_cfg = tmp_path / "xdg" / "tendcf" / "active-site"
    active_cfg.parent.mkdir(parents=True)
    active_cfg.write_text("acme\n", encoding="utf-8")

    r_switch = run(catalog, "--all")
    assert r_switch.returncode == 1  # only because `shared-manual` is a foreign manual link collision
    assert "other link ->" in r_switch.stdout
    assert "migrating from" not in r_switch.stdout
    assert not os.path.lexists(links / "managed-legacy")
    assert (links / "acme-only").readlink() == tpriv_only.resolve()
    assert (links / "manual-before-switch").readlink() == manual_before_src
    assert (links / "shared-manual").readlink() == manual_collide_src

