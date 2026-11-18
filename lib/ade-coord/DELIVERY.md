# Durable delivery and JSON CLI

`node cli.js <group> <command> [--state-dir /absolute/private/directory]`
reads one JSON object on stdin and returns exactly one JSON object on stdout:
`{ok:true,result}` (exit 0), or `{ok:false,error:{code,message}}` (exit 2 for
INVALID, 1 otherwise). Error messages never echo URL, input, token or stack.
`ADE_NATS_URL` and optional `ADE_NATS_TOKEN` come from the existing
sudo-secretspec injected environment. Never put authentication in a URL; userinfo,
query, fragment and nonempty path are rejected. There is no secret lookup here.
Do not put credentials into report payloads or operation intents: those are
persisted application data. Environment credentials are never persisted.

Default state is `~/.local/state/ade-coord`, shared per host, outside repositories.
Directory mode is 0700, database and SQLite sidecars 0600. State paths must be real
files/directories, not symlinks at the leaf. SQLite uses WAL, synchronous FULL,
10 second busy timeout and short BEGIN IMMEDIATE transactions. Transactions never
span network awaits. SQLITE_BUSY is a safe UNKNOWN command failure; retry the
identical intent, never assign another ID. Use a local filesystem with SQLite
locking and durability support, not a network mount. These are process-crash
and reopen tests, not power-loss/OS crash/storage-controller durability proof.

## Commands and request fields

Every network command requires `generation`, supplied from independently
reconciled authority evidence. Commands are exactly these two-token pairs:

| Command | Additional input |
|---|---|
| role get | role_id |
| role create | record (core schema) |
| role transition | snapshot, priorOwner, priorEpoch, nextOwner, quiescence |
| report publish | report, artifacts?: [{base64,media_type}] |
| report status | role_id, message_id |
| inbox list | snapshot, authority |
| inbox read | snapshot, authority, message_id |
| inbox intake | snapshot, authority, message_id |
| inbox dispose | snapshot, authority, message_id, disposition |
| outbox status | none (offline) |
| outbox reconcile | generation |
| operation intent | id, intent (offline) |
| operation inspect | id (offline) |
| operation reconcile | id, state: SUCCEEDED or NOT_APPLIED, result, evidence (offline) |
| artifact read | artifact (reference); returns base64 |
| doctor check | generation |

Current authority is `{owner:{host,server,agent},ownership_epoch,generation,
revision}`. It must match the supplied snapshot and a fresh leader role read.
Receipt commit still uses the core atomic fence to cover transfer after that
read. Role tokens are cooperative authority evidence, not cryptographic
credentials. Broker ACLs/authentication remain deployment responsibilities.
Report publication targets a stable recipient role, independent of its epoch;
producer assignment validation remains the integration caller's responsibility.

CLI report publish commits canonical intent and artifact bytes before opening
any network connection. API `Delivery.publish()` commits before making its own
network calls (its caller already owns the connection). Explicit message IDs are
required. Duplicate same ID/different content is IMMUTABLE. A disconnected host
can record/recover intent; no local fallback confers role ownership.

Artifacts are stored as durable SQLite BLOBs in the same intent transaction.
References `{sha256,size,media_type,reference:{kind:'nats-object',
bucket:'ADE_ARTIFACTS_V1',name:<sha256>}}` are deterministic before upload.
Provision the Object Store bucket explicitly in deployment with file storage,
no expiry, suitable capacity and broker synchronous persistence. Runtime never
creates a missing bucket implicitly. Object Store content is uploaded and then
retrieved and SHA256/size verified before report publication. Local paths are
never artifact references. Independent clients can use `Artifacts.readArtifact`
or the CLI to fetch and verify bytes. Full byte buffering is intentional for
this initial bounded CLI (16 MiB JSON input); streaming large blobs is future work.

A failed/partial upload leaves local-buffered state. Reconciliation first checks
broker report identity/digest; a committed matching report is adopted without
republishing. Otherwise it retries original persisted bytes/references and report.
Attempts/error codes are retained; no automatic timer or arbitrary effect retry
runs. Outbox rows remain after broker-accepted for evidence. Consumer ack state
never deletes authoritative reports or determines inbox completion.

`ADE-inbox-recorded` follows durable local intake of verified report/artifact
references. Artifacts remain retrievable in the broker; intake does not claim a
separate local artifact cache. A successor re-intakes into its independent DB,
preserves the original durable receipt owner/provenance, and commits processed
under its own current authority. Repeated dispositions are immutable; conflicting
content is refused. Durable machine intake implies no model comprehension.

Operations are a local intent/result journal. Recording intent immediately means
UNKNOWN: there is no automatic external invocation or retry. Only endpoint
reconciliation evidence resolves to SUCCEEDED or NOT_APPLIED. NOT_APPLIED is
information for a future explicit adapter decision, not permission to auto-retry.
A separate cross-host operation authority adapter remains future integration work.

## Additive API

Exports `canonicalJSON`, `LocalState`, `Delivery`, `Artifacts`,
`artifactReference`, alongside all prior exports/errors.
`LocalState(stateDir?)`: enqueue(report,artifacts?), reportStatus(role,id),
outbox(), readInbox(role,id), operationIntent(id,intent), operationInspect(id),
operationReconcile(id,{state,result,evidence}), close().
`Delivery(core,state,artifacts)`: publish(report,{artifacts}?), flush(outboxRow),
reconcile(), authority(snapshot,token), intake(snapshot,{message_id,authority}),
dispose(snapshot,{message_id,authority,disposition}), readInbox(role,id).
`Artifacts(nc)`: upload(bytes,media_type), readArtifact(reference).
No external effects, plugin/controller or legacy .done projections are included.

Maintained APIs checked: Node `node:sqlite` DatabaseSync exec/prepare/get/run,
NATS `@nats-io/obj` 3.5.0 Objm/open/putBlob/getBlob/put. CI resolves current
packages and Node LTS, records exact dependency resolution and SQLite version.
