# Evidence custody source pilot

This standalone library is source/model work only. It is not wired into the ADE
controller, CFEngine, an AWS account, a schedule, or any runtime. Its CLI returns
HOLD without importing boto3, constructing a client, or making a network request.
No bucket, account, principals, terms, privacy policy, prices, budgets or storage
architecture have been selected or enrolled. No actual archived evidence or
native qualification follows from a passing offline test.

## Protected inputs and authority

`ProtectedAuthority.current()` must come from the existing protected controller's
one-time operator enrollment, independently of candidate metadata. It returns a
fully specified `Policy`, or None. The separate `permits(purpose, closure)` port
must evaluate CURRENT authenticated revocations and standing authority. Neither
port has a production implementation here. JSON bytes, a matching receipt hash,
READY, ACCEPTED, and an S3 ExpectedBucketOwner parameter are not authentication.

All limits are required enrollment choices; there are no inherited proposal
values or accepted default architecture. The protected binding includes account,
region, bucket, namespace, contract/policy digests, generation/sequence rollback
floor, distinct persistent writer/reader identities, object/packet/control caps,
finite cycles and mutations, clocks, an absolute maximum authorized retention
horizon, cash quotes and preservation reserve. The cash quote must cover that
whole finite horizon; it cannot fund an arbitrarily chosen future date. Unknown
actual protection beyond the quoted ceiling holds admission and requires incident
reconciliation without erasing the original reservation.
The binding must remain recoverable independently of a lost Mac/journal. An old
offline checkpoint is not authoritative latest discovery. The existing host must
fetch the enrolled fixed CTRL key using authenticated S3 reads and obtain the
current enrollment/revocation state; absence of either is HOLD. No local file or
candidate-supplied locator enrolls a destination.

The host supplies separately bound writer and reader clients. `S3Store` checks
region, distinct identity labels and no hidden SDK retry. Those labels are the
trusted host's assertion, not an STS or IAM identity proof. The host must establish
that binding; this library never probes credentials or creates a client. A
future host may use boto3 sessions and botocore Config with explicit bounded
connect/read timeouts, `total_max_attempts=1`, and configured endpoints disabled.
The port accepts only the regional AWS S3 endpoint (plus the legacy global
endpoint for us-east-1); other partition/endpoint support is held. It enforces
the enrolled connect/read timeout ceiling and a total streaming
deadline in addition to byte caps; a blocked individual read can finish at most
one read timeout beyond the streaming deadline. No custom endpoint or candidate
profile is accepted by a shipped facade.

## State and finite frontier

The current CTRL has separate baseline A, proposal P, issuance/liability ledger,
control ancestry catalogue, immutable renewal censuses and incident history.
One unresolved proposal is the durable intake lease. Final operation authorization
rechecks the separate exact-closure screened purpose after the current-CTRL read
and immediately before a new upload/CAS. An unchanged Policy or ordinary upload/
accept permission does not preserve a revoked screening grant. Current cycle and
protection-floor predicates are resampled at the write boundary too. Every transition reads the
current protected CTRL and authority, validates/recomputes liability, rereads
current CTRL/authority, and uses IfMatch on its exact ETag. A CAS conflict or an
unknown response requires reconciliation from current CTRL. There is no blind
retry, liability refund, delete, hold removal, lifecycle or expiry operation.

`reserve` records exact screened hashes, lengths, namespace keys, cohort, horizon,
annual charge and worst-case lifetime charge BEFORE any payload PUT. Screening
is a separate current protected purpose for that exact closure. It is not a
keyword secret scanner or silent redaction. The caller supplies already approved
bytes, not paths or commands. Payloads are opaque data, including malformed
negative fixtures. One strict manifest names the full ordered data descriptor
closure. Oversized packets must be split into bounded single-PUT chunks before
admission; the operator selects caps. A 10 GiB data choice would require a
separate explicit control allowance (for example 64 MiB), not subtraction or
unbounded control growth. No such values are selected by this code.

The finite control pool is prepaid at enrollment for every possible bounded
control version, including failed/unknown/orphan writes. Intake cannot spend
that preservation reserve. Each issued payload atom retains its full quote even
after exact successful readback: no refund is inferred from deduplication, a
failed request, 404, timeout, abort, revocation or expired cycle. This conservative
pilot exposes no no-commit/quiescence release mechanism at all. Annual totals
retain their original issue year; lifetime totals never reset. Quotes are
operator-supplied upper bounds, not verified provider prices. They must include
all applicable storage/request/readback/egress/telemetry obligations and allowed
attempts. The library disables SDK retries; an integrating host must also bound
its issued RPC/recovery attempts within the enrolled cash authority. This code
is not an AWS billing cap or a guarantee against external account spending.

`ready` is only a phase transition. `resolve_current` is the ONE normal/recovery
reader. It independently checks exact actual bytes/version/protection, complete
closure/manifest, contract/ledger/census, current revocations, original cycle,
clock, and a stable current CTRL reread. Final authority/closure revocations and the
clock/floor/cycle/proof window are checked after transport, so a slow read cannot
backdate acceptance or turn a final-read revocation into a successful result. SDK/transport/malformed failures return
HOLD. Baseline and proposal are independently reported; a failed latest proposal
cannot erase an otherwise valid retained baseline. A baseline is reverified and
must name its exact protected READY origin. The protected minimum-sequence floor
applies to CURRENT discovery/reconciliation, not to an exact immutable historical
origin or fixed-census source. Historical bodies still require all schema,
identity/generation/policy/contract, exact-byte/protection and origin/census link
checks. Advancing the current floor cannot manufacture a replacement historical
origin, and an old exact body cannot substitute for CURRENT. Its prior 24-hour proposal window is
not reapplied to long-term baseline use. The enrolled ongoing floor and current
revocation/protection rules still apply.

