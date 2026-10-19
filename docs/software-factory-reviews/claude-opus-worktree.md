# Raw response: acp-run claude opus/high, resumed session, section 9 worktrees (2026-10-19 ~15:03 EDT)

Verified model: claude-opus-5-5; cost reported $0.29749760000000003

---

## Critique of §9 (worktree isolation)

**What works:** isolation is on by default, the worktree root sits outside the repo, `gc` is dry-run by default, and dirty or unpushed worktrees are never removed. Keep all of that.

**Problems, most important first:**

1. **A worktree isolates git state, not agents.** All worktrees share one `.git`. An agent running in yolo mode can still check out main, push, rewrite refs, edit `.git/config`, or delete the `pre-commit` hook from the shared hooks directory. "Daniel decides about `--no-verify`, not agents" can't be enforced. The only real guard is server-side branch protection plus a token that can't push to main.

2. **For factory jobs, the guard should be a hard rule.** `warn` is exactly the path someone who forgets takes, and an env var can be forgotten too. The orchestrator should refuse outright, with no setting to change it. Keep `warn` only for manual sessions.

3. **The guard check is fragile:**
   - `git rev-parse` can return relative paths, so the equality test can misfire. Use `--path-format=absolute`.
   - Hardcoding `main`/`master` misses repos whose default is something else. Read the default from `origin/HEAD`.
   - The bigger risk is two agents in the same checkout. A per-cwd lock in acp-run catches that on any branch.

4. **New worktrees are missing ignored files.** `.env`, `node_modules` and build caches aren't there, so `verify` fails or the builder improvises (for example, copying secrets). Add a per-repo `setup` command. Parallel worktrees also collide on ports, which is a reason to bring containers forward.

5. **`gc` gets merge detection wrong:**
   - Squash or rebase merges look unmerged forever. Ask `gh pr view` for the PR state, or use `git cherry`.
   - It must skip worktrees of running jobs. Have the orchestrator `git worktree lock` each job's worktree and unlock it when the job reaches a final state.

6. **`factory start` can't change your shell's directory.** A child process can't `cd` the parent shell, so this needs a shell function.

7. **The session registry adds another writer.** Who updates "agent runs" in `factory/sessions/<slug>.json`? If acp-run does, that breaks the single-writer rule again. Build the registry from the acp-run logs and `git worktree list` instead of storing it.

8. **The badge is mostly noise.** Every factory card will show green. Show only the red badge.

## How this changes my earlier review

- **Cleanup hole (old P0 #5):** mostly fixed by `gc`, once the squash-merge detection and locking in point 5 are added.
- **Resume (P0 #2):** now well-defined. Each job has its own worktree, so "reset to `head_sha`" applies cleanly. Add the lock.
- **Sandboxing (P0 #6):** unchanged, and the stakes are higher because §9 can look like isolation when it isn't. Containers are listed as "later", but they belong in the first release that runs unattended, with the worktree mounted into the container.
- **Scope:** most of §9 is a separate hygiene tool for manual work, not part of the factory. For v1, keep:
  - automatic job worktrees (9.1.1),
  - `gc` with locking,
  - `fs` as a shell function.

  Cut the pre-commit hook, the registry, the "Unisolated work" banner and the `jj` switch. Revisit them once the factory loop is reliable.
