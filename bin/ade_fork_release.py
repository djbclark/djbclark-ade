"""Qualification evidence and local binary-only deployment core; no live adapters."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
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


@dataclass
class Adapters:
    """All callbacks are trusted in-process code, never deserialized from records."""
    observe: Callable[[], str]
    preflight: Callable[[str], bool]
    stage: Callable[[str, bytes], None]
    activate: Callable[[str], None]
    verify: Callable[[str], bool]
    recover: Callable[[str], None]
    retained: Callable[[str], bool]
    authority: Callable[[str, str], bool] = lambda operation, identity: False
    authenticate: Callable[[Receipt], bool] = lambda receipt: False
    policy: Callable[[], dict] = lambda: {}
    reserve: Callable | None = None


class Journal:
    """One private local directory per compatibility group; no remote filesystems."""
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
        if type(row.get('generation')) is not int or row['generation'] < 0:
            raise ContractError('invalid generation')
        if not isinstance(row.get('verified'), str) or not row['verified']:
            raise ContractError('missing verified identity')
        if type(row.get('state')) is not str or row['state'] not in {'runtime_verified', 'preflight', 'stage', 'activate', 'verify', 'recover', 'recovery_required'}:
            raise ContractError('invalid journal state')
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
        """Explicit initial enrollment, never infer installed identity from a receipt."""
        with self.locked():
            if self.path.exists():
                raise ContractError('already enrolled')
            if adapters.authority('enroll', verified) is not True or adapters.observe() != verified or adapters.retained(verified) is not True:
                raise ContractError('enrollment evidence missing')
            self.write({'group': self.group, 'generation': 0, 'verified': verified,
                        'state': 'runtime_verified', 'candidate': None})

    def deploy(self, receipt: Receipt, expected: dict, policy: dict, artifact: bytes,
               adapters: Adapters, *, previous: str, generation: int,
               migration: str = 'unsupported', dry_run: bool = False) -> Result:
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
            def result(status, reason):
                return Result(status, reason, row['generation'])
            if row['generation'] != generation or row['verified'] != previous:
                return result('hold', 'stale_job')
            if row['state'] != 'runtime_verified':
                # Observe even on retry, but never blindly repeat an uncertain callback.
                adapters.observe()
                return result('recovery_required', 'unfinished_transaction')
            if adapters.observe() != previous:
                return result('recovery_required', 'runtime_drift')
            if migration != 'binary_only':
                return result('hold', 'unsafe_migration')
            if adapters.authenticate(receipt) is not True:
                return result('hold', 'unauthenticated_evidence')
            if adapters.reserve is None:
                return result('hold', 'reservation_required')
            if adapters.retained(previous) is not True:
                return result('hold', 'recovery_artifact_missing')
            # Reservation remains held through policy recheck, activation and verification.
            with adapters.reserve() as reserved:
                if reserved is not True:
                    return result('hold', 'busy')
                for operation in ('preflight', 'stage', 'activate', 'verify'):
                    if adapters.authority(operation, target) is not True:
                        return result('hold', 'permission_' + operation)
                if canonical(adapters.policy()) != canonical(policy):
                    return result('hold', 'policy_changed')
                row.update(generation=generation + 1, candidate=target)
                try:
                    for operation in ('preflight', 'stage', 'activate', 'verify'):
                        if adapters.authority(operation, target) is not True:
                            row['state'] = 'recovery_required'
                            self.write(row)
                            return result('recovery_required', 'authority_revoked')
                        if operation == 'activate':
                            if canonical(adapters.policy()) != canonical(policy) or adapters.observe() != previous or adapters.retained(previous) is not True:
                                row['state'] = 'recovery_required'
                                self.write(row)
                                return result('recovery_required', 'activation_precondition_changed')
                        row['state'] = operation
                        self.write(row)  # durable intent before every callback
                        if operation == 'stage':
                            adapters.stage(target, artifact)
                        elif operation == 'activate':
                            adapters.activate(target)
                        elif getattr(adapters, operation)(target) is not True:
                            raise ContractError(operation + ' refused')
                    if adapters.observe() != target or adapters.retained(target) is not True:
                        raise ContractError('runtime or retained artifact mismatch')
                    success = dict(row, state='runtime_verified', verified=target, candidate=None)
                    self.write(success)
                    return result('runtime_verified', 'verified')
                except Exception:
                    row['state'] = 'recovery_required'
                    self.write(row)
                    # Observation is evidence only; never convert lost ack to success.
                    try:
                        adapters.observe()
                    except Exception:
                        pass
                    return result('recovery_required', 'callback_or_journal_failure')

    def recover(self, adapters: Adapters, *, generation: int) -> Result:
        """Explicit safe binary recovery to last verified identity, new generation."""
        with self.locked():
            row = self.read()
            target = row['verified']
            if row['generation'] != generation:
                return Result('hold', 'stale_job', row['generation'])
            adapters.observe()  # required independent inspection, even after a crash
            if adapters.authority('recover', target) is not True or adapters.authority('verify', target) is not True or adapters.reserve is None or adapters.retained(target) is not True:
                return Result('hold', 'recovery_not_authorized_or_available', generation)
            with adapters.reserve() as reserved:
                if reserved is not True:
                    return Result('hold', 'busy', generation)
                if adapters.authority('recover', target) is not True or adapters.authority('verify', target) is not True or adapters.retained(target) is not True:
                    return Result('hold', 'recovery_revoked', generation)
                row.update(state='recover', generation=generation + 1)
                self.write(row)
                try:
                    adapters.recover(target)
                    if adapters.authority('verify', target) is not True or adapters.observe() != target or adapters.verify(target) is not True:
                        raise ContractError('recovery verification failed')
                    row.update(state='runtime_verified', candidate=None)
                    self.write(row)
                    return Result('runtime_verified', 'recovered', row['generation'])
                except Exception:
                    row['state'] = 'recovery_required'
                    self.write(row)
                    return Result('recovery_required', 'recovery_failed', row['generation'])
