"""bin/git-commit-own: commit own paths while another agent's unstaged edit stays on disk throughout."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "git-commit-own"

pytestmark = pytest.mark.skipif(shutil.which("pre-commit") is None, reason="pre-commit not installed")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "t")
    # The hook records what the foreign file holds while hooks run: a whole-tree stash would
    # show its committed content instead of the unstaged edit.
    (r / ".pre-commit-config.yaml").write_text(
        "repos:\n- repo: local\n  hooks:\n  - id: probe\n    name: probe\n    language: system\n"
        "    entry: sh -c 'cat foreign.txt >> ../seen.txt'\n    pass_filenames: false\n    always_run: true\n"
    )
    (r / "foreign.txt").write_text("committed\n")
    (r / "sub").mkdir()
    (r / "sub" / "mine.txt").write_text("v1\n")
    (r / "gone.txt").write_text("x\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "--no-verify", "-m", "init")
    # Installed like a real repo's, so a commit that ran it would stash the foreign edit.
    subprocess.run(["pre-commit", "install"], cwd=r, check=True, capture_output=True)
    return r


def run(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT), *args], cwd=cwd or repo, capture_output=True, text=True)


def test_commits_own_paths_and_never_hides_foreign_edit(repo: Path) -> None:
    (repo / "foreign.txt").write_text("another agent's unstaged edit\n")
    (repo / "sub" / "mine.txt").write_text("v2\n")
    (repo / "sub" / "new.txt").write_text("new\n")
    (repo / "gone.txt").unlink()

    res = run(repo, "own change", "mine.txt", "new.txt", cwd=repo / "sub")
    assert res.returncode == 0, res.stderr
    res = run(repo, "drop gone", "gone.txt")
    assert res.returncode == 0, res.stderr

    seen = (repo.parent / "seen.txt").read_text()
    assert "committed" not in seen  # the hook never saw the foreign file stashed back to HEAD
    assert "another agent's unstaged edit" in seen
    assert (repo / "foreign.txt").read_text() == "another agent's unstaged edit\n"
    assert git(repo, "show", "HEAD~1:sub/new.txt") == "new\n"
    assert git(repo, "show", "HEAD~1:sub/mine.txt") == "v2\n"
    assert "gone.txt" not in git(repo, "ls-files")
    assert git(repo, "status", "--short").strip() == "M foreign.txt"


def test_staged_mode_commits_index_only(repo: Path) -> None:
    (repo / "foreign.txt").write_text("committed\nmy hunk\n")
    git(repo, "add", "foreign.txt")
    (repo / "foreign.txt").write_text("committed\nmy hunk\ntheir unstaged hunk\n")

    res = run(repo, "--staged", "my hunk")
    assert res.returncode == 0, res.stderr
    assert git(repo, "show", "HEAD:foreign.txt") == "committed\nmy hunk\n"
    assert (repo / "foreign.txt").read_text().endswith("their unstaged hunk\n")


def test_failing_hook_blocks_commit(repo: Path) -> None:
    cfg = repo / ".pre-commit-config.yaml"
    cfg.write_text(cfg.read_text().replace("cat foreign.txt >> ../seen.txt", "exit 1"))
    git(repo, "commit", "-q", "--no-verify", "-am", "failing hook")
    (repo / "sub" / "mine.txt").write_text("v3\n")
    before = git(repo, "rev-parse", "HEAD")

    res = run(repo, "should not land", "sub/mine.txt")
    assert res.returncode != 0
    assert git(repo, "rev-parse", "HEAD") == before
