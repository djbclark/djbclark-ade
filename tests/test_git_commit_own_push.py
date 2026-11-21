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


@pytest.mark.parametrize("multiple", [False, True])
def test_different_or_multiple_push_urls_are_refused_before_remote_contact(published, multiple):
    import shlex

    repo, remote = published
    other = remote.parent / "push.git"
    subprocess.run(["git", "clone", "--bare", str(remote), str(other)],
                   check=True, capture_output=True)
    advance(repo, other)  # Only the push endpoint advances; fetch endpoint stays behind.
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    if multiple:
        git(repo, "config", "--add", "remote.origin.pushurl", str(remote))
    git(repo, "config", "--add", "remote.origin.pushurl", str(other))
    before = [git(r, "show-ref") for r in (remote, other)]
    contacted = remote.parent / "contacted"
    upload = remote.parent / "upload-probe"
    upload.write_text("#!/bin/sh\nprintf contacted > " + shlex.quote(str(contacted))
                      + "\nexit 99\n")
    upload.chmod(0o755)
    git(repo, "config", "remote.origin.uploadpack", str(upload))

    result = commit(repo)

    assert result.returncode == 3
    assert "PUBLISH FAILED remote=origin ref=refs/heads/main" in result.stderr
    assert "different fetch/push URLs or multiple push URLs" in result.stderr
    assert "--no-push and publish explicitly" in result.stderr
    assert not contacted.exists()
    assert [git(r, "show-ref") for r in (remote, other)] == before
    assert git(repo, "log", "-1", "--format=%s") == "own change"


def test_same_explicit_fetch_and_push_url_is_allowed(published):
    repo, remote = published
    git(repo, "config", "remote.origin.pushurl", str(remote))
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "topic") == git(repo, "rev-parse", "HEAD")


def test_explicit_config_wins_over_upstream(published):
    repo, remote = published
    git(repo, "branch", "--set-upstream-to=origin/main")
    git(repo, "config", "branch.topic.commitOwnPushRef", "chosen")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "chosen") == git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("target", ["main", "refs/heads/main", "HEAD:main"])
def test_configured_ref_supports_worktree_publish_target(published, target):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", target)
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_upstream_remote_and_slash_branch(published):
    repo, remote = published
    git(repo, "remote", "rename", "origin", "publisher")
    git(repo, "branch", "-m", "team/main")
    git(repo, "push", "-u", "publisher", "HEAD:team/main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "team/main") == git(repo, "rev-parse", "HEAD")


def test_configured_remote(published):
    repo, remote = published
    git(repo, "remote", "rename", "origin", "publisher")
    git(repo, "config", "branch.topic.commitOwnPushRemote", "publisher")
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_behind_target_rebases_then_pushes(published):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    peer = advance(repo, remote)
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "HEAD^") == peer
    assert (repo / "theirs").read_text() == "peer change\n"
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_conflicting_rebase_aborts_and_keeps_local_commit(published):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    peer = advance(repo, remote, conflict=True)
    result = commit(repo)
    assert result.returncode != 0
    assert "PUBLISH FAILED remote=origin ref=refs/heads/main" in result.stderr
    assert "temporary rebase failed; original commit retained" in result.stderr
    assert git(remote, "rev-parse", "main") == peer
    assert (repo / "mine").read_text() == "my change\n"
    assert git(repo, "log", "-1", "--format=%s") == "own change"
    assert not (Path(git(repo, "rev-parse", "--absolute-git-dir")) / "rebase-merge").exists()
    assert len(git(repo, "worktree", "list", "--porcelain").split("worktree ")) == 2


def test_behind_target_does_not_stash_foreign_edits(published):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    peer = advance(repo, remote)
    (repo / "foreign").write_text("leave alone\n")
    result = commit(repo)
    assert result.returncode == 3
    assert "dirty" in result.stderr
    assert (repo / "foreign").read_text() == "leave alone\n"
    assert git(remote, "rev-parse", "main") == peer


def test_rejected_push_is_loud_and_nonzero(published):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
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
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
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
    assert "No such remote" in result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "own change"


def test_fresh_worktree_does_not_publish_inherited_master_upstream(published):
    repo, remote = published
    tree = repo.parent / "feature-tree"
    git(repo, "worktree", "add", "-b", "feature", str(tree), "origin/main")
    before = git(remote, "rev-parse", "main")
    result = commit(tree)
    assert result.returncode == 0, result.stderr
    assert "skipping mismatched upstream origin refs/heads/main" in result.stderr
    assert "commit-own.pushRef" in result.stderr
    assert git(remote, "rev-parse", "main") == before
    assert git(remote, "rev-parse", "feature") == git(tree, "rev-parse", "HEAD")


