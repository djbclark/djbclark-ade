# Fork controller pilot v1

`bin/ade-fork-controller status|plan|tick` reads the real account's fixed
`.local/state/djbclark-ade/forks/controller.json`. HOME, CLI flags and environment
cannot substitute a grant path. No file is installed by this source change.
status/plan are deterministic protected-candidate planning; tick performs read-only GitHub discovery and private evidence retention, with no runtime mutations. Missing
or unsupported enrollment returns HOLD. No runtime adapter is selected by JSON.

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
Native mutation remains unsupported; later apply must recheck both under native
reservation at its own commit boundary, not trust an earlier selection response.

Discovery is bounded to five history pages, 80 metadata calls and four candidate
transport/receipt verification pairs per tick; exceeded bounds hold, never truncate
to a false newest claim. Shared GitHub quota is checked first (remaining <500 holds).
No scheduled job or evaluator runs are launched by discovery. No locally constructed
fixture receipt proves actual qualified producer/runtime execution.

Do not route master-snapshot through Sync's merge strategy: ADE upstream/fork
are identical, and that API rejects this strategy. Future scheduling can use the
existing ade-sched source mechanism. A read-only source example, deliberately
not installed, is:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>com.djbclark.ade-fork-controller-check</string>
  <key>ProgramArguments</key><array>
    <string>__ADE__/bin/ade-fork-controller</string><string>tick</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
</dict></plist>
```

No schedule, operational enrollment, native policy, secrets or live plugin calls
were installed/executed. Installing schedules needs separate consent.

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
Private held-operation transport is being specified by native owner049; no
unpublished endpoint/FD protocol is guessed. Until that reviewed bridge and real
producer are integrated, production NativeFacade remains unsupported, and there
is no automatic END/reopen path on failed or uncertain operations.


## Proposed native held-operation CLI transport

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
Default status/plan and discovery tick retain their existing roles. An approved
scheduled promotion can invoke apply under current consent once genuine native
support is available; selection is not a permanent planning-only substitute.
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
Its actual producer mapping and native capability/CLI binding remain pending.
Production V2 `supported` currently returns false before any V1 transport call.
Parser fixtures use explicitly synthetic independent wire/host/manifest values;
they do not establish executing-instance qualification. Wiring production V2
requires the committed native transport and actual canonical manifest/profile
mapping, plus a separate exact-source review and coupled proof.
