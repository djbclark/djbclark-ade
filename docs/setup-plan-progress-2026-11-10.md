# Setup implementation progress — 2026-11-10

Continuation: [verified merges and remaining work, 2026-11-11](setup-plan-progress-2026-11-11.md).

## A. Scope and evidence

The setup plan is **not complete**, and its remaining work is **not all Mac-only**.
Wave 6 source migrations are a separate milestone from the full S1–S9 plan.
This checkpoint follows master `2d77c496aaad5f0babdca57c51aeb9f856629bdf`;
later merges #553, #554 and #556 are recorded in the matrix (2026-11-12 snapshot).
The recent-PR table lists merged units; pending implementation PRs are
identified explicitly in the matrix.
It records code inspection, CI and review, not live installation acceptance.

Recent merged ADE units:

| PR | Result | Merge commit |
|---|---|---|
| #540 | Component-scoped doctor | `201905488cf0dfef9aa443811778fceaf4e82801` |
| #541 | Effective routing configuration | `06bc6e580b3c74388f4c21d833c649093520b42c` |
| #542 | Dependency source checkpoint and proposed history waivers | `24f9072432d98ec8e41fdb274eda0b56143a5ebc` |
| #543 | Merged-source status and remaining Mac evidence | `8de777502a45a3d7e32824b90e97a656a18fac8e` |
| #544 | First-run guidance and Python prerequisite diagnostics | `488261bf901751c19e7f332001966fc2d08f50a7` |
| #545 | Effective model-tier snapshot in runtime routing | `245804a8e81d605731c6df820aa7cdd21a9e2af2` |
| #546 | Pure dependency-update planning | `e2030a53d87a2f8a1bb2dee0aa9c56dfee92290f` |
| #547 | Whole-plan completion audit | `2f5fe462f589036e7703ccb79a4f5e7efb56dd88` |
| #548 | Effective install/key metadata reader adoption | `2d77c496aaad5f0babdca57c51aeb9f856629bdf` |

Required Linux/context-policy checks and owner-trust adversary status passed
before these merges. Available independent reviewers replaced unavailable
Cursor under the operator's explicit authorization; neutral/error Cursor
results are not claimed as successful reviews. No approval marker or new
waiver was invented. #544 passed 85 focused tests after repairing a cold
Python-cache write; #545 passed 538 tests and 51 subtests, one skipped.

#546 passed 92 focused tests, independent review, full Linux CI and the
required owner-trust gate before merging. Its update-plan command executes
no updates and establishes no installed state, freshness, ownership or admission.

