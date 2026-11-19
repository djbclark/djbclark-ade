# Fork controller pilot v1

`bin/ade-fork-controller status|plan|tick` reads the real account's fixed
`.local/state/djbclark-ade/forks/controller.json`. HOME, CLI flags and environment
cannot substitute a grant path. No file is installed by this source change.
`status` reads the existing Journal, retained verified payload and actual stable
qualified native/cohort identity without writing state or obtaining transaction
adapters. `plan` reports the protected candidate; `tick` performs GitHub discovery
and private evidence retention without runtime mutations. Missing, unknown or
mismatched facts return HOLD. No runtime adapter is selected by JSON.

`bin/ade_fork_controller.py` owns the pilot integration. Existing release,
GitHub CI, snapshot and updater containment libraries remain unchanged. The
pilot component is ade-yolo on master, in the full paseo-runtime compatibility
group; preserving the cohort does not mean the other components are qualified.
There is one existing Journal for that group, no second deployment journal.

## Protected enrollment

Strict version1 fields are `schema_version`, `component`, `channel`, `repository`,
`repository_id`, `cohort`, `policy`, `expected`, `evaluation`, `operations`,
`previous`, `generation`, `master_commit`, `evidence`, `discovery`, `native`. Unknown fields reject.
`component` is ade-yolo; channel master; repository djbclark/djbclark-ade.
`cohort` maps every catalog ID in enrolled paseo-runtime to a nonempty protected
expected identity record. `expected.dependencies` includes the entire cohort.
`policy` preserves every enrolled group feature and its protected assertion.
The executing native port must verify those exact identity records; nonempty
records alone do not prove compatibility or executing closure.

`evaluation` is the exact Evaluation constructor schema (jobs serialized as an
array). It identifies the protected evaluator workflow/repository/run/attempt,
archive and receipt, independently of candidate metadata. `expected` is the
complete release-core bindings dictionary; `evaluator` binds its reviewed commit,
`authority` is protected-ci, and toolchain is the canonical JSON string binding
protected evaluator evidence. `evidence` is the protected snapshot qualification
mapping. Passing locally constructed fixtures is not authentication.

`operations` allows only enroll/preflight/stage/activate/verify/recover/retain.
Each present consent has exactly `allowed` (literal bool), `identity` (receipt
SHA256), and `generation` (current outer deployment generation). Missing grants
deny. Reader rechecks the complete protected record before every permission
boundary. The controller does not create its own consent or install a policy.
`previous` is the retained baseline receipt identity; `generation` is outer
Journal generation. Native CAS comes separately from native journal status.
Protected policy writers and execution need a real serialized reservation before
production activation; no local flock is presented as runtime quiescence.

## Safe archive and retention

GitHubEvaluation.verify authenticates exact metadata and retains the ZIP.
The controller independently rehashes the retained no-follow regular file.
The ZIP has exactly receipt.json, snapshot.json, evaluator-evidence.json. Duplicate
or extra names, traversal aliases, directories, symlink/special modes, encrypted
entries and unsupported compression reject before payload consumption. Counts,
compressed/uncompressed size and aggregate expansion are bounded at 96MiB;
CRC/entry length are checked without extracting any archive-selected path.
A receipt must be canonical and separately authenticated, and core validation
binds exact payload bytes. Snapshot inspect/qualify enforce the trusted recipe.

Immutable payloads and release records are retained through file fsync,
no-overwrite hardlink publication and directory fsync in private owned paths.
Existing matching files are reused; corruption refuses overwrites. Release records
map receipt to expected policy/cohort/evaluation/evidence and payload identity.
They are retained evidence, not a new mutable deployment journal. `retained`
revalidates stored receipt and payload; failed retention is never activation.
Local readers traverse descriptors with no-follow/nonblocking opens, refuse
specials/unsafe ownership/writable modes, and enforce size/stability bounds.
Administrator-controlled private filesystem semantics remain required.

## Controller ports and transactions

Trusted in-process callers may invoke Controller.acquire, adapters and
tick('enroll'|'deploy'|'recover') with actual native ports. CLI exposes fixed
apply/recover but no enrollment or dependency-injection override. NativeFacade.supported requires the finite manifest, genuine enclosing authority
and complete qualified cohort; missing support holds before transaction work.
Its bounded read-only list_observations helper is not called by shipped CLI and
does not establish support. No guessed mutating CLI fallback exists.

A native port must implement supported/observe/preflight/activate/verify/recover/
reserve with genuine qualified-host capability and serialized complete cohort
identity evidence. observe returns an independently matched retained ADE receipt
identity, never the requested target. activate/recover consume exact native CAS,
current native authorization and explicit source/snapshot/bundle identities.
Journal owns outer generation/durable intent/retry behavior. Recovery consumes
retained baseline and current recover/verify consent without downloading candidate
CI artifacts again. Lost acknowledgement remains recovery_required.

Native worker coordinates getManagedPluginStatus(pluginId), wire
plugins.managed.status.request/response and proposed CLI plugin managed-status.
The coherent v1 result separates registration, journal phase/generation/baseline/
currentReceipt, and loaded receipt. coherent_native_status is an observation
consumer; uncertain/missing/incomplete data HOLD. Native journal generation can
advance while loaded.activationGeneration stays old. No default generation zero,
no deriving current state from a process version. Final native transport schema,
qualified producer and reservation are still integration prerequisites. This
source does not claim an atomic status API or install the native producer.

