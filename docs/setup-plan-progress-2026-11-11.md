# Setup implementation progress — 2026-11-11

## A. Verified merged work

This continues the [November 10 matrix](setup-plan-progress-2026-11-10.md).
The implementation plan is still incomplete; remaining work is not all Mac-only.
GitHub confirmed the following merges. The original checkpoint base was
`bc2a112a6e16f304d273f69b16d22c93e558dc6f`; refreshed 2026-11-12 against
`origin/master` `0cd37cb17133039fde2e162d81cf1b56204d6d01` (see the additions below).

| PR | Implemented result | Merge commit |
|---|---|---|
| #550 | Explicit missing-Just acquisition followed by installation preview; Python acquisition and full setup remain separate | `333e9f370fd32fa07cdd161fd30f922d8700f2cb` |
| #551 | Effective context-budget reader; explicit legacy file reads remain isolated | `d6ae33f152ff670abb058fc0c0f40da2fc6ec038` |
| #552 | Fixed OpenAI/OpenRouter authenticated metadata probes | `4f146bf9775724e2fe93cc23f1f1a7ba967df45b` |
| #553 | Opt-in PR-access task records, deadline registration, and github.com API completion proof | `9682dfce19f3f445a4cdc8823622723042fa8ed5` |
| #554 | Anthropic/Gemini/DeepSeek authenticated metadata probes; five catalog probes total | `991f8b51c4ffd1313c2f2ebdf1afa7c730611e08` |
| #555 | Bounded context-budget and existing key-metadata scalar writes, including consistent quoted get/set paths | `7a5f55ff161b513f8644eb42b2020a768bdfd3bf` |
| #556 | Failed GitHub environment prerequisites stop downstream App discovery and ruleset operations | `bc2a112a6e16f304d273f69b16d22c93e558dc6f` |

Merged after that base (verified with `gh pr view`, 2026-11-12 snapshot):
#557 (`e00a4989e3482fbec9610285124d60b838775a85`, 2026-11-11, Grok Bot
vendor-routing note), #563 (`dc3463b16c400a3c7af00a4aef3a8cbb4a0e1276`,
CFEngine-only upstream review gate), #562
(`17e03e34ae918d9946d36e68db6e1c91890aad45`), #566
(`d99a4cdf96ce84860f70f8996cb133446686cf11`), #558
(`13d70edb04d5b487c0e2a34d039e34047a00f646`, refuse default install after
unknown/failed probes) and #568 (`0cd37cb17133039fde2e162d81cf1b56204d6d01`),
the last four on 2026-11-12.

Required Linux CI, context-policy and owner-trust status passed before merge.
Available independent reviewers covered the exact final heads. In #553,
review found that GH_HOST could retarget verification; the fix pins github.com
and requires that host in persisted completion proof. The review thread was
resolved after inspecting the repair. Its final focused suite passed 103 tests.
#555 passed 872 tests and 51 subtests, with two skips; #554 passed 259 combined
tests. These overlapping suites must not be summed as distinct test coverage.

The automated Codex review on #555 reported a usage limit rather than an inline
finding. Its independent exact-head review passed and required checks were green;
the operator already authorized available-agent substitutes. That saved notice
is historical, not a live measurement of the current Codex allowance. Current
account quota is unknown. No approval marker or new waiver was fabricated.

## B. Remaining implementation and limits

