"""skills/diskfree/scripts/bigteam-prune.py deletes directories: every case here is a checkout that must be KEPT, plus
the clean pushed clone and linked worktree that must go. Hermetic: fixture repos under tmp_path with a bare 'remote'."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills/diskfree/scripts/bigteam-prune.py"


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return env


def g(cwd, *args, env=None):
    r = subprocess.run(["git", "-c", "protocol.file.allow=always", *args], cwd=cwd, capture_output=True, text=True,
                       env=env or _env())
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def rm(prune, c):
    """prune.remove with the task dir (the checkout's parent) judged eligible right now."""
    task = c.parent
    return prune.remove(c, task, {task: task.stat().st_mtime})


def commit(repo, name, text="x\n", msg=None):
    (Path(repo) / name).write_text(text)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", msg or f"add {name}")
    return g(repo, "rev-parse", "HEAD")


@pytest.fixture
def prune(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bigteam_prune", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "B", tmp_path / "bt")
    monkeypatch.setattr(m, "MIN_AGE", 0)
    (tmp_path / "bt").mkdir()
    return m


@pytest.fixture
def world(tmp_path):
    """A bare remote with one pushed commit on main; returns the remote path."""
    remote = tmp_path / "remote.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = tmp_path / "seed"
    g(tmp_path, "init", "-q", "-b", "main", str(seed))
    commit(seed, "README", "hello\n")
    g(seed, "remote", "add", "origin", str(remote))
    g(seed, "push", "-q", "origin", "main")
    return remote


def make_clone(tmp_path, remote, task="task1", name="clone"):
    d = tmp_path / "bt" / task
    d.mkdir(parents=True, exist_ok=True)
    g(tmp_path, "clone", "-q", str(remote), str(d / name))
    return d / name


def test_clean_pushed_clone_is_removed(prune, tmp_path, world, capsys, monkeypatch):
    c = make_clone(tmp_path, world)
    assert prune.safe(c)[0]
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert not c.exists()
    assert "REMOVED" in capsys.readouterr().out


def test_clean_pushed_linked_worktree_is_removed_and_branch_kept(prune, tmp_path, world):
    main = tmp_path / "mainrepo"
    g(tmp_path, "clone", "-q", str(world), str(main))
    d = tmp_path / "bt" / "task1"
    d.mkdir()
    wt = d / "wt"
    g(main, "worktree", "add", "-q", "-b", "worker", str(wt))
    ok, why = prune.safe(wt)
    assert ok, why
    assert rm(prune, wt) == (True, "worktree removed")
    assert not wt.exists()
    assert "worker" in g(main, "branch", "--list", "worker")


def test_detached_head_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "checkout", "-q", "--detach")
    commit(c, "secret", "detached work\n")
    ok, why = prune.safe(c)
    assert not ok and "not on a remote" in why
    assert rm(prune, c)[0] is False
    assert c.exists()


def test_tag_only_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "checkout", "-q", "--detach")
    commit(c, "t")
    g(c, "tag", "keepme")
    g(c, "checkout", "-q", "main")
    assert not prune.safe(c)[0]


def test_reflog_only_commit_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, "dropped", "lost soon\n")
    g(c, "reset", "-q", "--hard", "origin/main")
    ok, why = prune.safe(c)
    assert not ok and "reflog" in why


def test_unpushed_branch_commit_and_stash_are_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world, name="a")
    commit(c, "new")
    assert not prune.safe(c)[0]
    c2 = make_clone(tmp_path, world, name="b")
    (c2 / "README").write_text("changed\n")
    g(c2, "stash", "-q")
    ok, why = prune.safe(c2)
    assert not ok and "stash" in why


def test_clone_with_external_worktree_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    ext = tmp_path / "elsewhere"
    g(c, "worktree", "add", "-q", "-b", "other", str(ext))
    ok, why = prune.safe(c)
    assert not ok and "worktrees" in why
    assert rm(prune, c)[0] is False
    assert c.exists() and ext.exists()


@pytest.mark.parametrize("fname", ["my report.md", 'qu"ote.json', "caf\u00e9.txt", "out.rc"])
def test_ignored_report_with_odd_name_is_kept(prune, tmp_path, world, fname):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "*\n!.gitignore\n!README\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / fname).write_text("report\n")
    assert g(c, "status", "--porcelain", "--ignored")  # git does list it (quoted); the script must still see it
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why
    assert rm(prune, c)[0] is False
    assert (c / fname).exists()


def test_generated_ignored_dir_does_not_keep_a_clean_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / "node_modules/pkg").mkdir(parents=True)
    (c / "node_modules/pkg/index.json").write_text("{}\n")
    ok, why = prune.safe(c)
    assert ok, why


