"""Qualification evidence and local binary-only deployment core; no live adapters."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Callable


class ContractError(ValueError):
    """Malformed input, invalid evidence, or corrupt journal; no implicit repair."""


def canonical(value) -> bytes:
    """Version-1 canonical JSON: exact JSON types, sorted keys, UTF-8, no NaN."""
    def check(v):
        if type(v) in (str, int, bool, type(None)):
            return
        if type(v) is float and math.isfinite(v):
            return
        if type(v) is list:
            for item in v:
                check(item)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for item in v.values():
                check(item)
            return
        raise ContractError('not finite JSON')
    try:
        check(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as e:
        raise ContractError('not finite JSON') from e


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def parse(data: str) -> object:
    """Strict JSON decoder, including duplicate-key rejection."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError('duplicate key')
            result[key] = value
        return result
    try:
        result = json.loads(data, object_pairs_hook=pairs)
        canonical(result)
        return result
    except (ValueError, TypeError, RecursionError) as e:
        raise ContractError('invalid JSON') from e


FIELDS = {'schema_version', 'component', 'upstream_commit', 'fork_commit',
          'dependencies', 'patch_manifest_digest', 'applied_patches',
          'recipe_revision', 'platform', 'toolchain', 'artifact_sha256',
          'policy_digest', 'feature_contract_digest', 'authority', 'evaluator'}


