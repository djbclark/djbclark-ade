# Fork release core API v1

`bin/ade_fork_release.py` is a stdlib Python library, without CLI, installer,
merge engine, patch manager, publication or live adapters. The foundation's
managed updater guards continue to HOLD. This slice alone does not complete
fork maintenance or authorize any deployment. Existing human gates (including
initial cutover and daemon interruption) remain integration prerequisites.

## Evidence

`canonical(value) -> bytes` accepts only exact JSON types, finite floats and
string dictionary keys. It sorts keys, uses compact UTF-8 JSON, preserves array
order and rejects non-JSON types, cycles, nonfinite numbers and invalid Unicode.
It is a versioned ADE encoding, not an implementation of RFC 8785. `digest(value)`
is SHA256 of that encoding. `parse(str)` additionally rejects duplicate keys.

`Receipt(encoded: bytes)` is frozen; `sha256` identifies the entire receipt.
`make_receipt(bindings, policy, results)` encodes evidence; it does not attest it.
`validate(receipt, expected, policy, *, artifact=None, artifact_digest=None)`
returns None or raises `ContractError`. At least one artifact argument is required;
if both are supplied both must match. A caller-provided digest must come from a
trusted artifact reader. Deployment always checks the supplied bytes itself.

The trusted expected mapping contains exactly `FIELDS`: schema_version (1),
component, upstream_commit, fork_commit, dependencies (complete ID-to-commit
closure), patch_manifest_digest (content digest, not a filename), applied_patches
(ordered unique identities), recipe_revision, platform, toolchain,
artifact_sha256, policy_digest, feature_contract_digest, authority and evaluator.
Commits are full lowercase SHA1 or SHA256 identities. The trusted integration
must resolve the full dependency closure, recipe revision and patch manifest
content itself; this library cannot discover omitted dependencies or patches.

Policy is supplied by trusted code, never extracted from a candidate receipt.
It includes `compatibility_group` and a nonempty `features` mapping of stable IDs
to protected assertion definitions. Policy and feature-contract digests must
match the expected bindings. Results must contain precisely every protected ID,
each with exactly `contract_digest: digest(definition)` and `status: passed`.
Deleted, extra, skipped, pending, failing or weakened assertions fail validation.
Changing a receipt input changes its identity; frozen encoded bytes are detached
from mutable caller dictionaries. Storage of receipts in an immutable CI or
content-addressed archive is an integration obligation, not a journal feature.

**Matching evidence is not authentication or install authorization.** Pure
validation intentionally checks consistency only. Real adapters must authenticate
CI authority and evaluator provenance against a protected trust configuration,
exact reviewed commits and the artifact before returning True from
`authenticate(receipt)`. Arbitrary JSON workflow fields and locally constructed
receipts provide no authentication. No self-signed crypto is supplied here.
Tests use an explicitly trusted fake evaluator; never wire that fake into live use.

## Trusted adapter boundary

`Adapters` takes in-process callables only. Receipt content is never interpreted
as argv or code. `authority(operation, identity)` and `authenticate(receipt)`
default deny; `reserve` defaults absent (hold). `policy()` reloads current trusted
enrollment including revocation. Returning anything other than literal True from
preflight, verify, authenticate, authority or reservation must not grant access.
All authority and authentication callbacks must return literal bool True to grant. No implicit merge/publication/channel
permissions exist; callers implement those distinct gates outside this executor.

`observe()` returns an independently measured immutable runtime identity, not a
version label. For this API candidate identities are receipt SHA256s; an adapter
must prove runtime corresponds to those exact component/dependency/artifact
bindings. The initial installed identity is an opaque trusted enrollment identity.
`retained(identity)` confirms an exact recoverable artifact remains accessible.
`stage(identity, bytes)` must preserve previous artifacts; the core has no delete
operation. `preflight(identity)` must check the complete compatibility group.
`activate(identity)` changes only binaries. `verify(identity)` checks actual health.
`recover(identity)` restores only compatible binaries, never a snapshot of writable
state. Partial staging is possible and must be inspectable/recoverable by adapters.

