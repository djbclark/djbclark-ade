"""bin/ade-roster prints README's skills and bin/ roster from the files themselves, and --check fails a stale README (2026-11-07).

Every test but the last builds a throwaway repo in tmp_path and runs the real script with --root, so this checkout's
README.md is never written. The last one checks this checkout's README: the same check CI runs.
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
    assert "Skills (2," in out and "`bin/` (4," in out
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


def test_this_checkouts_readme_roster_is_current():
    r = run("--check", root=REPO)
    assert r.returncode == 0, r.stderr + " (run bin/ade-roster --write)"


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
