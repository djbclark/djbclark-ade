#!/usr/bin/env python3
"""rumination-watch must bring ITS OWN checkout forward, or say why it cannot.

The launchd job executes a tracked file in the shared djbclark-ade checkout, so a merge reaches it
only when that checkout moves. On 2026-10-29 it did not: the fix for "the entity never hears the
watcher" was merged (956d5b38) and the job kept running pre-fix code for hours while `last pass`
looked healthy. These tests pin the fast-forward, and — because the directory is SHARED with other
sessions — every case where moving it would destroy someone else's work.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return p.stdout.strip()


def commit(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    """(the checkout the job runs from, an upstream clone to move origin, origin's HEAD).

    `origin` is a bare repo so a push is the only way to be "upstream", exactly as on GitHub.
    """
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "--bare", "-q", "-b", "master")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "master")
    git(seed, "config", "user.email", "t@example.com")
    git(seed, "config", "user.name", "t")
    base = commit(seed, "code.txt", "v1\n", "base")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "master")
    # The job's checkout: cloned from origin, so its HEAD is an ancestor of anything pushed later.
    checkout = tmp_path / "ade"
    git(tmp_path, "clone", "-q", str(origin), str(checkout))
    git(checkout, "config", "user.email", "t@example.com")
    git(checkout, "config", "user.name", "t")
    # A second clone stands in for whatever session merged upstream.
    upstream = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(origin), str(upstream))
    git(upstream, "config", "user.email", "t@example.com")
    git(upstream, "config", "user.name", "t")
    return checkout, upstream, base


def load(monkeypatch, tmp_path: Path, checkout: Path):
    loader = importlib.machinery.SourceFileLoader(
        "rumination_watch_deploy", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    state = tmp_path / "state"
    monkeypatch.setattr(rw, "SELF_REPO", checkout)
    monkeypatch.setattr(rw, "STATE_DIR", state)
    monkeypatch.setattr(rw, "LOG", state / "rumination.log")
    monkeypatch.setattr(rw, "HOME", tmp_path)
    monkeypatch.setattr(rw, "REPO", tmp_path / "techno-euphora")
    monkeypatch.setattr(rw, "DEPLOY_OFF", False)
    monkeypatch.setattr(rw, "DEPLOY_COOLDOWN_S", 6 * 3600)
    monkeypatch.setattr(rw, "DEPLOY_TIMEOUT_S", 30)
    return rw


def loglines(rw) -> list[str]:
    return rw.LOG.read_text().splitlines() if rw.LOG.exists() else []


def test_a_merged_fix_reaches_the_job_on_the_next_pass(monkeypatch, tmp_path):
    """The whole point: origin moves, the checkout follows, and the log says so."""
    checkout, upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")

    word = rw.deploy_update({}, 0.0)

    assert git(checkout, "rev-parse", "HEAD") == new
    assert word == f"updated {base[:10]} -> {new[:10]}"
    assert any(f"deploy updated {base[:10]} -> {new[:10]}" in line for line in loglines(rw))


def test_a_current_checkout_is_silent(monkeypatch, tmp_path):
    """Every 300 s is 288 log lines a day; "nothing to do" must not be one of them."""
    checkout, _upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)

    assert rw.deploy_update({}, 0.0) == ""
    assert rw.deploy_update({}, 400.0) == ""
    assert loglines(rw) == []


def test_uncommitted_work_in_the_shared_checkout_is_never_touched(monkeypatch, tmp_path):
    """Another session's staged edit lives here; a fast-forward would rewrite it under them."""
    checkout, upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    (checkout / "code.txt").write_text("someone else's half-finished edit\n")

    word = rw.deploy_update({}, 0.0)

    assert word == "skipped: checkout has uncommitted changes"
    assert not git(checkout, "rev-parse", "HEAD") == new
    assert (checkout / "code.txt").read_text() == "someone else's half-finished edit\n"
    assert any("uncommitted path(s)" in line for line in loglines(rw))


def test_untracked_files_do_not_block_the_update(monkeypatch, tmp_path):
    """git will not touch an untracked file, so the job's own state/log beside it must not stall it."""
    checkout, upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    (checkout / "scratch-note.md").write_text("mine\n")

    assert rw.deploy_update({}, 0.0).startswith("updated ")
    assert git(checkout, "rev-parse", "HEAD") == new
    assert (checkout / "scratch-note.md").read_text() == "mine\n"


def test_a_revision_that_would_overwrite_an_ignored_local_file_is_refused(monkeypatch, tmp_path):
    """`git merge` rewrites IGNORED files by default, so the clean-tree check above cannot see this
    collision: the checkout holds a file locally, untracked and gitignored, and the incoming revision
    starts tracking that same path. Ordinary untracked files are safe from `git merge`; ignored ones
    are not (`--overwrite-ignore` is the documented default). The local content must survive, which
    only happens because the merge passes `--no-overwrite-ignore`.
    """
    checkout, upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    commit(upstream, ".gitignore", "local.cfg\n", "ignore the local config")
    git(upstream, "push", "-q", "origin", "master")
    assert rw.deploy_update({}, 0.0).startswith("updated ")  # the ignore rule is now in the checkout
    (checkout / "local.cfg").write_text("PRECIOUS LOCAL CONTENT\n")

    (upstream / "local.cfg").write_text("FROM UPSTREAM\n")
    git(upstream, "add", "-f", "local.cfg")
    git(upstream, "commit", "-q", "-m", "start tracking local.cfg")
    new = git(upstream, "rev-parse", "HEAD")
    git(upstream, "push", "-q", "origin", "master")

    word = rw.deploy_update({}, 400.0)

    assert word == "skipped: fast-forward failed"
    assert (checkout / "local.cfg").read_text() == "PRECIOUS LOCAL CONTENT\n"
    assert git(checkout, "rev-parse", "HEAD") != new
    assert any("local.cfg" in line for line in loglines(rw))


def test_local_commits_are_reported_not_merged_or_reset(monkeypatch, tmp_path):
    """A session that committed here without pushing must not have its commit swallowed."""
    checkout, _upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    mine = commit(checkout, "local.txt", "wip\n", "local work")

    word = rw.deploy_update({}, 0.0)

    assert word == "skipped: local commits not on origin"
    assert git(checkout, "rev-parse", "HEAD") == mine
    assert any("not merging, not resetting" in line for line in loglines(rw))


def test_a_git_operation_in_progress_blocks_the_update(monkeypatch, tmp_path):
    """Mid-merge or mid-rebase the checkout is not ours to move."""
    checkout, upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    (checkout / ".git" / "MERGE_HEAD").write_text(new + "\n")

    word = rw.deploy_update({}, 0.0)

    assert word == "skipped: MERGE_HEAD in progress"
    assert git(checkout, "rev-parse", "HEAD") != new


def test_a_repeated_refusal_is_logged_once_per_cooldown(monkeypatch, tmp_path):
    """An unfixable skip would otherwise write the same line 288 times a day."""
    checkout, upstream, _base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    (checkout / "code.txt").write_text("dirty\n")
    state: dict = {}

    one = rw.deploy_update(state, 1000.0)
    two = rw.deploy_update(state, 1000.0 + rw.DEPLOY_COOLDOWN_S - 1)
    three = rw.deploy_update(state, 1000.0 + rw.DEPLOY_COOLDOWN_S + 1)

    assert one == two == three == "skipped: checkout has uncommitted changes"
    assert len(loglines(rw)) == 2


def test_a_failed_fetch_leaves_the_job_running_what_it_has(monkeypatch, tmp_path):
    """Offline or unauthorised is a reason, not a crash: the pass still has to speak."""
    checkout, _upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    git(checkout, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    word = rw.deploy_update({}, 0.0)

    assert word == "skipped: fetch failed"
    assert git(checkout, "rev-parse", "HEAD") == base
    assert any("git fetch origin +refs/heads/master:refs/remotes/origin/master failed" in line
               for line in loglines(rw))


def test_a_detached_head_is_left_alone(monkeypatch, tmp_path):
    checkout, upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    git(checkout, "checkout", "-q", base)

    assert rw.deploy_update({}, 0.0) == "skipped: detached HEAD"
    assert git(checkout, "rev-parse", "HEAD") == base


def test_a_branch_switch_during_the_fetch_is_refused_not_followed(monkeypatch, tmp_path):
    """The checkout is SHARED: a session that changes branch while we fetch must not be tipped over.

    The merge operates on whatever HEAD happens to be, so without a re-read it fast-forwards the
    NEWLY checked-out branch whenever that branch is an ancestor of the fetched tip — and on
    2026-10-29 that was the ordinary case (the job pointed at a PR branch while the checkout sat on
    a clean master that is an ancestor of it by construction). The switch is injected inside the
    fetch, i.e. the widest real window; everything else here is real git.
    """
    checkout, upstream, base = make_repo(tmp_path)
    git(checkout, "branch", "other", base)               # a second local branch at the same commit
    rw = load(monkeypatch, tmp_path, checkout)
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")

    real_git = rw._git
    switched = []

    def git_that_switches_mid_fetch(args, timeout=20):
        if args and args[0] == "fetch" and not switched:
            git(checkout, "checkout", "-q", "other")     # another session, during our fetch
            switched.append(True)
        return real_git(args, timeout=timeout)

    monkeypatch.setattr(rw, "_git", git_that_switches_mid_fetch)

    assert rw.deploy_update({}, 0.0) == "skipped: checkout changed during the fetch"
    assert switched == [True], "the switch never happened: this test proved nothing"
    assert git(checkout, "rev-parse", "HEAD") == base    # nothing followed the fetched tip
    assert git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "other"
    assert any("changed during the fetch" in line for line in loglines(rw))


def test_the_kill_switch_does_nothing_at_all(monkeypatch, tmp_path):
    """RW_NO_DEPLOY=1 is the way out on a machine where this must never move the checkout."""
    checkout, upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    monkeypatch.setattr(rw, "DEPLOY_OFF", True)
    commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")

    assert rw.deploy_update({}, 0.0) == ""
    assert git(checkout, "rev-parse", "HEAD") == base
    assert loglines(rw) == []


def test_status_names_the_running_commit(monkeypatch, tmp_path):
    """`last pass` was healthy while the job ran day-old code; the sha is the honest answer."""
    checkout, _upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    assert rw.running_sha() == base[:10]


def test_status_prints_the_code_that_is_actually_running(monkeypatch, tmp_path, capsys):
    """The `code:` line is the whole reason `status` was worth changing — pin its shape, not just sha()."""
    checkout, _upstream, base = make_repo(tmp_path)
    rw = load(monkeypatch, tmp_path, checkout)
    monkeypatch.setattr(rw, "survey",
                        lambda: {"mail": [], "jobs": [], "prs": [], "stale": None})
    monkeypatch.setattr(rw, "load_state",
                        lambda: {"deploy": {"word": "updated:" + base[:10], "at": 1.0}})

    assert rw.cmd_status(argparse.Namespace()) == 0

    out = capsys.readouterr().out
    assert f"code:  {base[:10]} on master in {checkout}" in out
    assert f"(last deploy: updated:{base[:10]})" in out


def test_a_linked_worktree_is_still_checked_for_an_operation_in_progress(monkeypatch, tmp_path):
    """`.git` is a FILE in a linked worktree, so SELF_REPO/.git/<marker> never exists there: the old
    probe silently passed and the checkout looked free to move while it was mid-merge."""
    checkout, upstream, _base = make_repo(tmp_path)
    wt = tmp_path / "linked"
    git(checkout, "worktree", "add", "-q", "-b", "side", str(wt))
    new = commit(upstream, "code.txt", "v2\n", "the fix")
    git(upstream, "push", "-q", "origin", "master")
    marker = git(wt, "rev-parse", "--git-path", "MERGE_HEAD")
    marker_path = Path(marker) if Path(marker).is_absolute() else wt / marker
    assert not str(marker_path).startswith(str(wt / ".git")), "the marker is NOT under a .git dir"
    marker_path.write_text(new + "\n")
    rw = load(monkeypatch, tmp_path, wt)

    assert rw.deploy_update({}, 0.0) == "skipped: MERGE_HEAD in progress"
    assert git(wt, "rev-parse", "HEAD") != new


def test_a_mistyped_knob_cannot_take_the_watcher_down(monkeypatch, tmp_path):
    """One typo in one env var used to raise at IMPORT, killing the pass, the status and the voice.

    No fixture and no monkeypatched knobs: this loads the module exactly as launchd does and asserts
    the fallbacks, because the failure being pinned happens at load time, before any test helper runs.
    """
    monkeypatch.setenv("RW_DEPLOY_TIMEOUT_S", "1m")
    monkeypatch.setenv("RW_DEPLOY_COOLDOWN_S", "6h")
    monkeypatch.setenv("RW_STUCK_PASSES", "three")
    monkeypatch.setenv("RW_COOLDOWN_S", "6h")
    loader = importlib.machinery.SourceFileLoader("rw_knobs", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)

    loader.exec_module(mod)                               # raised ValueError before the fix

    assert mod.DEPLOY_TIMEOUT_S == 60
    assert mod.DEPLOY_COOLDOWN_S == 6 * 3600
    assert mod.SEAT_STUCK_PASSES == 3
    assert mod.DJB_COOLDOWN_S == 6 * 3600
