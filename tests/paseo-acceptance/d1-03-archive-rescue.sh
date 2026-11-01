#!/usr/bin/env bash
# d1-03-archive-rescue
# CONTRACT: D1.3/B4.1-4.2: archiving the last agent of a dirty, unpushed worktree workspace leaves a local rescue (bundle, stash commit, untracked tar) BEFORE the worktree is removed; the pushed rescue branch holds tracked changes only
# EXPECT:   rescue dir 0700 with branch.bundle (git bundle verify ok), stash ref in the bundle, untracked.tar; the remote branch rescue/<branch>-<date> has no untracked file
# ON-FAIL:  no slice moves into Paseo workspaces (plan D1.3)
# SCOPE:    DESTRUCTIVE: second daemon only
#           NEVER run this against the live daemon (plan B10). It refuses unless PASEO_HOME is a fresh test home.
# HOW:      ADE_RESCUE_BIN=bin/ade-rescue-worktree bash tests/paseo-acceptance/d1-03-archive-rescue.sh   (variant with a refusing remote: d1-03b-teardown-failure.sh)
# NEEDS:    isolated daemon; bin/ade-rescue-worktree (task T6, not yet written); a committed paseo.json teardown in the fixture repo
# STATUS:   DRAFT, never run; unverified CLI shapes are marked UNVERIFIED
set -u
here=$(cd "$(dirname "$0")" && pwd)
ACC_PROBE=d1-03-archive-rescue
. "$here/lib/common.sh"
ON_FAIL=no\ slice\ moves\ into\ Paseo\ workspaces\ \(plan\ D1.3\)
RESCUE=${ADE_RESCUE_BIN:-$here/../../bin/ade-rescue-worktree}
[ -x "$RESCUE" ] || skip "bin/ade-rescue-worktree does not exist yet (T6)"
isolated_up rescue; trap isolated_down EXIT
repo="$ACC_BASE/repo"; remote="$ACC_BASE/remote.git"
git init -q -b main "$repo" && git init -q --bare "$remote" && git -C "$repo" remote add origin "$remote"
printf 'x\n' > "$repo/a.txt"
printf '{"worktree":{"teardown":["%s --repo fx --branch \\"$PASEO_BRANCH_NAME\\" --worktree \\"$PWD\\" --remote origin"]}}\n' "$RESCUE" > "$repo/paseo.json"   # UNVERIFIED: teardown variable names, check upstream worktrees.md
git -C "$repo" add -A && git -C "$repo" -c user.name=t -c user.email=t@t commit -qm base && git -C "$repo" push -q origin main
id=$(pj run -q --no-wait --provider "${PROBE_PROVIDER:-claude}" --mode bypass --cwd "$repo" --new-workspace worktree --worktree-slug rescue-probe \
  "Edit a.txt (tracked change), create untracked.txt, commit one more change to b.txt, do NOT push, then stop.") || fail "create failed"
pj wait --timeout 300 "$id" >/dev/null 2>&1
wt=$(pj agent inspect --json "$id" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('Cwd',''))")
[ -d "$wt" ] || fail "worktree path not found" "{\"cwd\":\"$wt\"}"
t0=$(date +%s)
pj archive "$id" >/dev/null 2>&1 || pj agent archive --force "$id" >/dev/null 2>&1
for i in $(seq 1 60); do [ -d "$wt" ] || break; sleep 1; done
rdir=$(ls -d "$HOME"/.local/state/ade/rescue/fx/*/ 2>/dev/null | tail -1)
[ -n "$rdir" ] || fail "no rescue dir was written" "{\"worktreeGone\":$([ -d "$wt" ] && echo false || echo true)}"
mode=$(stat -f '%Lp' "$rdir" 2>/dev/null || stat -c '%a' "$rdir")
vb=$(git bundle verify "$rdir/branch.bundle" >/dev/null 2>&1 && echo ok || echo bad)
tar -tf "$rdir/untracked.tar" 2>/dev/null | grep -q untracked.txt && ut=ok || ut=missing
pushed=$(git --git-dir="$remote" for-each-ref 'refs/heads/rescue/*' --format='%(refname)' | head -1)
leak=$(git --git-dir="$remote" ls-tree -r --name-only "$pushed" 2>/dev/null | grep -c untracked.txt)
ev="{\"mode\":\"$mode\",\"bundle\":\"$vb\",\"untrackedTar\":\"$ut\",\"remoteBranch\":\"$pushed\",\"untrackedLeakedToRemote\":$leak,\"rescueBeforeRemoval\":\"compare mtime of $rdir with worktree removal in daemon.out\"}"
[ "$mode" = 700 ] && [ "$vb" = ok ] && [ "$ut" = ok ] && [ "$leak" = 0 ] && pass "$ev"
fail "rescue incomplete" "$ev"
