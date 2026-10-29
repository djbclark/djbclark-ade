---
schema_version: 1
handoff_id: 54c2
parent_handoff_ids: [fd05]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 8fe18cb2a5e1a687556ec4012ad8d5127cc42b06
created_at: 2026-10-29T00:58:00-04:00
writer: claude-code
---
# Handoff — PR 114 merged; PR 110 awaiting CI; PR 118 (CI waiver) in repair

## The Goal
Chain standalone-b457: the context-visibility audit (PRs 107, 108, 111, 114 merged; 110 open) and, added this session by djbclark, a CI-waiver
mechanism so low-risk changes stop waiting on (backed-up) CI, plus the picklist-safety build queued behind PR 110.

## Where We Are
1. PR 114 MERGED as b8c93de (squash, pinned to 0fd56f8). Master had advanced; the only conflict was CHANGELOG.md; `git patch-id` of the code diff vs master was
   15f51c7c before and after, so the code is byte-identical to the adversary-approved c72fdf9. 117 hook tests passed on the merged tree. macOS CI not awaited
   (djbclark said yes to merge without the macOS queue).
2. PR 110 (self-slash) head 41e1bfba9c0e2a0525f1fc68084273f98a17b879: master merged in (0522c74, `bin/self-slash` conflict hand-resolved: master's `agent read` then
   `pane read` fallback for zcode ported into the two-window loop), 157 tests passed at 0522c74, adversary r4 APPROVE 0522c74, then a 3-line doc fix in
   `skills/handoff/SKILL.md` for Codex's P1 on 557fae5 (thread RESOLVED via GraphQL), adversary r5 (codex gpt-6.1-sol medium) APPROVE 41e1bfb. PR body marker updated to 41e1bfb.
   CI on 41e1bfb: context-policy pass, pytest-linux and macOS pytest queued (GitHub runner backlog, 8+ runs queued since 03:34Z). Mergeable UNKNOWN (recomputing).
3. PR 118 (CI waiver, branch ci-waiver-2026-10-28, worktree ~/src/djbclark-ade-ci-waiver-wt) head c9f201a: adversary r1 BLOCK (omp Opus high), body updated with the BLOCK marker.
   Repair round 1 is RUNNING (codex gpt-6.1-sol via `acp-dispatch resume`, same job record).
4. Stray edits in the shared checkout restored (bin/self-slash, prompt_line.py): they duplicated agy PR 116; backup at `~/.local/state/bigteam/adhoc-2026-10-28/stray-shared-checkout.diff`.
   Four `paseo*/SKILL.md` edits remain: Paseo skill-sync overwrite, not an agent's edit.
