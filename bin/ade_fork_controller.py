"""ADE fork controller v1. Production native execution deliberately unsupported.

Only trusted in-process ports can exercise transactions until native status,
reservation and genuine execution-host qualification are integrated.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
import io
import os
from pathlib import Path
import pwd
import re
import stat
import selectors
import time
import subprocess
import tempfile
import zipfile

from ade_fork_ci import Evaluation, GitHubEvaluation
from ade_fork_release import Adapters, ContractError, Journal, Receipt, canonical, digest, parse, validate
from ade_fork_plugins import inspect, payload_tree_hash, qualify, stage
from ade_forks import load_policy

LIMIT = 96 * 1024 * 1024
MEMBERS = {'receipt.json', 'snapshot.json', 'evaluator-evidence.json'}
OPERATIONS = {'enroll', 'preflight', 'stage', 'activate', 'verify', 'recover', 'retain'}
FIELDS = {'schema_version', 'component', 'channel', 'repository', 'repository_id',
          'cohort', 'policy', 'expected', 'evaluation', 'operations', 'previous',
          'generation', 'master_commit', 'evidence'}


def locations():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    root = home / '.local/state/djbclark-ade/forks'
    return root / 'controller.json', root


def read_regular(path: Path, limit=LIMIT) -> bytes:
    """Descriptor traversal rejects links/specials before blocking or reading."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ContractError('unsafe local path')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            os.close(parent); parent = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                    before.st_mode & 0o022 or before.st_size > limit):
                raise ContractError('unsafe local evidence file')
            chunks = bytearray()
            while len(chunks) <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - len(chunks)))
                if not chunk: break
                chunks.extend(chunk)
            after = os.fstat(fd)
            if len(chunks) > limit or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ContractError('unstable or excessive local evidence')
            return bytes(chunks)
        finally: os.close(fd)
    finally: os.close(parent)


def enrollment(encoded: bytes, registry: list[dict]) -> dict:
    row = parse(encoded.decode('utf-8'))
    if type(row) is not dict or set(row) != FIELDS or type(row['schema_version']) is not int or row['schema_version'] != 1:
        raise ContractError('unsupported controller enrollment')
    if row['component'] != 'ade-yolo' or row['channel'] != 'master' or row['repository'] != 'djbclark/djbclark-ade':
        raise ContractError('unsupported controller pilot')
    if type(row['repository_id']) is not int or row['repository_id'] <= 0:
        raise ContractError('invalid enrolled repository')
    if type(row['generation']) is not int or row['generation'] < 0:
        raise ContractError('invalid deployment generation')
    for key in ('previous', 'master_commit'):
        pattern = r'[a-f0-9]{64}' if key == 'previous' else r'[a-f0-9]{40}|[a-f0-9]{64}'
        if type(row[key]) is not str or not re.fullmatch(pattern, row[key]):
            raise ContractError('invalid enrollment identity')
    cohort = row['cohort']
    required = {cid for item in registry if item['compatibility_group'] == 'paseo-runtime' for cid in item['catalog_ids']}
    if type(cohort) is not dict or set(cohort) != required or not required or any(not isinstance(v, dict) or not v for v in cohort.values()):
        raise ContractError('complete protected cohort required')
    policy = row['policy']
    features = {feature for item in registry if item['compatibility_group'] == 'paseo-runtime' for feature in item['required_features']}
    if (type(policy) is not dict or policy.get('compatibility_group') != 'paseo-runtime' or
            type(policy.get('features')) is not dict or not features <= set(policy['features'])):
        raise ContractError('complete protected feature policy required')
    expected = row['expected']
    if type(expected) is not dict or expected.get('component') != 'ade-yolo' or expected.get('fork_commit') != row['master_commit']:
        raise ContractError('wrong protected source')
    if type(expected.get('dependencies')) is not dict or not required <= set(expected['dependencies']):
        raise ContractError('complete dependency closure required')
    if type(row['evidence']) is not dict or not row['evidence']:
        raise ContractError('protected evaluator evidence required')
    ev = evaluation(row)
    if expected.get('authority') != 'protected-ci' or expected.get('evaluator') != ev.evaluator_commit:
        raise ContractError('protected evaluator identity mismatch')
    ops = row['operations']
    if type(ops) is not dict or set(ops) - OPERATIONS:
        raise ContractError('invalid operation consent')
    for operation, consent in ops.items():
        if (type(consent) is not dict or set(consent) != {'allowed', 'identity', 'generation'} or
                type(consent['allowed']) is not bool or type(consent['generation']) is not int or
                consent['generation'] != row['generation'] or not isinstance(consent['identity'], str) or
                not re.fullmatch('[a-f0-9]{64}', consent['identity'])):
            raise ContractError('invalid scoped consent')
    return row