def test_generated_dir_with_nested_repo_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / "node_modules/dep").mkdir(parents=True)
    g(c / "node_modules/dep", "init", "-q")
    assert not prune.safe(c)[0]


def test_untracked_file_seen_despite_show_untracked_no(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    g(c, "config", "status.showUntrackedFiles", "no")
    (c / "notes.txt").write_text("unsaved\n")
    assert g(c, "status", "--porcelain") == ""  # the config really hides it
    ok, why = prune.safe(c)
    assert not ok and "untracked" in why
    assert rm(prune, c)[0] is False


def test_submodule_checkout_is_kept(prune, tmp_path, world):
    sub = tmp_path / "subsrc"
    g(tmp_path, "init", "-q", "-b", "main", str(sub))
    commit(sub, "s")
    c = make_clone(tmp_path, world)
    g(c, "submodule", "add", "-q", str(sub), "vendor/sub")
    g(c, "commit", "-q", "-m", "sub")
    g(c, "push", "-q", "origin", "HEAD:main")
    ok, why = prune.safe(c)
    assert not ok and "submodule" in why


def test_dirty_submodule_is_not_clean_even_if_config_ignores_it(prune, tmp_path, world):
    sub = tmp_path / "subsrc"
    g(tmp_path, "init", "-q", "-b", "main", str(sub))
    commit(sub, "s")
    c = make_clone(tmp_path, world)
    g(c, "submodule", "add", "-q", str(sub), "vendor/sub")
    g(c, "config", "submodule.vendor/sub.ignore", "all")
    (c / "vendor/sub/new.txt").write_text("u\n")
    dirty, _ = prune.scan(c)
    assert dirty


def test_git_env_leak_cannot_redirect_the_checks(prune, tmp_path, world, monkeypatch):
    clean = make_clone(tmp_path, world, name="clean")
    dirty = make_clone(tmp_path, world, name="dirty")
    (dirty / "wip.txt").write_text("wip\n")
    monkeypatch.setenv("GIT_DIR", str(clean / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(clean))
    ok, why = prune.safe(dirty)
    assert not ok and "untracked" in why


def test_rebase_in_progress_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    (c / ".git/rebase-merge").mkdir()
    ok, why = prune.safe(c)
    assert not ok and "rebase-merge" in why


def test_recent_activity_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "MIN_AGE", 7 * 86400)
    ok, why = prune.safe(c)
    assert not ok and "7 days" in why


def test_symlinked_task_dir_is_skipped(prune, tmp_path, world, capsys, monkeypatch):
    outside = tmp_path / "outside"
    c = make_clone(tmp_path, world, task="real")
    (tmp_path / "bt" / "real").rename(outside)
    (tmp_path / "bt" / "link").symlink_to(outside)
    assert prune.task_dirs() == []
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert (outside / "clone").exists()
    assert "REMOVED" not in capsys.readouterr().out


def test_symlinked_checkout_is_never_followed(prune, tmp_path, world):
    real = tmp_path / "realclone"
    g(tmp_path, "clone", "-q", str(world), str(real))
    d = tmp_path / "bt" / "task1"
    d.mkdir()
    (d / "ln").symlink_to(real)
    assert prune.checkouts(d) == []
    ok, why = prune.safe(d / "ln")
    assert not ok
    assert real.exists()


def test_unfinished_job_record_and_claim_keep_the_dir(prune, tmp_path, world):
    c = make_clone(tmp_path, world, task="a")
    (c.parent / "jobs").mkdir()
    (c.parent / "jobs/j.json").write_text("{}")
    assert not prune.finished_dir(c.parent)
    c2 = make_clone(tmp_path, world, task="b")
    (c2.parent / "CLAIM").write_text("DONE 2026-10-13\n")
    assert not prune.finished_dir(c2.parent)
    c3 = make_clone(tmp_path, world, task="c")
    assert prune.finished_dir(c3.parent)


# ---- round 3 -------------------------------------------------------------------------------------------------------


def make_main_with_worktree(tmp_path, remote, branch=None):
    """A main repository OUTSIDE the bigteam root with a linked worktree inside it; returns (main, worktree)."""
    main = tmp_path / "mainrepo"
    g(tmp_path, "clone", "-q", str(remote), str(main))
    d = tmp_path / "bt" / "task1"
    d.mkdir(parents=True, exist_ok=True)
    wt = d / "wt"
    if branch:
        g(main, "worktree", "add", "-q", "-b", branch, str(wt))
    else:
        g(main, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    return main, wt


def test_linked_worktree_detached_reflog_only_commit_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    x = commit(wt, "x", "detached work\n")
    g(wt, "checkout", "-q", "--detach", "origin/main")
    ok, why = prune.safe(wt)
    assert not ok and "reflog" in why
    assert rm(prune, wt)[0] is False
    assert wt.exists()
    assert x  # the commit is only in the worktree's HEAD reflog


def test_linked_worktree_with_per_worktree_ref_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    y = commit(wt, "y", "kept on a worktree ref\n")
    g(wt, "update-ref", "refs/worktree/keep", y)
    g(wt, "checkout", "-q", "--detach", "origin/main")
    ok, why = prune.safe(wt)
    assert not ok and "per-worktree refs" in why
    assert rm(prune, wt)[0] is False
    assert wt.exists()


def test_clean_detached_linked_worktree_is_removed_and_says_no_branch(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    ok, why = prune.safe(wt)
    assert ok, why
    assert "detached" in why and "branch kept" not in why
    assert rm(prune, wt) == (True, "worktree removed")


def test_linked_worktree_commit_kept_on_its_branch_is_removed(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world, branch="worker")
    commit(wt, "w", "on a branch, pushed\n")
    g(wt, "push", "-q", "origin", "worker")
    ok, why = prune.safe(wt)
    assert ok, why


def test_siblings_that_are_each_others_remote_are_both_kept(prune, tmp_path, world):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    commit(a, "z", "only here\n")
    g(b, "remote", "add", "a", str(a))
    g(b, "fetch", "-q", "a")
    g(b, "merge", "-q", "--ff-only", "a/main")
    g(a, "remote", "add", "b", str(b))
    g(a, "fetch", "-q", "b")
    for c in (a, b):
        ok, why = prune.safe(c)
        assert not ok and "local path inside the bigteam root" in why


@pytest.mark.parametrize("style", ["file", "relative"])
def test_local_path_remote_inside_root_is_kept_in_any_spelling(prune, tmp_path, world, style):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    url = f"file://{a}" if style == "file" else "../a"
    g(b, "remote", "add", "sib", url)
    ok, why = prune.safe(b)
    assert not ok and "local path inside the bigteam root" in why


def test_remote_path_outside_root_still_counts(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    assert prune.local_remote_inside_root(c) is None


def test_ignored_report_under_dot_cache_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", ".cache/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    (c / ".cache").mkdir()
    (c / ".cache/adv-report.md").write_text("findings\n")
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why


@pytest.mark.parametrize("what", ["note", "hook", "exclude", "lfs", "config.worktree"])
def test_unusual_git_dir_content_keeps_the_clone(prune, tmp_path, world, what):
    c = make_clone(tmp_path, world)
    gd = c / ".git"
    if what == "note":
        (gd / "NOTES.md").write_text("notes\n")
    elif what == "hook":
        (gd / "hooks/pre-push").write_text("#!/bin/sh\n")
    elif what == "exclude":
        (gd / "info/exclude").write_text("*.secret\n")
    elif what == "lfs":
        (gd / "lfs").mkdir()
    else:
        (gd / "config.worktree").write_text("[core]\n")
    ok, why = prune.safe(c)
    assert not ok and "git dir" in why
    assert rm(prune, c)[0] is False
    assert c.exists()


def test_linked_worktree_git_dir_note_is_kept(prune, tmp_path, world):
    main, wt = make_main_with_worktree(tmp_path, world)
    gd = Path(g(wt, "rev-parse", "--absolute-git-dir"))
    (gd / "NOTES.md").write_text("notes\n")
    ok, why = prune.safe(wt)
    assert not ok and "git dir" in why


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unreadable_dir_inside_generated_dir_keeps_the_clone(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    hidden = c / "node_modules/a/hidden"
    hidden.mkdir(parents=True)
    hidden.chmod(0)
    try:
        assert prune.ignored_ok(c, "node_modules/") is False
    finally:
        hidden.chmod(0o755)


def test_failed_rmtree_is_reported_not_counted(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)

    def boom(path):
        raise OSError("disk says no")

    monkeypatch.setattr(prune.shutil, "rmtree", boom)
    ok, msg = rm(prune, c)
    assert ok is False and "half deleted" in msg


def test_second_apply_is_refused_while_the_lock_is_held(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    fd = prune.take_lock()
    assert fd is not None
    try:
        monkeypatch.setattr(sys, "argv", ["x", "--apply"])
        with pytest.raises(SystemExit) as e:
            prune.main()
        assert e.value.code == 3
        assert c.exists()
    finally:
        os.close(fd)
    fd = prune.take_lock()
    assert fd is not None  # released: a later run may take it
    os.close(fd)


# ---- round 4 (local Codex review of c7bccd76: three P1s) --------------------------------------------------------


def _siblings_with_remote(prune, tmp_path, world, url_for):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    commit(a, "z", "only here\n")
    g(b, "remote", "add", "sib", url_for(a))
    return a, b


def test_percent_encoded_file_url_remote_inside_root_is_kept(prune, tmp_path, world):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    # git decodes %XX in file:// URLs: .../%62t/... is .../bt/... (the encoded spelling does not exist on disk)
    enc = str(a).replace("/bt/", "/%62t/")
    assert enc != str(a)
    g(b, "remote", "add", "sib", f"file://{enc}")
    assert "%62t" in (prune.local_remote_inside_root(b) or "")
    ok, why = prune.safe(b)
    assert not ok and "bigteam root" in why


def test_file_url_with_foreign_host_or_helper_transport_cannot_be_resolved_and_is_kept(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    for url in ("file://somehost/tmp/x", "ext::sh -c true", "weird://x/y", "hg::file:///tmp/x"):
        g(c, "remote", "add", "odd", url)
        why = prune.local_remote_inside_root(c)
        assert why and "cannot be resolved" in why, url
        g(c, "remote", "remove", "odd")


@pytest.mark.parametrize("url", ["https://github.com/o/r.git", "git@github.com:o/r.git", "ssh://git@github.com/o/r.git"])
def test_ordinary_network_remotes_do_not_keep_a_clone(prune, tmp_path, world, url, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h: h)
    g(c, "remote", "add", "gh", url)
    assert prune.local_remote_inside_root(c) is None


@pytest.mark.parametrize("url", ["ssh://localhost/tmp/x", "me@localhost:tmp/x", "git://127.0.0.1/x", "http://[::1]/x"])
def test_network_urls_to_this_machine_are_kept(prune, tmp_path, world, url, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h: h)
    g(c, "remote", "add", "loc", url)
    assert prune.local_remote_inside_root(c)


def test_ssh_alias_resolving_to_this_machine_is_kept(prune, tmp_path, world, monkeypatch):
    c = make_clone(tmp_path, world)
    monkeypatch.setattr(prune, "ssh_real_host", lambda h: "localhost")
    g(c, "remote", "add", "alias", "myalias:work/x")
    assert prune.local_remote_inside_root(c)


def test_bare_repository_inside_generated_dir_keeps_the_checkout(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "node_modules/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    bare = c / "node_modules/cache/scratch.git"
    bare.parent.mkdir(parents=True)
    g(tmp_path, "init", "-q", "--bare", str(bare))
    ok, why = prune.safe(c)
    assert not ok and "ignored" in why
    assert rm(prune, c)[0] is False
    assert bare.exists()


def test_bare_repository_as_the_generated_dir_itself_keeps_the_checkout(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    commit(c, ".gitignore", "venv/\n")
    g(c, "push", "-q", "origin", "HEAD:main")
    g(tmp_path, "init", "-q", "--bare", str(c / "venv"))
    assert prune.ignored_ok(c, "venv/") is False


def _planned(prune, tmp_path, world):
    c = make_clone(tmp_path, world)
    task = c.parent
    baseline = {task: task.stat().st_mtime}
    return c, task, baseline


def test_claim_added_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "CLAIM").write_text("working\n")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert c.exists()


def test_unfinished_job_added_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "jobs").mkdir()
    (task / "jobs/j.json").write_text("{}")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert c.exists()


def test_task_dir_touched_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    (task / "new-notes.txt").write_text("someone is here\n")
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "changed since planning" in msg
    assert c.exists()


def test_task_dir_turned_into_a_symlink_after_planning_stops_the_deletion(prune, tmp_path, world):
    c, task, baseline = _planned(prune, tmp_path, world)
    moved = tmp_path / "moved"
    task.rename(moved)
    task.symlink_to(moved)
    ok, msg = prune.remove(c, task, baseline)
    assert not ok and "no longer eligible" in msg
    assert (moved / "clone").exists()


def test_two_checkouts_in_one_task_are_both_removed(prune, tmp_path, world, monkeypatch, capsys):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    assert not a.exists() and not b.exists()
    assert capsys.readouterr().out.count("REMOVED") == 2


def test_claim_appearing_between_two_removals_keeps_the_second(prune, tmp_path, world, monkeypatch, capsys):
    a = make_clone(tmp_path, world, task="t1", name="a")
    b = make_clone(tmp_path, world, task="t1", name="b")
    real = prune._remove

    def remove_then_claim(c):
        res = real(c)
        (c.parent / "CLAIM").write_text("a session just started here\n")
        return res

    monkeypatch.setattr(prune, "_remove", remove_then_claim)
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    prune.main()
    out = capsys.readouterr().out
    assert out.count("REMOVED") == 1 and "no longer eligible" in out
    assert sum(p.exists() for p in (a, b)) == 1