## Scheduling and master discovery

Controller.select_latest (shipped tick) discovers reviewed evaluator workflow runs
newer than protected discovery.baseline_run_id, with complete bounded pagination.
The initial baseline run is enrollment history, not a new manual source selection
for each master. discovery has exactly enabled (bool), artifact_prefix
(ade-yolo-qualified), baseline_run_id (positive integer). Enabling this protected
contract consents only to discovery/retention; selected outputs grant no runtime
operation permission. Existing artifact-scoped activation consent remains separate.

The required reviewed workflow-output contract is: fixed evaluator repository ID,
workflow path/ID, evaluator head commit, actor, event and required jobs as enrolled;
upload exactly one `ade-yolo-qualified-SOURCE_SHA-RUN_ID-ATTEMPT` artifact only after
all protected assertions pass. Its bounded ZIP contains the same exact three
members. Protected workflow, not candidate build code, chooses the artifact name,
source SHA, receipt and feature results. GitHub artifact metadata must supply its
SHA256 digest. The controller first authenticates transport against fixed reviewed
evaluator constraints, reads that authenticated output's receipt digest, then
reauthenticates exact receipt/attempt/archive through GitHubEvaluation again. It
never constructs a verification seal or accepts an output allowed boolean.
This workflow producer is a required external integration contract, not installed
or executed by the controller source. Its absence yields no new eligible candidate.

Expected receipt fields come from the protected recipe template: source fork and
upstream commit and payload SHA256 are independently recomputed; master and native
tree evidence are independently bound to payload. Exact compiled server digest is
read only from authenticated protected evaluator output. Compiler/tool identities,
helper binding/cold assertions, dependencies, recipe revision, policy/features and
authority stay protected and must match. Changing protected recipe/toolchain needs
reviewed enrollment changes, rather than a new expected source record each master.

Selection checks actual GitHub compare commit and merge-base identities. Source
must descend from enrolled/retained baseline and be an ancestor of latest master;
rewinds, incomparable outputs, duplicate attempts/artifacts and incomplete history
hold. Runs failing or missing qualification output do not erase a retained baseline.
Candidates are ordered by commit ancestry, never timestamps or version strings.
Result exposes latest_discovered separately from selected_qualified. Latest master
may fail while an older newly qualified ancestor or retained verified baseline wins.
Master and the entire protected policy are reread before retaining a selection and
again before returning it; changed state holds rather than publishing stale success.
`apply` rechecks current master and protected policy under the actual native
reservation at its commit boundary. Earlier selection/status responses grant no
permission. Missing qualified execution or current authority still HOLDs.

Discovery is bounded to five history pages, 80 metadata calls and four candidate
transport/receipt verification pairs per tick; exceeded bounds hold, never truncate
to a false newest claim. Shared GitHub quota is checked first (remaining <500 holds).
No scheduled job or evaluator runs are launched by discovery. No locally constructed
fixture receipt proves actual qualified producer/runtime execution.

Do not route master-snapshot through Sync's merge strategy: ADE upstream/fork
are identical, and that API rejects this strategy. The existing ade-sched source
mechanism can run separate discovery and authorized promotion jobs. This discovery
source example is deliberately not installed and does not promote anything:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>com.djbclark.ade-fork-controller-check</string>
  <key>ProgramArguments</key><array>
    <string>__ADE__/bin/ade-fork-controller</string><string>tick</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
</dict></plist>
```

Automatic standing promotion is a separate authorized `apply` job, not discovery
`tick`. Under an explicitly installed current schema2 standing qualified-latest
rule, each apply selects/authenticates the latest eligible retained master ancestor,
reads actual Journal CAS and executes the bounded native transaction only when all
producer/cohort/namespace/authority checks pass. A source-only example is:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>com.djbclark.ade-fork-controller-promote</string>
  <key>ProgramArguments</key><array>
    <string>__ADE__/bin/ade-fork-controller</string><string>apply</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
</dict></plist>
```

This example creates no consent and is not installed. Required current retain,
preflight, stage, activate and verify grants must match qualified-latest; matching
denial wins. A rollback promotion HOLD, uncertain reservation or revoked rule
prevents automatic promotion. Neither schedule performs enrollment, automatic
resume, bearer recovery or an evaluator run. Installing schedules, operational
enrollment or native policy requires separately authorized deployment. No schedule,
config or live plugin call was installed/executed by this source change.

## Validation limits

CI creates real temporary Git snapshots and ZIP/filesystem fixtures, plus clearly
fake native/evaluator ports for receipt/Journal integration, retention corruption,
consent refusal, stale jobs, lost acknowledgement and recovery. No local tests or
builds were run. Fake ports are not a JSON-to-capability path and cannot qualify
production. Genuine executing SDK/client/protocol/zod/Node/compiler/supervisor/
daemon proof, native phase/status/lease integration and separately authorized
baseline adoption/cutover remain HOLD. Python/Git helper closure for claim and
window-name remains separate; no macOS/Electron qualification is claimed.


## Reattestation and current qualified-latest consent

Stable release records exclude Evaluation run provenance. Each successful
reauthentication is retained independently under
attestations/RECEIPT_SHA/ATTESTATION_SHA.json, binding exact evaluator run/attempt/
archive metadata. Repeated qualification of the same immutable receipt neither
overwrites nor collides with stable release bytes. Old source-only records have
no deployed migration claim; no live store is modified by this source work.
Nested quota/run/artifact/master/ancestry inventory types reject through stable
ContractError before dereferencing; malformed metadata is HOLD, not success.

