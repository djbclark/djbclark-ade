#!/usr/bin/env python3
"""bigteam-prune.py: remove finished fan-out checkouts under ~/.local/state/bigteam without losing work or reports
(skills/diskfree step 7; operator's go first).

Only task dirs at least 7 days old, with no unfinished job record (jobs/*.json without `finished`) and no CLAIM file.
Inside them, a git checkout is removed when:
  - a linked worktree: `git status --porcelain` is empty and HEAD is on a remote branch; it is removed with
    `git worktree remove` from its main repository, so its branch and commits stay there;
  - a clone: the same clean check, every branch pushed, and no stash.
Report files are never removed, and a checkout holding an IGNORED report-like file (.md .json .txt .log .jsonl .diff
.patch .done .exit) is kept. Everything kept is printed with its reason.

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
KEEP_SUFFIX = {".md", ".json", ".txt", ".log", ".jsonl", ".diff", ".patch", ".done", ".exit"}


def git(d, *a, timeout=120):
    try:
        r = subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


def finished_dir(d):
    if time.time() - d.stat().st_mtime < 7 * 86400 or (d / "CLAIM").exists():
        return False
    for j in (d / "jobs").glob("*.json") if (d / "jobs").is_dir() else []:
        try:
            if not json.loads(j.read_text()).get("finished"):
                return False
        except (OSError, ValueError):
            return False
    return True


def checkouts(d):
    """Top-most directories under d that are git checkouts (a .git dir or file), not descending into them."""
    out = []
    for root, dirs, _files in os.walk(d):
        if (Path(root) / ".git").exists() and Path(root) != d:
            out.append(Path(root))
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if x != ".git"]
    return out


def has_reports(p):
    """True when the checkout holds a report-like file git does not track (an ignored file: untracked ones already
    fail the clean check). Tracked files are in the repository's history and on a remote, so they are not lost."""
    rc, out = git(p, "status", "--porcelain", "--ignored")
    if rc:
        return True
    for line in out.splitlines():
        if line.startswith("!! "):
            path = p / line[3:].rstrip("/")
            if path.is_file() and path.suffix in KEEP_SUFFIX:
                return True
            if path.is_dir() and any(Path(f).suffix in KEEP_SUFFIX for _r, _d, fs in os.walk(path) for f in fs):
                return True
    return False


def safe(c):
    linked = (c / ".git").is_file()
    # untracked files count too: removing the checkout would lose them
    rc, st = git(c, "status", "--porcelain")
    if rc or st.strip():
        return False, "uncommitted or untracked files, or unreadable"
    rc, rem = git(c, "remote")
    if rc or not rem.split():
        return False, "no remote"
    if linked:
        # a linked worktree's branches live in its main repository and survive `git worktree remove`;
        # only its checked-out commit must exist on a remote
        rc, on = git(c, "branch", "-r", "--contains", "HEAD")
        if rc or not on.strip():
            return False, "HEAD is on no remote branch"
    else:
        rc, un = git(c, "log", "--oneline", "--branches", "--not", "--remotes")
        if rc or un.strip():
            return False, f"{len(un.splitlines())} unpushed commit(s)"
        rc, stash = git(c, "stash", "list")
        if stash.strip():
            return False, "has stashes"
    if has_reports(c):
        return False, "holds report files of its own"
    return True, "clean; commits on a remote" + ("; branch kept in main repo" if linked else "")


def remove(c):
    gitpath = c / ".git"
    if gitpath.is_file():  # a linked worktree: remove through its main repository
        rc, common = git(c, "rev-parse", "--path-format=absolute", "--git-common-dir")
        main = Path(common.strip()).parent if rc == 0 else None
        if main and main.exists():
            rc2, _ = git(main, "worktree", "remove", str(c))
            if rc2 == 0:
                return "worktree removed"
        return None
    shutil.rmtree(c)
    return "clone deleted"


def main():
    apply = "--apply" in sys.argv
    plan, kept, freed = [], [], 0
    for d in sorted(p for p in B.iterdir() if p.is_dir()):
        if not finished_dir(d):
            continue
        for c in checkouts(d):
            ok, why = safe(c)
            size = int(subprocess.run(["du", "-sk", str(c)], capture_output=True, text=True).stdout.split()[0] or 0)
            (plan if ok else kept).append((c, size, why))
    for c, size, why in plan:
        res = remove(c) if apply else "would remove"
        if res:
            freed += size
        print(f"{'REMOVED' if apply and res else ('KEPT' if apply else 'PLAN')} {size/1024:7.1f} MB {c} ({res or 'git worktree remove failed'})")
    for c, size, why in kept:
        print(f"KEEP    {size/1024:7.1f} MB {c} ({why})")
    print(f"{'freed' if apply else 'would free'}: {freed/1048576 if apply else sum(s for _, s, _ in plan)/1048576:.2f} GB; kept {len(kept)} checkout(s)")


if __name__ == "__main__":
    main()
