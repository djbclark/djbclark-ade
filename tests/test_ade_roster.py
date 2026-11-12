"""bin/ade-roster prints README's skills and bin/ roster from the files themselves, and --check fails a stale README (2026-11-07).

Fixtures exercise legacy embedded documents and standalone publication without writing this checkout's README.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-roster"
REPO = SCRIPT.parent.parent


def run(*args, root=None):
    argv = [sys.executable, str(SCRIPT), *args]
    if root is not None:
        argv += ["--root", str(root)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=60)


def make_repo(tmp_path):
    skills = tmp_path / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: >-\n  Do the alpha thing, e.g. a test. Use when asked\n  for alpha.\n---\n\n# Alpha\n"
    )
    (skills / "beta").mkdir()
    (skills / "beta" / "SKILL.md").write_text(
        '---\nname: beta\ndescription: "Beta has a | pipe. Second sentence."\n---\nbody\n'
    )
    (skills / "nofile").mkdir()  # a directory with no SKILL.md is not a skill
    b = tmp_path / "bin"
    b.mkdir()
    (b / "tool-py").write_text('#!/usr/bin/env python3\n"""tool-py: do a python thing. More text.\n\nusage: x\n"""\n')
    (b / "tool-sh").write_text(
        "#!/bin/bash\n# tool-sh — wrap a shell\n# thing across two lines.\n#     tool-sh --flag   usage row\n"
    )
    (b / "lib.py").write_text('"""Library: no shebang, still listed."""\n')
    (b / "node.mjs").write_text("// node.mjs: the node half. Talks to a daemon.\n")
    (tmp_path / "README.md").write_text("# Title\n\nprose\n\n<!-- roster:start -->\nold\n<!-- roster:end -->\n\nafter\n")
    return tmp_path


def test_print_lists_every_skill_and_tool_with_its_first_sentence(tmp_path):
    root = make_repo(tmp_path)
    r = run(root=root)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert out.startswith("<!-- roster:start -->\n") and out.rstrip().endswith("<!-- roster:end -->")
    assert "| [`alpha`](skills/alpha/SKILL.md) | Do the alpha thing, e.g. a test. |" in out
    assert "| [`beta`](skills/beta/SKILL.md) | Beta has a \\| pipe. |" in out
    assert "nofile" not in out
    assert "Skills (from each `skills/*/SKILL.md`):" in out
    assert "`bin/` (from each file's first docstring or comment):" in out
    assert "| [`tool-py`](bin/tool-py) | Do a python thing. |" in out
    assert "| [`tool-sh`](bin/tool-sh) | Wrap a shell thing across two lines. |" in out
    assert "| [`lib.py`](bin/lib.py) | Library: no shebang, still listed. |" in out
    assert "| [`node.mjs`](bin/node.mjs) | The node half. |" in out


def test_check_fails_on_a_stale_block_and_write_fixes_it(tmp_path):
    root = make_repo(tmp_path)
    r = run("--check", root=root)
    assert r.returncode == 1 and "stale" in r.stderr
    before = (root / "README.md").stat().st_mode
    r = run("--write", root=root)
    assert r.returncode == 0, r.stderr
    text = (root / "README.md").read_text()
    assert text.startswith("# Title\n\nprose\n\n<!-- roster:start -->\n")
    assert text.endswith("<!-- roster:end -->\n\nafter\n")
    assert "old" not in text
    assert (root / "README.md").stat().st_mode == before
    assert run("--check", root=root).returncode == 0


def test_a_new_skill_makes_the_readme_stale(tmp_path):
    root = make_repo(tmp_path)
    assert run("--write", root=root).returncode == 0
    (root / "skills" / "gamma").mkdir()
    (root / "skills" / "gamma" / "SKILL.md").write_text("---\nname: gamma\ndescription: Gamma.\n---\n")
    assert run("--check", root=root).returncode == 1


def test_missing_markers_or_readme_is_exit_2(tmp_path):
    root = make_repo(tmp_path)
    (root / "README.md").write_text("# no block here\n")
    r = run("--check", root=root)
    assert r.returncode == 2 and "roster:start" in r.stderr
    (root / "README.md").unlink()
    assert run("--check", root=root).returncode == 2
    assert run(root=tmp_path / "nowhere").returncode == 2


def test_this_checkout_links_to_published_roster_and_generates_locally():
    assert "blob/generated-roster/ROSTER.md" in (REPO / "README.md").read_text()
    assert "<!-- roster:start -->" not in (REPO / "README.md").read_text()
    r = run(root=REPO)
    assert r.returncode == 0, r.stderr


def test_standalone_roster_links_to_source_snapshot(tmp_path):
    root = make_repo(tmp_path)
    (root / "README.md").unlink()
    prefix = "https://github.com/example/repo/blob/0123456/"
    r = run("--link-prefix", prefix, root=root)
    assert r.returncode == 0, r.stderr
    assert f"]({prefix}skills/alpha/SKILL.md)" in r.stdout
    assert f"]({prefix}bin/tool-py)" in r.stdout


def test_untracked_files_are_left_out_in_a_git_checkout(tmp_path):
    import shutil
    if shutil.which("git") is None:
        return
    root = make_repo(tmp_path)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "skills", "bin", "README.md"], check=True)
    assert run("--write", root=root).returncode == 0
    (root / "bin" / "scratch-tool").write_text("#!/bin/sh\n# scratch: a local file nobody added\n")
    (root / "skills" / "local").mkdir()
    (root / "skills" / "local" / "SKILL.md").write_text("---\nname: local\ndescription: Local.\n---\n")
    r = run("--check", root=root)
    assert r.returncode == 0, r.stderr
    assert "scratch-tool" not in run(root=root).stdout and "`local`" not in run(root=root).stdout


def test_tracked_disables_inspected_tree_fsmonitor(tmp_path):
    """--root may be untrusted: ls-files must not exec that checkout's core.fsmonitor (PR #445)."""
    import shutil

    if shutil.which("git") is None:
        return
    root = make_repo(tmp_path / "repo")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "skills", "bin", "README.md"], check=True)
    marker = tmp_path / "fsmonitor-fired"
    hook = tmp_path / "fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\necho fired >> {marker}\nprintf ''\n")
    hook.chmod(0o755)
    subprocess.run(["git", "-C", str(root), "config", "core.fsmonitor", str(hook)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.fsmonitorHook", str(hook)], check=True)
    # Control: bare ls-files in that tree still fires the hook.
    if marker.exists():
        marker.unlink()
    subprocess.run(["git", "-C", str(root), "ls-files"], check=True, capture_output=True)
    assert marker.exists(), "control: core.fsmonitor must fire without -c override"
    marker.unlink()
    r = run(root=root)
    assert r.returncode == 0, r.stderr
    assert not marker.exists(), "ade-roster tracked() must disable the inspected tree's fsmonitor"
    assert "tool-py" in r.stdout


def test_additions_leave_headings_stable_and_rows_sorted(tmp_path):
    root = make_repo(tmp_path)
    before = run(root=root)
    assert before.returncode == 0, before.stderr
    (root / "skills" / "aardvark").mkdir()
    (root / "skills" / "aardvark" / "SKILL.md").write_text(
        "---\nname: aardvark\ndescription: New skill.\n---\n"
    )
    (root / "bin" / "aaa-tool").write_text("# aaa-tool: New tool.\n")
    after = run(root=root)
    assert after.returncode == 0, after.stderr
    headings = lambda text: [line for line in text.splitlines() if line.startswith(("Skills (", "`bin/` ("))]
    assert headings(before.stdout) == headings(after.stdout)
    assert after.stdout.index("[`aardvark`]") < after.stdout.index("[`alpha`]") < after.stdout.index("[`beta`]")
    assert after.stdout.index("[`aaa-tool`]") < after.stdout.index("[`lib.py`]") < after.stdout.index("[`node.mjs`]")


def test_publication_updates_only_generated_branch_and_tracks_add_remove(tmp_path):
    import shutil
    root = make_repo(tmp_path / "source")
    shutil.copy2(SCRIPT, root / "bin" / "ade-roster")
    remote = tmp_path / "remote.git"

    def git(*args, cwd=root):
        return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    remote.mkdir()
    git("init", "--bare", cwd=remote)
    git("init", "-b", "master")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("add", ".")
    git("commit", "-m", "initial")
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "master:master", "master:pr-head")
    old = git("rev-parse", "HEAD")
    publisher = REPO / ".github" / "scripts" / "publish-roster.py"

    def publish():
        result = subprocess.run([sys.executable, str(publisher), "--root", str(root)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert git("rev-parse", "HEAD") == git("rev-parse", "refs/heads/master")
        assert git("status", "--porcelain") == ""
        return git("show", "generated-roster:ROSTER.md", cwd=remote)

    text = publish()
    assert f"/blob/{old}/bin/tool-py" in text
    assert "[`alpha`]" in text
    (root / "skills" / "alpha" / "SKILL.md").unlink()
    (root / "bin" / "new-tool").write_text("# New tool.\n")
    git("add", ".")
    git("commit", "-m", "inventory change")
    new = git("rev-parse", "HEAD")
    text = publish()
    assert "[`alpha`]" not in text and "[`new-tool`]" in text
    assert f"/blob/{new}/bin/new-tool" in text
    assert git("rev-parse", "master", cwd=remote) == old
    assert git("rev-parse", "pr-head", cwd=remote) == old
    assert git("ls-tree", "--name-only", "generated-roster", cwd=remote) == "ROSTER.md"


def test_publisher_is_master_only_and_never_consumes_pr_content():
    import yaml
    # PyYAML's YAML 1.1 treats the workflow key `on` as a boolean.
    workflow = yaml.safe_load((REPO / ".github/workflows/roster.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push", "schedule", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["master"]
    job = workflow["jobs"]["publish"]
    assert job["if"] == "github.ref == 'refs/heads/master'"
    assert job["steps"][0]["with"]["ref"] == "master"
    assert workflow["concurrency"]["cancel-in-progress"] is False
