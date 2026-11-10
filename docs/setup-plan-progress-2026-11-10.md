# Setup implementation progress — 2026-11-10

## A. Scope and evidence

The setup plan is **not complete**, and its remaining work is **not all Mac-only**.
Wave 6 source migrations are a separate milestone from the full S1–S9 plan.
This snapshot follows master `245804a8e81d605731c6df820aa7cdd21a9e2af2`.
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

Required Linux/context-policy checks and owner-trust adversary status passed
before these merges. Available independent reviewers replaced unavailable
Cursor under the operator's explicit authorization; neutral/error Cursor
results are not claimed as successful reviews. No approval marker or new
waiver was invented. #544 passed 85 focused tests after repairing a cold
Python-cache write; #545 passed 538 tests and 51 subtests, one skipped.

[#546](https://github.com/djbclark/djbclark-ade/pull/546), head
`30e4ab86aff95737ef9f34379367a2e613b74f68`, implements pure dependency
update planning. Its 92 focused tests and independent review pass; full CI
and merge remain pending at this snapshot. It executes no updates and
establishes no installed state, version freshness, ownership or admission.

## B. S1–S9 completion matrix

| Section | Implemented | Still required |
|---|---|---|
| S1 configuration | Effective loader/schema, atomic scalar set, legacy isolation, routing/gates and runtime tiers | **Cloud code:** remaining domains and consumers. `KNOWN_TOP_LEVEL` in `bin/ade_config.py` covers only routing tables, gates and tiers. `ade_install.load_catalog()` still refuses a present unified file. No tracked `ade.toml` yet. |
| S2 entry point | Thin Just recipes for the implemented tools; scoped doctor | Recipes do not imply the underlying S3–S8 behaviors are complete. |
| S3 installation | Typed catalog, doctor/plan, user install helpers, explicit system transaction and installation ledger; #544 diagnostics | **Cloud code:** real Python/Just bootstrap and orchestration, incomplete component recipes. **Live:** fresh Mac/Linux acceptance and provider logins. Diagnostics are not bootstrap. |
| S3a Hermes | DIY/AI prompt and recipes, catalog installation and chosen-component doctor | **Cloud code:** install choice flow and richer checklist probes. **Live:** Hermes/bridge/skills configuration and credentials. Scoped doctor currently delegates to the existing catalog probe. |
| S3b keys | Registry, bulk presence check, verification engine, outcome state and daily check artifact | **Cloud code:** configured verification coverage, batch collect/retry/skip, delivery and expiry handling. All 12 shipped key rows currently lack `verify_argv`. **Live:** credentials, authenticated validation and evidence of Paseo's secure-store behavior. |
| S4 updates | Checkout/skill-link updater and daily behind-check; opt-in checkout-only auto-apply; #546 candidate planning | **Cloud code:** dependency execution, installed/ownership/activity evidence, retry/doctor outcomes and new-dependency handling. **Policy:** scheduled apply, mid-turn behavior and failure notification remain the stated options 2–3 decision. |
| S4b jobs/services | Backend inventory/diff; launchd/systemd/cron and Paseo writes; pending/committed ownership ledger, locking and read-back | **Cloud code:** stronger shared admission, per-job activity/draining, durable busy/unknown/self-update deferral and cross-backend migration contracts. Backend support alone does not prove these. **Live:** backend activation, Linux user-manager/linger and installed-job verification. |
| S5/S5a hardening | Existing trust/review boundaries and design documents | **Explicitly deferred:** new hardening application/classifier, reader adoption and canaries. `ade_harden.apply_refused()` still refuses mutation. This is a policy deferral, not a Mac limitation. |
| S6 ongoing checks | Read-only GitHub/inventory/interaction-limit comparison; daily plist and install recipe | Remaining CI/notification/Forgejo/access coverage, renewal and canaries stay subject to the security ruling. **Live:** install/read-back the check job and authenticated observations. A check grants no repair authority. |
| S7 browser tasks | Templates and list/render/relay, dry-run and explicit send; unsafe tasks refused | **Cloud code:** persistent lifecycle, deadline and API/artifact completion read-back. `RelayResult` is sent/unsent/dry-run, not completion. **Live/operator:** browser session, confirmations and private keys. |
| S8 GitHub setup | Manifest/config, observe/plan/dry-run and API-only environment/ruleset apply/verify | **Cloud code/testing:** fuller setup orchestration and T0–T3b verification harness. **Live/operator:** App create/install, permissions, stdin secret store and throwaway-account/PR tests. These need account access, not specifically macOS. |
| S9 cloud/Paseo | Design and pre-existing limited Cursor cloud tooling | **Gated:** signing and separate approval-token contract, earlier plan prerequisites, security un-deferral/order change and headroom. No new mailbox, launcher, cloud profile or pairing starts under routine continuation. |

The matrix was audited against the plan, source and pinned PR diffs. The
12-key count was also read directly from tracked `config/install.toml`.
Tests and source inspection used this cloud host; no provider login, secret
entry, daemon update, installed-file change or live admission proof occurred.

## C. Next work and hard stops

1. Finish #546's required checks and merge at its reviewed head.
2. Prepare a bounded S1 install/keys fold: an explicit projection table,
   schema composition, no import cycle, malformed-input refusal and preserved
   class/choice/system boundaries. This is cloud code; design preparation is
   underway, not an implemented adoption. Do not ship a tracked unified file.
3. Follow with genuine S3 bootstrap/catalog coverage, configured S3b probes
   or S7 completion verification, each as a separately tested unit.
4. Keep scheduled automatic apply, new security implementation and S9 behind
   their existing decisions. Do not infer provider acceptance from code tests.
5. Wave 6 still needs installed Mac migration proof, fleet delivery/receipt
   verification, B2 drain and recapture. C1+C2 remain granted; CFEngine/aiuse
   retained-history waivers remain proposed. Preserve logs/history, shims and
   `review-launch`, held Pi pools, the November 20 gate and explicit deletion
   confirmation. See [the continuation](slim/wave6-cloud-continuation-2026-11-10.md).

## D. Vendor-neutral resume prompt

```text
Continue djbclark/djbclark-ade from docs/setup-plan-progress-2026-11-10.md.
Read AGENTS.md, setup-plan.md, this matrix and the Wave 6 continuation.
Verify current PR/branch state rather than treating this snapshot as live.
#540–#545 are merged. #546 is candidate-only update planning, not execution;
finish required checks/review before merging if it remains open. Next S1
install/keys adoption needs the explicit mapping and compatibility design.
Use claimed worktrees, available capable independent reviewers, exact-head
checks and owner-trust status; no fabricated APPROVE or new waivers.
Do not claim whole-plan completion or a Mac-only remainder. Preserve security,
scheduled-apply and S9 decisions. No live credentials/config/provider changes
are implied by cloud tests. Mac proof/B2/date/operator deletion gates remain.
Commit/push coherent work and update this snapshot when evidence changes.
```

Account quota/token telemetry is unavailable here; actual usage is unknown.
This batch reused available agents with bounded implementation/review roles.
