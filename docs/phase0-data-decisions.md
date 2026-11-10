# Phase 0 data decisions (Carried #21)

Proposals, 2026-11-10. Source scan (snapshot 2026-10-20T04:38:17-0400):
[history/ade-everywhere-phase0-scan-2026-10-20.md](history/ade-everywhere-phase0-scan-2026-10-20.md).
Nothing below was executed: this PR only records the recommended choices so capture can run
once the operator answers the items marked **operator yes**. Re-run `bin/ade-scan-state` (or a
successor) before any copy, push or bundle; the scan tool itself is gone from the live tree (E2),
and paths may have moved since 2026-10-20.

Standing order 11: writing into `~/ops/site-private`, hosting a new remote, pushing a branch on
someone else's fork, or deleting host state all need the operator's explicit yes. Documenting
the proposal inside `djbclark-ade` does not.

Legend for each decision:

| Tag | Meaning |
|---|---|
| **operator yes** | May not run until djbclark says yes for that change (order 11). |
| **deferred** | Not needed to close the three Phase 0 capture questions; later cleanup or a fresh scan. |
| **lead may prep** | Planning, inventory refresh, and dry-run command lists inside this repo; no host write. |

## A. The 41 unreferenced bigteam report sets

**Facts (scan §0 / §1.2).** 29 `unique` + 12 `mixed` = 41 task dirs under
`~/.local/state/bigteam/`. Unique report markdown is ~1.24 MiB; whole dirs are larger because
`mixed` rows carry logs and worktrees. A mention elsewhere was counted as a reference, not a
copy of the report.

### A1. Proposed decision

1. **One destination for all 41.** Copy only `*report*.md` files (preserving basename) into
   `~/ops/site-private/phase0-reports/<task>/`. Do not copy logs, worktrees, APKs, JSONL, or
   job records in this pass.
2. **Reports-only even for `mixed`.** Default answer to the scan's "do the logs/worktrees
   beside it matter?" is **no for Phase 0 capture**. Those trees stay on disk until a later
   cleanup pass (A4).
3. **Open `CLAIM` / unclosed jobs.** Before copying a dir whose scan row had an open `CLAIM`
   (`quotafix`, `emu39`, `aiusegpt`, `jev-shadow`, `ralph-acp-plugin`, `afs-tokens-2026-10-18`,
   `emufix`, `wdfollow`) or unclosed job records, confirm the claim is `DONE` or abandoned on
   a fresh listing. Copy is read-only of the report files; originals stay until A4.
4. **Priority read before copy.** `emufix`, `wdfollow` (open claim + mixed) and
   `research-brain-emulation-agent-teams` (22 reports, ~88 MiB dir, no claim) first, then the
   remaining unique rows, then the other mixed rows.

### A2. Operator yes

| # | Decision | Why order 11 |
|---|---|---|
| A2a | Create / write `~/ops/site-private/phase0-reports/` and land the 41 report sets there | Writes outside `djbclark-ade` into the private companion |
| A2b | Confirm open-claim dirs are finished (or explicitly abandon) before capture | Operator owns live session state on the Mac |

### A3. Lead may prep (no host write)

- Refresh the 41-row inventory against a current `~/.local/state/bigteam` listing.
- Emit the exact `cp` plan from scan §3.1 with `<DEST>=~/ops/site-private/phase0-reports`.

### A4. Deferred

- Deleting any bigteam task dir (including the 93 `scratch` dirs).
- Capturing or deleting the ~54.5 GiB `adhoc-2026-10-18/hm-promo-rehearsal/` tree (scan §0: not Phase 0).
- Closing the 75 unclosed job records (loose ends, not lost report content).
- Re-classifying `scratch` dirs that might hold non-`*report*.md` decision notes (scan limit 2).

## B. Host vs bundle `~/src/one-offs`

**Facts (scan §0 / §3.2).** `~/src/one-offs` has **no `origin` remote**, 37 commits on
`master`, plus the linked worktree `~/orca/workspaces/one-offs/Hermes` (branch `Hermes`, 2
commits, same repo). Nothing outside this Mac holds that history.

### B1. Proposed decision

1. **Bundle first (preservation).** Create
   `~/ops/site-private/bundles/one-offs.bundle` with `git -C ~/src/one-offs bundle create … --all`
   so branch `Hermes` is included in one artifact. That is the Phase 0 capture.