`accept()` recomputes the complete predicate without accepting any external proof
object, then CASes a baseline carry. Its `VerifiedAcceptance` describes the finite
observed pre-CAS frontier, not a self-authenticating new terminal CTRL. The next
reader must observe and fully verify the actual terminal CTRL version. There is
no infinite ACK-of-ACK chain and no output granting runtime/promotion authority.
A failed/lost terminal CAS reply is recovered by reading current CTRL, never by
trusting an in-memory proof or an ACCEPTED marker.

An expired P cannot reset t0/H/liability. `revalidate` requires separately granted
standing purpose and finite cycle capacity, appends a new cycle with a new t0,
retains every original cycle and original issue liability, and never lowers H.
It does not extend object protection by assertion; missing actual protection
remains HOLD. Materially changed contracts/enrollment require a separate owner
choice and are refused against the old CTRL in this pilot.

## Renewal and preservation

Preservation has its own current authority purpose and remains possible while
intake is denied or an upload outcome is unknown. Incidents, known exact outcome
reconciliation and renewal use the same CTRL CAS; an expired COMPLIANCE date can be repaired
under preservation authority while actual legal hold remains ON; no state is overwritten from
a stale snapshot and no reservation is cleared to make room.

`renew_begin` persists a fixed protected source frontier, sequence cutoff, exact
census/root, original due and target. Membership covers every issued atom,
including unresolved ones, and all known historical CTRL versions plus the
source CTRL itself. Completion recomputes membership against that exact source;
a forged empty census/raw done flag cannot satisfy it. This is a bounded single
catalogue shard: reaching the enrolled byte/member/control cap holds further
intake. It never silently truncates membership or claims an implemented unlimited
sharded index. A future larger enrollment needs an independently reviewed shard
protocol before exceeding these finite bounds.

Progress is idempotent per census member. An extension with a lost reply is read
back from the exact actual version before another extension is considered.
Unknown old atoms block that job. Progress/control writes are newborn control
versions in the prepaid finite pool, and later payload births retain their own
cohort/horizon/liability. They do not move the old job's finish line. A late atom
already in the original issuance census stays in that census. The final CAS
uses the latest complete ledger as its explicit delta watermark, preserves all
newborn atoms and unrelated reservations, and closes only if every original
member has fresh actual protection and the original due has not passed.
Finish resamples monotone trusted time after census/member transport, after the
final current read and at commit. Original due, progress/proof age and applicable
protection floors must still hold. `completed_at` is the actual completed pre-CAS
proof observation, not the entry clock and not a provider terminal-commit-time
certificate. The final current reader must still verify the actual terminal
version; an in-flight CAS response cannot fabricate a timely terminal observation.
A refused finish preserves all progress, due, census and liability.
An expired observation may be refreshed by the same progress operation; the
original deadline never moves. Missing the original due holds admission and
requires an independently authorized incident/repair policy; the library cannot
brand it timely by starting another job. Accepted state rechecks finished census
actual protection; `done` itself is insufficient.

The namespace must enforce enrollment's sole serialized writer/controller
capabilities and no out-of-ledger creation/delete markers. S3 LIST is not used as
a fictitious atomic census. Account compromise or loss, privileged legal-hold
removal, provider failure/account closure and forged protected host authority
remain explicit threats. Finite COMPLIANCE dates are not literal forever;
policy-indefinite retention needs continuing funded renewal. No extra service,
root key, scheduler or PKI is added. Extra CloudTrail/data-event/logging services
recommended by AWS security guidance would need a separate explicit operator
selection and budget; none is provisioned or silently required here.

## Validation and boundaries

The dedicated Linux workflow runs only the authoritative offline versioned model
and botocore Stubber request/response validation with dummy credentials and a
socket-denying fixture. It tests actual API parameter spelling/version binding,
CAS/no-overwrite, lost acknowledgments, retained unknown liability, independent
readback, caps/cash, raw phase refusal, revocations, immutable old cycles,
retained baselines, fixed renewal census and newborn deltas. No local tests,
cloud calls, live runtime or genuine retained qualification are part of delivery.

The model's protected enrollment/authority and clock are synthetic. Real owner
architecture/terms/budget/privacy/recovery acceptance, independently bound
persistent principals, actual storage/readback/restore proof, CF semantic/full
contract/Fable gates and controller integration remain HOLD. Do not treat the
source pilot as an operator enrollment or successful production archive.

Primary API references checked for this source:
[PutObject](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html),
[GetObject](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html),
[GetObjectRetention](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object_retention.html),
[GetObjectLegalHold](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object_legal_hold.html),
[PutObjectRetention](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object_retention.html),
and [botocore Stubber](https://botocore.amazonaws.com/v1/documentation/api/latest/reference/stubber.html).
