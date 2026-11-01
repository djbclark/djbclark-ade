#!/usr/bin/env python3
"""bigteam-prune.py: remove finished fan-out checkouts under ~/.local/state/bigteam without losing work or reports
(skills/diskfree step 7; operator's go first).

This script DELETES directories, so every check fails closed: any error, timeout or doubt keeps the checkout.

Only task dirs (real directories directly under the root, never symlinks, never resolving outside it) at least 7 days
old, with no CLAIM file (a CLAIM that records DONE still blocks) and no unfinished job record (jobs/*.json without
`finished`). Inside them, a git checkout is removed only when ALL of this holds:
  - git itself says the checkout's top level is that directory (a broken `.git` never falls through to an enclosing
    repository), with every GIT_* environment variable cleared for every git call;
  - nothing in the checkout changed in the last 7 days (newest mtime of the directory, index, HEAD, HEAD reflog,
    FETCH_HEAD), and no rebase, merge, cherry-pick, revert, bisect or sequencer is in progress;
  - `git status --porcelain=v1 -z --ignored=matching` run with untracked files forced on and submodules never ignored
    lists nothing but ignored paths; no tracked file is marked assume-unchanged or skip-worktree; no submodule;
  - at least one remote is configured;
  - an IGNORED path is only allowed when it is a known generated directory (node_modules .venv venv __pycache__
    .pytest_cache .mypy_cache .ruff_cache .cache .gradle) holding no nested git repository; any other ignored file or
    directory (a report, an `out.rc`, a database, a scratch repo) keeps the checkout;
  - a linked worktree: a standard `<main>/.git/worktrees/NAME` worktree whose HEAD is on a remote-tracking branch; it is
    removed with `git worktree remove` (no --force) from its main repository, so its branch and commits stay there;
  - a clone: `git worktree list` lists only itself, no stash, and nothing in ANY ref (branches, tags, notes, HEAD, so a
    detached HEAD too) or reflog is missing from the remote-tracking refs.
"On a remote" means the local remote-tracking refs; they are never fetched or verified, so a branch deleted upstream, or
a remote that is a local path, still counts. Safety is re-checked right before each deletion. Everything kept is
printed with its reason.

bigteam-prune.py [--apply]     (without --apply: dry run, prints the plan)
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

B = Path.home() / ".local/state/bigteam"
MIN_AGE = 7 * 86400
GENERATED = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache", ".gradle"}
STATE_PATHS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "sequencer")


def git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(d, *a, timeout=120):
    """(returncode, stdout); 124 on timeout, 127 when git cannot run. Never raises."""
    cmd = ["git", "-c", "status.showUntrackedFiles=all", "-c", "core.fsmonitor=false", "-C", str(d), *a]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="surrogateescape", timeout=timeout, env=git_env())
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""


def root_resolved():
    return B.resolve()


def inside_root(p):
    try:
        return p.resolve().is_relative_to(root_resolved())
    except (OSError, RuntimeError):
        return False


def task_dirs():
    """Real directories directly under B: a symlink, or anything resolving elsewhere, is skipped."""
    root = root_resolved()
    out = []
    for p in sorted(B.iterdir()):
        if p.is_symlink() or not p.is_dir():
            continue
        try:
            if p.resolve().parent != root:
                continue
        except (OSError, RuntimeError):
            continue
        out.append(p)
    return out


def finished_dir(d):
    try:
        if time.time() - d.stat().st_mtime < MIN_AGE or os.path.lexists(d / "CLAIM"):
            return False
        jobs = d / "jobs"
        if jobs.is_symlink():
            return False
        for j in jobs.glob("*.json") if jobs.is_dir() else []:
            if not json.loads(j.read_text()).get("finished"):
                return False
    except (OSError, ValueError, AttributeError):
        return False
    return True


def checkouts(d):
    """Top-most directories under d that are git checkouts (a .git dir, file or link), not descending into them.
    os.walk never follows a symlinked directory."""
    out = []
    for root, dirs, _files in os.walk(d):
        if os.path.lexists(Path(root) / ".git") and Path(root) != d:
            out.append(Path(root))
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if x != ".git"]
    return out


def scan(c):
    """(dirty, ignored_paths) from `git status`, or None when it cannot be read. Untracked files are forced on and
    submodules never ignored, whatever the repository's config says; -z gives raw, unquoted paths."""
    rc, out = git(c, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=all", "--ignore-submodules=none")
    if rc:
        return None
    ignored = []
    for e in out.split("\0"):
        if not e:
            continue
        if e.startswith("!! "):
            ignored.append(e[3:])
        else:
            return True, ignored
    return False, ignored


def ignored_ok(c, rel):
    """An ignored path is expendable only when it is a real generated directory with no nested git repository."""
    rel = rel.rstrip("/")
    if rel.rsplit("/", 1)[-1] not in GENERATED:
        return False
    p = c / rel
    if p.is_symlink() or not p.is_dir():
        return False
    for _root, dirs, files in os.walk(p):
        if ".git" in dirs or ".git" in files:
            return False
    return True


def git_path(c, name):
    rc, out = git(c, "rev-parse", "--path-format=absolute", "--git-path", name)
    return Path(out.strip()) if rc == 0 and out.strip() else None


def newest_activity(c):
    t = c.stat().st_mtime
    for name in ("index", "HEAD", "logs/HEAD", "FETCH_HEAD"):
        p = git_path(c, name)
        if p is None:
            raise OSError(name)
        try:
            t = max(t, p.stat().st_mtime)
        except FileNotFoundError:
            pass
    return t


def identity(c):
    """(None, 'linked'|'clone') when c is a standard checkout git agrees about, else (reason, None)."""
    gp = c / ".git"
    if c.is_symlink() or gp.is_symlink() or not inside_root(c):
        return "symlink or outside the bigteam root", None
    if not (gp.is_file() or gp.is_dir()):
        return ".git is neither a file nor a directory", None
    rc, top = git(c, "rev-parse", "--show-toplevel")
    if rc or not top.strip() or os.path.realpath(top.strip()) != os.path.realpath(c):
        return "git does not report this directory as its own top level (unreadable)", None
    rc1, gitdir = git(c, "rev-parse", "--path-format=absolute", "--absolute-git-dir")
    rc2, common = git(c, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc1 or rc2:
        return "git dir unreadable", None
    gitdir, common = os.path.realpath(gitdir.strip()), os.path.realpath(common.strip())
    if gp.is_dir():
        if gitdir != common or gitdir != os.path.realpath(gp):
            return "unexpected git dir layout", None
        return None, "clone"
    if Path(common).name != ".git" or Path(gitdir).parent != Path(common) / "worktrees":
        return "not a standard linked worktree (submodule, bare main repository or odd layout)", None
    return None, "linked"


def safe(c):
    why, kind = identity(c)
    if why:
        return False, why
    linked = kind == "linked"
    try:
        if time.time() - newest_activity(c) < MIN_AGE:
            return False, "changed within the last 7 days"
    except OSError:
        return False, "activity unreadable"
    for name in STATE_PATHS:
        p = git_path(c, name)
        if p is None or os.path.lexists(p):
            return False, f"{name} in progress or unreadable"
    rc, flags = git(c, "ls-files", "-v", "-z")
    if rc:
        return False, "index unreadable"
    for e in flags.split("\0"):
        if e and (e[0].islower() or e[0] == "S"):
            return False, "a tracked file is assume-unchanged or skip-worktree (status cannot see its changes)"
    rc, staged = git(c, "ls-files", "--stage", "-z")
    if rc:
        return False, "index unreadable"
    if any(e.startswith("160000 ") for e in staged.split("\0")):
        return False, "has submodules (their unpushed commits live inside the checkout)"
    res = scan(c)
    if res is None:
        return False, "status unreadable"
    dirty, ignored = res
    if dirty:
        return False, "uncommitted or untracked files"
    odd = [i for i in ignored if not ignored_ok(c, i)]
    if odd:
        return False, f"holds ignored files of its own ({odd[0]!r}...)" if len(odd) > 1 else f"holds an ignored file of its own ({odd[0]!r})"
    rc, rem = git(c, "remote")
    if rc or not rem.split():
        return False, "no remote"
    if linked:
        # a linked worktree's branches live in its main repository and survive `git worktree remove`;
        # only its checked-out commit must exist on a remote-tracking ref
        rc, on = git(c, "branch", "-r", "--contains", "HEAD")
        if rc or not on.strip():
            return False, "HEAD is on no remote branch"
    else:
        rc, wl = git(c, "worktree", "list", "--porcelain")
        trees = [ln[len("worktree "):] for ln in wl.splitlines() if ln.startswith("worktree ")]
        if rc or len(trees) != 1 or os.path.realpath(trees[0]) != os.path.realpath(c):
            return False, "other linked worktrees are attached to this clone (or the list is unreadable)"
        rc, stash = git(c, "stash", "list")
        if rc or stash.strip():
            return False, "has stashes (or unreadable)"
        rc, un = git(c, "log", "--oneline", "--all", "--not", "--remotes")
        if rc or un.strip():
            return False, f"{len(un.splitlines())} commit(s) on a branch, tag, HEAD or other ref not on a remote (or unreadable)"
        rc, un = git(c, "rev-list", "--reflog", "--not", "--remotes")
        if rc or un.strip():
            return False, f"{len(un.split())} reflog-only commit(s) not on a remote (or unreadable)"
    return True, "clean; commits on a remote" + ("; branch kept in main repo" if linked else "")


def remove(c):
    """(removed, message). Re-checks safety right before deleting."""
    ok, why = safe(c)
    if not ok:
        return False, f"no longer safe: {why}"
    if (c / ".git").is_file():  # a linked worktree: remove through its main repository
        rc, common = git(c, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc:
            return False, "git worktree remove not run: common dir unreadable"
        common = Path(os.path.realpath(common.strip()))
        main = common.parent
        rc, mc = git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc or os.path.realpath(mc.strip()) != str(common):
            return False, f"git worktree remove not run: {main} is not the main repository"
        rc, _ = git(main, "worktree", "remove", str(c))
        return (True, "worktree removed") if rc == 0 else (False, "git worktree remove failed")
    try:
        shutil.rmtree(c)
    except OSError as e:
        return False, f"rmtree failed part way: {e}"
    return True, "clone deleted"


def size_kb(c):
    try:
        r = subprocess.run(["du", "-sk", str(c)], capture_output=True, text=True, timeout=300)
        return int(r.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def main():
    apply = "--apply" in sys.argv
    plan, kept, freed = [], [], 0
    for d in task_dirs():
        if not finished_dir(d):
            continue
        for c in checkouts(d):
            ok, why = safe(c)
            (plan if ok else kept).append((c, size_kb(c), why))
    for c, size, why in plan:
        ok, res = remove(c) if apply else (True, "would remove")
        if ok and apply:
            freed += size
        print(f"{'REMOVED' if apply and ok else ('KEPT' if apply else 'PLAN')} {size/1024:7.1f} MB {c} ({res})")
    for c, size, why in kept:
        print(f"KEEP    {size/1024:7.1f} MB {c} ({why})")
    print(f"{'freed' if apply else 'would free'}: {freed/1048576 if apply else sum(s for _, s, _ in plan)/1048576:.2f} GB; kept {len(kept)} checkout(s)")


if __name__ == "__main__":
    main()
