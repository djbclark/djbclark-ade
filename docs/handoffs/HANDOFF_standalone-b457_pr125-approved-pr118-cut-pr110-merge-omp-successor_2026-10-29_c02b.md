---
schema_version: 1
handoff_id: c02b
parent_handoff_ids: [3092]
lineage: deterministic
chain: [standalone-b457]
repo: djbclark-ade
workspace: main
branch: master
head_sha: 8fe18cb2a5e1a687556ec4012ad8d5127cc42b06
created_at: 2026-10-29T04:52:00-0400
writer: claude-code
---

# Handoff — PR 125 approved, PR 118 cut to docs-only needs a new pool, PR 110 master-merge running; lead moves to omp Sonnet 5.5

## The Goal

Land the open ADE PRs on djbclark's pinned-merge yes, each with an adversary APPROVE marker for the exact head: PR 125 (macOS CI on request), PR 110 (`bin/self-slash`), PR 118 (CI waiver), then picklist slice 1. Spend the omp credit grant ($80 of $200 left at 03:52 ET snapshot, expires 2026-11-04T12:00Z) before the Claude quota resets (2026-10-30T09:59Z), carefully near the end.

## Where We Are

1. **Lead hand-off.** Claude weekly is 13% left (reset 09:59Z Oct 30). djbclark ordered: finish the step, write Tier 1, then `~/src/djbclark-ade/bin/self-slash --finish --successor omp/anthropic/claude-sonnet-5-5 --thinking high` (API credits, off the subscription). This handoff is the Tier 2 for that successor.
2. **PR 125** (https://github.com/djbclark/djbclark-ade/pull/125, branch `ci-macos-on-request-2026-10-29`, worktree `/Users/djbclark/src/djbclark-ade-ci-macos-wt`, head `cbae596e6890edbfb72776d70c121c4ff0318f27`): macOS `pytest` runs only on a manual `Tests` dispatch with the `macos` input. Adversary round 1 is **APPROVE** for that head (report `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/adv-pr125-report.md`, marker line 2 of the report). Non-blocking findings to fold in: A1 MEDIUM, once PR 125 and PR 118 both merge no waiver can verify (PR 118's waiver treats a skipped macOS job one way; fix in PR 118's cut or its docs); A2 LOW, `docs/threat-model.md:63` is now false (rule 8 docs move with code); A3 LOW, the bash 3.2 regression net is off by default and nothing says so; A4 LOW, precedence of `context_only` vs `macos` unstated; A5 NIT, job id `pytest` no longer says macOS. Fixing A2/A3/A4 makes a new head, so the PR body then needs a new adversary marker for it (or djbclark accepts them as a follow-up). Its own CI: `pytest` skipped, `pytest-linux` and `context-policy` were pending at 04:40 ET.
3. **PR 110** (`ctx-selfslash-2026-10-28`, worktree `/Users/djbclark/src/djbclark-ade-ctx-selfslash-wt`, head `41e1bfba9c0e2a0525f1fc68084273f98a17b879`, `DIRTY`): codex slice `pr110-merge` (kind mechanical) is **running**: merge `origin/master` in (CHANGELOG-only conflict expected, BLOCKED if code conflicts), prove the code unchanged, run self-slash tests, push. It writes `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/pr110-merge-report.md`. The new head needs a fresh adversary APPROVE marker, CI, and djbclark's yes for that head (his 2026-10-28 yes covered `41e1bfb` only). PR 116 also edits `bin/self-slash`.
4. **PR 118** (CI waiver, branch `ci-waiver-2026-10-28`, worktree `/Users/djbclark/src/djbclark-ade-ci-waiver-wt`, head `72dad2aadd972a058cae9b8eb4ee95f49bd251ba`, still pushed, `DIRTY`): adversary r5 is **BLOCK** (retarget events `base_ref_deleted` and `automatic_base_change_succeeded`; B1 whole-`head` comparison with volatile fields; B2 shadow modules like a root `pluggy.py`). I started repair r5 (the docs-only cut, brief `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/ci-waiver-repair5-brief.md`) on codex, but **codex is out of `--kind code` eligibility (0% on its tightest window, it dropped out of `aiuse --available`)**: the dispatch was refused before it ran; no work was done on the branch. It must be re-dispatched on another pool.
5. **omp credits:** the PR 125 adversary round ran on omp Opus (cost not yet measured: the `aiuse` snapshot refreshes hourly, last read $80.00 at 03:52 ET). The shared checkout is on `master` `8fe18cb` with four foreign uncommitted `skills/paseo*/SKILL.md` edits (not mine, never touch); the ci-waiver and PR 110 worktrees each carry two graft-owned dirty hook files (`.claude/settings.json`, `.cursor/hooks.json`): never stage them.

## What We Tried

1. Dispatching PR 118 repair r5 to codex `gpt-6.1-sol --kind code`: refused ("codex takes --kind code only while every window has at least 50% left, [routing].plenty_min; now: 0% left on its tightest window"), because the earlier four repair rounds spent codex's window. Nothing ran. Lesson: check `aiuse --available --json` for the codex row before a codex batch.
2. PR 118 rounds 1 to 5: each adversary round found a new HIGH in the `master-merge` class (forgeable H0 green, replace refs and grafts, forged commit-graph, `pull_requests[]` computed from current PRs, retarget event names). Structural fix in repair r3 (private GitHub-fetched object store) closed the local-object-store class; the provenance-of-H0 class stays open-ended. The `docs-only` class had no finding in r5.

## Key Decisions

Cutting PR 118 to `docs-only` was my recommended option; djbclark asked "What is 118?" and never picked an option, so the cut is **my choice, not his ruling**; it is reversible (head `72dad2a` stays in PR history). Everything else is as in the parent handoff (3092): omp Opus for adversary rounds, a worktree per PR, no merge without djbclark's yes for the exact head.
New global rule (djbclark, 2026-10-29): CI is Linux-only in every project, no macOS job unless he asks by name; in `~/ops/site-djbclark/home-agents.md` item 37 (commit `a4bfc3f`, 13,992 bytes) and `~/ops/site-private/memory/feedback_macos_ci_on_request_only.md` (`78b5689`).

## Decisions

- [decision] cut PR 118 to the docs-only class; rejected: a fifth master-merge repair round; because every round found a new high in that class and r5 A1 is another API-semantics hole
- [decision] PR 125 makes macOS CI dispatch-only rather than label-triggered; rejected: a `ci-macos` label on `pull_request` types; because a label add re-runs every job on the PR
- [ruling] "Nothing needs to use macos unless specifically requested." (djbclark, 2026-10-29)
- [ruling] "That is for all projects not just us." (djbclark, 2026-10-29)
- [ruling] "Spend the credits now. Our aim is to exhaust the omp pool before quota resets, but be careful towards the end to be able to restart work elsewhere with minimal token loss." (djbclark, 2026-10-29)
- [ruling] "Claude subscription critical: weekly 87% used, 13% left, its reset is 09:59Z. Finish the current step, write your Tier 1 handoff, then run ~/src/djbclark-ade/bin/self-slash --finish --successor omp/anthropic/claude-sonnet-5-5 --thinking high" (djbclark, 2026-10-29)
- decided_in [[HANDOFF_standalone-b457_pr125-approved-pr118-cut-pr110-merge-omp-successor_2026-10-29_c02b]]

## Relations

- continues [[HANDOFF_standalone-b457_pr118-r4-pushed-adv-r5-running-quota-critical_2026-10-29_3092]]

## Evidence & Data

Reports under `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-28/`: `adv-pr118-report.md` through `adv-pr118-r5-report.md` (all BLOCK), `ci-waiver-report.md` through `ci-waiver-r4-report.md`. Under `.../adhoc-2026-10-29/`: `adv-pr125-report.md` (APPROVE `cbae596`), `pr110-merge-brief.md`, `ci-waiver-repair5-brief.md`, `adv-pr125-brief.md`.
Pool readings at 04:50 ET: Claude 13% left; omp credits $80 (40%); z.ai 5-hour 61.7%; agy (Gemini weekly) 54%; Grok Bot 47.6%; Grok 100%; codex absent from `aiuse --available` (tightest window 0%).

## Operator Feedback

Replies are numbered/labelled; no merge without a yes for the exact head; "Nothing needs to use macos unless specifically requested" is for all projects.

## Where We're Going

1. **Read the PR 110 merge slice report, then dispatch its adversary round.** `~/src/djbclark-ade/bin/acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-29/jobs/pr110-merge.json`; read `.../pr110-merge-report.md`; if `STATUS: merged master, pushed <sha>`, write an adversary brief for that sha (copy `.../adhoc-2026-10-28/` PR 110 r5 brief shape) and dispatch `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high --name adv-pr110-r6 ...`; BLOCKED: read the question and decide.
2. **Re-dispatch the PR 118 docs-only cut** on a pool that can take it, same brief: `bin/acp-dispatch omp --model anthropic/claude-sonnet-5-5 --kind code --effort high --name ci-waiver-r5b -f ~/.local/state/bigteam/adhoc-2026-10-29/ci-waiver-repair5-brief.md -C ~/src/djbclark-ade-ci-waiver-wt --out ~/.local/state/bigteam/adhoc-2026-10-29 --perm all --timeout 3600 --detach --no-wait` (or zcode/agy per `route_agent.py plan`; check `aiuse --available --json` first, item 32). Then adversary r6 on omp Opus for the new head, PR body refresh with the marker.
3. **PR 125:** fix A2 (`docs/threat-model.md:63`), A3 and A4 in the PR 125 worktree (small; a codex/omp slice or by hand in that worktree), push, new adversary marker for the new head, wait for CI, then ask djbclark for the pinned merge yes (`gh pr merge 125 --squash --match-head-commit <sha>`). Or ask djbclark to accept the low findings as a follow-up and merge `cbae596` as approved.
4. **Credit pacing:** before each batch `aiuse --available --json` (omp row `balance_usd`, `observed_at` hourly); stop starting omp rounds below about $15; before that checkpoint every slice, push every branch, write a handoff so work restarts on another pool with little rework. Measure one adversary round's cost from the balance change.
5. After PR 110 merges: picklist slice 1 (Opus design) in a new worktree (research in bigteam `adhoc-2026-10-28` and `docs/queue.md`, PR 111 entry). PR 117: `gh pr checks 117`, GraphQL `reviewThreads`, ask for the merge yes.

## Detached jobs

1. `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/jobs/pr110-merge.json`; report `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/pr110-merge-report.md`; done `/Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/pr110-merge-report.md.done` (absent at 04:50 ET, running); rearm: `/Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait /Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/jobs/pr110-merge.json /Users/djbclark/.local/state/bigteam/adhoc-2026-10-29/pr110-merge-report.md.done`. Codex slice merging master into PR 110's branch; read the report, then item 1 above; then close the record.
Closed this session: `adv-pr125` (APPROVE read), `ci-waiver-r5` (never ran; re-dispatch is item 2). No sub-agent report is BLOCKED.

## Quick Start

```bash
cd ~/src/djbclark-ade
bin/acp-dispatch check ~/.local/state/bigteam/adhoc-2026-10-29/jobs/pr110-merge.json
aiuse --available --json 2>/dev/null | head -c 1500
gh pr checks 125 -R djbclark/djbclark-ade; gh pr view 110 -R djbclark/djbclark-ade --json headRefOid,mergeStateStatus
# re-arm the waiter as its own run_in_background Bash call (timeout 7200000) if pr110-merge is not done:
# /Users/djbclark/src/djbclark-ade/bin/acp-dispatch-wait <jobs/pr110-merge.json> <pr110-merge-report.md.done>
```
