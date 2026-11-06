"""bin/ade-rescue-worktree: the D1.3 local rescue must hold every kind of unpushed work, push only tracked
changes, and survive a refused push (plan docs/d1-implementation-plan.md T6). Hermetic: temp repos only."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tarfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "bin" / "ade-rescue-worktree"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check,
                          env={**os.environ, **GIT_ENV})


@pytest.fixture
def fx(tmp_path):
    """A main checkout with an origin, and a linked worktree on branch `feat/x` holding one unpushed commit, a
    staged change, an unstaged change, an untracked file and an ignored file."""
    remote = tmp_path / "remote.git"
    main = tmp_path / "main"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(tmp_path, "init", "-q", "-b", "main", str(main))
    (main / "a.txt").write_text("a0\n")
    (main / "s.txt").write_text("s0\n")
    (main / ".gitignore").write_text("*.log\n")
    git(main, "add", "-A")
    git(main, "commit", "-qm", "base")
    git(main, "remote", "add", "origin", str(remote))
    git(main, "push", "-q", "origin", "main")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    (wt / "b.txt").write_text("committed\n")
    git(wt, "add", "b.txt")
    git(wt, "commit", "-qm", "unpushed")
    (wt / "s.txt").write_text("staged\n")
    git(wt, "add", "s.txt")
    (wt / "a.txt").write_text("unstaged\n")
    (wt / "new dir").mkdir()
    (wt / "new dir" / "u.txt").write_text("untracked\n")
    (wt / "debug.log").write_text("ignored\n")
    return {"tmp": tmp_path, "remote": remote, "main": main, "wt": wt, "root": tmp_path / "rescue"}


def run(fx, *extra, remote="origin"):
    argv = ["python3", str(TOOL), "--repo", "fx", "--branch", "feat/x", "--worktree", str(fx["wt"]), "--json", *extra]
    if remote:
        argv += ["--remote", remote]
    r = subprocess.run(argv, capture_output=True, text=True,
                       env={**os.environ, **GIT_ENV, "ADE_RESCUE_ROOT": str(fx["root"])})
    return r, json.loads(r.stdout)


def restore_into(fx, bundle):
    """Clone the bundle into a fresh repo, as an operator would after the worktree is gone."""
    dest = fx["tmp"] / "restored"
    git(fx["tmp"], "init", "-q", str(dest))
    git(dest, "fetch", "-q", str(bundle), "refs/*:refs/*")
    return dest


def verify_standalone(fx, bundle):
    """`git bundle verify` in an empty repository: passes only if the bundle needs no objects from elsewhere."""
    empty = fx["tmp"] / "empty"
    if not empty.exists():
        git(fx["tmp"], "init", "-q", str(empty))
    git(empty, "bundle", "verify", str(bundle))


def test_rescue_holds_every_change_and_pushes_tracked_only(fx):
    r, res = run(fx)
    assert r.returncode == 0, r.stderr
    d = Path(res["rescueDir"])
    assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stat.S_IMODE((fx["root"] / "fx").stat().st_mode) == 0o700
    assert not [p for p in (fx["root"] / "fx").iterdir() if p.name.startswith(".tmp-")]
    verify_standalone(fx, d / "branch.bundle")

    rest = restore_into(fx, d / "branch.bundle")
    assert git(rest, "show", "refs/heads/feat/x:b.txt").stdout == "committed\n"
    assert git(rest, "show", "refs/rescue/feat/x:a.txt").stdout == "unstaged\n"
    assert git(rest, "show", "refs/rescue/feat/x^2:s.txt").stdout == "staged\n"  # the index commit
    with tarfile.open(d / "untracked.tar") as tf:
        assert tf.getnames() == ["new dir/u.txt"]  # untracked yes, ignored debug.log no

    assert res["pushed"] is True
    pushed = git(fx["remote"], "ls-tree", "-r", "--name-only", res["pushRef"]).stdout.split()
    assert "b.txt" in pushed and "new dir/u.txt" not in pushed
    assert git(fx["remote"], "show", f"{res['pushRef']}:a.txt").stdout == "unstaged\n"
    # The worktree itself is untouched: the rescue is read-only for it.
    assert (fx["wt"] / "a.txt").read_text() == "unstaged\n"
    assert git(fx["wt"], "diff", "--cached", "--name-only").stdout.split() == ["s.txt"]


def test_refused_push_exits_zero_and_keeps_local_rescue(fx):
    hook = fx["remote"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho refused-by-test >&2\nexit 1\n")
    hook.chmod(0o755)
    r, res = run(fx)
    assert r.returncode == 0
    assert res["pushed"] is False and "refused-by-test" in res["pushError"]
    d = Path(res["rescueDir"])
    verify_standalone(fx, d / "branch.bundle")
    assert json.loads((d / "push.json").read_text())["pushed"] is False
    assert json.loads((fx["root"] / "rescue.log").read_text().splitlines()[-1])["pushed"] is False
    assert git(fx["remote"], "for-each-ref", "refs/heads/rescue/").stdout == ""


def test_dry_run_writes_and_pushes_nothing(fx):
    r, res = run(fx, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert res["untrackedCount"] == 1 and res["stashCommit"]
    assert not fx["root"].exists()
    assert git(fx["main"], "for-each-ref", "refs/rescue/").stdout == ""
    assert git(fx["remote"], "for-each-ref", "refs/heads/rescue/").stdout == ""


def test_clean_tree_bundles_branch_and_pushes_its_tip(fx):
    git(fx["wt"], "add", "-A")
    git(fx["wt"], "commit", "-qm", "everything")
    r, res = run(fx)
    assert r.returncode == 0, r.stderr
    assert res["stashCommit"] is None and res["refs"] == ["refs/heads/feat/x"]
    tip = git(fx["wt"], "rev-parse", "HEAD").stdout.strip()
    assert git(fx["remote"], "rev-parse", res["pushRef"]).stdout.strip() == tip


def test_unknown_branch_is_usage_error_and_writes_nothing(fx):
    r = subprocess.run(["python3", str(TOOL), "--repo", "fx", "--branch", "nope", "--worktree", str(fx["wt"]), "--json"],
                       capture_output=True, text=True, env={**os.environ, "ADE_RESCUE_ROOT": str(fx["root"])})
    assert r.returncode == 2 and json.loads(r.stdout)["ok"] is False
    assert not fx["root"].exists()


def test_failed_local_rescue_exits_one_and_leaves_no_partial_dir(fx):
    unreadable = fx["wt"] / "new dir" / "u.txt"
    os.chmod(unreadable, 0o000)  # the tar step fails after the bundle is already in the temp directory
    try:
        r, res = run(fx)
    finally:
        os.chmod(unreadable, 0o600)
    assert r.returncode == 1 and res["ok"] is False
    assert list((fx["root"] / "fx").iterdir()) == []
    assert git(fx["remote"], "for-each-ref", "refs/heads/rescue/").stdout == ""  # no push without a local rescue
