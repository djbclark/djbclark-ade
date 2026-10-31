---
schema_version: 1
handoff_id: quota
parent_handoff_ids: [db3f]
lineage: 32c0
chain: [standalone-32c0]
repo: kool-ade
workspace: you-can-compact-yourself
branch: djbclark/you-can-compact-yourself (merged; worktree persists as Orca workspace)
head_sha: a46aa16
created_at: 2026-10-18T03:55:00-04:00
writer: claude-code
---

# Handoff: quota-reset recovery for a fully-merged worktree with no in-flight code

## The Goal

A quota reset kills the session but not the worktree. The worktree should
be resumable by a fresh agent session — even one with zero conversation
memory of what came before — by reading two files and running two commands.
No rediscovering, no re-deriving, no surprise pushes.

## Where We Are

The branch `djbclark/you-can-compact-yourself` is fully merged into
`origin/master` (`0bea176` reachable from `origin/master` = `855282b`).
On top of that merged HEAD sits one local-only commit, `a46aa16`, that
pins four hook files to the worktree's own path:

| File | Pin |
| --- | --- |
| `.claude/helpers/graft-hooks.cjs` | `BAKED = "/Users/djbclark/src/Graft/dist/claude"` |
| `.claude/helpers/graft-statusline.cjs` | same |
| `.cursor/hooks/graft-hooks.cjs` | same |
| `.cursor/hooks.json` | all three commands point at this worktree's `.cursor/hooks/graft-hooks.cjs` (was `/Users/djbclark/orca/projects/djbclark-ade/...` — a path that no longer exists) |

Without `a46aa16`, a fresh session in this checkout gets a broken statusline
and broken Cursor hooks silently, because the baked path is a Homebrew
install that is no longer current and the Cursor path is a stale
`orca/projects/` reference that was replaced when this worktree moved to
`orca/workspaces/`.

## The Recovery Protocol (what the next session should do, verbatim)

The resume recipe lives at three layers; the session reads the one closest
to where it wakes up:

1. **Worktree-local Tier 1 pointer**:
   `~/orca/workspaces/kool-ade/you-can-compact-yourself/SESSION_LOG.md`
   — readable by any session whose cwd resolves to the worktree.
2. **Out-of-tree canonical Tier 1 log**:
   `~/.local/state/handoffs/chains/standalone-32c0/SESSION_LOG.md`
   (pointer file at `~/.local/state/handoffs/kool-ade/you-can-compact-yourself/SESSION_LOG.md` redirects here).
3. **Tier 2 durable handoff**: this file.

### Resume recipe (the next session's two commands)

```
cd ~/orca/workspaces/kool-ade/you-can-compact-yourself
git rev-parse HEAD         # expect a46aa16
git status                 # expect "nothing to commit, working tree clean"
```

If `HEAD` ≠ `a46aa16`: the local-env fix is lost. Re-apply the patch from
the table above and commit it (do not push). Do *not* try to "fix forward"
by changing the four files to point at master paths; the worktree is
deliberately self-referential so it can be moved or cloned without breaking.

### Two commands the next session must NOT run

- `git push -u origin djbclark/you-can-compact-yourself` — would push
  `a46aa16`'s path-local fixes onto a branch that, if ever re-checked out
  elsewhere, would silently break every other worktree.
- `git merge` / `git rebase` against `master` — the branch is already at
  `master`; either is a no-op or a foot-gun.

## Verified facts (audit results, 2026-10-18T03:55:00-04:00)

- Branch tip `0bea176b670318331663a98bd0308e698286b546` is an ancestor of
  `origin/master` `855282b9cbd4c0e47a2117362b8c801ccf4773c5` —
  `git merge-base --is-ancestor 0bea176 origin/master` → YES.
- `git rev-list --left-right --count origin/master...HEAD` →
  `0 0`. Branch is exactly even with origin.
- 4 uncommitted files → committed in `a46aa16`; working tree now clean.
- `git status --porcelain` → empty.
- `SESSION_LOG.md` (worktree-local) exists and points at the canonical
  out-of-tree log; canonical log's `redirect` is back at it.
- `docs/queue.md` first entry (`self-slash cannot drive omp`, 2026-10-13)
  is independent of this worktree and not in scope here.

## Where to put the next in-progress recovery

Same three-layer pattern, every time:

- Drop a Tier 1 pointer inside the worktree, even if the worktree will
  later be deleted: `git reflog` survives a `git worktree remove`, but a
  pane restart with quota zero does not.
- Refresh the canonical chain log; the schema requires `head_sha` to match
  the workspace's actual HEAD or `session_log.py read` will mark the entry
  stale.
- Author a Tier 2 handoff under `docs/handoffs/` for anything that took
  judgment — don't expect the next session to re-derive the "do not push"
  reasoning from `git log` alone.

## Rule of thumb

> "Resume after a quota reset" = the next session's first two commands
> succeed and tell the truth. Everything else is downstream.