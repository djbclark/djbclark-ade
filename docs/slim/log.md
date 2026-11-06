# Slim-down log

One entry per wave (PLAN.md F): what merged, what was lost on purpose, what the operator must do by hand. Appended by the slim lead; the operator pastes gate output (C7, C1) here when asked.

## Wave 0 (2026-11-06, lead session 01BvGHM3M9bXWXHwGGHz6Ctd, Fable 5.1 high)

Branch: the slim branch is `claude/determined-maxwell-uvddaz` (this session's designated branch), started at master e397dda (PR 295). `claude/cool-hopper-61dqzq` was PR 295's branch and is finished.

### Verified against the artifact

- **Baseline suite**: done, `docs/slim/baseline.md` (166 failed / 10,141 passed at master da6b2e7d in a container, 2026-11-06). Not re-run.
- **PR 289** (head `beb417db6e811080db6434eb788427743696a54c`): `pytest-linux`, `context-policy`, both Cursor checks `success`; marker APPROVE on that head; all 5 Codex and Cursor review threads `is_resolved: true`. Merge-ready; not merged (operator step, R2).
- **PR 291** (head `e95816ebf83b36d388243d142839134dba79b4f8`): same checks `success`; marker APPROVE on that head; all 4 Codex threads resolved. Merge-ready; not merged (operator step, R3). PR 293 is stacked on its branch and is already draft.
- **gitignore-aider**: branch `origin/gitignore-aider` @ 9946ed38 (djbclark's commit from the shared checkout, report F1). Adversary (Opus 5.5, high) APPROVE, 3 LOW. Opened as [PR 296](https://github.com/djbclark/djbclark-ade/pull/296) with the marker; the commit is unchanged. No changelog fragment (not user-visible, rule 10).
- **Rulings already carried out** (open-PR list, 2026-11-06): PRs 261, 292 and 294 are closed; 270, 290 and 293 are draft. Still open and non-draft, per R8's provisional rows: 194, 208, 227, 231, 254, 256, 260, 269, 281.
- **Tag `pre-slim-2026-11-06`**: points at master fb3b9deb (after PRs 289, 291 and 296, before any slim change). Created locally in the lead's checkout; pushing a tag is refused by the cloud proxy (`git push` and the refs API both), pushed by the operator with `gh api` on 2026-11-06 (verified: `refs/tags/pre-slim-2026-11-06` → fb3b9deb on origin).
- **J questions**: J1, J2, J2a, J2b, J2c, J3–J11 all carry an answer in PLAN.md; none is open.
- **R6 (batch-2 stragglers)**: the consolidated report (37 agents) covers it; its section H lists the two unverified herdr panes (w20:pM, w36:pB) and five agents named without a report (c987a634, d8891c91, 1d003359, 01BvGHLzKz, 7c54a88c-as-c688cc). J1 is answered (the three slices exited). Treated as satisfied for Wave 1 (reads only); the C7 drain gate before Wave 2 is where a late straggler still matters.

### Added on the branch

- `docs/slim/inventory.md`: a mechanical inventory (file, lines, whole-word reference count outside tests and history, tests naming it) of `bin/` (76 entries, 49,670 lines), `skills/` (65 entries), `tests/` (181 files, 86,584 lines), `docs/` and the other tracked areas. Input for the Wave 1 readers; no judgement in it.
- This log.

### Lost on purpose

Nothing yet.

### Merged by the lead (operator, 2026-11-06 19:35Z: "handle all merges now and in the future")

- PR 289 squash-merged at head beb417db (REST merge with `sha` pinned, the API form of `--match-head-commit`): master 734b7d9b.
- PR 291 squash-merged at head e95816eb: master 00839c48. Branch `claude/issue-279-linux-ports-1-sched` kept: PR 293 is stacked on it (R3).
- PR 296 squash-merged at head 9946ed38 after `pytest-linux` went green (Codex code and security reviews completed, no findings; Cursor approved): master fb3b9deb.
- The slim branch merged master in (merge commit, no rewrite of pushed history).
- Not done: deleting branch `claude/issue-284-ndc-oslo-ideas` (the proxy refuses ref deletion over the API and over `git push --delete`); operator step 3a below.

### Operator steps (in this order)

1. ~~Merge PR 289~~ done.
2. ~~Merge PR 291~~ done.
3. ~~Merge PR 296~~ done.
3a/3b. ~~Tag and branch deletions~~ done by the operator with `gh api` (2026-11-06; the cloud proxy drops tag pushes and ref deletions silently).
4. On the Mac, in the shared checkout: `cd ~/src/djbclark-ade && git status` (stop if another session's edits are there: their owner migrates them, order 9), then `git fetch origin && git checkout master && git reset --keep origin/master` (drops the local 9946ed38, now merged; `--keep` refuses rather than discarding uncommitted edits).
5. On the Mac: `cd ~/src/djbclark-ade && git worktree prune && git worktree list | wc -l` (89–115 entries at check-in, report I6; prune removes only entries whose directory is gone).
6. Approve or resize the W1 workflow (section H of PLAN.md) proposed in the lead's Wave 0 reply, then the ledger once it exists.

### Ruling taken (2026-11-06)

Operator: "Try to minimize the number of blocking things like this in the future." Applied as PLAN.md H: workflows start on the stated count; the ledger is posted, not awaited; Mac-only steps are batched per wave. W1 started at once (5 readers, 3-vote refute per KEEP row, 1 critic, cap 100 agents).

### Gate

**Wave 0 closed 2026-11-06**: tag on origin, three merges done, slim branch carries master fb3b9deb. Still open from the operator list: shared-checkout reset and `git worktree prune` (now in the Wave 2 batch, step 7). Wave 1 (reads only, no merge) starts on the W1 approval; it does not need the tag.

## Wave 1 (started 2026-11-06 20:05Z)

W1 round 1 done 20:40Z (99 agents, 11.1M tokens, 39 min): 627 rows, 263 KEEP rows, 31 voted (cap 100), 2 refuted (`failover.py`, `bin/pytest`), 50 rows disagree with the plan, 119 unlisted paths, critic: 12 missing-path groups, 27 inconsistencies, 9 uncovered outside dependents, 15 questions (answered in `docs/slim/ledger-rulings.md`). Round 2 (the remaining 61 code KEEP rows, 183 refuters + 1 critic) started 20:41Z; the ledger is regenerated from it. Ledger posted as v1; Wave 2 briefs follow without waiting.

W1 as designed: 5 Sonnet readers (bin, skills, tests, docs, outside), dedup by path, 3-lens refute per KEEP row, 1 Opus critic; cap 100 agents. The ledger (`docs/slim/ledger.md`) is written by the lead from its output and posted, not awaited (H ruling).

Facts found while preparing Wave 2 (so a slice does not trip on them):

- `git filter-repo` was not installed in this container (PLAN.md D12 recorded a40bce5 from the previous session's container); installed here with pip, version a40bce5.
- tendcf and nix2cf live at `frdminc/tendcf` and `frdminc/nix2cf` on GitHub (push access); Plektra at `djbclark/plektra-djbclark`, paseo4herdr at `djbclark/paseo4herdr`, site-djbclark and site-private at `djbclark/`. All five C3 repos are attachable from the cloud (J2b), as is the E1 destination.
- PLAN.md C7 names `bin/cow-pasture ls` and `acp-dispatch ls`; neither exists. `cow-pasture` has create/remove/scrub/trust/check/untrust and reads `cow list --json`; acp-dispatch has check/resume/wait/tell/outcome, and its records are the files under `~/.local/state/bigteam/*/jobs/`. The batch below uses the real commands.

### Operator batch for Wave 2 (the C7 drain gate; run on the Mac, paste the output here as one block)

Nothing in E2, E3, E4 or E6 merges before this is pasted. All read-only except step 7.

1. Sleeping herdr panes holding a Claude session: `herdr plugin action invoke djbclark.herdr-sleeper.list` (or `~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper list; ~/src/djbclark-ade/plugins/herdr-sleeper/herdr-sleeper log | tail -20`). Expected: nothing sleeping, nothing orphaned.
2. Resumable acp-dispatch records: `ls -la ~/.local/state/bigteam/*/jobs/ 2>/dev/null | grep -v '\.done'` and `launchctl list | grep -i acp-dispatch`. Expected: every record has a `.done`, no launchd job.
3. Worktrees and pastures: `cd ~/src/djbclark-ade && git worktree list` and `cow list --json 2>/dev/null | head -50`; for each listed path, `git -C PATH status --short | head -3` (clean = nothing printed). A dirty one is its owner's to migrate (order 9) or yours to waive by name (report F4, F5, F7).
4. Queued relay acks: `python3 ~/src/djbclark-ade/skills/session-finder/relay.py --pending --summary`. Expected: empty, or each of the eight ids in report I3 retired with `relay.py --retire ID --reason "slim-down C7"`.
5. Bigteam inboxes: `find ~/.local/state/bigteam -name 'inbox*' -newer ~/.local/state/bigteam -type f 2>/dev/null | head`; expected: none unread.
6. C1 live processes: `launchctl list | grep com.djbclark` and `pgrep -fl 'acp-run|acp-dispatch' || echo none`. Expected: deadline-sweep, pr-policy, load-watch listed; no acp-run process.
8. J2 pool audit input (ledger ruling 10): `aiuse --json` (or `aiuse pools`), so the lead can settle which paid plans are reachable only through omp or opencode before E9's machine-side uninstalls.
9. `bg`'s live path (ledger ruling 14): `ls -la ~/ops/site-private/bin/bg ~/ops/site-public-djbclark/bin/bg 2>&1`.
7. Wave 0 leftovers (tag and branch deletions done): in the shared checkout `git status` (stop on another session's edits), then `git fetch origin && git checkout master && git reset --keep origin/master`; then `git worktree prune`.

Facts from the site-djbclark clone (2026-11-06, `djbclark/site-djbclark` @ f11d8218, attached with push access as the E1 destination):

- `bin/fleet-watch` is in site-djbclark (`bin/fleet-watch`, beside `bin/bg`, `hook-deadline`, `hermes-ping`); PLAN.md C3's "home unverified" is settled: it is site-public, not site-private, and AGENTS.md's doc-table row pointing at a local `bin/fleet-watch` is wrong (E11 fixes the row).
- `skills/README.md` there says the hub layer was retired on 2026-10-14 ("nothing should link here any more"; public skills live in djbclark-ade, private ones in site-private). J2a makes that directory a third `skill-everywhere` root again for the moved skills, so the E1 intake branch rewrites that README in the same change, and `bin/skill-everywhere` gains the root (E1 owns that one edit, PLAN.md E10).
