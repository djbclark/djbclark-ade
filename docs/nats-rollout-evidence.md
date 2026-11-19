# NATS rollout evidence — 2026-11-18

The implementation and approved bounded rollout are **complete**. See the
[final acceptance](nats-jetstream-final-acceptance.md),
[implementation plan](nats-jetstream-implementation-plan.md), and
[execution ledger](nats-jetstream-execution.md) for the published implementation,
approved activation, native physical two-host succession, first real workstream,
and recovery evidence.

The implementation/deployment snapshot below predates final acceptance and is
retained as historical evidence. Its earlier pending decisions are resolved as
recorded below. Existing workstreams remain unenrolled; broader enrollment still
requires separate authorization.

## Implementation and deployment — historical snapshot

| Artifact | Verified state |
|---|---|
| [ADE PR795](https://github.com/djbclark/djbclark-ade/pull/795) | Functional source `42810d69be8005909327497fe61e3beb67528a28` independently reviewed; documentation changes follow it. Merge requires current-head review, checks and normal bot/approval gates. |
| [Full functional-source CI](https://github.com/djbclark/djbclark-ade/actions/runs/44375262277) | 12,609 passed, 56 skipped, 1,290 subtests. Earlier executable-mode failure was repaired; the failed run is retained. |
| [Documentation-head CI](https://github.com/djbclark/djbclark-ade/actions/runs/44380208815) | Head `25ceb01af19647e3309d02c6786770d628904398` passed, including pytest-linux. Later heads require their own applicable checks. |
| Hub | Published site revision `7c8c82812130298196d6674f16a405e03d8c012b` deployed; NATS 2.14.4 authenticated tailnet access, loopback monitoring, synchronous file storage and reject-new capacity verified. Existing services remained healthy. |
| Mac runtime/plugin | Verified source `42810d69be8005909327497fe61e3beb67528a28` installed; actual native plugin compilation, loading and reload exercised on daemon 0.16.0-beta.2. |
| [Site PR279](https://github.com/djbclark/site-djbclark/pull/279) | Merged as `fa96b2d7cc00eed422ce1a4c83fca7ff98805bfb`. Exact published primary closure built in CI, imported and dry-activated only; **not activated**. |

CI exercises conditional transactions, simultaneous handoff/publication/receipts,
late consumer acknowledgements, immutable IDs beyond the duplicate window,
process death/reopen, partial/missing/corrupt artifacts, real TCP reply loss and
reconnect, reject-new capacity, bounded real ENOSPC and stale restored authority.
Native API fixtures in CI do not establish real provider retirement. The live
proofs below supply that evidence for the exercised Mac provider only.

## Executed acceptance matrix

| Requirement | Executed proof | Limit |
|---|---|---|
| Physical two-host delivery | Mac and primary independently read reports/artifacts, preserve prior intake provenance, process with successor authority and reject predecessor receipts. | This first cross-host role used protocol-only identities, not native agents. |
| Native processing and wake | Two reports processed at receipt revisions 24/26 under epoch 1; successor report processed at 39 under epoch 2. Artifact bytes/hashes verified; two coalesced wakes accepted. | Explicit disposition establishes recorded processing, not model comprehension. Guidance turns are counted. |
| Native resource-free handoff | Positive native archive completion and closed readback, checkpoint verification and conditional transfer to role revision 30/epoch 2. Retired native open/history and stale disposition refused. | Mac native provider; no live native cross-host transfer yet. |
| Bound workspace and offline policy | Admitted job and ordinary edits continued offline; guarded Git add refused with unchanged index; new job refused without output. Online guarded add succeeded. | Managed paths only; arbitrary filesystem writes are not hard fenced. |
| Lingering writer and successor | A real tracked job blocked transfer. After its exit, the same attempt retired the native predecessor and transferred at revision 44/epoch 2. Actual successor verified checkpoint, both job outcomes and claim projection, then performed a guarded add; stale predecessor assignment/open refused. | Bound workspace stayed on the same host. Nonempty cross-host resource migration is unsupported. |
| Offline durable report | Independently observed local-buffered intent; fresh processes reconciled the original report at revision 45 with unchanged digest and no republish. The 114-byte artifact verified, intake recorded at 47, explicit processing at 49. | Historical offline failure retained; successful reconciliation does not erase it. |
| Broker restart | Actual production restart retained the earlier two-host role, reports, receipts and artifact bytes. | Process restart, not power loss or clustered failover. |
| Off-host recovery | Separately authenticated isolated restore retained native epoch 2, processed receipts 24/26/39 and all three artifacts. Independent incompatible generation refused read/write; owned broker exited and its port closed. | Snapshot sequence 39; newest backup sequence 49/object sequence 18 is retained separately. No production disaster cutover. |
| Client rollback | Quiesced designated actors, disabled only their plugin, temporarily selected the previous runtime, then restored current runtime/plugin. Three authorities, six reports/artifacts, receipts, local logical SQLite fingerprints and claim bytes unchanged. Legacy release/reclaim and stale assignment refused while disabled and on old runtime. | Client rollback only; no OS or production database rollback. |

Rollback's final restore initially encountered an already-running enable error.
It was reconciled without rerunning the fault: inspect plugin state, reload the
running plugin, verify data and restore only the original controller flags.
The original failure and separate successful reconciliation are both retained.
Both current disposable native owners remain deliberately archived/closed;
their single-owner grants and claim projection remain durable.

## Measurements and interpretation

The original three-report native pilot used seven model turns and 34 provider
requests, including READY/setup and request corrections: 2,212,028 input tokens
(2,061,440 cached subset) and 12,069 output tokens. These are cumulative transcript
deltas, not sums of the plugin's last-request usage. Later bound/offline pilot
work is additional and is not included in that three-report count.

Nine historical acknowledgment-only turns had median 4.147 seconds, median
174,812 input tokens and median 316 uncached input tokens. Models, effort,
context and workloads differ; these observations do **not** establish savings.
Fresh local legacy lookup samples were 44.896–48.028 ms; fresh managed NATS CLI
lookups were 2320.987–2419.976 ms including credential/startup/network overhead.
The isolated native snapshot measured startup 110.939 ms, restore 2774.644 ms
and application verification 578.485 ms. This is not a disaster-recovery RTO.
The exercised native inbox had no pending report after explicit dispositions.
No lost accepted report, duplicate committed disposition, unauthorized transfer
or accepted stale-owner mutation was observed in these exercised proofs.

## Completed rollout gates

1. ADE review, required checks and normal merge gates passed; the implementation
   was published through [PR795](https://github.com/djbclark/djbclark-ade/pull/795).
2. The operator approved primary activation and its listed restarts. The approved
   release, subsequent formatting-only release and managed client credential
   setup completed; source/revision and service checks passed.
3. Dedicated native physical cross-host handoff passed with independent primary
   state, preserved intake provenance, explicit processing and stale-owner refusal.
4. The operator separately approved one fresh resource-free read-only inventory
   workstream. Machine intake, one reconciled coalesced wake, explicit completion
   and independent output/artifact verification passed.

The [final acceptance](nats-jetstream-final-acceptance.md) records the exact
published revisions, checks, limits and evidence for these results. Broader
workstream enrollment, nonempty remote resource migration and implementation of
the central-questions feature remain separate work; this closeout does not
authorize them.

The bounded optional Temporal OSS fake-effect experiment passed in Linux CI.
No Google resources, Temporal Cloud subscription or paid trial conversion was
used. Single-node disk loss, arbitrary untracked effects and clustered failover
remain explicit limits, not completed proofs.

Private evidence is retained outside the repository under the owning session's
`nats779` report directory: native-bound controller/successor/stale-open evidence,
offline publication/disposition, snapshot restore, token/lookup measurements and
original/reconciled rollback results. Runtime identities, database state and
credentials are not published here.