def evaluation(row):
    fields = dict(row['evaluation'])
    if type(fields.get('jobs')) is not list:
        raise ContractError('invalid evaluator jobs')
    fields['jobs'] = tuple(fields['jobs'])
    try: return Evaluation(**fields)
    except TypeError as error: raise ContractError('invalid evaluator expectations') from error


def read_enrollment():
    path, _ = locations()
    return enrollment(read_regular(path, 1024 * 1024), load_policy())


def unpack_archive(archive: bytes) -> tuple[Receipt, bytes, dict]:
    """Verify all central-directory entries first; never extract paths to disk."""
    if len(archive) > LIMIT:
        raise ContractError('archive exceeds bound')
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            infos = z.infolist()
            if len(infos) != len(MEMBERS) or {i.filename for i in infos} != MEMBERS:
                raise ContractError('unexpected or duplicate archive members')
            total = 0
            for info in infos:
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if (info.is_dir() or info.flag_bits & 1 or kind not in (0, stat.S_IFREG) or
                        info.file_size > LIMIT or info.compress_size > LIMIT or
                        info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ContractError('unsafe archive entry')
                total += info.file_size
            if total > LIMIT:
                raise ContractError('archive expansion exceeds bound')
            data = {}
            for info in infos:
                with z.open(info) as source:
                    content = source.read(min(info.file_size, LIMIT) + 1)
                    if len(content) != info.file_size:
                        raise ContractError('archive content length mismatch')
                    data[info.filename] = content
            receipt = Receipt(data['receipt.json'])
            if canonical(parse(receipt.encoded.decode())) != receipt.encoded:
                raise ContractError('noncanonical receipt')
            inspect(data['snapshot.json'])
            evidence = parse(data['evaluator-evidence.json'].decode())
            if type(evidence) is not dict:
                raise ContractError('invalid evaluator evidence')
            return receipt, data['snapshot.json'], evidence
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeError) as error:
        raise ContractError('invalid archive') from error


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077 or path.resolve() != path:
        raise ContractError('private store required')


def immutable(path, content):
    private_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix='.retain-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content); f.flush(); os.fchmod(f.fileno(), 0o444); os.fsync(f.fileno())
        try: os.link(name, path)
        except FileExistsError:
            if read_regular(path) != content: raise ContractError('retained identity corruption')
        sync_dir(path.parent)
    finally: os.unlink(name)


def coherent_native_status(value, plugin_id):
    """Consumer for proposed ManagedPluginStatus v1; observations grant no support."""
    if (type(value) is not dict or value.get('version') != 1 or value.get('pluginId') != plugin_id or
            value.get('consistency') != 'coherent'):
        raise ContractError('native status uncertain')
    registration, journal, loaded = (value.get(key) for key in ('registration', 'journal', 'loaded'))
    if (type(registration) is not dict or type(journal) is not dict or type(loaded) is not dict or
            type(journal.get('generation')) is not int or journal['generation'] < 0 or
            journal.get('phase') not in ('ready', 'activating', 'replacing', 'held') or
            type(journal.get('baseline')) is not dict or type(journal.get('currentReceipt')) is not dict):
        raise ContractError('native status incomplete')
    # Native CAS is exclusively journal.generation, never loaded.activationGeneration.
    return value


