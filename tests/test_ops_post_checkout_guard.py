"""The ops deploy-checkout guard must warn for the main checkout and stay silent in linked worktrees."""
import os
import shutil
import subprocess
from pathlib import Path

HOOK = Path(os.environ.get("GUARD_HOOK") or Path(__file__).resolve().parent.parent / "bin" / "ops-post-checkout-guard")


def git(cwd, *args, check=True):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)


def make_repo(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "master", str(origin))
    repo = tmp_path / "deploy"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "checkout", "-q", "-b", "master")
    (repo / "f").write_text("x")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "push", "-q", "origin", "master")
    hook = repo / ".git" / "hooks" / "post-checkout"
    shutil.copy(HOOK, hook)
    hook.chmod(0o755)
    return repo


def test_main_checkout_branch_still_warns(tmp_path):
    repo = make_repo(tmp_path)
    r = git(repo, "checkout", "-b", "feature")
    assert "post-checkout-guard: deploy checkout is now on 'feature'" in r.stderr


def test_linked_worktree_add_is_silent(tmp_path):
    repo = make_repo(tmp_path)
    r = git(repo, "worktree", "add", "-b", "feature", str(tmp_path / "wt"))
    assert "post-checkout-guard" not in r.stderr
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "master"


def test_checkout_inside_linked_worktree_is_silent(tmp_path):
    repo = make_repo(tmp_path)
    wt = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    r = git(wt, "checkout", "-b", "another")
    assert "post-checkout-guard" not in r.stderr
