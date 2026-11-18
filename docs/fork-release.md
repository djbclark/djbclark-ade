# Fork release Journal transactions

This library provides one durable binary-only deployment record per compatibility
group. It does not authenticate candidates itself: protected controller adapters
must authenticate evaluator evidence, re-read current rules, verify the complete
native cohort and retained artifacts, and enforce native maintenance ownership.
Unit adapters are synthetic, never evidence of runtime qualification.

## Schema and identity transitions

Schema 2 requires exactly `schema_version`, `group`, `generation`, `verified`,
`baseline`, `state`, `candidate`, `transaction`, and `promotion_hold`. Enrollment
sets nullable `baseline` and `transaction` to null. Missing/legacy fields hold;
no reconstruction from directories, candidate claims, or protected previous values.
Migration needs a separate explicitly reviewed procedure. Nothing deletes retained
artifacts or restores writable-state snapshots.

A successful A-to-B deployment atomically writes verified B and baseline A in
`verified_held`, then separately releases maintenance. A failed C deployment from
B preserves verified B and baseline A. Default `recover` reconciles only an
unfinished transaction to its recorded verified identity; it never rolls back a
healthy deployment. Explicit `rollback_target` must equal the recorded nonnull
baseline of a healthy deployment. Current recover AND verify authority, retained
evidence, compatibility and qualified native agreement are still required.

Before recovery callbacks the Journal records exact kind, target, from-verified,
transaction ID and generation. The durable recovery direction retains that baseline target even if the old
verified pointer differs. Unknown callback/process outcomes hold without replay;
only a confirmed eligible same-held result can retry through the reuse lane.
Successful explicit rollback consumes the baseline and sets a durable promotion
hold. Qualification of the former target remains valid, but automation cannot
repromote it until a separately current explicit resume grant clears the hold.

## Public in-process API

`TransactionContext` is frozen with constructor fields in this order:
`schema_version, group, kind, cas_generation, generation, transaction_id,
verified, baseline, target, rule_digest`. Version is 1, generation is exactly
CAS+1, transaction ID is a fresh UUID hex string, rule digest is lowercase SHA256
of the entire immutable protected rule. Kinds are `deploy`, `reconcile`,
`verified-rollback`, `resume`, and `reconcile-release`. These are observations and
bindings, not consent or private native execution brands.

`ReservationIntent(native_generation, plugin_generation, server_id,
daemon_incarnation)` is frozen and nonsecret. Maintenance generation must be
positive and plugin CAS nonnegative. Journal CAS, maintenance sequence and native
plugin journal CAS are independent. Never infer plugin CAS from loaded activation
generation or invent maintenance counters from null/missing status.

The trusted Adapters extension is:

1. `prepare(context) -> ReservationIntent`: read-only context binding plus coherent
   qualified native status. Revalidate the entire protected rule. This runs under
   the Journal lock; it must not BEGIN or mutate native state. Resume and release
   reconciliation use it for read-only binding; their return value is unused.
2. `reserve(context, intent) -> BeginResult(status)`: called only AFTER durable
   context/reservation intent. Literal status `held` means exact native ownership;
   literal `busy` is permitted only for authoritative typed
   `MAINTENANCE_KNOWN_BUSY`, never generic message parsing or later idle status.
   The native typed refusal covers proven no-barrier active work, or confirmed
   provisional rollback. Unknown, failed or lost-ack BEGIN leaves sticky intent.
3. `finish(context, intent) -> True`: sends END only after the Journal has committed
   verified-held and durable release intent. No context exit sends END. Native
   authorized idle rename is the logical release commit point; acknowledgement is
   not that commit point. Tokens stay only in private native adapter memory/FDs.
4. `released(original_context, original_intent) -> True`: independent observation
   only, matching original maintenance generation/transaction/server/incarnation
   and stable authorized idle commit. It never ENDs, recovers or restarts. Current
   context/rule is bound separately; do not relabel original evidence.

All existing identity callback signatures remain unchanged; `prepare` binds them
to this transaction context. Missing new hooks or rule digest fail closed.
The controller must check native identity and current rules after waits and at
native boundaries; Journal authority checks do not replace native CAS enforcement.

`deploy` retains `previous` and `generation` as exact CAS kwargs and adds
`rule_digest=None` (missing denies). `recover` takes keyword `generation`,
`rollback_target=None`, `rule_digest=None`. `resume` and `reconcile_release` take
keyword `generation`, `rule_digest=None`. Both consume one fresh Journal CAS only
on successful authorized completion; neither performs native mutation.

Known busy consumes the allocated Journal sequence but never increments native
counters or cancels work. Fresh attempts need fresh coherent status and authority.
An interrupted/unknown BEGIN cannot be guessed away. Runtime callback failures keep
an exact recovery intent. Write/response uncertainty after release intent stays in
`release_intent`/`release_uncertain`, bars new deployment and binary recovery, and
can only be resolved through separately authorized independent release observation.
A process crash in `activate`, `verify` or `recover` holds as unknown and cannot
acquire another reservation. A process crash in `verified_held` requires release reconciliation, not
an inferred successful END. No blind replay or automatic rollback after possible
release is allowed.