Protected operations preflight/stage/activate/verify/retain may explicitly name
identity `qualified-latest` instead of a receipt SHA. This is a CURRENT operator
policy grant under the exact enrolled repository/channel/evaluator recipe/features/
dependency/cohort constraints, not a candidate flag. Enroll and recover still
require explicit baseline identity. Selection does not modify enrollment.
Derivation requires a fresh independently selected retained receipt, unchanged
full enrollment digest and unchanged latest master. Existing Journal transaction
then consumes that selected record's receipt/expected bindings/payload, rather
than reacquiring the old fixed candidate. The selected exact receipt is
reauthenticated against a separately retained attestation from the currently
protected evaluator. Authority callbacks recheck current consent and master;
missing native execution transport/lease still holds before any production work.

concrete_grant derives artifact-specific native authorization from current
consent, coherent native CAS (not loaded generation), actual retained sealed tree,
compiled bundle and a receipt-bound protected native_passive_profile in policy.
That profile must be native-passive-contract-1 with independently qualified
execution/runtime/helper digests; absence holds, and no profile is synthesized.
The result carries no token and grants no support by itself. It is not a newly
invented held-operation wire ABI: final native endpoint must validate and consume
it under its genuine private owner lease/current policy and exact CAS.
The committed private held-operation transport is bound below to retained bytes,
actual native identity and current authorization. NativeFacade remains unavailable
when those genuine facts are missing. There is no automatic END/reopen path on
failed or uncertain operations; feature availability alone grants no support.


## Bound native held-operation CLI transport

The native owner published paseo-held-operation-api-v1.md as proposed/unqualified.
The facade implements its exact commands: retained Node + retained CLI,
plugin managed-status; daemon maintenance begin/end/plugin-operation; bare JSON
one-document --json output. Nonzero exit ignores stdout. Reads enforce a 30s
streaming deadline and 1MiB cap, kill/reap only the exact child, and never echo raw
output. Private owner tokens are exactly43base64url bytes in memory and anonymous
stdin pipe FD0 with a trailing newline, never argv/env/file paths/logs/journals.
The bridge environment excludes caller loader/runtime overrides. Expected server
ID and enclosing incarnation accompany native mutation requests. Native validates
the bearer/CAS/current authority/private scope; controller metadata grants none.

Protected enrollment native is null (unsupported) or an exact transport mapping:
node and cli each contain path+sha256; serverId, daemonIncarnation,
distributionSha256 bind the reviewed retained transport expectation. Source
checks exact read-only regular bridge bytes/digests before use and pins the whole
mapping through a transaction, refusing changed identity before writing any token.
These on-disk checks DO NOT prove qualified executing namespace/incarnation.
Native qualified status/cohort metadata follows the coordinated strict v1
consumer below; supported/observe refuse missing or mismatched genuine
owner-producer coupling. No speculative feature/status keys or brand constructors are added.
Thus CLI apply/recover refuse unavailable support, even though the concrete transport methods
are now real source, and none of these commands was executed on a live daemon.

The private reserve context deliberately never sends END in finally. Journal may
return recovery_required without an exception after a lost ACK or late validation
failure. Only an explicit verified committed result and still-current verify
consent can call finish(); uncertainty retains owner token/hold and requires
explicit reconciliation. A failed, unknown or unverified operation never invokes
END/rollback/reconnect cleanup. Real native status and fresh successor barrier
remain mandatory release predicates in the native endpoint.


Selected transactions carry the exact newly authenticated attestation expectation
from selection, then reauthenticate that exact run/attempt at transaction entry.
Obsolete or expired prior attempts cannot obstruct a freshly valid same-receipt
rerun merely because their digest filenames sort first. Retained-baseline fallback
orders provenance by run/attempt rather than hash. All local attestation files
are still validated before use, including obsolete files; corruption remains a
hard refusal. A current attempt or current-policy authentication failure propagates
without a catch-and-ignore fallback to older evidence.


## Fixed explicit transaction commands

`ade-fork-controller apply` invokes the existing Journal deployment path;
`ade-fork-controller recover` invokes retained-baseline recovery. Both read only
the fixed real-account protected enrollment and use the real NativeFacade.
There are no port/path/grant override flags. They emit one canonical structured
result; HOLD/recovery_required returns nonzero, runtime_verified returns zero.
Read-only status, protected-candidate plan and discovery tick have separate roles.
The standing apply schedule source above promotes automatically only under current
consent and genuine native support; discovery alone does not complete promotion.
The commands do not bypass unavailable execution/cohort qualification.


## Finite Linux cohort facade

The real facade consumes the coordinated strict ManagedPluginCohortStatus v1 via
`plugin cohort-status --json` (RPC plugins.managed.cohort.status, native feature
managedPluginCohortStatus). Only a coherent complete union of actual config,
builtin, runtime and enrollment IDs is usable. Uncertain/missing endpoints refuse.
Each loaded entry must have an actual qualified execution descriptor and a native
journal currentReceipt equal to its loaded receipt. Its execution incarnation must
equal loaded.processStartToken by construction of the private owned-child path;
legacy random tokens have no execution metadata and refuse. The journal CAS and
loaded activation generation remain separate.

