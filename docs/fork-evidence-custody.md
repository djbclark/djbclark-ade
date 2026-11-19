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
must evaluate CURRENT authenticated revocations and standing authority. The source integration below implements these ports; no operator anchor,
credential source, enrolled account or runtime facade is installed here. JSON bytes, a matching receipt hash,
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
that binding; the standalone S3Store never resolves credentials. The Stage3 binder can create
explicit clients and perform metered identity checks only after selected protected
inputs; those calls have not been executed during this delivery. A
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


## Stage3 source integration, not runtime enrollment

`Enrollment.load` requires an independently supplied exact anchor digest, expected
OS owner and selected executor. Every Policy, principal kind/stable ID/session,
standing scope/privacy digest, executor-specific private journal location/device/
inode, term, wallet limit and cash quote is mandatory. No selected values ship.
The loader checks no-follow private regular bytes before SDK/client work. Live
wire guards recheck anchor bytes/owner/expiry. The CLI stays HOLD and never loads
an enrollment, credential provider or SDK client by default.

`CredentialBinder` uses explicit immutable CredentialBundle material from the
selected host, not a credential resolver. The actual lazy boto3 factory passes
explicit keys/token/region/official endpoint, TLS, bounded timeout and one-attempt
configuration. An enrolled prepaid identity slot is fsynced before STS
GetCallerIdentity. Exact Account, ARN and stable user/role ID/session must match;
two sessions of the same role do not make independent principals. Only then is
an S3 client constructed from the SAME bundle. Refresh/replacement/expiry needs
new binding. Identity response alone is not authorization. No credential material
is stored in request records; unknown SDK parameters are refused before journaling.
These are actual API source paths, exercised only with dummy offline clients.

Schema2 explicitly appends a protected integration header to the schema1 custody
shape. It records owner-anchor identity, current authority expiry/fence/floor,
revocations, exact closure screening and the fully charged RPC-wallet ledger.
`prepare_schema2` requires exact-source/version consent and the owner-pinned
header template (excluding the anchor digest, avoiding self-reference).
`migrate_schema1` is explicit; cold recovery never invokes it. The old READY,
accepted baseline, census and their exact schema1 versions remain intact.
Schema2 current validation enforces current floors and actual protected header
bindings; historical schema1 validation is preserved. Raw READY still needs the
same complete existing reader predicate. No owner policy/schema migration is
inferred from discovering a newer candidate.

`AttemptJournal` is an existing selected executor's private consumption file,
not a new cloud service. Its pure genesis builder never installs or resets it.
Missing/relocated/nonprivate journals HOLD before client creation. Root-approved
seed wallets must already be wholly escrowed. Every SDK operation (including
identity/current/protection/history reads) consumes one durable slot with bounded
method/destination/body digest/response allowance before send. File and directory
fsync precede the wire; authorizations, screened closure, time, binding and fence
are checked AGAIN afterward. A rejected post-fsync send remains charged. No
status/404/timeout/lost ACK or unused slot refunds a wallet. The whole escrow,
original issue-year and payload/control reserves remain additive. Request metadata
contains exact nonsecret targets, hashes and intended new wallet IDs; it cannot
silently include SDK credential/customer-key fields.

Successor allocation uses current CTRL CAS paid by the old coordination wallet,
not an unaccounted recursive call. Reservation is immutable and parent-linked;
local registration waits for actual current readback. Lost replies reuse the same
observed wallet ID; a new nonce cannot hide uncertain old liability. Explicit
refencing needs a separate current grant, keeps all old wallets/issuance atoms
and does not prove quiescence. Every executor consumes only its own selected
journal/wallet. Journal capacity, attempt/response/cash/term limits HOLD further
intake rather than reinitializing counters or inventing free discovery.

Cold recovery lazily binds only the independent reader, reads the fixed actual
CURRENT key and exact VersionId/bytes/protection, ingests its protected authority,
and calls the SAME resolve_current reader. It never treats an old checkpoint,
backup journal, raw phase or locator as current consent. A separately surviving
enrolled executor/journal can consume its own seed, discover registered successor
wallets and continue within existing standing scope; lost executor wallets remain
charged and cannot be reused from copied counters. All-journals/anchors-lost
recovery is an exceptional owner gate, not a new automatic allowance. Deliberate
protected-host journal rollback or stolen direct credentials remains outside
this trusted-controller meter; it is not an account-wide provider billing cap.

All fixtures are synthetic. Actual account/architecture/principal/term/budget/
privacy/executor choices, credential acquisition, cloud enrollment/migration,
retention/restore/identity proof, runtime facade and CF/Fable/evidence/promotion
remain unselected or HOLD. No client, STS, S3, account or credential call was run
on the Mac. Only source/static checks and offline Linux CI belong to this unit.

Primary new API references: [boto3 Session](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/core/session.html),
[GetCallerIdentity](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sts/client/get_caller_identity.html),
and [IAM principal values](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_variables.html#principaltable).


Authority ingestion is bound to the Runtime's metered store and verified actual
current read; a caller's internally consistent Observation is refused. Private
anchor/current memory copies must still match their protected bytes. A missing
or relocated journal is never rebuilt from a backup counter; directory identity
is checked again before consumption. Authentic current bytes with expired
COMPLIANCE retention but legal hold ON may establish preservation context;
the existing reader still refuses eligibility until current protection is
repaired under separate authority. Actual SDK errors retain their primary
exception even if secondary outcome journaling fails; the slot stays spent.
