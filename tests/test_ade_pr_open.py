"""bin/ade-pr-open: gh pr create, then fill `(#PR)` in the branch's changelog fragment (2026-11-21).

Every test uses a throwaway repo with a local bare remote and a fake `gh` on PATH; the real
`gh pr create` is never called.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-pr-open"
FOLD = SCRIPT.parent / "changelog-fold"
BRANCH = "fix/pr-number-demo"
FRAGMENT = "changelog.d/fix-pr-number-demo.md"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def env(tmp_path):
    remote, repo, shims = tmp_path / "remote.git", tmp_path / "work", tmp_path / "shims"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "master", str(repo)], check=True, capture_output=True)
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid")):
        git(repo, "config", k, v)
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n### Added\n\n- old (#1)\n")
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d/README.md").write_text("x\n")
    git(repo, "add", ".")
    git(repo, "commit", "--no-verify", "-m", "base")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "master")
    git(repo, "checkout", "-b", BRANCH)
    shims.mkdir()
    log = tmp_path / "gh.log"
    gh = shims / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" >> {log}\n'
                  'if [ -n "$FAKE_GH_FAIL" ]; then echo "gh: boom" >&2; exit 1; fi\n'
                  'echo "Creating pull request"\n'
                  'echo "https://github.com/djbclark/djbclark-ade/pull/${FAKE_PR:-901}"\n'
                  'echo "hint: wait with gh event listen --resource https://github.com/o/r/pull/5"\n'
                  'echo "  - It prints the first event as a JSON line and exits"\n')
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    e = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
    return repo, remote, log, e


def commit_fragment(repo, body):
    (repo / FRAGMENT).write_text(body)
    git(repo, "add", FRAGMENT)
    git(repo, "commit", "--no-verify", "-m", "fragment")
    git(repo, "push", "origin", BRANCH)


def open_pr(repo, e, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, env=e,
                          capture_output=True, text=True, timeout=120)


def check(repo):
    return subprocess.run([sys.executable, str(FOLD), "--repo", str(repo), "--check"],
                          capture_output=True, text=True)


def test_placeholder_not_at_line_end_is_left_alone_and_fails_the_check(env):
    repo, remote, log, e = env
    commit_fragment(repo, "### Fixed\n\n- one thing (#PR)\n- wrapped entry\n  continues here (#PR).\n"
                          "- mid (#PR) stays\n")
    assert check(repo).returncode == 1  # the placeholder alone fails the check

    r = open_pr(repo, e, "--title", "T", "--body", "B")

    # `mid (#PR) stays` does not end with the placeholder, so it is left alone and the check says so.
    assert r.returncode == 4 and "changelog-fold --check exited 1" in r.stderr
    text = (repo / FRAGMENT).read_text()
    assert "- one thing (#901)\n" in text and "continues here (#901).\n" in text
    assert "mid (#PR) stays" in text
    assert git(repo, "status", "--porcelain", "--", FRAGMENT)  # filled, not committed on failure
    assert "--title T --body B" in log.read_text()
    assert "--existing 901" in r.stderr


def test_clean_fragment_commits_and_pushes_the_fill(env):
    repo, remote, log, e = env
    commit_fragment(repo, "### Fixed\n\n- one thing (#PR)\n- wrapped entry\n  continues here (#PR).\n")

    r = open_pr(repo, e, "--", "--title", "T", "--body", "B")

    assert r.returncode == 0, r.stderr
    assert "pull/901" in r.stdout
    text = (repo / FRAGMENT).read_text()
    assert "(#PR)" not in text and "- one thing (#901)\n" in text and "continues here (#901).\n" in text
    assert check(repo).returncode == 0
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-1", "--format=%s") == "docs: fill changelog fragment PR number (#901)"
    assert git(remote, "rev-parse", BRANCH) == git(repo, "rev-parse", "HEAD")
    assert git(repo, "diff", "--name-only", "HEAD~1", "HEAD") == FRAGMENT  # only the fragment


def test_only_the_branchs_own_fragment_changes(env):
    repo, remote, log, e = env
    (repo / "changelog.d/other.md").write_text("### Fixed\n\n- theirs (#PR)\n")
    git(repo, "add", "changelog.d/other.md")
    commit_fragment(repo, "### Fixed\n\n- mine (#PR)\n")

    r = open_pr(repo, e, "--title", "T", "--body", "B")

    # the other fragment still fails the whole-directory check: reported, never edited
    assert r.returncode == 4
    assert "(#PR)" in (repo / "changelog.d/other.md").read_text()
    assert "mine (#901)" in (repo / FRAGMENT).read_text()


def test_fragment_without_placeholder_just_checks(env):
    repo, remote, log, e = env
    commit_fragment(repo, "### Fixed\n\n- already numbered (#7)\n")

    r = open_pr(repo, e, "--title", "T", "--body", "B")

    assert r.returncode == 0, r.stderr
    assert "nothing to commit" in r.stdout
    assert git(repo, "log", "-1", "--format=%s") == "fragment"


def test_gh_failure_exits_3_and_touches_nothing(env):
    repo, remote, log, e = env
    commit_fragment(repo, "### Fixed\n\n- one (#PR)\n")

    r = open_pr(repo, {**e, "FAKE_GH_FAIL": "1"}, "--title", "T", "--body", "B")

    assert r.returncode == 3 and "gh pr create exited 1" in r.stderr
    assert "(#PR)" in (repo / FRAGMENT).read_text()


def test_missing_or_dirty_fragment_is_refused_before_gh_runs(env):
    repo, remote, log, e = env
    r = open_pr(repo, e, "--title", "T")
    assert r.returncode == 2 and "no fragment" in r.stderr and not log.exists()

    commit_fragment(repo, "### Fixed\n\n- one (#PR)\n")
    (repo / FRAGMENT).write_text("### Fixed\n\n- one (#PR)\n- edited (#PR)\n")
    r = open_pr(repo, e, "--title", "T")
    assert r.returncode == 2 and "uncommitted" in r.stderr and not log.exists()


def test_existing_flag_reruns_the_fill_without_gh(env):
    repo, remote, log, e = env
    commit_fragment(repo, "### Fixed\n\n- one (#PR)\n")

    r = open_pr(repo, e, "--existing", "42", "--message", "fill it")

    assert r.returncode == 0, r.stderr
    assert not log.exists()
    assert "one (#42)" in (repo / FRAGMENT).read_text()
    assert git(repo, "log", "-1", "--format=%s") == "fill it"


def test_no_arguments_is_a_usage_error(env):
    repo, remote, log, e = env
    assert open_pr(repo, e).returncode == 2


def test_check_still_rejects_a_leftover_placeholder(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text("# C\n\n## Unreleased\n")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "changelog.d/x.md").write_text("### Fixed\n\n- forgot to fill (#PR)\n")
    r = check(tmp_path)
    assert r.returncode == 1 and "does not end with (#N)" in r.stdout + r.stderr