Protected native adds distributionRoot, distributionBuildId and closure with the
runtime/helper/qualification SHA256 triple. Enclosing serverId/incarnation/build
and triple must match exactly. Daemon cohort member paseo is represented by
`{role:"daemon",enabled:true,loaded:true,distributionBuildId,closure}` and never
as an alias plugin entry. Every non-target protected plugin record is exactly
`{enabled,loaded,registration,receipt,execution}`: receipt is null or stable
sourcePath/snapshotRoot/snapshotSha256/serverBundleSha256; execution is null or
contract/distributionBuildId/closure. Fresh pid/start token are observations.
All enrolled catalog members remain required; explicit additional protected
builtin members may be declared, with dependency bindings. Extra active or
omitted members refuse rather than being silently dropped or disabled.

Target running identity is resolved against validated retained receipt records:
exact immutable source/root/tree/bundle AND exact executing profile closure triple
must match. Different recipe qualifications of the same bytes cannot be relabelled
by requested target or loaded generation; missing/ambiguous mapping refuses.
Supported status also requires actual native enclosing authority/features, but a
qualified boolean alone cannot satisfy the full cohort and bridge checks.

Before EVERY transport call, Python independently verifies the existing producer
manifest algorithm: canonical root-owned non-runtime-writable ancestry;
ROOT.manifest.json raw SHA256 equals distributionSha256 and runtimeClosureSha256;
schemaVersion2/profile enclosing-daemon-v2; exact build and fixed entries/binding
keys; complete symlink-free retained file set; exact path/size/mode/content hashes;
explicit external native library hashes and reconstructed helper inventory/hash.
Helper hashing preserves producer JSON field order, not release canonical sorting.
Node is exactly ROOT/runtime/node, CLI exactly ROOT/cli-entry.mjs, and both entry
hashes match protected enrollment. No unverified executable bootstraps this check.
The fixed verified CLI then performs its producer kernel/runtime/maps/current
qualification-enrollment checks before importing CLI code. Mac/dev/root execution
or missing/changed bridge/HOME qualification remains unsupported. No new manifest,
role brand, authority flag or journal is introduced.

Parser/identity tests use clearly synthetic wire facts; a separate CI test checks
actual disposable root-owned /var/lib inventory bytes without executing its dummy
Node. These do not qualify a production host. Root owns the real integrated
producer/native/evaluator A-to-B-to-A proof, and the proposed wire must still be
implemented/reviewed in that exact distribution before any real support can pass.


Recovery capability and target liveness are separate. A coherent qualified daemon
and unchanged complete non-target cohort can support recovery even when the named
failed target is absent or disabled. Ordinary observation and deployment still
require its actual loaded receipt. Only a currently recover+verify-authorized
baseline transaction enables absent-target inspection, which returns an explicit
native-target-absent observation identity, never a fake retained-baseline receipt.
Native journal CAS/retained baseline/grants remain mandatory. Managed recovery
inspection can carry loaded=null; uncertain/missing non-target state still refuses.
After a successful recovery response, the inspection allowance is removed before
verification: fresh actual running/enabled receipt and complete cohort mapping
must pass. A lost child after apparent recovery keeps recovery_required/hold and
never triggers END. This does not adopt an unmanaged or missing native baseline.


## Version2 protected rule schema (Journal context amendment)

schema_version2 keeps the immutable protected enrollment separate from current
transaction state. Each operations value is exactly
`{version:1,grants:[...]}` with1–32 explicit grants; duplicate canonical grants
reject. An exact grant has mode exact, literal allowed bool, SHA256 identity and
nonnegative generation. A standing grant has mode standing, literal allowed bool
and a nonempty unique finite selector list. Unknown fields/selectors/wildcards
reject. V1 dictionaries retain exact numeric-generation scope; they are never
reinterpreted as standing permission. Missing Journal context support holds V2
mutations instead of invoking an older transaction engine.

The selector table is explicit:

| Context / operation | Matching standing selector |
| --- | --- |
| deploy: retain/preflight/stage/activate/verify | qualified-latest, exact freshly authenticated selected target |
| failed-deploy reconcile: recover/verify | recorded-verified, exact context verified target |
| verified-rollback or its interrupted intent: recover/verify | recorded-baseline, exact context baseline target |
| resume / reconcile-release, including their verify | NONE; exact current identity+JournalCAS required |

Matching allowed=false vetoes all matching allows. Absent matching allow denies.
Exact resume/release verification can coexist explicitly with standing candidate
verification in the bounded list; no union/widening is inferred. The whole rule
digest must match the immutable context produced under Journal lock, and current
rule is reread at authority boundaries. Reconciliation uses recorded authority,
not a candidate GitHub query or a synthetic loaded receipt. Transaction context,
intent-before-BEGIN and final release hooks are pending the separately owned
same-Journal source amendment; these parser helpers do not manufacture that API.


Native prepare uses the new explicit reservationGeneration+ready fields from
qualified idle maintenance status. Missing fields, old generation:null, held,
pending, unready or unknown status never imply zero or permission. Next native
generation is only validated reservationGeneration+1; native plugin CAS is its
own coherent journal.generation. BEGIN BUSY is recognized only from nonzero
retained CLI with empty stdout and exact typed MAINTENANCE_KNOWN_BUSY stderr.
Generic messages, malformed/truncated stderr, later idle, timeout or another
operation cannot close an allocated attempt as BUSY. The separate Journal owner
will consume only this authoritative refusal through BeginResult; until its new
hooks are integrated, no old context-manager behavior is relabelled as success.