`reserve()` is a context manager yielding literal True only while an actual
quiescence/reservation is held; it must prevent conflicting group members and
external updaters from modifying runtime throughout activation and verification.
A lock file alone is not runtime quiescence. False yields busy; absence holds.
The policy authority must remain serialized with the activation boundary: the
core reloads immediately before activation, but cannot stop an external policy
writer from racing a callback without the integration's reservation protocol.

## Durable transaction lifecycle

`Journal(directory: Path, group: str)` uses a group-hashed journal and flock path.
Use one stable private directory across all writers of that compatibility group,
on a local filesystem with working flock, atomic rename and fsync semantics.
Do not delete lock files or independently select directories for group members.
`enroll(verified, adapters)` requires explicit enroll authority, observation and
retained recovery bytes, and refuses an existing journal. Enrollment establishes
only a binary-compatible recovery baseline; migrated state is unsupported.

`deploy(receipt, expected, policy, artifact, adapters, *, previous, generation,
migration='unsupported', dry_run=False) -> Result` validates evidence before
locking; real execution authenticates it. Only explicitly trusted
`migration='binary_only'` is supported. Every other state migration holds.
Dry run performs pure evidence/group checks, no callbacks, locks or filesystem
changes, and does not claim runtime readiness. Expected previous identity and
generation must match the journal. Candidate policy group must match the journal.

Normal flow is qualified evidence → permission checks → preflight → stage →
activate → verify → runtime_verified. Qualification is separate from authorization,
staging, activation and runtime verification. Policy, actual previous identity,
recovery artifact and activate permission are checked again at activation.
Every callback intent is atomically persisted with file fsync, replace, and
parent-directory fsync first. Transaction start increments the generation even
when the attempt later fails. The last verified identity is preserved on failure.

`recover(adapters, *, generation) -> Result` independently observes runtime,
requires recovery and verify authority, retained baseline bytes and reservation,
then records a new monotonic generation before the recovery callback. Recovery
is explicit even after a lost acknowledgement with apparently correct runtime.
It never re-executes activation on retry, guesses success, or discards new writes.
To intentionally roll back to another qualified artifact, deploy its receipt
with the current previous identity/generation: that is also a new generation.
Artifacts must be retained outside the journal for recovery; no garbage collector
is supplied. A successful deployment changes the baseline to its verified identity.

## Results, errors and crashes

`Result(status, reason, generation)` is frozen. Status is `hold`, `dry_run`,
`runtime_verified` or `recovery_required`; reason is a stable machine-readable
code (except the explanatory dry-run reason). Holds include stale_job,
unsafe_migration, unauthenticated_evidence, permission_OPERATION, busy,
reservation_required, policy_changed and recovery_artifact_missing. Unfinished
journal phases return recovery_required; runtime drift also requires recovery.
Changed activation preconditions, callback failures and authority revocation
preserve the baseline and require recovery. A staged or activated phase never
means runtime verified. Recovery failure remains recovery_required.

Malformed input/evidence or invalid journal data raises `ContractError`.
Infrastructure errors (I/O, locking, observation, authority, reservation entry or
exit) can propagate: callers must treat any raised exception as **no success**,
inspect the durable journal and runtime, and request recovery. Ordinary exceptions
inside recorded callback phases attempt to persist recovery_required and return
that result; failure to write that record propagates. BaseException/process death
is intentionally not swallowed; the recorded intent remains uncertain. Retrying
an unfinished transaction observes actual runtime but never repeats a callback.
The journal and runtime cannot be atomically committed together; even a failure
after the final rename must be reconciled through observation, never assumed safe.

Focused CI exercises fake adapters only. Real authenticated CI verification,
artifact archival, compatibility and migration analysis, enrollment, policy
serialization, native quiescence and runtime identity adapters remain required
before a controlled pilot can qualify for live use.
