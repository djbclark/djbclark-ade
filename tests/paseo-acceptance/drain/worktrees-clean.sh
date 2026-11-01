#!/usr/bin/env bash
# worktrees-clean
# CONTRACT: D0.2: no listed worktree has uncommitted work or an unmerged branch before its tool is disabled
# EXPECT:   every repo in the list is clean and fully pushed
# ON-FAIL:  uncommitted or unpushed work exists: commit and push or archive it first
# SCOPE:    read-only (reads launchd, relay and git state; changes nothing)
# HOW:      bash tests/paseo-acceptance/drain/worktrees-clean.sh [repo...]
# NEEDS:    git; repos default to ~/src/djbclark-ade and its worktrees
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=worktrees-clean
. "$here/lib/common.sh"
ON_FAIL=uncommitted\ or\ unpushed\ work\ exists:\ commit\ and\ push\ or\ archive\ it\ first
repos=("$@"); [ "${#repos[@]}" = 0 ] && repos=("$HOME/src/djbclark-ade")
held=0; ev=""
for r in "${repos[@]}"; do
  git -C "$r" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2}' | while read -r w; do
    [ -n "$(git -C "$w" status --porcelain 2>/dev/null)" ] && echo "dirty $w"
    git -C "$w" log --oneline '@{u}..' 2>/dev/null | ggrep -q . && echo "unpushed $w"
  done
done > "${TMPDIR:-/tmp}/wt-held.$$"
held=$(wc -l < "${TMPDIR:-/tmp}/wt-held.$$" | tr -d ' ')
printf '{"tool":"worktrees","held":%s,"evidence":%s}\n' "$held" "$(python3 -c 'import json,sys;print(json.dumps(open(sys.argv[1]).read()[:2000]))' "${TMPDIR:-/tmp}/wt-held.$$")"
rm -f "${TMPDIR:-/tmp}/wt-held.$$"
[ "$held" = 0 ]