### Versioned standing authority and the existing Journal

Enrollment schema 1 remains exact identity plus its explicit Journal generation.
Schema 2 makes each operation a strict `{version:1,grants:[...]}` wrapper (1–32
unique canonical grants). An exact grant names `mode:exact`, literal `allowed`,
receipt `identity`, and current Journal CAS `generation`. A standing grant names
`mode:standing`, literal `allowed`, and a finite `selectors` list. Any matching
denial vetoes matching allows. No matching allow denies. The immutable digest of
the whole current protected enrollment binds every Journal context; rereads after
waits and at the native boundary reject revocation or policy replacement.

| Context / operations | Finite standing selector |
| --- | --- |
| Deploy retain/preflight/stage/activate/verify | `qualified-latest`: freshly authenticated selected release, with current master recheck |
| Failed-deploy reconciliation recover/verify | `recorded-verified`: the Journal's verified identity |
| Explicit verified rollback recover/verify | `recorded-baseline`: the Journal's retained baseline |
| Resume, release reconciliation, and their verify | None: separate exact identity + current CAS grants required |

`apply` reads the existing Journal generation and verified identity and passes
both to its lock/CAS operation. It never advances enrollment on a candidate's
behalf. Journal `prepare` binds the actual locked context and a read-only native
plan. The Journal persists that context and reservation intent before BEGIN.
Native reservation generation comes only from explicit qualified ready-idle
`reservationGeneration + 1`; plugin CAS comes only from native journal status.
Neither counter comes from the ADE Journal or loaded activation generation.
Only the exact authenticated typed native known-BUSY response closes an allocated
unstarted attempt. Other BEGIN failures keep the durable uncertainty intent.

`recover` on a healthy verified record explicitly selects its recorded baseline;
an unfinished transaction keeps its recorded recovery direction. Verified rollback
consumes the baseline and installs the same Journal's promotion HOLD. The fixed
`resume` command clears that HOLD only under separately current exact resume and
verify grants. It performs no BEGIN, END, restart or replacement. The fixed
`reconcile-release` command similarly requires separate current exact grants and
independent qualified stable-idle evidence matching the original reservation
server/incarnation/generation/transaction plus the actual verified target. It never
retries END. No token is persisted in the Journal.

The native known-failure lane additionally requires the actual reviewed
`maintenanceKnownFailedHeldV1` transport, an allowlisted normal return, the same
live in-memory bearer, and fresh matching complete-cohort/current-CAS/baseline
facts. It maps to the Journal's exact descriptive `KnownFailedHeld` type; that
type is not native authority. Successful activate/recover callbacks return `None`.
Unexpected values, arbitrary throws, timeouts, lost acknowledgements or process
loss remain sticky unknown. Same-held recovery uses the original native intent
and a fresh Journal context/plugin CAS through the explicit reuse hook, without
another BEGIN, bearer reconnect or fallback reservation. Missing API or producer
facts HOLD. Synthetic CI ports demonstrate orchestration only; actual coupled
producer/native proof is a separate acceptance gate.

### Explicit cohort V2 parser boundary

Protected `native.cohortVersion: 2` opts in to the separate committed native V2
schema (`22285d1f1`, `ManagedPluginCohortV2StatusSchema`). Absence keeps the exact
V1 path. No malformed/uncertain/unsupported V2 response falls back to V1.

The pure `cohort_v2_observation` parser accepts tagged `directory` entries with
`plugin-child` receipt/execution wrappers and separately tagged
`builtin-in-process` entries. Directory validation reuses the unchanged V1
receipt/CAS checks after validating the wrappers. It never constructs a child
receipt, PID, activation ordinal or journal for an in-process builtin.

All fourteen protected builtin records are required. Each stable record is
`{kind:"builtin-in-process",enabled:true,loaded:true,registration:{path},execution}`.
Its execution binds kind, contract `builtin-in-process-v1`, distributionBuildId,
sourcePath/sourceSha256/serverBundleSha256/moduleTableSha256/profileSha256 and
closure. Source paths must equal the SAME protected
`distributionRoot/builtin-plugins/ID`. The complete stable identity must match
both the protected record and the independently verified manifest mapping.
Fresh actual instance IDs must be nonempty and unique; enclosing incarnation
must match the same protected daemon. Loaded/execution observations must agree.
A null profile is provenance only and cannot qualify any maintenance operation,
even if both host and manifest describe null. Missing builtin, wrong tags,
extra builtin, mixed identities and non-target absence all HOLD.

The manifest mapping argument is an internal pure-parser dependency, not a CLI,
configuration override, authority factory or extractor invented by this adapter.
The committed mapping, observation CLI and shared namespace-port binding are
described below; actual retained-system/private-runtime qualification remains a
separate pending gate. Unsupported V2 never calls the V1 transport. Parser
fixtures use explicitly synthetic independent wire/host/manifest values and do
not establish executing-instance qualification. Production acceptance requires a
separate exact-source review and actual native/producer coupled proof.

### Committed builtin manifest/profile mapping and V2 transport

