# ADE coordination protocol core

ESM package, Node 22 or newer. Resolve current maintained dependencies with
`npm install`; CI records the exact resolution as an artifact. Linux CI starts
and terminates a disposable current released NATS server; do not run on the Mac.

## Contract

`Coordination.connect(nc, {generation})` takes an existing authenticated nats.js
connection. Deployment creates `ADE_COORD_V1` using `streamConfig()` and must
verify server `jetstream.sync_interval: always`, capacity, credentials and
independently retained generation evidence before enabling writes. `doctor()`
checks stream safety, but cannot verify filesystem durability or restore safety.
Never derive generation solely from the restored broker. The current generation
must come from reconciled independent high-water evidence. No automatic takeover.

Role snapshot: `{record: {role_id, owner: {host,server,agent}, ownership_epoch,
generation, state, bindings, quiescence?}, revision}`. `revision` is the global
stream sequence of the last role-subject record, not the ownership epoch.
`createRole(record)` requires epoch 1. `getRole(role_id)` uses leader API reads.
`transferRole(snapshot, {priorOwner, priorEpoch, nextOwner, quiescence})` checks
owner/epoch and CAS revision. Quiescence is explicit evidence bound to the prior
revision/epoch/owner: `{prior_revision, prior_epoch, prior_owner,
processes_stopped:true, jobs_stopped:true, operations_reconciled:true,
checkpoint_digest:<64 hex>}`. The adapter must verify that evidence before
calling; booleans cannot stop processes or fence external resources. No lease,
heartbeat, wall clock or expiry confers authority.

`publishReport({role_id,message_id,payload,producer_assignment?,artifacts?})`
requires the caller to persist the full intent and stable ID first and validate
producer assignment. Report identity contains no recipient owner or epoch.
Retry the identical intent with its original ID. Stable subject sequence-zero
checks and canonical SHA256 digests enforce immutability beyond broker dedup.
`reportStatus(role_id,message_id)` resolves an uncertain publish by leader read.
Returned snapshots contain `{record:{report,digest},revision}`.

Receipt stages are `local-buffered` (caller persisted intent), `broker-accepted`
(confirmed report publish or reconciliation), `ADE-inbox-recorded`, `processed`.
Only the last two are durable receipt subjects, accepted by
`commitReceipt(roleSnapshot,{message_id,stage,disposition})`.
`receiptStatus(role_id,message_id,stage)` returns the durable record. Stage
names are evidence labels, never a claim of model comprehension. A processed
receipt is an explicit disposition, not proof of arbitrary external effects.

A receipt uses the maintained client `startBatch()` / `commit()` API: entry one
is a fresh guard subject checking role revision via the cross-subject expected
sequence header; entry two is the receipt checking its own sequence zero.
The role subject is never changed within the batch. Crucially, conformance tests
require the guard condition to remain valid at commit after an intervening
transfer. If a server accepts the stale receipt, this recipe is incompatible:
do not activate dependent integrations or replace it with unconditional writes.
CI must prove this invariant; writing these tests alone is not protocol proof.

`listInbox(role_id)` scans retained reports and excludes durable processed
dispositions. No consumer acknowledgement deletes reports. This initial scanner
is intentionally simple and unpaged; capacity/performance improvements belong
to the delivery slice. Reads can race new reports; repeat reconciliation.

Exports: `Coordination`, `CoordError`, `safeToken`, `subject`, `digest`,
`streamConfig`. `CoordError.code`: INVALID, CONFLICT, STALE, GENERATION,
UNKNOWN, IMMUTABLE, UNSUPPORTED. Unknown outcomes require reconciliation with
stable IDs; errors never authorize unconditional retry or local authority.
There is no implicit local fallback, blob implementation, persisted outbox,
operation ledger, watcher, CLI or plugin in this unit. Artifact availability,
producer assignment validation and external-effect reconciliation remain adapter
responsibilities; they have not been tested here.

## Evidence and sources

Linux conformance exercises CAS, a deterministic staged-guard/transfer race,
concurrent receipt races, dedup-window expiry, recipient transfer, actual broker
commit followed by injected ack loss, and duplicate batch atomicity. The ack-loss
test injects failure at the client return boundary, not a real network partition.

Current API checked against released @nats-io/jetstream 3.5.0, server v2.15.3,
[advanced publishing](https://docs.nats.io/learn/jetstream/advanced-publishing),
and [ADR-50](https://github.com/nats-io/nats-architecture-and-design/blob/main/adr/ADR-50.md).
CI deliberately resolves latest releases rather than freezing these observations.