def _expected(expected, policy):
    canonical(expected)
    canonical(policy)
    if type(expected) is not dict or set(expected) != FIELDS:
        raise ContractError('expected bindings must be complete')
    if type(expected['schema_version']) is not int or expected['schema_version'] != 1:
        raise ContractError('unsupported schema')
    if type(policy) is not dict or not isinstance(policy.get('features'), dict) or not policy['features']:
        raise ContractError('trusted feature contract required')
    if any(not isinstance(k, str) or not k or not v for k, v in policy['features'].items()):
        raise ContractError('empty feature contract')
    if expected['policy_digest'] != digest(policy) or expected['feature_contract_digest'] != digest(policy['features']):
        raise ContractError('trusted policy binding mismatch')
    for key in FIELDS - {'schema_version', 'dependencies', 'applied_patches'}:
        if type(expected[key]) is not str or not expected[key]:
            raise ContractError('empty binding: ' + key)
    for key in ('upstream_commit', 'fork_commit'):
        if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', expected[key]):
            raise ContractError('invalid commit')
    deps = expected['dependencies']
    if type(deps) is not dict or any(not k or type(v) is not str or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', v) for k, v in deps.items()):
        raise ContractError('invalid dependencies')
    patches = expected['applied_patches']
    if type(patches) is not list or any(type(p) is not str or not p for p in patches) or len(set(patches)) != len(patches):
        raise ContractError('invalid patch identities')
    for key in ('artifact_sha256', 'policy_digest', 'patch_manifest_digest', 'feature_contract_digest'):
        if not re.fullmatch('[0-9a-f]{64}', expected[key]):
            raise ContractError('invalid digest')


@dataclass(frozen=True)
class Receipt:
    """Immutable encoded content, not an authentication credential."""
    encoded: bytes

    def __post_init__(self):
        if type(self.encoded) is not bytes:
            raise ContractError('receipt must contain immutable bytes')

    @property
    def sha256(self):
        return hashlib.sha256(self.encoded).hexdigest()


def make_receipt(bindings: dict, policy: dict, results: dict) -> Receipt:
    """Evaluator-side encoding only; does NOT authenticate results."""
    _expected(bindings, policy)
    return Receipt(canonical({'bindings': bindings, 'results': results}))


def validate(receipt: Receipt, expected: dict, policy: dict, *,
             artifact: bytes | None = None, artifact_digest: str | None = None) -> None:
    """Pure exact binding check. Caller must separately authenticate CI evidence."""
    _expected(expected, policy)
    try:
        record = parse(receipt.encoded.decode('utf-8'))
    except UnicodeError as e:
        raise ContractError('invalid receipt UTF-8') from e
    if canonical(record) != receipt.encoded or type(record) is not dict or set(record) != {'bindings', 'results'}:
        raise ContractError('noncanonical receipt')
    if canonical(record['bindings']) != canonical(expected):
        raise ContractError('binding mismatch')
    wanted = {key: {'contract_digest': digest(contract), 'status': 'passed'}
              for key, contract in policy['features'].items()}
    if canonical(record['results']) != canonical(wanted):
        raise ContractError('feature evidence mismatch')
    if artifact is None and artifact_digest is None:
        raise ContractError('artifact evidence required')
    if artifact is not None and hashlib.sha256(artifact).hexdigest() != expected['artifact_sha256']:
        raise ContractError('artifact mismatch')
    if artifact_digest is not None and artifact_digest != expected['artifact_sha256']:
        raise ContractError('artifact digest mismatch')


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    generation: int


@dataclass(frozen=True)
class TransactionContext:
    schema_version: int
    group: str
    kind: str
    cas_generation: int
    generation: int
    transaction_id: str
    verified: str
    baseline: str | None
    target: str
    rule_digest: str


@dataclass(frozen=True)
class ReservationIntent:
    """Nonsecret independent native maintenance and plugin journal counters."""
    native_generation: int
    plugin_generation: int
    server_id: str
    daemon_incarnation: str


@dataclass(frozen=True)
class BeginResult:
    """Trusted adapter classification; busy requires authoritative typed refusal."""
    status: str


@dataclass(frozen=True)
class KnownFailedHeld:
    """Descriptive trusted-adapter observation, never a native execution brand."""
    reason: str
    plugin_generation: int


@dataclass
class Adapters:
    """Trusted orchestration callbacks, never serialized grants/execution brands.

    prepare binds current protected rule/context and reads coherent native counters.
    reserve returns BeginResult only; it must never infer busy from generic errors.
    finish sends END only after durable release intent. released observes independently.
    Tokens remain private to the adapter, never in these objects or the Journal.
    """
    observe: Callable[[], str]
    preflight: Callable[[str], bool]
    stage: Callable[[str, bytes], None]
    activate: Callable[[str], KnownFailedHeld | None]
    verify: Callable[[str], bool]
    recover: Callable[[str], KnownFailedHeld | None]
    retained: Callable[[str], bool]
    authority: Callable[[str, str], bool] = lambda operation, identity: False
    authenticate: Callable[[Receipt], bool] = lambda receipt: False
    policy: Callable[[], dict] = lambda: {}
    reserve: Callable | None = None
    prepare: Callable | None = None
    finish: Callable | None = None
    released: Callable | None = None
    reuse: Callable | None = None


def _identity(value):
    return type(value) is str and 0 < len(value) <= 1024 and not any(ord(c) < 32 for c in value)


def _context(value):
    try:
        c = TransactionContext(**value)
    except (TypeError, ValueError) as error:
        raise ContractError('invalid transaction context') from error
    if (type(c.schema_version) is not int or c.schema_version != 1 or
            type(c.kind) is not str or c.kind not in {'deploy', 'reconcile', 'verified-rollback', 'resume', 'reconcile-release'} or
            any(not _identity(v) for v in (c.group, c.verified, c.target)) or
            (c.baseline is not None and not _identity(c.baseline)) or
            type(c.cas_generation) is not int or c.cas_generation < 0 or
            type(c.generation) is not int or c.generation != c.cas_generation + 1 or
            type(c.transaction_id) is not str or not re.fullmatch('[a-f0-9]{32}', c.transaction_id) or
            type(c.rule_digest) is not str or not re.fullmatch('[a-f0-9]{64}', c.rule_digest)):
        raise ContractError('invalid transaction context')
    return c


def _reservation(value):
    try:
        r = ReservationIntent(**value)
    except (TypeError, ValueError) as error:
        raise ContractError('invalid reservation intent') from error
    if (type(r.native_generation) is not int or r.native_generation <= 0 or
            type(r.plugin_generation) is not int or r.plugin_generation < 0 or
            not _identity(r.server_id) or not _identity(r.daemon_incarnation)):
        raise ContractError('invalid reservation intent')
    return r


class Journal:
    """One versioned atomic record per compatibility group; never a token ledger."""
    RELEASE_STATES = {'verified_held', 'release_intent', 'release_uncertain'}
    STATES = RELEASE_STATES | {'runtime_verified', 'reservation_intent', 'reservation_unknown',
                              'preflight', 'stage', 'activate', 'verify', 'recover', 'recovery_required', 'known_failed_held'}

    def __init__(self, directory: Path, group: str):
        self.directory = Path(directory)
        self.group = group
        self.path = self.directory / (digest(group) + '.json')

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        if not self.path.exists():
            raise ContractError('journal not enrolled')
        row = parse(self.path.read_text())
        if type(row) is not dict or row.get('group') != self.group:
            raise ContractError('incompatible group')
        if set(row) != {'schema_version', 'group', 'generation', 'verified', 'baseline',
                        'state', 'candidate', 'transaction', 'promotion_hold'} or type(row['schema_version']) is not int or row['schema_version'] != 2:
            raise ContractError('unsupported journal schema; explicit enrollment/migration required')
        if type(row['generation']) is not int or row['generation'] < 0:
            raise ContractError('invalid generation')
        if not _identity(row['verified']):
            raise ContractError('missing verified identity')
        if row['baseline'] is not None and (not _identity(row['baseline']) or row['baseline'] == row['verified']):
            raise ContractError('invalid baseline')
        if type(row['promotion_hold']) is not bool:
            raise ContractError('invalid promotion hold')
        if type(row['state']) is not str or row['state'] not in self.STATES:
            raise ContractError('invalid journal state')
        if row['candidate'] is not None and not _identity(row['candidate']):
            raise ContractError('invalid candidate')
        tx = row['transaction']
        if row['state'] == 'runtime_verified':
            if tx is not None or row['candidate'] is not None:
                raise ContractError('unexpected settled transaction')
        else:
            if type(tx) is not dict or set(tx) not in ({'context', 'reservation'}, {'context', 'reservation', 'origin'}):
                raise ContractError('missing transaction intent')
            c, r = _context(tx['context']), _reservation(tx['reservation'])
            if 'origin' in tx:
                origin = tx['origin']
                if type(origin) is not dict or set(origin) != {'context', 'reservation'}:
                    raise ContractError('invalid reservation origin')
                oc, ore = _context(origin['context']), _reservation(origin['reservation'])
                if (oc.group != c.group or oc.generation > c.generation or
                        oc.kind not in {'deploy', 'reconcile', 'verified-rollback'} or
                        oc.verified != c.verified or oc.baseline != c.baseline or
                        ore.native_generation != r.native_generation or ore.server_id != r.server_id or
                        ore.daemon_incarnation != r.daemon_incarnation or ore.plugin_generation > r.plugin_generation):
                    raise ContractError('inconsistent reservation origin')
                if oc.generation == c.generation:
                    if oc != c: raise ContractError('changed original transaction')
                elif c.kind != ('reconcile' if oc.kind == 'deploy' else oc.kind) or c.target != (oc.verified if oc.kind == 'deploy' else oc.target):
                    raise ContractError('changed original recovery direction')
            elif row['state'] == 'known_failed_held':
                raise ContractError('missing confirmed reservation origin')
            if c.group != self.group or c.generation != row['generation'] or row['candidate'] != c.target:
                raise ContractError('inconsistent transaction intent')
            if type(c.kind) is not str or c.kind not in {'deploy', 'reconcile', 'verified-rollback'}:
                raise ContractError('invalid persisted transaction kind')
            if c.kind == 'verified-rollback' and (c.baseline is None or c.target != c.baseline):
                raise ContractError('invalid rollback intent')
            if c.kind == 'reconcile' and c.target != c.verified:
                raise ContractError('invalid reconciliation intent')
            if row['state'] in self.RELEASE_STATES:
                baseline = c.verified if c.kind == 'deploy' else None if c.kind == 'verified-rollback' else c.baseline
                if row['verified'] != c.target or row['baseline'] != baseline:
                    raise ContractError('inconsistent committed identity')
            elif row['verified'] != c.verified or row['baseline'] != c.baseline:
                raise ContractError('inconsistent previous identity')
        return row

    def write(self, row):
        data = canonical(row)
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='.transaction-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def enroll(self, verified: str, adapters: Adapters):
        with self.locked():
            if self.path.exists():
                raise ContractError('already enrolled')
            if not _identity(verified) or adapters.authority('enroll', verified) is not True or adapters.observe() != verified or adapters.retained(verified) is not True:
                raise ContractError('enrollment evidence missing')
            self.write({'schema_version': 2, 'group': self.group, 'generation': 0,
                        'verified': verified, 'baseline': None, 'state': 'runtime_verified',
                        'candidate': None, 'transaction': None, 'promotion_hold': False})

    def _new_context(self, row, kind, target, rule_digest):
        return _context(dict(schema_version=1, group=self.group, kind=kind,
                             cas_generation=row['generation'], generation=row['generation'] + 1,
                             transaction_id=uuid.uuid4().hex, verified=row['verified'],
                             baseline=row['baseline'], target=target, rule_digest=rule_digest))

    @staticmethod
    def _hooks(adapters, rule_digest):
        return (all(callable(f) for f in (adapters.prepare, adapters.reserve, adapters.finish)) and
                type(rule_digest) is str and re.fullmatch('[a-f0-9]{64}', rule_digest) is not None)

    def _begin(self, row, adapters, context, policy=None):
        """Plan is read-only. No BEGIN until its exact nonsecret intent is durable."""
        intent = adapters.prepare(context)
        if type(intent) is not ReservationIntent:
            raise ContractError('reservation plan required')
        _reservation(asdict(intent))
        operations = ('preflight', 'stage', 'activate', 'verify') if context.kind == 'deploy' else ('recover', 'verify')
        for operation in operations:
            if adapters.authority(operation, context.target) is not True:
                raise ContractError('permission_' + operation)
        retained = context.verified if context.kind == 'deploy' else context.target
        if adapters.retained(retained) is not True:
            raise ContractError('recovery_artifact_missing')
        if policy is not None and canonical(adapters.policy()) != canonical(policy):
            raise ContractError('policy_changed')
        close_on_busy = row['state'] == 'runtime_verified'
        row.update(generation=context.generation, candidate=context.target,
                   transaction={'context': asdict(context), 'reservation': asdict(intent)},
                   state='reservation_intent')
        self.write(row)
        try:
            result = adapters.reserve(context, intent)
            if type(result) is not BeginResult or result.status not in {'held', 'busy'}:
                raise ContractError('native begin uncertain')
        except Exception:
            row['state'] = 'reservation_unknown'
            self.write(row)
            return None
        if result.status == 'busy':
            # Only typed no-transition refusal can close an unstarted attempt.
            if close_on_busy:
                row.update(state='runtime_verified', candidate=None, transaction=None)
            else:
                row['state'] = 'recovery_required'
            self.write(row)
            return False
        return True

    def _known_failed(self, row, observation):
        """Only a normal exact typed adapter return can describe confirmed failure."""
        if (type(observation) is not KnownFailedHeld or type(observation.reason) is not str or
                observation.reason not in {'compiler_error', 'initialization_rejected'} or
                type(observation.plugin_generation) is not int or
                not 0 <= observation.plugin_generation <= 2**53 - 1):
            raise ContractError('unconfirmed native outcome')
        tx = row['transaction']
        original = tx.get('origin', {'context': tx['context'], 'reservation': tx['reservation']})
        current = _reservation(tx['reservation'])
        if observation.plugin_generation < current.plugin_generation:
            raise ContractError('stale known failure CAS')
        # Preserve the BEGIN context/intent before rotating only the plugin CAS.
        row['transaction'] = dict(tx, origin=original, reservation=asdict(ReservationIntent(
            current.native_generation, observation.plugin_generation, current.server_id, current.daemon_incarnation)))
        row['state'] = 'known_failed_held'
        self.write(row)
        return Result('known_failed_held', observation.reason, row['generation'])

    def _reuse(self, row, adapters, context):
        """No BEGIN, token reconstruction or fallback on any same-held failure."""
        if not callable(adapters.reuse): raise ContractError('same_held_reuse_required')
        origin = row['transaction']['origin']
        original_context = _context(origin['context'])
        original_intent = _reservation(origin['reservation'])
        current = _reservation(row['transaction']['reservation'])
        intent = adapters.prepare(context)
        if type(intent) is not ReservationIntent: raise ContractError('reservation plan required')
        _reservation(asdict(intent))
        if (intent != current or intent.native_generation != original_intent.native_generation or
                intent.server_id != original_intent.server_id or intent.daemon_incarnation != original_intent.daemon_incarnation):
            raise ContractError('same_held_identity_or_CAS_changed')
        if any(adapters.authority(op, context.target) is not True for op in ('recover', 'verify')) or adapters.retained(context.target) is not True:
            raise ContractError('same_held_recovery_not_authorized')
        row.update(generation=context.generation, candidate=context.target, state='reservation_intent',
                   transaction={'context': asdict(context), 'reservation': asdict(intent), 'origin': origin})
        self.write(row)
        try:
            outcome = adapters.reuse(context, intent, original_context, original_intent)
            if type(outcome) is not BeginResult or outcome.status != 'held':
                raise ContractError('same held owner unconfirmed')
        except Exception:
            row['state'] = 'reservation_unknown'
            self.write(row)
            return None
        return True

    def _release(self, row, adapters, context):
        intent = _reservation(row['transaction']['reservation'])
        # No unauthorized release after verification waits; this state never rolls back.
        if (adapters.authority('verify', context.target) is not True or
                adapters.retained(context.target) is not True or adapters.observe() != context.target or
                adapters.verify(context.target) is not True or
                adapters.authority('verify', context.target) is not True):
            return Result('hold', 'verified_release_not_authorized', row['generation'])
        # A crash/write failure from here is release reconciliation, never rollback.
        row['state'] = 'release_intent'
        self.write(row)
        try:
            if adapters.finish(context, intent) is not True:
                raise ContractError('release acknowledgement uncertain')
            settled = dict(row, state='runtime_verified', candidate=None, transaction=None)
            self.write(settled)
        except Exception:
            row['state'] = 'release_uncertain'
            self.write(row)
            return Result('release_uncertain', 'release_not_acknowledged', row['generation'])
        return Result('runtime_verified', 'verified' if context.kind == 'deploy' else 'recovered', row['generation'])

    def deploy(self, receipt: Receipt, expected: dict, policy: dict, artifact: bytes,
               adapters: Adapters, *, previous: str, generation: int,
               migration: str = 'unsupported', dry_run: bool = False,
               rule_digest: str | None = None) -> Result:
        if type(artifact) is not bytes:
            raise ContractError('artifact must be immutable bytes')
        policy = parse(canonical(policy).decode('utf-8'))
        expected = parse(canonical(expected).decode('utf-8'))
        validate(receipt, expected, policy, artifact=artifact)
        if policy.get('compatibility_group') != self.group:
            raise ContractError('incompatible candidate group')
        target = receipt.sha256
        if dry_run:
            return Result('dry_run', 'no callbacks or filesystem changes', generation)
        with self.locked():
            row = self.read()
            def result(status, reason): return Result(status, reason, row['generation'])
            if type(generation) is not int or generation < 0 or row['generation'] != generation or row['verified'] != previous:
                return result('hold', 'stale_job')
            if row['state'] != 'runtime_verified':
                adapters.observe()
                return result('recovery_required', 'unfinished_transaction')
            if row['promotion_hold']:
                return result('hold', 'promotion_hold')
            if target == previous:
                return result('hold', 'already_verified')
            if adapters.observe() != previous:
                return result('recovery_required', 'runtime_drift')
            if migration != 'binary_only': return result('hold', 'unsafe_migration')
            if adapters.authenticate(receipt) is not True: return result('hold', 'unauthenticated_evidence')
            if not self._hooks(adapters, rule_digest): return result('hold', 'reservation_required')
            if adapters.retained(previous) is not True: return result('hold', 'recovery_artifact_missing')
            context = self._new_context(row, 'deploy', target, rule_digest)
            # prepare binds callbacks to the actual locked context, before authority checks.
            try:
                # Initial authority checks happen inside _begin's read-only prepare binding.
                started = self._begin(row, adapters, context, policy)
            except Exception as error:
                return result('hold' if row['state'] == 'runtime_verified' else 'recovery_required', str(error) if isinstance(error, ContractError) else 'reservation_prepare_failed')
            if started is None: return result('recovery_required', 'reservation_unknown')
            if started is False: return result('hold', 'busy')
            native_started = False
            try:
                for operation in ('preflight', 'stage', 'activate', 'verify'):
                    if adapters.authority(operation, target) is not True:
                        raise ContractError('authority_revoked')
                    if canonical(adapters.policy()) != canonical(policy):
                        raise ContractError('policy_changed')
                    if operation == 'activate' and (adapters.observe() != previous or adapters.retained(previous) is not True):
                        raise ContractError('activation_precondition_changed')
                    row['state'] = operation
                    self.write(row)
                    if operation == 'stage': adapters.stage(target, artifact)
                    elif operation == 'activate':
                        native_started = True
                        outcome = adapters.activate(target)
                        if type(outcome) is KnownFailedHeld: return self._known_failed(row, outcome)
                        if outcome is not None: raise ContractError('unconfirmed native outcome')
                    elif getattr(adapters, operation)(target) is not True:
                        raise ContractError(operation + ' refused')
                if adapters.authority('verify', target) is not True or adapters.observe() != target or adapters.retained(target) is not True:
                    raise ContractError('runtime or retained artifact mismatch')
                committed = dict(row, state='verified_held', verified=target, baseline=previous)
                self.write(committed)
            except Exception as error:
                row['state'] = 'reservation_unknown' if native_started else 'recovery_required'
                self.write(row)
                return result('recovery_required', str(error) if isinstance(error, ContractError) else 'callback_or_journal_failure')
            return self._release(committed, adapters, context)

    def recover(self, adapters: Adapters, *, generation: int, rollback_target: str | None = None,
                rule_digest: str | None = None) -> Result:
        with self.locked():
            row = self.read()
            def result(status, reason): return Result(status, reason, row['generation'])
            if type(generation) is not int or generation < 0 or row['generation'] != generation: return result('hold', 'stale_job')
            if row['state'] in self.RELEASE_STATES: return result('hold', 'release_reconciliation_required')
            if row['state'] in {'reservation_intent', 'reservation_unknown', 'activate', 'verify', 'recover'}: return result('hold', 'reservation_unknown')
            if row['state'] == 'runtime_verified':
                if rollback_target is None: return result('hold', 'no_unfinished_transaction')
                if row['baseline'] is None or rollback_target != row['baseline']:
                    return result('hold', 'rollback_target_not_baseline')
                kind, target = 'verified-rollback', rollback_target
            else:
                old = _context(row['transaction']['context'])
                kind = old.kind if old.kind != 'deploy' else 'reconcile'
                target = old.target if old.kind != 'deploy' else old.verified
                if rollback_target is not None and rollback_target != target:
                    return result('hold', 'recovery_direction_conflict')
            if not self._hooks(adapters, rule_digest): return result('hold', 'recovery_not_authorized_or_available')
            context = self._new_context(row, kind, target, rule_digest)
            same_held = row['state'] == 'known_failed_held'
            if 'origin' in (row['transaction'] or {}) and not same_held:
                return result('hold', 'same_held_outcome_not_confirmed')
            try:
                started = self._reuse(row, adapters, context) if same_held else self._begin(row, adapters, context)
            except Exception as error:
                return result('hold', str(error) if isinstance(error, ContractError) else 'reservation_prepare_failed')
            if started is None: return result('recovery_required', 'reservation_unknown')
            if started is False: return result('hold', 'busy')
            try:
                adapters.observe()
                if any(adapters.authority(op, target) is not True for op in ('recover', 'verify')) or adapters.retained(target) is not True:
                    raise ContractError('recovery_not_authorized_or_available')
                row['state'] = 'recover'
                self.write(row)
                outcome = adapters.recover(target)
                if type(outcome) is KnownFailedHeld: return self._known_failed(row, outcome)
                if outcome is not None: raise ContractError('unconfirmed native outcome')
                if adapters.authority('verify', target) is not True or adapters.authority('recover', target) is not True or adapters.observe() != target or adapters.retained(target) is not True or adapters.verify(target) is not True:
                    raise ContractError('recovery verification failed')
                committed = dict(row, state='verified_held', verified=target,
                                 baseline=None if kind == 'verified-rollback' else row['baseline'],
                                 promotion_hold=row['promotion_hold'] or kind == 'verified-rollback')
                self.write(committed)
            except Exception:
                row['state'] = 'reservation_unknown'
                self.write(row)
                return result('recovery_required', 'recovery_failed')
            return self._release(committed, adapters, context)

    def resume(self, adapters: Adapters, *, generation: int, rule_digest: str | None = None) -> Result:
        """Clear rollback promotion hold only under a distinct current explicit grant."""
        with self.locked():
            row = self.read()
            if type(generation) is not int or generation < 0 or row['generation'] != generation: return Result('hold', 'stale_job', row['generation'])
            if row['state'] != 'runtime_verified' or not row['promotion_hold']:
                return Result('hold', 'resume_not_available', row['generation'])
            try:
                c = self._new_context(row, 'resume', row['verified'], rule_digest)
                if not callable(adapters.prepare): raise ContractError('context binding required')
                adapters.prepare(c)  # read-only, never reserve/END
                if any(adapters.authority(op, c.target) is not True for op in ('resume', 'verify')) or adapters.retained(c.target) is not True or adapters.observe() != c.target or adapters.verify(c.target) is not True:
                    raise ContractError('resume not authorized')
                if any(adapters.authority(op, c.target) is not True for op in ('resume', 'verify')) or adapters.retained(c.target) is not True or adapters.observe() != c.target:
                    raise ContractError('resume revoked')
            except Exception:
                return Result('hold', 'resume_not_authorized', row['generation'])
            row.update(generation=c.generation, promotion_hold=False)
            self.write(row)
            return Result('runtime_verified', 'resumed', row['generation'])

    def reconcile_release(self, adapters: Adapters, *, generation: int,
                          rule_digest: str | None = None) -> Result:
        """Observe a matched authorized idle commit; never retry END or binary work."""
        with self.locked():
            row = self.read()
            def result(status, reason): return Result(status, reason, row['generation'])
            if type(generation) is not int or generation < 0 or row['generation'] != generation: return result('hold', 'stale_job')
            if row['state'] not in self.RELEASE_STATES: return result('hold', 'no_release_intent')
            original = _context(row['transaction']['context'])
            intent = _reservation(row['transaction']['reservation'])
            try:
                c = self._new_context(row, 'reconcile-release', original.target, rule_digest)
                if not callable(adapters.prepare) or not callable(adapters.released):
                    raise ContractError('release observation required')
                adapters.prepare(c)
                if any(adapters.authority(op, c.target) is not True for op in ('reconcile-release', 'verify')):
                    raise ContractError('release reconciliation not authorized')
                if adapters.retained(c.target) is not True or adapters.observe() != c.target or adapters.verify(c.target) is not True:
                    raise ContractError('release target not verified')
                if adapters.released(original, intent) is not True:
                    raise ContractError('matched authorized idle not proven')
                if any(adapters.authority(op, c.target) is not True for op in ('reconcile-release', 'verify')) or adapters.retained(c.target) is not True or adapters.observe() != c.target or adapters.verify(c.target) is not True:
                    raise ContractError('release reconciliation revoked')
            except Exception:
                return result('hold', 'release_reconciliation_required')
            row.update(state='runtime_verified', candidate=None, transaction=None, generation=c.generation)
            self.write(row)
            return result('runtime_verified', 'release_reconciled')
