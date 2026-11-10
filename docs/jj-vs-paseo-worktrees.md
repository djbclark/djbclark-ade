# jj vs Paseo worktrees (design, 2026-11-10)

**Status:** design only. No jj install, no runtime change, no outside-repo
edit. Closes the *evaluation* half of queue #26; adoption stays deferred.
Snapshot facts below are dated; re-probe before acting.

## A. Why this exists

A1. **Queue #26** (carried since 2026-08-23): jj (Jujutsu) was listed as a
larger, separate bet from the CoW-pasture trial. Cow won the 2026-08-23
workspace bake-off because it already had agent wiring; jj stayed open
because it solves more than "cheap parallel checkouts" and costs more to
adopt (`git show pre-slim-2026-11-06:docs/queue.md` around the
plain-git / cow / rift / jj table).

A2. **Post-CoW world (2026-11-06/07 slim-down E2).** `bin/cow-pasture` and
`skills/cow-workspaces` are gone. Isolation is a **Paseo worktree**
(`paseo run --new-workspace worktree …`, `.worktreeinclude`) or a plain
`git worktree add`, plus the **ade-git-guard claim registry** (owner,
branch, path, `expires_at`). Claims are the seatbelt for one writer per
workspace (AGENTS.md order 9; `docs/git-guard.md`, `docs/workspace-layout.md`).

A3. **Question for this design:** with CoW pastures retired and claims in
place (even though nothing auto-creates claims yet — W2 still open), does
jj still earn a pilot, or should #26 stay deferred?

## B. What each side is for

| Concern | Paseo / git worktrees today | jj (colocated or workspace) |
|---|---|---|
| Parallel agent checkouts | Linked git worktrees under a Paseo workspace; shared object store | jj workspaces / working copies over one store; Git-compatible backend |
| One writer per tree | Claim on **path + branch + owner + TTL**; shim + ref hooks | No ADE claim integration; would need a new rule surface |
| Ref safety | `reference-transaction` / `pre-push` see every git ref update | jj writes without those hooks (`docs/git-guard.md` "What is NOT covered" item 1 names `jj` explicitly) |
| Agent harness | Paseo is the only harness (2026-10-31) | jj is a VCS layer under whatever harness runs |
| CoW / clone cost | APFS/btrfs CoW pastures retired; fresh Paseo worktree + `.worktreeinclude` (empty here) | Not a CoW tool; cheaper *semantic* workspace ops, not APFS clonefile |
| Undo / conflict UX | git stash/rebase/amend; agents already trained on git | Operation log, first-class conflicts, working-copy-as-commit |
| GitHub / PR path | Native `git push` + `gh` | Still git remotes via colocated repo, but bookmark ↔ branch mapping is another dialect |

## C. When jj would help

C1. **Conflict-heavy multi-agent merges.** First-class conflicts and an
operation log beat "stash, rebase, hope the agent does not `reset --hard`
the wrong tree" when many writers converge on one history. That pain is
real in theory; in this ADE the standing rule is **one writer per claimed
workspace**, so conflict volume is deliberately kept low.

C2. **Working-copy-as-commit / no staging area.** Agents often forget
`git add` or stage the wrong paths. jj's model reduces that class of
mistake. Mitigation already in force: claim shim refuses several
destructive shared-checkout forms; review and PR flow still speak git.

C3. **Multi-workspace ergonomics without `git worktree` ceremony.** jj
workspaces can be lighter to create/abandon than managing linked
worktrees + per-worktree `ade-claim` pointers. That only helps if ADE
stops treating "git worktree + claim path" as the isolation unit.

C4. **Not a replacement for the retired CoW pastures.** The 2026-08-23
note already said jj is not a CoW-workspace tool. Disk-clone speed is
solved (or accepted) by Paseo worktrees + filesystem CoW where the OS
gives it; jj does not restore `cow-pasture`'s dependency-dir reuse story.

## D. Conflicts with ade-git-guard claims

D1. **Hooks never see jj.** The O2 redesign put ref enforcement in git's
`reference-transaction` / `pre-push` hooks so argv spelling cannot bypass
them. Writers that never run those hooks — libgit2, gitoxide, **jj**,
IDE-embedded git — are listed as uncovered (`docs/git-guard.md`, 2026-10-25).
Putting agents on jj without a new enforcement point re-opens the
"accidental write to another owner's branch" class the guard exists to stop.

D2. **Claim schema is git-shaped.** A claim records `path` (realpath of
the workspace root), `repo_origin`, `branch`, `base_sha`, and a per-git-dir
pointer file `ade-claim` (`bin/ade_claims.py` module docstring). jj
bookmarks are not `refs/heads/<branch>`; change ids are not commit SHAs
agents and GitHub already name; a jj workspace root may not be a git
worktree git-dir the pointer and `samefile` path checks expect.

