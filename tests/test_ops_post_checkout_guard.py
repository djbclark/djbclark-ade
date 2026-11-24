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


def test_main_branch_tendcf_deploy_checkout_and_worktree_silence(tmp_path):
    """Queue #123: ~/tendcf-ops deploy checkouts on `main` warn on feature branches; `.worktrees/` stay silent."""
    origin = tmp_path / "origin-main.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    tendcf_ops = tmp_path / "tendcf-ops"
    repo = tendcf_ops / "tendcf-private-acme"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "f").write_text("x")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    hook = repo / ".git" / "hooks" / "post-checkout"
    shutil.copy(HOOK, hook)
    hook.chmod(0o755)

    # Linked worktree under ~/tendcf-ops/.worktrees/ stays silent.
    wt = tendcf_ops / ".worktrees" / "feat-wt"
    r_wt = git(repo, "worktree", "add", "-b", "feat-wt", str(wt))
    assert "post-checkout-guard" not in r_wt.stderr
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"

    # Switching the deploy checkout itself off `main` warns naming `main`.
    r_main = git(repo, "checkout", "-b", "stray")
    assert "post-checkout-guard: deploy checkout is now on 'stray', not main." in r_main.stderr


def _make_fake_gh(tmp_path, pr_json: str) -> Path:
    gh = tmp_path / "fake-gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"data = {pr_json!r}\n"
        "args = sys.argv[1:]\n"
        "base = args[args.index('--base') + 1] if '--base' in args else None\n"
        "items = json.loads(data)\n"
        "if base is not None:\n"
        "    items = [it for it in items if it.get('baseRefName') == base]\n"
        "print(len(items))\n"
    )
    gh.chmod(0o755)
    return gh


def _make_main_deploy_repo(tmp_path):
    origin = tmp_path / "origin-main.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "tendcf-ops" / "tendcf-private-acme"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "f").write_text("base\n")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    return origin, repo


def _install_hook(repo: Path) -> None:
    hook = repo / ".git" / "hooks" / "post-checkout"
    shutil.copy(HOOK, hook)
    hook.chmod(0o755)


def test_auto_heal_refuses_unmerged_local_commits_even_with_merged_pr_name(tmp_path):
    """Finding 5: historical merged PR of the same branch name must NOT delete unmerged local commits."""
    _, repo = _make_main_deploy_repo(tmp_path)
    # Create a branch with an unmerged local commit (NOT in origin/main) before installing hook.
    git(repo, "checkout", "-q", "-b", "reused-branch")
    (repo / "local.txt").write_text("unmerged work\n")
    git(repo, "add", "local.txt")
    git(repo, "commit", "-q", "-m", "local unmerged commit")
    git(repo, "checkout", "-q", "main")
    _install_hook(repo)

    fake_gh = _make_fake_gh(tmp_path, '[{"number": 42, "baseRefName": "main"}]')
    env = {**os.environ, "OPS_GUARD_GH": str(fake_gh), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = subprocess.run(["git", "checkout", "reused-branch"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "could not confirm 'reused-branch' tip is merged into main" in r.stderr
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "reused-branch"
    assert (repo / "local.txt").read_text() == "unmerged work\n"


def test_auto_heal_refuses_pr_merged_into_wrong_base(tmp_path):
    """Finding 5: PR merged into a non-default base branch must NOT trigger auto-heal or deletion."""
    _, repo = _make_main_deploy_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "other-base-branch")
    git(repo, "checkout", "-q", "main")
    _install_hook(repo)

    fake_gh = _make_fake_gh(tmp_path, '[{"number": 77, "baseRefName": "release-v1"}]')
    env = {**os.environ, "OPS_GUARD_GH": str(fake_gh), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = subprocess.run(["git", "checkout", "other-base-branch"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "could not confirm 'other-base-branch' tip is merged into main" in r.stderr
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "other-base-branch"


def test_auto_heal_succeeds_safely_when_tip_is_contained_in_default_branch(tmp_path):
    """Finding 5: when tip IS contained in origin/main and PR merged into main, auto-heal switches back and safe-deletes (-d)."""
    _, repo = _make_main_deploy_repo(tmp_path)
    git(repo, "checkout", "-q", "-b", "merged-feature")
    (repo / "m.txt").write_text("merged\n")
    git(repo, "add", "m.txt")
    git(repo, "commit", "-q", "-m", "feature")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "merged-feature")
    git(repo, "push", "-q", "origin", "main")
    _install_hook(repo)

    fake_gh = _make_fake_gh(tmp_path, '[{"number": 99, "baseRefName": "main"}]')
    env = {**os.environ, "OPS_GUARD_GH": str(fake_gh), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = subprocess.run(["git", "checkout", "merged-feature"], cwd=repo, env=env, capture_output=True, text=True, check=True)
    assert "auto-healing to main" in r.stderr
    assert "back on main" in r.stderr
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert "merged-feature" not in git(repo, "branch", "--list", "merged-feature").stdout