The V2 read facade now uses the committed `56faaa4de` `plugin cohort-v2-status
--json` command, whose CLI checks `server_info.features.managedPluginCohortV2`.
That is API availability only. Global native operation readiness remains a
separate check. V2 never retries the V1 command.

Before any retained Node execution, Python still verifies the raw manifest digest,
complete protected file inventory, runtime/helper/external-library identities and
fixed Node/CLI bytes. For V2 it additionally reads the producer's fixed real-account
`.local/state/djbclark-ade/forks/paseo-qualified-host-policy.json` through protected
ancestry, matching exactly one immutableRoot row to the configured raw manifest,
build, qualification and immutability adapter. All fourteen exact external builtin
profiles are required. Changing that policy during the facade lifetime latches HOLD.

The map mirrors committed `6acaa01dd4d86f6dcf91f7882f705d26fbb4e387`
`daemon-verifier.ts`, `builtin-profile.ts`, `builtin-inventory.json`,
`builtin-bindings-recipe.json` and `canonicalBuiltinJson`. The canonical module
table binds the finite recipe, runtime bytes, daemon bytes and external library
inventory. Every builtin artifact binds source-identity bytes, original bundle
bytes, adapted `server.factory.js` bytes, manifest/metafile and the same module
table. Loaded bundle identity is the adapted evaluated factory digest, never the
original bundle digest. Actual SAME-root builtin directory inventory must be the
exact fourteen IDs. Protected profile source/bundle/table fields must match those
independently verified manifest identities. The public profile hash does not mint
executing-instance authority.

Only after the complete tagged V2 union validates does the facade expose a private
unwrapped directory view to the existing retained-target/CAS code; actual builtin
entries remain separate and never become fake receipts/journals. Missing profiles,
changed external policy, unsupported current native readiness or incomplete runtime
facts still HOLD. New `systemClosure` manifests explicitly HOLD before Node until
the producer's exact retained-library/private-namespace verifier contract is
integrated; old host-library or missing mount facts are not substituted.

### Committed retained system-closure metadata and scoped held recovery

Producer `cf96bec96825162457f9adca514faea71bae4093` adds
`systemClosure` / `systemClosureSha256`. The controller mirrors its strict finite
metadata schema and canonical digest, bounds, duplicate/path checks, retained
ELF/interpreter/alias/search/cache/preload declarations and retained-file
cross references. External rows now bind absolute loader paths to
`system-closure/elf/...` backing members; the pinned cache binds its retained
loader member. Preexec verifies the sealed backing inventory rather than reading
host libraries as a substitute. The builtin canonical module table additionally
binds systemClosureSha256. This structural validation cannot establish namespace,
ELF resolver or kernel-map identity. The shared read-only port below now supplies
that verification boundary; execution HOLDs unless its actual current-namespace
checks pass. Superseded blocked helper revisions are never imported or executed.

Native `2410a2c4a050c7568d506e6bfbe0c2158d908356` supplies the actual scoped
recovery guard and installed-only `maintenanceHeldRecoveryV1`. The existing SAME
live facade can pass the global operation-capability refusal only for explicit
recover/verify of its already confirmed failure, with original bearer, private
origin, unlatched uncertainty and a fresh current context. Journal prepare/reuse
still checks its persisted original context/intent, current recover+verify consent,
coherent complete non-target cohort, original reservation/server/incarnation and
fresh plugin CAS. No new BEGIN, reconnect, generic-error fallback, ordinary replace,
END shortcut or public readiness flag is introduced. Native private eligibility
and real fresh barriers remain the final gate.

The committed CLI's confirmed alternative has nonidle maintenance state and
`recoveryRequired:true`; older synthetic `false` assumptions are rejected.
Installed known-failure or held-recovery API flags only permit parsing the
separately authenticated exact normal result. Same-held recovery requires the
new installed held-recovery API plus actual restriction, not availability alone.
The private confirmed cache persists through `recover-required` to
`verify-required` and clears only after the separately authorized verify response
and fresh same-tuple status prove durable restriction removal. Generic throws,
malformed results or lost acknowledgements latch UNKNOWN and discard reuse
eligibility. All tests with synthetic wire remain source orchestration evidence;
actual coupled native qualification and exact-source review remain required.

### Shared read-only namespace port

Reviewed native source `389bb84ea48c8c800a3c528b23e1d192be052959` provides
`verify_existing_namespace(root, expected_manifest_sha256) -> None` in the SAME
packaged `ROOT/system-closure/namespace-bootstrap.py`, mode 0444. Controller
preexec now consumes this real port instead of unconditional systemClosure HOLD.
It first independently authenticates the raw manifest and full sealed inventory,
then measures that exact member AND requires one of the three independently
reviewed size/SHA pairs encoded in controller source (listed below):389,d8 or
a3f. The manifest cannot choose an unreviewed import implementation. All three
known sources were independently reviewed to import definitions only; no generic
AST predicate or Python sandbox is claimed. Unknown/modified future helper bytes
HOLD until a separately reviewed controller adapter source update. There is no
JSON flag, path override, approval key or runtime acceptance bypass. Controlled
import uses the actual fixed `__file__` and a temporary private module name, never
the `__main__`/Admin launch path. No arbitrary module,
PID, command, recipe or policy path is exposed. Every exception, missing port,
changed source or non-None return is HOLD.