D3. **Shim rules assume git subcommands.** Foreign-workspace allowlists,
linked-worktree stash refusal, `worktree remove|move|prune` of a claimed
tree, and rename/copy destination checks all parse **git** argv. `jj …`
never enters that path. A colocated repo where agents still call `git`
keeps the shim; the moment the agent prefers `jj new` / `jj edit` /
`jj git push`, the seatbelt is blind.

D4. **Auto-claim wiring (W2) is Paseo-shaped.** The planned
`worktree.create.after` plugin runs `ade_claims.py new --ttl` and
`ade-git-guard install` for each agent worktree (`docs/git-guard.md`
Integration status; queue item 6). That hook does not know about jj
workspaces. Shipping jj before W2 lands means either hand-claimed trees
(easy to forget) or a second launcher path.

D5. **Shared-object / colocated surprises.** Colocated `.jj` + `.git` means
operation-log rewrites and bookmark moves can change what `git` sees
without the agent using a guarded git verb. Secret-deny already skips
`.jj` as a VCS dir (`docs/secret-deny.md`); that is scan hygiene, not
write isolation.

## E. Migration risks (if a pilot were approved later)

E1. **Dual dialect for every agent brief.** Skills, dispatch footers,
review-launch, and standing order 9 all say git worktree / Paseo
worktree. A pilot needs an explicit "git only" vs "jj allowed" matrix or
agents will mix commands in one tree.

E2. **CI and merge gate stay git.** Adversary-marker, Tests, `gh pr merge
--squash --match-head-commit` are GitHub/git. jj must remain a local UX
over a git remote; any bookmark naming drift breaks "head reviewed =
head merged".

E3. **Claim expiry and path exclusivity.** `create_claim` refuses another
owner's active path (exit 4). A jj workspace at a new path is fine; a
workspace that shares the primary checkout path, or moves under an
existing claim without releasing it, fights the registry.

E4. **Training and undo culture.** jj's undo is powerful; combined with
fail-open hooks and same-uid agents, a mistaken `jj op restore` can erase
another session's visible history in a colocated store. Needs an
allowlist of jj verbs per role before any yolo agent may run them.

E5. **Pre-1.0 churn.** Upstream jj still accepts breaking CLI/behavior
changes. Pinning is against standing order 8 (track latest); tracking
latest without pins is a support cost on a non-critical path.

E6. **Outside-repo / install surface.** A real pilot needs jj on the Mac
image and possibly Linux CI agents — operator yes under order 11 for
anything outside this repo's docs. This design deliberately does not
request that.

## F. Alternatives already chosen (do not relitigate without new evidence)

F1. **Paseo worktrees** replaced cow pastures (slim-down E2, 2026-11-06).
F2. **Claims + hooks** are the isolation seatbelt (O2, 2026-10-25; owner +
TTL 2026-11-06).
F3. **Software-factory reviews (2026-10-19)** already cut or deferred jj
(`docs/history/software-factory-design.md` § alternatives;
`docs/history/software-factory-reviews/*` — "Defer jj", "Cut jj
entirely", no `isolation = "jj"`).
F4. **Containers / VMs** remain the heavier isolation option for untrusted
builders; they address env and network, which neither git worktrees nor
jj workspaces contain.

## G. Recommendation

G1. **Defer adoption.** Keep queue #26 as design-complete / wait. Do not
install jj, do not add an `isolation = "jj"` switch, do not teach agents
jj verbs in skills.

G2. **Revisit only after** (all of): W2 auto-claims on Paseo
`worktree.create.after` are live and measured; a concrete pain report
shows claim+git worktrees failing where jj's conflict/undo model would
have prevented loss; and the operator approves a **read-only operator
pilot** (human shell, one throwaway colocated clone, no agent PATH, no
claim bypass) under order 11.

G3. **If a pilot is approved later**, minimum bar before any agent use:
a jj-aware enforcement sketch (either forbid agent `jj` while claims
exist, or a parallel rule that maps bookmarks → claimed branches and
refuses foreign workspace paths); colocated-only; bookmarks named 1:1
with `refs/heads/*` used by claims; documented undo policy; no change to
the GitHub PR path.

G4. **One-liner:** Prefer Paseo git worktrees + ade-git-guard claims; jj
remains an attractive VCS bet that bypasses today's seatbelt, so defer
until claims auto-wire and a guarded pilot is designed.

## H. Pointers

| Doc / code | Role |
|---|---|
| `docs/queue.md` #26 | Carried item this design addresses |
| `docs/git-guard.md` | Claims, hooks, shim; jj named as uncovered writer |
| `docs/workspace-layout.md` | Paseo workspace / worktree naming |
| `bin/ade_claims.py` | Claim schema and guard rules |
| `docs/slim/reports/wave2-E2.md` | Cow → Paseo worktree replacement |
| `docs/history/software-factory-design.md` | Earlier "maybe later" jj note |
