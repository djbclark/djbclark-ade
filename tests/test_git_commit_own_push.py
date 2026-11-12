"""Offline publishing checks against real temporary bare remotes."""
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bin/git-commit-own"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def published(tmp_path):
    remote, repo = tmp_path / "remote.git", tmp_path / "local"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "topic", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "mine").write_text("base\n")
    git(repo, "add", "mine")
    git(repo, "commit", "--no-verify", "-m", "base")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "HEAD:main")
    return repo, remote


def commit(repo, *flags):
    (repo / "mine").write_text("my change\n")
    return subprocess.run([str(SCRIPT), *flags, "own change", "mine"], cwd=repo,
                          capture_output=True, text=True, timeout=60)


def advance(repo, remote, conflict=False):
    peer = remote.parent / "peer"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(peer)],
                   capture_output=True, check=True)
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.invalid")
    (peer / ("mine" if conflict else "theirs")).write_text("peer change\n")
    git(peer, "add", ".")
    git(peer, "commit", "--no-verify", "-m", "peer")
    git(peer, "push", "origin", "main")
    return git(peer, "rev-parse", "HEAD")


def test_default_push_creates_same_branch(published):
    repo, remote = published
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "topic") == git(repo, "rev-parse", "HEAD")


def test_upstream_wins_over_configured_target(published):
    repo, remote = published
    git(repo, "branch", "--set-upstream-to=origin/main")
    git(repo, "config", "commit-own.pushRef", "wrong")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("target", ["main", "refs/heads/main", "HEAD:main"])
def test_configured_ref_supports_worktree_publish_target(published, target):
    repo, remote = published
    git(repo, "config", "commit-own.pushRef", target)
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_upstream_remote_and_slash_branch(published):
    repo, remote = published
    git(repo, "remote", "rename", "origin", "publisher")
    git(repo, "push", "-u", "publisher", "HEAD:team/main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "team/main") == git(repo, "rev-parse", "HEAD")


def test_configured_remote(published):
    repo, remote = published
    git(repo, "remote", "rename", "origin", "publisher")
    git(repo, "config", "commit-own.pushRemote", "publisher")
    git(repo, "config", "commit-own.pushRef", "main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_behind_target_rebases_then_pushes(published):
    repo, remote = published
    git(repo, "branch", "--set-upstream-to=origin/main")
    peer = advance(repo, remote)
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "HEAD^") == peer
    assert (repo / "theirs").read_text() == "peer change\n"
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_conflicting_rebase_aborts_and_keeps_local_commit(published):
    repo, remote = published
    git(repo, "branch", "--set-upstream-to=origin/main")
    peer = advance(repo, remote, conflict=True)
    result = commit(repo)
    assert result.returncode != 0
    assert "PUBLISH FAILED remote=origin ref=refs/heads/main" in result.stderr
    assert "rebase failed and was aborted" in result.stderr
    assert git(remote, "rev-parse", "main") == peer
    assert (repo / "mine").read_text() == "my change\n"
    assert git(repo, "log", "-1", "--format=%s") == "own change"
    assert not (Path(git(repo, "rev-parse", "--absolute-git-dir")) / "rebase-merge").exists()


def test_behind_target_does_not_stash_foreign_edits(published):
    repo, remote = published
    git(repo, "branch", "--set-upstream-to=origin/main")
    peer = advance(repo, remote)
    (repo / "foreign").write_text("leave alone\n")
    result = commit(repo)
    assert result.returncode != 0
    assert "dirty" in result.stderr
    assert (repo / "foreign").read_text() == "leave alone\n"
    assert git(remote, "rev-parse", "main") == peer


def test_rejected_push_is_loud_and_nonzero(published):
    repo, remote = published
    git(repo, "config", "commit-own.pushRef", "main")
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'policy rejected' >&2\nexit 1\n")
    hook.chmod(0o755)
    before = git(remote, "rev-parse", "main")
    result = commit(repo)
    assert result.returncode != 0
    assert "PUBLISH FAILED remote=origin ref=refs/heads/main" in result.stderr
    assert "policy rejected" in result.stderr
    assert git(remote, "rev-parse", "main") == before
    assert git(repo, "log", "-1", "--format=%s") == "own change"


def test_no_push_still_commits_without_remote(published):
    repo, remote = published
    git(repo, "remote", "remove", "origin")
    result = commit(repo, "--no-push")
    assert result.returncode == 0, result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "own change"


def test_failed_commit_does_not_push(published):
    repo, remote = published
    git(repo, "config", "commit-own.pushRef", "main")
    before = git(remote, "rev-parse", "main")
    result = subprocess.run([str(SCRIPT), "nothing", "mine"], cwd=repo,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert git(remote, "rev-parse", "main") == before


def test_staged_push_preserves_unstaged_edit(published):
    repo, remote = published
    (repo / "mine").write_text("staged\n")
    git(repo, "add", "mine")
    (repo / "mine").write_text("staged\nforeign\n")
    result = subprocess.run([str(SCRIPT), "--staged", "staged change"], cwd=repo,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert git(remote, "show", "topic:mine") == "staged"
    assert (repo / "mine").read_text() == "staged\nforeign\n"


def test_missing_remote_is_failure_after_local_commit(published):
    repo, remote = published
    git(repo, "remote", "remove", "origin")
    result = commit(repo)
    assert result.returncode != 0
    assert "PUBLISH FAILED remote=origin ref=refs/heads/topic" in result.stderr
    assert "does not appear to be a git repository" in result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "own change"