def test_matching_upstream_is_used(published):
    repo, remote = published
    git(repo, "branch", "-m", "main")
    git(repo, "branch", "--set-upstream-to=origin/main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_unrelated_history_is_not_rebased(published):
    repo, remote = published
    peer = remote.parent / "unrelated"
    subprocess.run(["git", "init", "-b", "other", str(peer)], check=True, capture_output=True)
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.invalid")
    (peer / "unrelated").write_text("other\n")
    git(peer, "add", ".")
    git(peer, "commit", "--no-verify", "-m", "unrelated")
    git(peer, "push", str(remote), "HEAD:other")
    before = git(remote, "rev-parse", "other")
    git(repo, "config", "branch.topic.commitOwnPushRef", "other")
    result = commit(repo)
    assert result.returncode == 3
    assert git(remote, "rev-parse", "other") == before
    assert git(repo, "show", "HEAD:mine") == "my change"


def test_published_commits_are_not_rewritten(published):
    repo, remote = published
    (repo / "earlier").write_text("published\n")
    git(repo, "add", "earlier")
    git(repo, "commit", "--no-verify", "-m", "published")
    git(repo, "push", "origin", "HEAD:already-published")
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    before = advance(repo, remote)
    result = commit(repo)
    assert result.returncode == 3
    assert "rewrite previously published commits" in result.stderr
    assert git(remote, "rev-parse", "main") == before


def test_rebase_does_not_discard_edits_made_during_replay(published):
    import shlex

    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    before = advance(repo, remote)
    hook = Path(git(repo, "rev-parse", "--absolute-git-dir")) / "hooks" / "post-rewrite"
    hook.write_text("#!/bin/sh\nprintf 'foreign edit\\n' > " + shlex.quote(str(repo / "mine")) + "\n")
    hook.chmod(0o755)
    result = commit(repo)
    assert result.returncode == 3
    assert "checkout changed during rebase" in result.stderr
    assert (repo / "mine").read_text() == "foreign edit\n"
    assert git(repo, "show", "HEAD:mine") == "my change"
    assert git(remote, "rev-parse", "main") == before


def test_detached_head_explains_local_only_option(published):
    repo, remote = published
    git(repo, "checkout", "--detach")
    result = commit(repo)
    assert result.returncode == 3
    assert "detached HEAD; publish explicitly or use --no-push" in result.stderr


@pytest.mark.parametrize("scope", ["branch", "worktree"])
def test_explicit_target_does_not_leak_to_sibling_worktree(published, scope):
    repo, remote = published
    if scope == "branch":
        git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    else:
        git(repo, "config", "extensions.worktreeConfig", "true")
        git(repo, "config", "--worktree", "commit-own.pushBranch", "topic")
        git(repo, "config", "--worktree", "commit-own.pushRef", "main")
    sibling = repo.parent / "sibling"
    git(repo, "worktree", "add", "-b", "sibling", str(sibling), "origin/main")
    before = git(remote, "rev-parse", "main")
    result = commit(sibling)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == before
    assert git(remote, "rev-parse", "sibling") == git(sibling, "rev-parse", "HEAD")


def test_worktree_scoped_target_is_supported(published):
    repo, remote = published
    git(repo, "config", "extensions.worktreeConfig", "true")
    git(repo, "config", "--worktree", "commit-own.pushBranch", "topic")
    git(repo, "config", "--worktree", "commit-own.pushRef", "main")
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")


def test_repo_wide_legacy_target_is_refused_loudly(published):
    repo, remote = published
    git(repo, "config", "commit-own.pushRef", "main")
    before = git(remote, "rev-parse", "main")
    result = commit(repo)
    assert result.returncode == 3
    assert "shared across worktrees" in result.stderr
    assert git(remote, "rev-parse", "main") == before


@pytest.mark.parametrize("url", ["https://github.com/CFEngine/core.git",
                                 "git@github.com:NorthernTechHQ/libntech.git"])
@pytest.mark.parametrize("override", ["", "0", "1"])
def test_automatic_push_obeys_upstream_gate_before_contacting_remote(published, url, override):
    import os

    repo, remote = published
    git(repo, "remote", "set-url", "--push", "origin", url)
    (repo / "mine").write_text("own gated change\n")
    env = os.environ.copy()
    env["UPSTREAM_REVIEW_GATE_OFF"] = override
    result = subprocess.run([str(SCRIPT), "gated", "mine"], cwd=repo,
                            capture_output=True, text=True, timeout=10, env=env)
    assert result.returncode == 3
    assert "upstream review gate refuses publishing" in result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "gated"


def test_rebase_does_not_move_other_local_branches(published):
    repo, remote = published
    git(repo, "config", "branch.topic.commitOwnPushRef", "main")
    git(repo, "config", "rebase.updateRefs", "true")
    (repo / "earlier").write_text("earlier\n")
    git(repo, "add", "earlier")
    git(repo, "commit", "--no-verify", "-m", "earlier")
    git(repo, "branch", "side")
    side = git(repo, "rev-parse", "side")
    advance(repo, remote)
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "side") == side


# --- Forgejo remotes publish through git-forgejo (2026-11-21) -------------------------------

import os
import shutil
import stat


