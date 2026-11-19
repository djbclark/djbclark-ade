# NATS JetStream implementation plan — ADE issue 779

Status: implementation and the approved bounded rollout verified complete. See [final acceptance](nats-jetstream-final-acceptance.md) and [the execution ledger](nats-jetstream-execution.md) for published code, CI, native two-host succession, the first real workstream, activation and recovery evidence. Broader enrollment remains separately gated. Updated on 2026-11-18; existing NixOS `vps-hub`, no Google Cloud.

Issue: [Rethink handoff: pub/sub and leadership-token registry](https://github.com/djbclark/djbclark-ade/issues/779).

## A. Objective and execution contract

A1. Implement ticket 779 with NATS JetStream, using stable role addresses, conditional ownership transfers, durable report delivery, and machine receipts. GPT Astra reviewed the architecture and implementation sequence.

A2. Begin implementation with `/goal`, then `/fan-out`, the approved replacement for retired `/bigteam`. The goal covers reviewed code, CI, a two-host pilot, approved activation, recovery evidence, and documentation. Planning or merged code alone does not complete it.

A3. Develop in exclusively claimed task workspaces. Revalidate the published base, session ownership, and current lead before writing; the previously named lead reported `closed` during planning. Preserve others' edits in the shared checkout.

A4. Keep the final plan in the task workspace and open its Markdown file for the operator. Revalidate dated observations before execution. No model roster or quota snapshot in this document authorizes a later launch.

## B. Architecture and interfaces

B1. Use one authoritative coordination stream containing role-control records, immutable report envelopes, receipts, and operation records. This keeps conditional updates within one JetStream transaction domain. Use NATS Object Store for larger artifacts; references must work across hosts and include content hashes.

B2. A role has a stable identity independent of its current agent. Its record contains owner identity, ownership epoch, coordination generation, lifecycle state, resource bindings, and handoff evidence. Distinguish the ownership epoch from the record's compare-and-swap revision.

B3. Obtain authoritative ownership state from the stream leader. Transfer ownership using expected-subject-sequence checks. Fence ownership-sensitive receipts against the current role revision; where uniqueness and ownership must be checked together, use a same-stream atomic batch. Prove this exact recipe in CI before building dependent integrations. <sup>[1](#S1) [2](#S2)</sup>

B3a. Use `ADE_COORD_V1` with role-control subjects `ade.v1.role.<role_id>`, immutable report subjects `ade.v1.report.<role_id>.<message_id>`, and receipt subjects `ade.v1.receipt.<role_id>.<message_id>.<stage>`. IDs must be opaque subject tokens. Transfer writes the role subject with `Nats-Expected-Last-Subject-Sequence` set to the observed role revision. To fence a receipt, set that header to the role revision and `Nats-Expected-Last-Subject-Sequence-Subject` to the role subject. Where a receipt must also be unique, atomically publish a guard record checking the role revision and the receipt checking its own subject sequence is `0`. Do not modify the guarded role subject earlier in that batch. A failed condition rejects the entire batch; it never falls back to unconditional publication.

B3b. Use the maintained JavaScript NATS client and its batch API in the shared coordination library, the Paseo plugin, and a narrow JSON CLI called by existing Python helpers. Keep consumer acknowledgements, local storage, and external effects outside the claimed scope of the JetStream atomic batch. The protocol proof must race transfer against receipt publication and test retries after an unknown commit result.

B4. Reports address the stable receiving role, not its current owner's epoch. A handoff must not invalidate a legitimate worker report. Validate the producer's assignment separately.

B5. Expose a narrow shared coordination interface:

| Interface | Responsibility |
|---|---|
| Role get/watch/transition | Authoritative lookup and conditional lifecycle changes |
| Report publish/status | Stable message ID, artifact references, publication evidence |
| Inbox list/read/dispose | Durable intake and explicit disposition |
| Outbox reconcile | Recover buffered or uncertain publications |
| Operation inspect/reconcile | Resolve uncertain external effects before retries |
| Doctor | Capability and connectivity checks without ownership changes |

B6. Define receipts precisely: **local-buffered → broker-accepted → ADE-inbox-recorded → processed**. None implies model comprehension. A queued Paseo notification cannot establish delivery or processing. Keep the authoritative inbox separate from its coalesced wake notification.

B7. Persist reports and retry intent locally before announcing completion. Reuse message and operation IDs after crashes. Enforce immutable report IDs with digest checks and application deduplication beyond the broker's duplicate window.

B8. Retain authoritative reports independently of consumer acknowledgements. Successors replay retained records and consult durable dispositions, so an old consumer's late acknowledgement cannot hide unfinished work.

B9. Configure file storage, synchronous persistence with `sync_interval: always`, reject-new capacity limits, and no automatic expiry during the pilot. Preserve records rather than discard old reports when capacity is exhausted. Single-node storage remains vulnerable to total disk loss; maintain verified off-host backups. <sup>[3](#S3)</sup>

B10. Preserve existing behavior for unenrolled roles. For enrolled roles, NATS becomes authoritative and local claims become projections. Never silently fall back to independent local ownership during a network failure. Update receipt policy, handoff instructions, and compatibility helpers together.

## C. Ownership and infrastructure

C1. Initial pilot policy (operator confirmed 2026-11-18): disconnected agents may keep editing, continue already-running jobs and buffer reports. Guarded Git mutations and new job launches wait for NATS connectivity. They cannot acquire new ownership or expand their scope. Broader cached-grant execution is deferred. Heartbeat expiry, quota exhaustion, or an idle agent does not authorize takeover.

C2. Handoff follows a persisted sequence: **active → draining → verified quiescence → durable checkpoint → conditional transfer → successor reconciliation**. Quiescence includes tracked subprocesses, background jobs, and outstanding external-operation intents.

C3. Registry fencing does not fence arbitrary filesystem writes. Managed Git operations use the existing guards plus ownership checks; workspace reuse requires one writer and proven quiescence. If a resource cannot enforce authority and its old writer cannot be stopped or isolated, transfer remains blocked.

C4. Run the authoritative NATS broker on the existing NixOS `vps-hub` host, accessed over Tailscale. There is no Google VM or cloud fallback in the NATS implementation. Prove authenticated broker connectivity from two participating hosts, including reconnect behavior and public-interface isolation.

C5. Extend the existing host configuration; do not reinstall NixOS, invoke `nixos-anywhere`, repartition disks, or replace the host's current networking. Preserve its other services and Tailscale settings. Survey capacity, disk availability, current ownership and running jobs before proposing the deployment. <sup>[4](#S4)</sup>

C6. Build the NixOS system and required NATS artifacts in Linux CI, not on the Mac or `vps-hub`. Promote the reviewed, published head through the existing `deploy-vps-hub` branch and verify the running configuration revision after activation. Preserve recovery access before changing the firewall or service configuration. <sup>[5](#S5)</sup>

C7. Put a reusable `nixos/modules/ade-nats.nix` module in the existing public site NixOS repository and import it from the current `vps-hub` configuration. Add explicit CI coverage for the hub output and affected shared modules. Expose NATS only over the tailnet; keep its monitoring endpoint local. Do not add subnet routing or exit-node functionality for the broker.

C8. Persist broker data in a service-owned `/var/lib/nats` directory on the hub's existing persistent filesystem. Set explicit capacity limits and service startup checks; if the surveyed host uses a dedicated data mount, require that mount before NATS starts. Back up the stream, artifacts, and generation manifest to another existing host. Store credentials through the existing managed-secret mechanism, outside Nix expressions, the Nix store, and logs.

C9. Deploy only reviewed, published branch heads using the existing promotion pattern. Verify that adding NATS does not disrupt the hub's existing services. OS rollback must not restore an older coordination database.

C10. Google billing verification, project creation, VM provisioning, image builds and trial-expiry migration are removed from the NATS critical path. No Google Cloud or Temporal paid subscription, upgrade or post-trial charge is authorized.

C11. Before enrolling a real workstream, test off-host backup and restore in an isolated broker instance. Keep the restored instance outside the production authority namespace. Any later host move requires quiescence, generation reconciliation and one deliberate client cutover; never run independently writable brokers for the same roles.

## D. Parallel implementation and dynamic staffing

D1. Before every wave and each launch, refresh provider availability and pool-specific quota headroom, account for in-flight consumption, run load admission, and obtain a fresh router plan. Use its dispatch unchanged. Record the selected model, effort, workspace, ownership, and acceptance criteria.

D2. The table specifies capabilities rather than a frozen roster. Runtime recommendations come from the current policy: eligible coding profiles for implementation, high-quality judgment profiles for protocol decisions, and an independent family for review where available. Astra remains an option for genuinely difficult protocol adjudication.

D2a. Use actual router kinds `research`, `code`, `judgment` and, only for a justified hard protocol decision, `frontier`. Coding candidates normally include eligible Sonnet-class or everyday Codex profiles; judgment normally uses an eligible Opus-class profile, with Astra as a frontier candidate. These are recommendations, not entitlements or pinned model IDs. At each launch, obtain an ordered eligible shortlist from the current router and select using live pool-specific headroom, quality gates, native-tool suitability and concurrency limits. Do not fan out to every vendor.

| Step | Dependencies | Exclusive responsibility | Task kind | Parallel work |
|---|---|---|---|---|
| D3. Baseline and contract | Approved plan | Map routing/ack paths; define schemas and receipt policy | Research + judgment | Infrastructure preparation |
| D4. Protocol proof | D3 contract | CAS, atomic batch, stale-owner and duplicate-ID conformance tests | `code`; concurrency expertise | Measurement and resource audit |
| D5. Resource/quiescence audit | D3 | Enumerate guarded write paths and transfer blockers | Judgment | D4 and infrastructure |
| D6. Coordination library | D4 passes | Authoritative reads, conditional writes, records, typed errors | Code | D7 and D8 |
| D7. Delivery persistence | D3 contract | Outbox, artifacts, inbox, receipts, reconciliation | Code | D6 and D8 |
| D8. Resource adapters | D5 | Guard integration, tracked jobs, quiescence evidence | `code`; systems expertise | D6 and D7 |
| D9. NixOS infrastructure | Configuration contract | Hub NATS module, persistent state, tailnet access, backup and promotion configuration | `code`; NixOS expertise | Application work; separate CI-workflow owner |
| D10. ADE integration | D6–D8 | Claims, handoff, send guard, completion helper, plugin adapters | `code`; integration expertise | Documentation finalization |
| D11. Independent verification | Integrated heads | Fault harness, exact-head review, CI and bot triage | Code + independent judgment | Per-PR reviews as slices finish |
| D12. Pilot and activation | Checks and deployment approval | One rollout owner: observation, shadow, two-host proof, enrollment | Operations | Optional Temporal experiment |

D13. Give every worker disjoint ownership and a claimed workspace, including reviewers that run tests. Shared integration files have one writer. Briefs include checkpoints, stable attempt IDs, allowed effects, verification commands, reports, and completion evidence.

D14. Commit and push coherent units through the prescribed helper. Run heavy tests and builds in CI. Obtain the required adversary verdict before PR creation; satisfy exact-head CI, approval-marker policy, and review-bot triage before merge.

D15. Recover autonomously from quota and agent failures. Classify quota exhaustion, rate limits, authentication failures, permission requests, and genuine stalls separately. Use bounded retries, then dynamically select an eligible equivalent-quality route. Preserve unfinished output and reconcile effects before replacement. Establish quiescence before transferring write ownership.

D15a. Default to at most three retries for a transient transport failure, honoring server retry timing and retaining the same operation IDs. Then reroute an affected agent to an eligible peer or park its slice until reset. Register a checkpoint deadline for each slice; elapsed quiet time alone is not proof of a stall. Inspect tracked jobs and request a checkpoint before declaring the agent stuck. After two unsuccessful replacement attempts for the same diagnosed event, the lead investigates the underlying failure autonomously while other ready work continues. Escalate to the human only for a genuine permission, spending or unresolved product decision; never bypass it by changing the tool or credentials.

D16. Never cancel healthy paid work, launch overlapping replacement writers, bypass a denied permission, or switch to metered credits to evade quota limits. If no eligible route is available, park that slice and advance another ready task.

D17. While waiting for CI or a human decision, continue disjoint implementation, review, documentation, or authorized ADE backlog work. Keep secondary work separate from the primary goal's completion criteria. Use existing scripts/events for waiting and notification rather than recurring model polling.

## E. Acceptance, rollout, and optional Temporal test

E1. Required fault tests cover concurrent ownership transfers; publication and receipt races during handoff; late old-consumer acknowledgements; producer crashes around publication; duplicates beyond the broker window; partial artifacts; server/plugin restarts; partitions; disk exhaustion; lingering writers; uncertain external effects; and stale authority after restore.

E2. Recovery must preserve an independently retained coordination-generation record and host high-water evidence. Restoring a backup cannot silently reset authority. If old writers cannot be fenced, restored ownership mutations remain disabled.

E3. Roll out through **observation → isolated shadow namespace → disposable two-host pilot → one approved workstream → staged enrollment**. Preserve existing delivery proofs until the enrolled-role machine-receipt policy is activated.

E4. Require zero lost accepted reports, duplicate committed dispositions, unauthorized transfers, or accepted stale-owner mutations in the exercised tests. Measure coordination model calls/tokens, lookup and recovery latency, backlog, and artifact availability against the baseline; do not claim savings in advance.

E5. Rollback preserves the stream, artifacts, and outboxes. Quiesce writers, reconcile pending work, and explicitly designate one authority per role. Disabling the plugin must not create independently writable legacy ownership.

E6. Optional Temporal experiment: at most half an engineering day, outside the NATS critical path. Use a fake agent adapter to wait for simulated CI and approval, restart its worker, retry a fake operation, and verify one recorded effect. No paid models, real merges, or production dependencies. Run in isolated Linux CI by default; use a local test environment only if explicitly allowed by the normal test policy. Do not provision Google resources for this experiment. If it cannot fit this bound, record the finding and defer it. <sup>[6](#S7)</sup>

E7. Do not enroll in Temporal Cloud's standard trial: its credits can expire into billable usage. Its managed trial becomes eligible only if a separately verified arrangement guarantees no charges and is separately approved. The small OSS experiment provides the useful learning without that billing exposure. <sup>[7](#S8)</sup>

E8. Complete the future implementation goal only after implementation, pilot, activation, documentation, and recovery evidence are verified. The active operator goal is to achieve all goals in this plan, including implementation and the approved rollout, not merely to deliver this document. Genuine approval or infrastructure blockers remain explicit; they are not treated as completed work.

## F. Sources

F1. <a id="S1"></a>NATS publish headers and conditional writes: [upstream documentation](https://github.com/nats-io/nats.docs/blob/master/nats-concepts/jetstream/headers.md).

F2. <a id="S2"></a>JetStream atomic batch publishing: [ADR-50](https://github.com/nats-io/nats-architecture-and-design/blob/main/adr/ADR-50.md).

F3. <a id="S3"></a>JetStream consistency and persistence: [upstream documentation](https://github.com/nats-io/nats.docs/blob/master/nats-concepts/jetstream/README.md).

F4. <a id="S4"></a>Existing NixOS hub and Tailscale configuration: [site host configuration](https://github.com/djbclark/site-djbclark/blob/master/nixos/vps-hub/configuration.nix).

F5. <a id="S5"></a>NixOS source, CI and published-head deployment conventions: [site deployment documentation](https://github.com/djbclark/site-djbclark/blob/master/docs/nixos-in-git.md).

F7. <a id="S7"></a>Temporal mocked Activities and time-skipping tests: [Python testing guidance](https://docs.temporal.io/develop/python/best-practices/testing-suite).

F8. <a id="S8"></a>Temporal trial credits and billing: [pricing terms](https://temporal.io/pricing.md).