2. **Do not host yet.** Defer creating a GitHub/Forgejo remote and the where-does-it-live
   choice until after the bundle exists and the operator picks a home. A new private repo is
   the likely eventual host; naming and remote URL wait for B2b.
3. **Leave the working trees in place** until the bundle verifies (`git bundle verify`) and
   a second copy or remote exists.

### B2. Operator yes

| # | Decision | Why order 11 |
|---|---|---|
| B2a | Write the bundle under `~/ops/site-private/bundles/` | Outside this project |
| B2b | Create / choose a remote host and push `one-offs` (if ever) | New repo / hosting; not lead discretion |

### B3. Deferred

- Choosing the final host (GitHub private vs Forgejo vs stay bundle-only).
- Removing `~/src/one-offs` or the Hermes worktree after a remote exists.
- Any rename or split of the one-offs history.

## C. Push vs bundle branches with no origin

**Facts (scan §0 item 3 / §3.2).** Besides `one-offs` (covered in B), five checkouts hold
commits on no origin branch:

| Checkout | Branch | Ahead | Notes |
|---|---|---|---|
| `~/orca/workspaces/djbclark-ade/you-can-compact-yourself` | `djbclark/you-can-compact-yourself` | 2 | Own ADE tree |
| `~/orca/workspaces/orca/aiuse-integration` | `djbclark/aiuse-integration` | 2 | Outside ADE |
| `~/.cow/pastures/crush/crush-merge-v0981` | `merge/upstream-v0.98.1` | 8 | Outside ADE (crush) |
| `~/.cow/pastures/janekbaraniewski_openusage/opencode-v2` | `fix/opencode-telemetry-v2` | 1 | Outside ADE (fork) |
| `~/.cow/pastures/litellm/clinepass-pr44379` | `clinepass-upstream` | 2 (+stash, dirty) | Outside ADE (litellm) |

### C1. Proposed decision

1. **Default: bundle, do not push.** For every row above, land a git bundle under
   `~/ops/site-private/bundles/phase0-checkouts/` named after `<shortpath>-<branch>.bundle`
   (scan §3.2 command shapes). Bundling preserves the commits without publishing a branch.
2. **Exception — ADE-owned branch may push after yes.**
   `you-can-compact-yourself` is the only row in this project's own remotes. Prefer
   `git push -u origin djbclark/you-can-compact-yourself` **if** the operator still wants that
   work as a live branch; otherwise bundle like the others. Do not push without the yes in C2a
   (publishing is outward-facing even on an owned remote).
3. **Third-party forks stay bundle-only** until an explicit upstreaming yes (`aiuse-integration`,
   `crush-merge-v0981`, `opencode-v2`, `clinepass-pr44379`). Order 8 (file upstream) applies
   only after that yes.
4. **`clinepass-pr44379` extras.** Also save `stash show -p --include-untracked` for each stash
   entry and copy untracked paths beside the bundle (scan §3.2).

### C2. Operator yes

| # | Decision | Why order 11 |
|---|---|---|
| C2a | Push `djbclark/you-can-compact-yourself` (vs bundle-only) | Publishes a branch |
| C2b | Write bundles (and stash/untracked sidecars) under `~/ops/site-private/bundles/` | Outside this project |
| C2c | Push any of the four third-party-fork branches, or open upstream PRs from them | Changes / publishes outside `djbclark-ade` |

### C3. Deferred

- Dirty / untracked-only rows that are not "commits on no origin" (`barnacle` modified files,
  `wearos-investigation` untracked, forgejo-ci untracked shared dirt, cow copies of in-flight
  ADE edits): preserve or discard in a later hygiene pass, not these three decisions.
- Deleting cow pastures or Orca worktrees after capture.
- Re-fetching origin tips before a push (do it immediately before any approved push).

## D. Execution gate (after yes)

When A2a/A2b, B2a, and C2b (and optionally C2a/C2c) are answered:

1. Re-scan or re-list the named paths; abort a row that is gone or claim-still-open without A2b.
2. Create the DEST directories; run the copies / `git bundle create` commands; `git bundle verify`
   each bundle.
3. Record the run date and artifact paths in a short note under
   `~/ops/site-private/phase0-reports/README.md` (operator yes already covers that tree).
4. Only then mark Carried #21 closable in `docs/queue.md` (move to Done with the PR that
   recorded the completed capture, or a follow-up).

## E. What this PR is not

- Not a capture run, push, host create, or delete.
- Not an APPROVE of any host change.
- Not a decision on the 54.5 GiB Hermes rehearsal scratch tree.