Immediately before the retained Node/CLI subprocess starts, the shared port
rechecks the CURRENT process namespace with its existing finite Distribution
resolver, ELF/cache/alias/hwcaps/absence/path authority, retained/current same inode,
actual readonly/nosuid/nodev target mounts, private propagation and stable final
snapshots. This code does not copy those checks, enter/create a namespace, invoke
Admin, mount, unshare, change identity or execute a privileged helper. A caller
outside the proved namespace refuses. Successful read-only verification is not an
execution-owner or qualification brand; genuine native private daemon/child/cohort
facts and current transaction authority remain mandatory.

Dedicated controller CI checks out the exact shared-source revision for a real
import/refusal case and module cleanup. Unreviewed synthetic helpers, even with
matching manifest records and the accepted byte length, refuse before compile/exec;
production acceptance is never relaxed to make a synthetic positive pass. Tests
cover module/class decorator rebinding and eager defaults/annotations without
claiming arbitrary Python import safety. These source tests never establish
actual namespace qualification. Root's disposable actual Linux
namespace proof and exact source review of this adapter delta remain separate gates.


### Truthful read-only status

`status` never acquires a Journal lock, writes/repairs/enrolls state, obtains
transaction adapters, retains/downloads candidates, compiles a candidate, reserves,
reconnects a bearer or performs recovery. It reads a canonical existing SAME
Journal twice around native observation, requires settled runtime_verified state
and retained validated verified bytes, then checks actual full qualified cohort,
ready target native journal/current loaded identity, bound enclosing authority and
stable idle/no-recovery native status. The full cohort/epoch and maintenance read
must remain equal across the bounded observation. Protected enrollment and Journal
bytes/retention are rechecked before reporting success; this is a stable read
observation, not a claim that independent APIs form an atomic transaction.

Success reports runtime_verified with matching verified/observed receipt, actual
Journal CAS/state and promotion_hold; authorized is always false and
observation_only true. A promotion HOLD remains visible even when running identity
is verified. Ordinary activity may block promotion while leaving the currently
executing qualified identity unchanged; status does not use an operation-readiness
flag as qualification or predict apply admission. Native mutable/unknown/held state,
missing/unqualified/fullcohort mismatch or identity drift HOLDs. Injected synthetic
ports cannot provide the shipped status path; tests with real facade/parser and
synthetic wire demonstrate source behavior only.

Finite refusal reasons include protected_enrollment_unavailable,
journal_unavailable, journal_unsettled, verified_artifact_unavailable,
native_observer_unavailable, native_observation_unavailable,
native_identity_mismatch and state_changed_during_status. Status provides no
operation grant; apply rechecks current authority and all actual native boundaries.

### Optional finiteGit G data, separate from helper qualification

Committed producer `9b62e77941d6c1563cf7d09726cceb2a3dfaa722` adds optional
`finiteGit` ONLY on the `worktree-include` protected builtin profile row. Other
builtin IDs retain their original exact schema. Its strict wrapper is
`{schemaVersion:1,recipeSha256,recipe}`; recipeSha256 hashes canonicalBuiltinJson
of the recipe ONLY. The independent parent profileSha256 continues to represent
external behavior approval and is never replaced by that recipe digest.

The G recipe has only contract, distributionManifestSha256, systemClosureSha256,
literal retained tools/argv, direct-dotgit repository, original environment,
system/global/local configRoots, ordered includes, sorted unique readonly file
identities and sorted unique disjoint protectedAbsent. Parser checks exact nested
keys, UTF-8/no-NUL and native text limits, 64KiB canonical recipe, environment
32-key/32KiB limits, 64 files/1MiB each/8MiB aggregate, 32 include edges and
64 absent paths. Config roots and include endpoints must appear in the files.
Original GIT_CONFIG_SYSTEM/GLOBAL values must match their declared roots; local
must equal cwd/.git/config. Include order and duplicate edges are preserved.
No flags/path aliases/unknown tool/argv fields or profileSha256 alias are accepted.

Retained mapping additionally binds the recipe's distribution/systemClosure SHA
to the actually verified raw manifest and canonical retained system closure, and
requires the literal runtime/git, runtime/git-observer and runtime/git-gate.so
members with sealed modes in the actual measured inventory. Missing identities
HOLD. No new executable path/config override or command is exposed or invoked by
this data parser. The existing fixed real-account policy path/HOME behavior is
unchanged; private gate additions are not part of the original recipe environment.

This parser reads no Git config and launches nothing. It cannot establish actual
original environment equality/real-account HOME, recursive include depth, complete
immutable config/source/index/ancestor/absence coverage, actual Git semantics,
private once-only SDK request/start or descendant settlement. Those are private
producer audit/admission facts. Unsupported ordinary helper behavior remains
unchanged with maintenance HOLD; neither parser success, recipe digest nor an
external profile hash mints admission. CI fixtures include nonempty system/global,
relative unconditional includes, excludesFile and safe.directory as DATA only;
they do not establish real helper qualification.

### Verification scope is not another native policy grant

Native protected plugin policy accepts only activate/recover. Verification sends
current CAS and exact artifact claims through the held operation, but native
qualification consumes the original loaded ticket's unchanged authorization row.
No verify row, activate-at-current row or recover-at-current row is needed for
verification. The controller's existing concrete description is not installed or
consumed as such a new policy row. Initial Aactivate0, Bactivate1, Arecover2 remain
the three unchanged rows for normal A-B-A: successful plugin CAS/loaded generations
are1/2/3; verifies at2 and3 leave CAS and loaded receipts unchanged. Recovered A has
a fresh execution receipt; retained baseline A remains separately available. The
same-live synthetic failure trace uses replace expected8->failure CAS9, recover
expected9->CAS10, then two verifies expected10 with CAS10 unchanged. These counters
remain distinct from the ADE Journal and native reservation generations.


