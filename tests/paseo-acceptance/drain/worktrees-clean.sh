#!/usr/bin/env bash
# worktrees-clean
# CONTRACT: D0.2: no worktree of a listed repo has uncommitted work or commits no remote has, before its tool is disabled
# EXPECT:   every worktree is clean and every commit reachable from a remote, exit 0
# ON-FAIL:  uncommitted or unpushed work exists: its owner commits and pushes it (or archives it) first; never stash or reset it for them
# SCOPE:    read-only: `git worktree list`, `git status --porcelain`, `git rev-list` with GIT_OPTIONAL_LOCKS=0 (no index refresh written)
# HOW:      bash tests/paseo-acceptance/drain/worktrees-clean.sh [REPO...]     (default: ~/src/djbclark-ade and its worktrees)
# NEEDS:    git, python3
# OUTPUT:   {"tool":"worktrees","held":N,"evidence":["dirty PATH (n paths)" | "unpushed PATH (n commits)"...]}; exit 0 / 1 / 77
# NOTE:     "unpushed" = commits on HEAD that no remote-tracking ref contains (works for a branch with no upstream).
#           A pushed branch whose PR is open is NOT held: it is safe on the remote.
# STATUS:   run live 2026-11-02 (see the T3 report)
set -u
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
[ "$#" -gt 0 ] || set -- "$HOME/src/djbclark-ade"
python3 - "$here" "$@" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import drain_common as dc
TOOL = "worktrees"
repos = sys.argv[2:]
ev, seen, nwt = [], set(), 0
for repo in repos:
    rc, out, err = dc.run(["git", "-C", repo, "worktree", "list", "--porcelain"], 30)
    if rc != 0:
        sys.exit(dc.cannot(TOOL, f"git worktree list failed in {repo}: {err.strip()[:100]}"))
    wts = [l[len("worktree "):] for l in out.splitlines() if l.startswith("worktree ")]
    prunable = {l for l in out.splitlines() if l.startswith("prunable")}
    for w in wts:
        if w in seen:
            continue
        seen.add(w)
        nwt += 1
        if not os.path.isdir(w):
            ev.append(f"missing {w} (listed but not on disk)")
            continue
        rc, st, err = dc.run(["git", "-C", w, "status", "--porcelain"], 60)
        if rc is None or rc != 0:
            sys.exit(dc.cannot(TOOL, f"git status failed in {w}: {err.strip()[:100]}"))
        n = len([l for l in st.splitlines() if l.strip()])
        if n:
            ev.append(f"dirty {w} ({n} paths)")
        rc, cnt, err = dc.run(["git", "-C", w, "rev-list", "--count", "HEAD", "--not", "--remotes"], 60)
        if rc != 0:
            sys.exit(dc.cannot(TOOL, f"git rev-list failed in {w}: {err.strip()[:100]}"))
        if cnt.strip() not in ("", "0"):
            ev.append(f"unpushed {w} ({cnt.strip()} commits on no remote)")
sys.exit(dc.emit(TOOL, len(ev), ev, [f"checked {nwt} worktrees of {len(repos)} repos"]))
PY
exit $?
