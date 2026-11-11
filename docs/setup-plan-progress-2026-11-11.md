# Setup implementation progress — 2026-11-11

## A. Verified merged work

This continues the [November 10 matrix](setup-plan-progress-2026-11-10.md).
The implementation plan is still incomplete; remaining work is not all Mac-only.
GitHub confirmed the following merges. The checkpoint base is
`bc2a112a6e16f304d273f69b16d22c93e558dc6f`.

| PR | Implemented result | Merge commit |
|---|---|---|
| #550 | Explicit missing-Just acquisition followed by installation preview; Python acquisition and full setup remain separate | `333e9f370fd32fa07cdd161fd30f922d8700f2cb` |
| #551 | Effective context-budget reader; explicit legacy file reads remain isolated | `d6ae33f152ff670abb058fc0c0f40da2fc6ec038` |
| #552 | Fixed OpenAI/OpenRouter authenticated metadata probes | `4f146bf9775724e2fe93cc23f1f1a7ba967df45b` |
| #553 | Opt-in PR-access task records, deadline registration, and github.com API completion proof | `9682dfce19f3f445a4cdc8823622723042fa8ed5` |
| #554 | Anthropic/Gemini/DeepSeek authenticated metadata probes; five catalog probes total | `991f8b51c4ffd1313c2f2ebdf1afa7c730611e08` |
| #555 | Bounded context-budget and existing key-metadata scalar writes, including consistent quoted get/set paths | `7a5f55ff161b513f8644eb42b2020a768bdfd3bf` |
| #556 | Failed GitHub environment prerequisites stop downstream App discovery and ruleset operations | `bc2a112a6e16f304d273f69b16d22c93e558dc6f` |

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

1. **S1:** install arrays/choices and unsupported metadata writes remain refused.
   Other transitional consumers still prevent shipping a tracked unified
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

At this checkpoint, the next scoped code units are:

1. [#558](https://github.com/djbclark/djbclark-ade/pull/558): refuse default
   installation after unknown or failed component probes; explicit force must
   retain every existing authority check.
2. [#559](https://github.com/djbclark/djbclark-ade/pull/559): a pure nonsecret
   key worklist with explicit cache/freshness and coverage gaps. This is planning,
   not credential collection or current verification.
3. Shared installer-ledger locking to prevent concurrent operations from
   replacing each other's evidence; preserve dry-run and refused-operation
   behavior. Python acquisition remains a later unit.

Verify these live PR states before continuing. This document records a moving
checkpoint; it does not authorize stopping while actionable work remains.

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
verify actual PR, worktree, claim, agent and process states. #550–#556 merged;
check #558/#559 and the installer-ledger locking unit before starting overlap.
Resume existing owned work safely or create a fresh exclusively claimed WT.
Use available independent exact-head reviewers when a provider is unavailable;
preserve required CI/owner-trust checks. No invented approval or new waiver.
Continue cloud implementation while preserving security/S9, scheduled-apply,
credential, Pi acceptance, Mac/B2/evidence/date/operator-deletion boundaries.
Commit and push coherent units; maintain this checkpoint without stopping work.
```