def _shim_env(tmp_path, remote, url, with_forgejo):
    """PATH with a logging `git` shim (network calls to URL go to the bare REMOTE) and, if asked,
    a fake git-forgejo that logs and execs the real git with the same rewrite. The real
    ~/.local/bin/git-forgejo is kept off PATH."""
    real_git = shutil.which("git")
    bindir = tmp_path / "shims"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    rewrite = f"-c url.{remote}.insteadOf={url}"
    # Only network subcommands are rewritten, so `git remote get-url` still shows the raw URL.
    (bindir / "git").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in ls-remote|fetch|push)\n'
        f'  echo "plain $*" >> {log}; exec {real_git} {rewrite} "$@" ;; esac; done\n'
        f'exec {real_git} "$@"\n')
    if with_forgejo:
        (bindir / "git-forgejo").write_text(
            f'#!/bin/sh\necho "forgejo host=${{FORGEJO_HOST:-unset}} $*" >> {log}\nexec {real_git} {rewrite} "$@"\n')
    for f in bindir.iterdir():
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    # Symlink only what the script needs, never whole directories: ~/.local/bin holds both python3
    # and the real git-forgejo on this Mac.
    for tool in ("python3", "bash"):
        found = shutil.which(tool)
        assert found, tool
        (bindir / tool).symlink_to(found)
    dirs = [str(bindir), "/usr/bin", "/bin"]
    assert not any((Path(d) / "git-forgejo").exists() for d in dirs[1:]), "git-forgejo on base PATH"
    # BASH_ENV (~/.bashrc) would put ~/.local/bin, with the real git-forgejo, back in front of the shims.
    clean = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "ENV", "GIT_ASKPASS", "FORGEJO_HOST")}
    return {**clean, "PATH": os.pathsep.join(dirs)}, log


def _commit_env(repo, env):
    (repo / "mine").write_text("my change\n")
    return subprocess.run([str(SCRIPT), "own change", "mine"], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def test_forgejo_remote_publishes_through_git_forgejo(published, tmp_path):
    repo, remote = published
    url = "https://forgejo.mit.edu/djbclark/example.git"
    git(repo, "remote", "set-url", "origin", url)
    env, log = _shim_env(tmp_path, remote, url, with_forgejo=True)

    result = _commit_env(repo, env)

    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "topic") == git(repo, "rev-parse", "HEAD")
    calls = log.read_text().splitlines()
    assert any(c.startswith("forgejo host=forgejo.mit.edu -C ") and " push -- origin HEAD:refs/heads/topic" in c
               for c in calls), calls
    assert not any(c.startswith("plain ") for c in calls), calls


def test_github_remote_still_uses_plain_git_push(published, tmp_path):
    repo, remote = published
    url = "https://github.com/example/example.git"
    git(repo, "remote", "set-url", "origin", url)
    env, log = _shim_env(tmp_path, remote, url, with_forgejo=True)

    result = _commit_env(repo, env)

    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "topic") == git(repo, "rev-parse", "HEAD")
    calls = log.read_text().splitlines()
    assert any(c.startswith("plain ") and " push -- origin HEAD:refs/heads/topic" in c
               for c in calls), calls
    assert not any(c.startswith("forgejo ") for c in calls), calls


def test_forgejo_remote_without_git_forgejo_exits_3_naming_it(published, tmp_path):
    repo, remote = published
    url = "https://forgejo.mit.edu/djbclark/example.git"
    git(repo, "remote", "set-url", "origin", url)
    env, log = _shim_env(tmp_path, remote, url, with_forgejo=False)

    result = _commit_env(repo, env)

    assert result.returncode == 3
    assert "PUBLISH FAILED remote=origin" in result.stderr
    assert "git-forgejo" in result.stderr and "not on PATH" in result.stderr
    assert git(repo, "log", "-1", "--format=%s") == "own change"  # committed locally
    assert not log.exists()  # the remote was never contacted
    with pytest.raises(subprocess.CalledProcessError):
        git(remote, "rev-parse", "topic")


@pytest.mark.parametrize("url", ["git@forgejo.mit.edu:djbclark/example.git",
                                 "ssh://git@forgejo.mit.edu/djbclark/example.git",
                                 "http://forgejo.mit.edu/djbclark/example.git",
                                 "https://forgejo.mit.edu@evil.example.com/o/r.git",
                                 "https://notforgejo.mit.edu.example.com/o/r.git"])
def test_non_https_or_lookalike_hosts_stay_on_plain_git(published, tmp_path, url):
    repo, remote = published
    git(repo, "remote", "set-url", "origin", url)
    env, log = _shim_env(tmp_path, remote, url, with_forgejo=True)

    result = _commit_env(repo, env)

    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("forgejo ") for c in log.read_text().splitlines())


def test_exported_forgejo_host_is_pinned_to_the_remote_host(published, tmp_path):
    repo, remote = published
    url = "https://forgejo.mit.edu/djbclark/example.git"
    git(repo, "remote", "set-url", "origin", url)
    env, log = _shim_env(tmp_path, remote, url, with_forgejo=True)
    env["FORGEJO_HOST"] = "other.example.org"

    result = _commit_env(repo, env)

    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls and all(c.startswith("forgejo host=forgejo.mit.edu ") for c in calls), calls