## Confirmed known failure under the original reservation

`KnownFailedHeld(reason, plugin_generation)` is a frozen descriptive adapter
observation. Only the exact type returned normally by trusted `activate` OR
`recover` is recognized; reasons are limited to `compiler_error` and
`initialization_rejected`, plugin CAS is a safe nonnegative integer. The controller
may construct it only from the actual authenticated capability-gated native
`known_failed_held` alternative and the SAME live in-process bearer. This Python
object never mints a native private brand, supplies consent, or proves settlement.
Native must privately certify actual compiler/helper/child settlement, original
scope/lease/owner, current authority and full held cohort before returning it.

Successful callbacks normalize to None. Dicts/tags, malformed typed observations,
throws/timeouts/lost replies, and unknown outcomes during activation or recovery
become sticky `reservation_unknown`, with no fallback BEGIN, verification-as-success
or END. A normal accepted known failure writes `known_failed_held`, preserves the
verified/baseline pointers and returns that status without verifying/releasing.
It introduces no automatic baseline restart.

The SAME schema-2 transaction allows exactly one optional `origin` object with
exact keys `context` and `reservation`. On confirmed failure it retains the exact
original BEGIN context/intent, then updates only current plugin CAS in the current
reservation description. Missing origin for known-failure state is invalid; no
legacy reconstruction. Origin's maintenance generation/server/incarnation stay
fixed, original Journal transaction and fresh recovery transaction remain distinct,
and its original recovery kind/target cannot change across retries.

An explicit separately authorized recovery calls `prepare` for a fresh Journal
context/CAS. The fresh plan must match the recorded current plugin CAS and original
maintenance generation/server/incarnation exactly. After durably writing fresh
context/intent plus unchanged origin, Journal invokes:
`reuse(context, new_intent, original_context, original_intent) -> BeginResult('held')`.
This optional four-argument trusted callback must prove the private same-process
bearer, confirmed eligibility, fresh native ownership/restriction, current recover
AND verify authority and full cohort. Missing hook, restart/lost token, changed
identity/CAS or any uncertainty holds. There is NEVER fallback to `reserve`/BEGIN.
Non-held/throw from reuse becomes sticky unknown; another explicit confirmed normal
failure from recover may retain the same origin and advance only current plugin CAS.

Recovery then separately verifies the actual baseline/full cohort under current
verify consent. Native's durable recovery-only restriction must independently refuse
replace/END until actual recover and separate verify clear it. Journal success alone
cannot clear a native latch. Existing `finish`/`released` signatures remain unchanged:
trusted `prepare` can snapshot validated SAME Journal origin under its existing
lock to match original native transaction identity; current release context target
remains the recovered target, never the original failed candidate. No bearer is
persisted, logged, regenerated, reconnected or exposed to child processes here.

These tests exercise synthetic callbacks only. Native private result validation,
actual settlement, durable restriction and authenticated controller mapping require
separate exact-head review and the genuine root-owned coupled fixture.

## Protected selector responsibilities

| Context kind | Protected authority target |
| --- | --- |
| deploy | Authenticated qualified-latest candidate, or older exact grant |
| reconcile | Recorded verified target, recover plus verify |
| verified-rollback (including interrupted intent) | Recorded baseline target, recover plus verify |
| resume | Exact current identity AND current Journal CAS; own resume plus verify grants |
| reconcile-release | Exact current identity AND current Journal CAS; own reconcile-release plus verify grants |

Standing baseline consent cannot authorize reconciliation to a different verified
identity. Standing verification cannot substitute for exact resume/release verify.
The controller's version-2 finite grant wrapper supports coexisting grants, rejects
duplicates and lets any matching denial veto matching allows. The Journal never
synthesizes these permissions. Resume checks current identity, retained evidence,
actual qualified runtime verification and current authority under lock. Release
reconciliation additionally verifies the loaded complete cohort and independently
matched native release; callback data alone is not consent.

## Verification and limits

`fork-journal.yml` runs Linux-only mocked unit tests with JUnit evidence and no
scheduled/live mutation. Coverage includes baseline rotation, failed third target,
interrupted rollback direction, exact CAS races, reservation/write crashes, typed
busy, unknown BEGIN, release-loss/no-replay, strict schema, retained artifacts,
revocation and explicit resume/release authority. Old controller adapters default
to hold until their separately owned context/native integration is supplied.
The root-owned genuine coupled fixture remains separate acceptance work.

Prior art: [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html), read
for durable intent and commit-point distinctions; this implementation retains its
existing file-fsync, atomic replace and directory-fsync writer, not SQLite or a
second journal engine. Its filesystem/durability assumptions remain applicable.