5. bb2a32df (Paseo agent, "loadwatch sonnet") is alive: owns PR 105 (merged 54afb58), PR 117 (nudge log + PostToolUse, adversary running, hook registration awaits djbclark's yes). Relay acks exchanged both ways (delivered).

## What We Tried
1. `bg bash -lc '... pytest ...'` was refused by bg (read as a full suite in the ade repo). Use `cd WT && bg uv run --no-project --with pytest pytest -q <files> > log 2>&1` directly, in the background.
2. Merging PR 114 pinned to c72fdf9 failed: "Pull Request has merge conflicts" (master moved). Fixed by merging master in the worktree.
3. A foreground `gh pr checks` polling loop (8 x 45 s): a rule violation (never poll); wait on a notification or a file instead.
4. `relay.py --cancel` does not close expectations (only deferred messages); two old expectations (pr105-owner-check, nudge-overlap) stay `open` although bb2a32df answered them; treat as answered.
5. astra consult's `ADVISOR EDITED THE TREE` flag was a false positive (status hash identical, only HEAD moved from a foreign fast-forward).

## Key Decisions
Picklist design: Opus consult (fleet.py lets Claude's registry `waiting`/`waitingFor` survive herdr's overwrite; self-slash waits and exits 6 naming the card; relay defers a blocked target) and
astra consult (shared fail-closed submission gate plus fake-herdr harness, refuse Paseo-Claude busy steers) agree on principles; djbclark chose "Opus slice 1, then the harness".
It is queued behind PR 110's merge (same file). Opus also said: leave `askUserQuestionTimeout` unset globally; root cause of herdr `working` during a card is herdr#3467; comment on herdr#5263 is an
upstream option (not posted).
CI waiver design (djbclark's idea 2026-10-28): classifier `bin/ci-waiver` (`docs-only`: CHANGELOG.md, docs/handoffs/**; `master-merge`), `pr-wait` `ci_state: waived` only with a live `ci-waiver:v1`
marker for the full head plus an adversary APPROVE, a red check never waived, no `[skip ci]` (squash would copy it and skip master's push run), the push-to-master run is the backstop.
Adversary r1 BLOCK reasons (A1 H0 green forgeable, A2 PR head's own classifier decides, A3 reviewer unauthenticated: all agents post as one GitHub account, A4 .gitattributes merge=union)
drove repair round 1 (brief: `~/.local/state/bigteam/adhoc-2026-10-28/ci-waiver-repair1-brief.md`).

## Decisions
- [ruling] "If we have high confidence that a change is correct we should bypass CI, and at most ask another agent of appropriate strength for a review directly." (djbclark, 2026-10-28)
- [ruling] Restore the two stray files in the shared checkout to HEAD (card answer 1) (djbclark, 2026-10-28)
- [ruling] Picklist build: "1. Opus slice 1, then the harness" (card answer) (djbclark, 2026-10-28)
- [ruling] Merge 114 now, merge 110 once its Linux job passes, without waiting for the macOS queue (card answer 1) (djbclark, 2026-10-28)
- [ruling] "Try 4 overdue now, if you can not get through, assume those agents are archived and reroute." (djbclark, 2026-10-28)
- [decision] Build the CI waiver with a mechanical classifier, not an agent claim; rejected: a label or `[skip ci]` convention; because a claim is forgeable and `[skip ci]` can swallow master's push run
- [decision] Merge PR 114 after a CHANGELOG-only conflict on the strength of an identical code patch-id; rejected: a new adversary round; because the reviewed code diff was provably unchanged
- continues [[HANDOFF_standalone-b457_ctx-prs-merged-110-r3-consults-running_2026-10-28_fd05]]
- decided_in [[HANDOFF_standalone-b457_pr114-merged-pr110-ci-pr118-repair_2026-10-29_54c2]]

## Relations
- continues [[HANDOFF_standalone-b457_ctx-prs-merged-110-r3-consults-running_2026-10-28_fd05]]

## Evidence & Data
Reports under `~/.local/state/bigteam/adhoc-2026-10-28/`: `adv-pr110-r4-report.md`, `adv-pr110-r5-report.md`, `adv-pr118-report.md` (A1-A4 critical/high, B1-B3, C1-C6; exploit harnesses /tmp/adv-pr118/),
`picklist-consult-opus-report.md`, `picklist-consult-astra-report.md`, `ci-waiver-report.md` (being rewritten by the repair). Test counts: PR 110 157 passed (4 files, 591 s, via bg); PR 114 117 passed.
Adversary r4 A1 (Low): no test covers the `herdr pane read` fallback (mutant survives). Open Codex marker on PR 110 said has_unresolved_findings true at 557fae5; the real thread was found via
`gh api graphql reviewThreads`, and `pr-wait` reported `findings-not-collected` instead of the finding.

## Operator Feedback
djbclark: wants CI skipped when confidence is high, reviewed directly by a suitably strong agent; walks via /steps; merges are his yes, pinned to a head.

## Where We're Going
1. Re-arm the ci-waiver waiter (Detached jobs); when the repair report is DONE, read it, then dispatch adversary r2 on PR 118's new head (omp Opus 5.5 high, brief as `adv-pr118-brief.md` with the head replaced; also have it
   re-run the four round-1 exploits e1/e1b/e1c/e4/e6). APPROVE: write the marker for the new head into PR 118's body (replace the BLOCK marker's head note), confirm CI, ask djbclark to merge pinned to that head.
   PR 118 touches `.github/workflows/test.yml`, which PR 105 also changed: expect a conflict, resolve by hand (a code file: needs re-review).
2. PR 110: check `gh pr checks 110` (pytest-linux, context-policy; macOS may stay queued). When Linux passes, run `bin/pr-wait 110 --repo djbclark/djbclark-ade --head 41e1bfba9c0e2a0525f1fc68084273f98a17b879 --out /tmp/prw110 --adversary-required --no-request` in the background,
   recheck `reviewThreads` isResolved (GraphQL, not the marker), then merge `gh pr merge 110 --squash --match-head-commit 41e1bfba9c0e2a0525f1fc68084273f98a17b879` with an explicit `--subject/--body` (djbclark said yes to this, card 2026-10-28). If mergeable turns CONFLICTING, merge origin/master in `~/src/djbclark-ade-ctx-selfslash-wt` (git status/log first), compare `git patch-id` of the code diff before and after, retest via bg, push, and tell djbclark.
3. After PR 110 merges: build picklist slice 1 (Opus design) in a new worktree; PR 116 (agy, c0cd832) also edits bin/self-slash and prompt_line.py: whichever merges second takes a master merge.
4. Follow-ups, last: PR 110 follow-up test for the `pane read` fallback (r4 A1); `pr-wait` surfaced `findings-not-collected` instead of the open Codex thread (investigate collecting reviewThreads); sibling RecursionError readers (`guard_level` in `bin/claude-fleet-governor`, `load_state` in `bin/claude-quota-guard`);
   a zcode busy-pattern and `read_screen` fallback (r4 A3); remove worktrees after merges: `-ctx-selfslash-wt`, `-ctx-f2-wt` (PR 114 merged: remove now), `-ci-waiver-wt` after PR 118, `-handoff-b-wt` after this handoff branch merges or drops.
5. Uncommitted: only the four daemon-sync `skills/paseo*/SKILL.md` edits in the shared checkout (not ours). Graft dirties `.claude/settings.json` and `.cursor/hooks.json` in worktrees: never stage them.

## Detached jobs
1. `~/.local/state/bigteam/adhoc-2026-10-28/jobs/ci-waiver.json`; report `.../ci-waiver-report.md`; done `.../ci-waiver-report.md.done` (absent, running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/jobs/ci-waiver.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/ci-waiver-report.md.done`. Repair round 1 of PR 118 (codex gpt-6.1-sol). Read the report, then item 1 above; then close the record.
All other records of this session are closed. No sub-agent report is BLOCKED.

## Quick Start
```bash
cd ~/src/djbclark-ade
# re-arm the waiter above as its own run_in_background Bash call (timeout 7200000)
bin/acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-28/jobs/ci-waiver.json
for n in 110 116 117 118; do gh pr view $n -R djbclark/djbclark-ade --json state,headRefOid,mergeable; done
gh pr checks 110 -R djbclark/djbclark-ade
```
