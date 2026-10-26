---
name: ade-workspace-sweep
description: >-
  Recurring read-only sweep of scattered djbclark-ade workspaces: git worktrees under ~/src, ~/src/ops-worktrees, ~/orca and ~/.local/state/bigteam, bigteam task dirs, and stale or prunable entries. Reports what is unique, unpushed, dirty or merged; removes nothing. Use for /ade-workspace-sweep, "sweep the worktrees", "what is left lying around", or as the periodic maintenance pass.
---

# ade-workspace-sweep

The ADE leaves work in many places: linked worktrees, cow pastures, bigteam
task dirs and one-off scan reports. This skill is the recurring pass that finds
them. It changes nothing: it reads, reports, and asks before any cleanup.

## Procedure

1. **Scan state (read-only).** Run from the canonical checkout, writing outside
   the repo:

   ```sh
   mkdir -p "$HOME/.local/state/ade-workspace-sweep/$(date +%Y-%m-%d)"
   ~/src/djbclark-ade/bin/ade-scan-state --bigteam ~/.local/state/bigteam \
       --ref-root ~/src/djbclark-ade/docs --ref-root ~/ops/site-private/memory \
       --git-root ~/src --git-root ~/orca/workspaces --git-root ~/orca/projects \
       --git-root ~/.cow/pastures --remote --json \
       > "$HOME/.local/state/ade-workspace-sweep/$(date +%Y-%m-%d)/scan.json" 2>&1
   echo "rc=$?"
   ```

   Read the exit status and the JSON file itself. Exit 0 with an empty JSON is
   not a clean result; check the counts.

2. **Worktree inventory.** For each checkout root in `~/src`, `~/src/ops-worktrees`,
   `~/orca/workspaces` and `~/.local/state/bigteam`, run `git worktree list --porcelain`
   and classify each linked tree:
   - `prunable` (the directory is gone): report it; `git worktree prune` only after the operator says so.
   - branch already merged into `origin/master` (`git merge-base --is-ancestor <tip> origin/master`): candidate for removal.
   - dirty tree (`git -C <wt> status --porcelain` non-empty) or commits not on any remote branch: keep, and name the owner if the branch name says so.
   - detached HEAD: report; it may be a sole copy of a report.

3. **Bigteam dirs.** From the scan, list only `unique` and `mixed` verdicts. A
   `scratch` verdict is a candidate for deletion, still only with the operator's yes.

4. **Report** in this order: A. summary counts; B. worktrees that are merged
   and clean (removal candidates); C. dirty, unpushed or unique work (keep);
   D. prunable entries. Label each list item (`B1`, `B2`, ...). Give full paths.

5. **Act only on a yes.** Removal goes through `git worktree remove <path>` one
   path at a time, after the operator names it. Never `rm -rf` a worktree, never
   stash, reset or `commit -a` another session's edits.

6. **Skill links.** Finish with `~/src/djbclark-ade/bin/skill-everywhere --check --all`
   and report any missing or blocked target row. Repair links only with
   `/skills-everywhere`, not here.

## Rules

- Verify against the artifact: the git output and `scan.json`, not a remembered branch state.
- Run every command yourself; never hand the operator a command to type.
- Start the scan in the background if it runs past about 15 seconds, and wait on its output file.
- Finish with one line via `~/.local/bin/hermes-ping "<repo>: <line>"` only when the operator must decide something.