### Copied Sherpa addon provenance is finite data

Producer source `522ba78b4b54c6b59e293bc58672a248346b47d3` (parent
`da68f41fd430036af2fe42bdeac7b3513923794d`) records exactly one copied
`node_modules/sherpa-onnx-linux-x64/sherpa-onnx.node` adaptation. The controller
accepts only its closed schema1 record at fixed
`native-provenance/sherpa-addon-adaptation.json`, ordinary sealed file/helper
inventory. No manifest top-level extension or namespace helper change is used.
`builtinModuleTable.recipe.copiedSherpaAddonRecipeSha256` binds the WHOLE raw
canonical record file; the record's internal `recipeSha256` separately hashes
canonicalBuiltinJson(recipe). Substituting one digest for the other refuses.
The adapted-profile binding table and helper inventory mirror the committed
producer's builtin-helper binding and system-closure/native-provenance/.so members.
Legacy manifests without this record retain their existing mapping.

The consumer fixes package1.12.28, integrity/revision/member, original840296-byte
SHA, three ordered sibling library identities, literal patchelf argv and eight
ordered primary source URL/size/SHA identities (including LICENSE). Tool version,
bytes/size and compressed provenance are bound as measured evidence. It validates
closed bounded before/after metadata and their stable code/relocation/init/symbol/
version/protection observations, without deriving any observations from ELF bytes.
Output size/SHA and compact sibling ELF descriptions must match actual manifest,
helper inventory and systemClosure rows. Original/tool gzip provenance is read
with bounded single-stream decompression and exact uncompressed size/SHA, without
writing/extracting/executing anything. Source and all other actual retained bytes
still pass the existing complete raw-manifest/sealed-file verification first.
Unknown keys, changed source/tool/argv/dependency/output/metadata, noncanonical
JSON, missing cross references and bounds violations HOLD.

This is data consistency, not a third ELF resolver, build transformation permission,
CPU behavior approval, or proof that metadata describes executed code. The reviewed
packaged389 namespace verifier remains pinned unchanged and checks actual current
namespace/ELF/cache/inode facts immediately before transport. External protected
qualification and all14 profiles, actual private owner/full cohort, current consent
and native CAS remain mandatory. Build provenance and the pinned upstream source
correlation do not supply reproducible-build attestation or meaningful model-bound
CPU/native feature proof. No live configuration, profile, schedule or grant is
installed by this change.

Dedicated Linux source CI consumes the exact producer522 build artifact as DATA,
checks its independently supplied ZIP digest and inner archive digest, and reads
only named bounded tar members without extraction/native import. It tests the
actual measured record/output/siblings and gzip provenance along with synthetic
canonical/mismatch/unknown-schema negatives. Actual namespace/private execution
qualification is not inferred from this positive data test. Existing actual389
import/refusal and no-Popen-on-final-verifier-failure regressions remain required.


### Three reviewed read-only namespace source identities

The controller's source-identity gate now accepts the CLOSED three-pair set:
`(52756, 605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7)`
from reviewed389, and
`(53480, 4f9164025314df755116ed09330a9d2c5d7b0d7ad3bc18c9abd28345b99001cf)`
from SOURCE APPROVED `d8f983b964214ea13abf21648d905a50fa5aab40`; and
`(54910, 39ce30d1fc0e102889075e778f26a15c7b12a2ed770c1692325198ced5bc0cda)`
from SOURCE APPROVED `a3f19ed7bdf56cc5d72f53fc60014960e8ebcf9a`.
Both whole byte size and SHA must match the same reviewed pair. The d8 Git bytes
were independently rehashed before this adapter change. Full R5 source review
covers its narrow retained-caller/direct-sudo-monitor ancestry amendment; the
actual read-only port is unchanged. Blocked2c/c19 and every unlisted or modified
helper remain refused before compilation/import even if manifest claims match.
This is compatibility for exactly three known read-only implementations; it is not
a generic fallback, mutable path or manifest-selected import authority.

Fixed member/mode, complete sealed inventory/raw-manifest authentication, actual
source measurement and postcheck stability, controlled module cleanup and final
real None-or-raise namespace port before Popen remain required. Dedicated source
CI checks out all THREE exact Git revisions for actual import/refusal and mutation/
mixed-pair negatives. Existing522 build DATA coverage still uses approved389
and supplies no namespace qualification. This three-source controller read-only set
is distinct from privileged launcher/root acquisition pins: those change separately for each exact measured successor archive. No privileged helper/namespace launch,
Mac/live use, new profile/loader or runtime qualification is performed here.

The a3f source adds only the reviewed retained-directory/measured-ELF descriptor
route. Its helper size/SHA was independently recomputed from frozen Git, and the
FULL retained-ELF adversary report was read. This source identity does not
approve an unmeasured new archive or perform privileged acquisition; no resolver
logic is copied into the controller. Existing389/d8 baseline read-only
compatibility, full raw-manifest/sealed inventory, fixed source/member/mode and
final actual None-or-raise port/native guards remain unchanged.
