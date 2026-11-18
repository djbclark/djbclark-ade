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
tick('enroll'|'deploy'|'recover') with actual native ports. CLI exposes none of
those mutation modes or dependency injection. Default NativeFacade.supported is
False, so production tick mutations HOLD before acquisition/staging/journal work.
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
Native qualified status/cohort metadata is still being coordinated; supported()
stays false and observe() refuses until its genuine owner-producer coupling is
implemented. No speculative feature/status keys or brand constructors are added.
Thus CLI deployment remains unavailable, even though the concrete transport methods
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