1. **S1:** (2026-11-12, W16) install arrays/choices, key identities and `context_budget.dirs` writes landed
   ([config-migration C4](config-migration.md#c4-install-arrays-choices-and-key-identities-2026-11-12)); the remaining
   direct readers (`model_tiers`, `context_size_nudge`) now accept `ade.toml`, and `ade-config export-unified` generates
   it with an equivalence proof. The tracked file itself waits for in-flight catalog slices (section F cut-over
   checklist). Before W16: other transitional consumers prevented shipping a tracked unified
   `ade.toml`. New hardening reader/application work retains its policy deferral.
2. **S3:** supported Python must still be available before the merged Just
   bootstrap starts. Python acquisition, fuller orchestration, catalog gaps,
   and richer Hermes setup/probes remain. A proposed cold bootstrap bridge is
   design-only: existing install-ledger writers need concurrency protection,
   pending operations need explicit recovery, and elevated acquisition must not
   fall through into a root-owned user installation.
3. **S3b:** five metadata probes establish authentication only, never inference
   entitlement, funding, quota, subscription status, or Pi acceptance. Seven
   registry probes remain unknown. Aggregate presence checks, unlinked keys and
   unknown creation URLs prevent a complete collection claim. Interactive batch
   collection, delivery, and expiry handling remain unfinished.
4. **S4/S4b:** dependency execution and installed/ownership/activity evidence,
   shared admission/draining, durable deferrals and cross-backend migration
   remain. Scheduled apply, mid-turn behavior and notifications retain their
   existing decisions. Installer ledger locking alone is not fleet admission.
5. **S7:** only PR-access has the new completion protocol. Issue-access and App
   setup remain unverified. A registered deadline does not prove a running
   sweep or successful notification. Browser replies never prove completion.
6. **S8:** prerequisite ordering is repaired, but throwaway-account and T0–T3b
   live acceptance still require account access. Mocked tests are not that proof.
7. **S5/S5a/S9:** security deferrals, signing/approval-token prerequisites and
   cloud/Paseo gates remain unchanged.

## C. Active continuation, not a stopping point

State at 2026-11-12 (live `gh` snapshot; re-verify before acting):

1. #558: merged (see A).
2. [#559](https://github.com/djbclark/djbclark-ade/pull/559): open, in fix; a pure
   nonsecret key worklist with cache/freshness and coverage gaps. Planning only,
   not credential collection or current verification.
3. [#561](https://github.com/djbclark/djbclark-ade/pull/561): open, in fix; shared
   installer-ledger locking so concurrent operations keep each other's evidence.
   Python acquisition remains a later unit.
4. [#567](https://github.com/djbclark/djbclark-ade/pull/567) (native
   self-compaction/self-handoff): in fix in the 2026-11-12 wave (`gh pr view 567`
   reports `CLOSED` unmerged at `2026-11-12T17:04:55Z`); #564, #565 and #569
   are open (2026-11-12 snapshot). [#569](https://github.com/djbclark/djbclark-ade/pull/569)
   hands cloud continuation to local agents: follow its
   `docs/handoffs/cloud-to-local-2026-11-12/` handoff once merged, not this file's
   resume prompt alone.

This document records a moving checkpoint; it does not authorize stopping while
actionable work remains.

The progress watchdog is an in-session subagent, not a persistent cron service.
Workers and the watchdog stopped across a session interruption and were explicitly
reactivated. After any interruption, inspect actual agent/process state rather
than assuming a prior assignment is still running. `send_message` alone does not
restart a completed worker; use the environment's task-resumption mechanism.

## D. Preserved live gates and resume prompt

Wave 6 still needs installed Mac evidence, fleet delivery/receipt reconciliation,
B2 drain/recapture, and the granted C1+C2 snippets in live proofs. CFEngine/aiuse
history waivers remain proposed. Keep the held Pi pools unaccepted, preserve
logs/handoffs and relay.py, acp-dispatch, acp-run, and review-launch. No deletion
before the November 20 gate, successful evidence check and explicit operator
confirmation. See [the Wave 6 continuation](slim/wave6-cloud-continuation-2026-11-10.md).

```text
Continue djbclark/djbclark-ade; do not stop at this checkpoint.
Read AGENTS.md, docs/setup-plan.md, docs/setup-plan-progress-2026-11-11.md,
the prior completion matrix and the Wave 6 continuation. Fetch master and
verify actual PR, worktree, claim, agent and process states. #550–#558, #562,
#563, #566 and #568 merged (2026-11-12 snapshot); check #559, #561 and #567 (in fix)
plus the local handoff (#569) before overlap.
Resume existing owned work safely or create a fresh exclusively claimed WT.
Use available independent exact-head reviewers when a provider is unavailable;
preserve required CI/owner-trust checks. No invented approval or new waiver.
Continue implementation (local agents per #569) while preserving security/S9, scheduled-apply,
credential, Pi acceptance, Mac/B2/evidence/date/operator-deletion boundaries.
Commit and push coherent units; maintain this checkpoint without stopping work.
```