[#548](https://github.com/djbclark/djbclark-ade/pull/548), reviewed head
`3e590145a1c438b39274bafd9b53374631385fce`, implements joint install/key
metadata adoption. Combined tests: 702 passed, one skipped, 51 subtests.
Independent architecture/correctness/security review found no remaining
blockers after fixing optional-key semantics and full raw-schema validation
before domain isolation. Full Linux CI, context-policy and owner-trust status
passed before merge.
No live configuration, key operations, installs or catalog choices changed.

## B. S1–S9 completion matrix

| Section | Implemented | Still required |
|---|---|---|
| S1 configuration | Effective loader/schema, atomic scalar set, legacy isolation, routing/gates and runtime tiers; #548 adds install/key readers; #551 adds the context-budget reader; #555 adds bounded context/key scalar writes | **Cloud code:** remaining domains/consumers and broader array/identity writer adoption. #548 preserves isolated legacy `install_path` reads while the default reader adopts unified/local metadata. Install arrays, key identities/commands and other unsupported metadata writes remain refused. GitHub/hardening and other domains remain transitional; no tracked `ade.toml` yet. |
| S2 entry point | Thin Just recipes for the implemented tools; scoped doctor | Recipes do not imply the underlying S3–S8 behaviors are complete. |
| S3 installation | Typed catalog, doctor/plan, user install helpers, explicit system transaction and installation ledger; #544 diagnostics. #550 merged at `333e9f370fd32fa07cdd161fd30f922d8700f2cb`: explicit missing-Just acquisition followed only by installation preview | **Cloud code:** Python acquisition and full bootstrap/orchestration, incomplete component recipes. **Live:** fresh Mac/Linux acceptance and provider logins. Successful Just bootstrap is not full setup. |
| S3a Hermes | DIY/AI prompt and recipes, catalog installation and chosen-component doctor | **Cloud code:** install choice flow and richer checklist probes. **Live:** Hermes/bridge/skills configuration and credentials. Scoped doctor currently delegates to the existing catalog probe. |
| S3b keys | Registry, bulk presence check, verification engine, outcome state and daily check artifact. #552 merged fixed OpenAI/OpenRouter metadata probes at `4f146bf9775724e2fe93cc23f1f1a7ba967df45b`; #554 merged Anthropic/Gemini/DeepSeek coverage at `991f8b51c4ffd1313c2f2ebdf1afa7c730611e08` (2026-11-11 snapshot). #559 adds pure cached `keys-plan` reporting with chosen-component gating and explicit coverage gaps | **Cloud code:** remaining seven provider probes, interactive batch collect/retry/skip, delivery and expiry handling. Cached reports never establish current verification or setup completeness. Metadata authentication does not establish inference funding/quota or pool acceptance. **Live:** credentials, authenticated validation and evidence of Paseo's secure-store behavior. |
| S4 updates | Checkout/skill-link updater and daily behind-check; opt-in checkout-only auto-apply; #546 candidate planning | **Cloud code:** dependency execution, installed/ownership/activity evidence, retry/doctor outcomes and new-dependency handling. **Policy:** scheduled apply, mid-turn behavior and failure notification remain the stated options 2–3 decision. |
| S4b jobs/services | Backend inventory/diff; launchd/systemd/cron and Paseo writes; pending/committed ownership ledger, locking and read-back | **Cloud code:** stronger shared admission, per-job activity/draining, durable busy/unknown/self-update deferral and cross-backend migration contracts. Backend support alone does not prove these. **Live:** backend activation, Linux user-manager/linger and installed-job verification. |
| S5/S5a hardening | Existing trust/review boundaries and design documents | **Explicitly deferred:** new hardening application/classifier, reader adoption and canaries. `ade_harden.apply_refused()` still refuses mutation. This is a policy deferral, not a Mac limitation. |
| S6 ongoing checks | Read-only GitHub/inventory/interaction-limit comparison; daily plist and install recipe | Remaining CI/notification/Forgejo/access coverage, renewal and canaries stay subject to the security ruling. **Live:** install/read-back the check job and authenticated observations. A check grants no repair authority. |
| S7 browser tasks | Templates and list/render/relay, dry-run and explicit send; unsafe tasks refused | **Merged 2026-11-11:** [#553](https://github.com/djbclark/djbclark-ade/pull/553) added opt-in pr-access lifecycle/deadline and exact github.com API completion readback (`9682dfce19f3f445a4cdc8823622723042fa8ed5`). Remaining template-specific readback and automatic polling stay pending. `RelayResult` is sent/unsent/dry-run, not completion. **Live/operator:** browser session, confirmations and private keys. |
| S8 GitHub setup | Manifest/config, observe/plan/dry-run and API-only environment/ruleset apply/verify; #556 (merged 2026-11-11, `bc2a112a6e16f304d273f69b16d22c93e558dc6f`) stops apply after a failed environment prerequisite | **Cloud code/testing:** fuller setup orchestration and T0–T3b verification harness. **Live/operator:** App create/install, permissions, stdin secret store and throwaway-account/PR tests. These need account access, not specifically macOS. |
| S9 cloud/Paseo | Design and pre-existing limited Cursor cloud tooling | **Gated:** signing and separate approval-token contract, earlier plan prerequisites, security un-deferral/order change and headroom. No new mailbox, launcher, cloud profile or pairing starts under routine continuation. |

The matrix was audited against the plan, source and pinned PR diffs. The
12-key count was also read directly from tracked `config/install.toml`.
Tests and source inspection used this cloud host; no provider login, secret
entry, daemon update, installed-file change or live admission proof occurred.

## C. Next work and hard stops

1. Continue remaining S1 domains and consumers, preserving explicit legacy
   isolation and writer boundaries. The install/key mapping and compatibility
   contract are in `docs/config-migration.md`; do not ship a tracked unified
   file while remaining consumers still refuse it.
2. Continue genuine S3 bootstrap/catalog coverage, configured S3b probes or
   S7 completion verification as separately tested cloud units. These remain
   code gaps, not Mac blockers.
3. Keep scheduled automatic apply, new security implementation and S9 behind
   their existing decisions. Do not infer provider acceptance from code tests.
4. Wave 6 still needs installed Mac migration proof, fleet delivery/receipt
   verification, B2 drain and recapture. C1+C2 remain granted; CFEngine/aiuse
   retained-history waivers remain proposed. Preserve logs/history, shims and
   `review-launch`, held Pi pools, the November 20 gate and explicit deletion
   confirmation. See [the continuation](slim/wave6-cloud-continuation-2026-11-10.md).

## D. Vendor-neutral resume prompt

```text
Continue djbclark/djbclark-ade from docs/setup-plan-progress-2026-11-10.md.
Read AGENTS.md, setup-plan.md, this matrix and the Wave 6 continuation.
Verify current PR/branch state rather than treating this snapshot as live.
Fetch origin/master and create a fresh claimed task worktree; older ADE
worktree paths in prior checkpoints are historical after cleanup.
#540–#548 are merged. #546 is candidate-only update planning, not execution.
#548 adopts install/key metadata readers, not new writer capabilities or live
operations. Follow config-migration.md for its
scopes and preserved explicit legacy reads. Next work is remaining S1 domains,
genuine bootstrap/catalog coverage, configured key verification or browser
completion read-back. No new source implementation should be assumed running.
Use claimed worktrees, available capable independent reviewers, exact-head
checks and owner-trust status; no fabricated APPROVE or new waivers.
Do not claim whole-plan completion or a Mac-only remainder. Preserve security,
scheduled-apply and S9 decisions. No live credentials/config/provider changes
are implied by cloud tests. Mac proof/B2/date/operator deletion gates remain.
Commit/push coherent work and update this snapshot when evidence changes.
```

Account quota/token telemetry is unavailable here; actual usage is unknown.
This batch reused available agents with bounded implementation/review roles.

Merged, clean ADE task worktrees through #548 were closed after verifying
their exact heads on GitHub; their claims were released and remote branches
retained. Source, handoff records and GitHub CI evidence remain available.