class NativeFacade:
    """No mutating CLI fallback: incomplete native status cannot grant support."""
    def supported(self): return False

    def list_observations(self):
        with subprocess.Popen(['paseo', 'plugin', 'ls', '--json'], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as proc:
            deadline = time.monotonic() + 30
            data = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ContractError('native observation timed out')
                        chunk = os.read(proc.stdout.fileno(), min(65536, 1024 * 1024 + 1 - len(data)))
                        if not chunk: break
                        data.extend(chunk)
                        if len(data) > 1024 * 1024: raise ContractError('native observation too large')
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise ContractError('native observation timed out')
                try: code = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired as error: raise ContractError('native observation timed out') from error
                if code: raise ContractError('native observation failed')
                return parse(data.decode())
            finally:
                if proc.poll() is None: proc.kill()
                proc.wait()



class Controller:
    """Ports are trusted in-process injection ONLY. CLI cannot select a port."""
    def __init__(self, reader=read_enrollment, evaluator=None, native=None, root=None):
        self.reader = reader
        self.evaluator = evaluator or GitHubEvaluation()
        self.native = native or NativeFacade()
        self.root = Path(root) if root is not None else locations()[1]

    def plan(self):
        row = self.reader()
        return {'status': 'planned', 'component': row['component'], 'channel': row['channel'],
                'source': row['master_commit'], 'generation': row['generation'],
                'authorized': False, 'native_supported': self.native.supported() is True,
                'reason': 'protected_candidate_only_no_live_discovery'}

    def discover_master(self):
        """Read-only channel signal; cannot promote a newly observed head by itself."""
        row = self.reader()
        repo = self.evaluator.api('repos/' + row['repository'])
        if type(repo) is not dict or repo.get('id') != row['repository_id']:
            raise ContractError('channel repository mismatch')
        ref = self.evaluator.api('repos/' + row['repository'] + '/git/ref/heads/master')
        if (type(ref) is not dict or ref.get('ref') != 'refs/heads/master' or
                type(ref.get('object')) is not dict or ref['object'].get('type') != 'commit' or
                not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', ref['object'].get('sha', ''))):
            raise ContractError('invalid channel head')
        head = ref['object']['sha']
        return {'discovered': head, 'protected_candidate': row['master_commit'],
                'status': 'candidate_current' if head == row['master_commit'] else 'hold',
                'reason': 'exact_candidate' if head == row['master_commit'] else 'new_head_requires_protected_evaluation',
                'authorized': False}

    def permits(self, row, operation, identity):
        current = self.reader()
        if canonical(current) != canonical(row): return False
        grant = current['operations'].get(operation)
        return (type(grant) is dict and grant['allowed'] is True and
                grant['identity'] == identity and grant['generation'] == current['generation'])

    def acquire(self, row):
        ev = evaluation(row)
        if not self.permits(row, 'retain', ev.receipt_sha256):
            raise ContractError('retention consent absent')
        private_directory(self.root)
        private_directory(self.root / 'archives')
        verified = self.evaluator.verify(ev, self.root / 'archives')
        archive = read_regular(verified.archive)
        if hashlib.sha256(archive).hexdigest() != ev.archive_sha256:
            raise ContractError('archive substituted after authentication')
        receipt, payload, evidence = unpack_archive(archive)
        if verified.authenticates(receipt) is not True:
            raise ContractError('receipt not authenticated')
        if qualify(payload, row['component'], receipt, row['expected'], row['policy'], verified,
                   evidence, row['evidence']) != 'QUALIFIED':
            raise ContractError('plugin qualification held')
        # Complete core validation is required even if qualify later changes its HOLD ordering.
        validate(receipt, row['expected'], row['policy'], artifact=payload)
        if not self.permits(row, 'retain', receipt.sha256):
            raise ContractError('retention consent changed')
        record = {'receipt': base64.b64encode(receipt.encoded).decode(),
                  'payload_sha256': hashlib.sha256(payload).hexdigest(),
                  'expected': row['expected'], 'policy': row['policy'], 'cohort': row['cohort'],
                  'evaluation': row['evaluation'], 'evidence': evidence}
        immutable(self.root / 'payloads' / record['payload_sha256'], payload)
        immutable(self.root / 'records' / (receipt.sha256 + '.json'), canonical(record))
        return receipt, payload, verified

    def retained(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity): return False
        try:
            record = parse(read_regular(self.root / 'records' / (identity + '.json')).decode())
            receipt = Receipt(base64.b64decode(record['receipt'], validate=True))
            if receipt.sha256 != identity: return False
            payload = read_regular(self.root / 'payloads' / record['payload_sha256'])
            if hashlib.sha256(payload).hexdigest() != record['payload_sha256']: return False
            validate(receipt, record['expected'], record['policy'], artifact=payload)
            inspect(payload)
            return True
        except (OSError, ValueError, KeyError, TypeError): return False

    def adapters(self, row, verified):
        native = self.native
        if native.supported() is not True: raise ContractError('native execution producer/status/reservation unsupported')
        def record(identity):
            if not self.retained(identity): raise ContractError('retained evidence unavailable')
            return parse(read_regular(self.root / 'records' / (identity + '.json')).decode())
        def staging(identity, payload):
            r = record(identity)
            if hashlib.sha256(payload).hexdigest() != r['payload_sha256']: raise ContractError('staging substitution')
            stage(payload, self.root / 'snapshots', payload_tree_hash(payload))
        return Adapters(
            observe=lambda: native.observe(row['cohort']),
            preflight=lambda identity: native.preflight(record(identity)),
            stage=staging,
            activate=lambda identity: native.activate(identity, record(identity)),
            verify=lambda identity: native.verify(identity, record(identity)),
            recover=lambda identity: native.recover(identity, record(identity)),
            retained=self.retained,
            authority=lambda operation, identity: self.permits(row, operation, identity),
            authenticate=verified.authenticates if verified is not None else lambda receipt: False,
            policy=lambda: self.reader()['policy'], reserve=native.reserve)

    def tick(self, operation='plan'):
        row = self.reader()
        if operation == 'plan': return self.plan()
        # No acquisition, staging, journal or native mutations on unsupported runtime.
        if self.native.supported() is not True:
            return {'status': 'hold', 'reason': 'native_execution_status_reservation_unsupported', 'authorized': False}
        journal = Journal(self.root / 'journal', row['policy']['compatibility_group'])
        if operation == 'recover':
            # Recovery never depends on candidate CI availability or current candidate retention consent.
            adapters = self.adapters(row, None)
            return asdict(journal.recover(adapters, generation=row['generation']))
        receipt, payload, verified = self.acquire(row)
        adapters = self.adapters(row, verified)
        if operation == 'enroll':
            journal.enroll(receipt.sha256, adapters)
            return {'status': 'enrolled', 'identity': receipt.sha256, 'authorized': False}
        if operation != 'deploy': raise ContractError('unsupported operation')
        return asdict(journal.deploy(receipt, row['expected'], row['policy'], payload, adapters,
                                    previous=row['previous'], generation=row['generation'], migration='binary_only'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'plan', 'tick'))
    args = parser.parse_args(argv)
    try:
        # Shipped tick is read-only planning. No CLI deploy/enroll/port override exists.
        result = Controller().plan()
        if args.command == 'status': result['status'] = 'hold'; result['reason'] = 'native_execution_status_reservation_unsupported'
        print(canonical(result).decode()); return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(canonical({'status': 'hold', 'reason': type(error).__name__, 'authorized': False}).decode()); return 1


if __name__ == '__main__': raise SystemExit(main())
