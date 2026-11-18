"""ADE fork controller v1. Production native execution deliberately unsupported.

Only trusted in-process ports can exercise transactions until native status,
reservation and genuine execution-host qualification are integrated.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import stat
import selectors
import time
import subprocess
import sys
import tempfile
import zipfile

from ade_fork_ci import Evaluation, GitHubEvaluation
from ade_fork_release import Adapters, ContractError, Journal, Receipt, canonical, digest, parse, validate
from ade_fork_plugins import inspect, payload_tree_hash, qualify, stage, tree_hash
from ade_forks import load_policy

LIMIT = 96 * 1024 * 1024
MEMBERS = {'receipt.json', 'snapshot.json', 'evaluator-evidence.json'}
OPERATIONS = {'enroll', 'preflight', 'stage', 'activate', 'verify', 'recover', 'retain'}
FIELDS = {'schema_version', 'component', 'channel', 'repository', 'repository_id',
          'cohort', 'policy', 'expected', 'evaluation', 'operations', 'previous',
          'generation', 'master_commit', 'evidence', 'discovery', 'native'}


def locations():
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    root = home / '.local/state/djbclark-ade/forks'
    return root / 'controller.json', root


def read_regular(path: Path, limit=LIMIT, *, owner=None) -> bytes:
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
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != (os.getuid() if owner is None else owner) or
                    before.st_mode & 0o022 or before.st_size > limit):
                raise ContractError('unsafe local evidence file')
            chunks = bytearray()
            while len(chunks) <= limit:
                chunk = os.read(fd, min(65536, limit + 1 - len(chunks)))
                if not chunk: break
                chunks.extend(chunk)
            after = os.fstat(fd)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            keys = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if len(chunks) > limit or any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(current, key) for key in keys):
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
    if type(cohort) is not dict or not required <= set(cohort) or not required or any(not isinstance(v, dict) or not v for v in cohort.values()):
        raise ContractError('complete protected cohort required')
    policy = row['policy']
    features = {feature for item in registry if item['compatibility_group'] == 'paseo-runtime' for feature in item['required_features']}
    if (type(policy) is not dict or policy.get('compatibility_group') != 'paseo-runtime' or
            type(policy.get('features')) is not dict or not features <= set(policy['features'])):
        raise ContractError('complete protected feature policy required')
    expected = row['expected']
    if type(expected) is not dict or expected.get('component') != 'ade-yolo' or expected.get('fork_commit') != row['master_commit']:
        raise ContractError('wrong protected source')
    if type(expected.get('dependencies')) is not dict or not set(cohort) <= set(expected['dependencies']):
        raise ContractError('complete dependency closure required')
    if type(row['evidence']) is not dict or not row['evidence']:
        raise ContractError('protected evaluator evidence required')
    ev = evaluation(row)
    if expected.get('authority') != 'protected-ci' or expected.get('evaluator') != ev.evaluator_commit:
        raise ContractError('protected evaluator identity mismatch')
    native = row['native']
    if native is not None:
        if type(native) is not dict or set(native) != {'node', 'cli', 'serverId', 'daemonIncarnation', 'distributionSha256', 'distributionBuildId', 'distributionRoot', 'closure'}:
            raise ContractError('invalid retained native transport')
        for key in ('node', 'cli'):
            item = native[key]
            if (type(item) is not dict or set(item) != {'path', 'sha256'} or
                    type(item['path']) is not str or not Path(item['path']).is_absolute() or
                    type(item['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
                raise ContractError('invalid retained transport identity')
        for key in ('serverId', 'daemonIncarnation', 'distributionBuildId', 'distributionRoot'):
            if type(native[key]) is not str or not native[key]: raise ContractError('missing native transport identity')
        if type(native['distributionSha256']) is not str or not re.fullmatch('[a-f0-9]{64}', native['distributionSha256']):
            raise ContractError('invalid protected distribution digest')
        closure_identity(native['closure'])
    discovery = row['discovery']
    if (type(discovery) is not dict or set(discovery) != {'enabled', 'artifact_prefix', 'baseline_run_id'} or
            type(discovery['enabled']) is not bool or discovery['artifact_prefix'] != 'ade-yolo-qualified' or
            type(discovery['baseline_run_id']) is not int or discovery['baseline_run_id'] <= 0):
        raise ContractError('invalid protected discovery contract')
    ops = row['operations']
    if type(ops) is not dict or set(ops) - OPERATIONS:
        raise ContractError('invalid operation consent')
    for operation, consent in ops.items():
        if (type(consent) is not dict or set(consent) != {'allowed', 'identity', 'generation'} or
                type(consent['allowed']) is not bool or type(consent['generation']) is not int or
                consent['generation'] != row['generation'] or not isinstance(consent['identity'], str) or
                not (re.fullmatch('[a-f0-9]{64}', consent['identity']) or
                     (consent['identity'] == 'qualified-latest' and operation in {'retain', 'preflight', 'stage', 'activate', 'verify'}))):
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


def coherent_native_status(value, plugin_id, *, allow_target_absent=False):
    """Consumer for proposed ManagedPluginStatus v1; observations grant no support."""
    if (type(value) is not dict or value.get('version') != 1 or value.get('pluginId') != plugin_id or
            value.get('consistency') != 'coherent'):
        raise ContractError('native status uncertain')
    registration, journal, loaded = (value.get(key) for key in ('registration', 'journal', 'loaded'))
    if (type(registration) is not dict or type(journal) is not dict or (type(loaded) is not dict and not (allow_target_absent and loaded is None)) or
            type(journal.get('generation')) is not int or journal['generation'] < 0 or
            journal.get('phase') not in ('ready', 'activating', 'replacing', 'held') or
            type(journal.get('baseline')) is not dict or
            (type(journal.get('currentReceipt')) is not dict and not (allow_target_absent and journal.get('currentReceipt') is None))):
        raise ContractError('native status incomplete')
    # Native CAS is exclusively journal.generation, never loaded.activationGeneration.
    return value


def closure_identity(value):
    keys = {'runtimeClosureSha256', 'helperClosureSha256', 'qualificationSha256'}
    if type(value) is not dict or set(value) != keys or any(type(v) is not str or not re.fullmatch('[a-f0-9]{64}', v) for v in value.values()):
        raise ContractError('invalid qualified closure identity')
    return value


def protected_root_path(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path: raise ContractError('noncanonical retained root path')
    for current in (path, *path.parents):
        st = current.lstat()
        if st.st_uid != 0 or st.st_mode & 0o022 or stat.S_ISLNK(st.st_mode):
            raise ContractError('retained ancestry not root-owned and protected')
    return path


def verify_transport_distribution(config):
    """Python preexec mirror of producer daemon-verifier.ts finite v2 manifest."""
    if sys.platform != 'linux' or os.getuid() == 0: raise ContractError('finite non-root Linux adapter required')
    root = protected_root_path(config['distributionRoot'])
    if not root.is_dir(): raise ContractError('retained distribution root missing')
    manifest_path = protected_root_path(Path(str(root) + '.manifest.json'))
    raw = read_regular(manifest_path, 4 * 1024 * 1024, owner=0)
    manifest_digest = hashlib.sha256(raw).hexdigest()
    if manifest_digest != config['distributionSha256'] or manifest_digest != config['closure']['runtimeClosureSha256']:
        raise ContractError('protected raw distribution manifest mismatch')
    raw_manifest = raw
    manifest = parse(raw.decode())
    if (type(manifest) is not dict or manifest.get('schemaVersion') != 2 or manifest.get('profile') != 'enclosing-daemon-v2' or
            manifest.get('distributionBuildId') != config['distributionBuildId'] or
            manifest.get('entries') != {'daemon':'daemon.mjs','pluginChild':'plugin-child-entry.mjs','compiler':'compiler-entry.mjs','terminal':'terminal-entry.mjs'}):
        raise ContractError('unsupported enclosing distribution manifest')
    binding_keys = sorted(['@getpaseo/plugin/internal/activity','@getpaseo/plugin','@getpaseo/plugin/server',
        '@getpaseo/plugin/server/provider','@getpaseo/plugin/server/acp','@getpaseo/plugin/server/usage',
        '@getpaseo/client','@getpaseo/client/internal/daemon-client','@getpaseo/protocol/binary-frames/index','zod'])
    if manifest.get('bindingKeys') != binding_keys: raise ContractError('qualified namespace inventory mismatch')
    files, external = manifest.get('files'), manifest.get('externalLibraries')
    if type(files) is not list or not files or len(files) > 20000 or type(external) is not list or len(external) > 1000:
        raise ContractError('invalid distribution inventory')
    by_name = {}
    def verify(item, absolute=False):
        if (type(item) is not dict or set(item) != {'path','mode','size','sha256'} or type(item['path']) is not str or
                type(item['size']) is not int or not 0 <= item['size'] <= 512 * 1024 * 1024 or
                type(item['mode']) is not int or not 0 <= item['mode'] <= 0o777 or
                type(item['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
            raise ContractError('invalid distribution file identity')
        relative = item['path']
        if not absolute and (Path(relative).is_absolute() or '\\' in relative or any(p in ('', '.', '..') for p in relative.split('/'))):
            raise ContractError('unsafe distribution path')
        if absolute and not Path(relative).is_absolute(): raise ContractError('external library not absolute')
        path = protected_root_path(Path(relative) if absolute else root / relative)
        raw = read_regular(path, item['size'], owner=0)
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size != item['size'] or st.st_mode & 0o777 != item['mode'] or hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ContractError('distribution file mismatch')
    for item in files:
        verify(item)
        if item['path'] in by_name: raise ContractError('duplicate distribution file')
        by_name[item['path']] = item
    names = set()
    def visit(directory):
        for path in directory.iterdir():
            protected_root_path(path)
            st = path.lstat()
            if stat.S_ISDIR(st.st_mode): visit(path)
            elif stat.S_ISREG(st.st_mode): names.add(path.relative_to(root).as_posix())
            else: raise ContractError('special distribution entry')
    visit(root)
    if names != set(by_name): raise ContractError('incomplete distribution manifest inventory')
    if (manifest.get('runtime') != by_name.get('runtime/node') or manifest.get('esbuild') != by_name.get('runtime/esbuild') or
            config['node']['path'] != str(root / 'runtime/node') or config['cli']['path'] != str(root / 'cli-entry.mjs') or
            'cli-entry.mjs' not in by_name):
        raise ContractError('fixed transport entry mismatch')
    external_names = set()
    for item in external:
        verify(item, True)
        if item['path'] in external_names: raise ContractError('duplicate external library')
        external_names.add(item['path'])
    helpers = [item for item in files if item['path'].startswith('runtime/') or
        re.search(r'(?:compiler|terminal)-(?:entry|code)\.mjs$', item['path']) or item['path'].endswith('.node') or
        item['path'].endswith('spawn-helper') or item['path'].startswith('node_modules/esbuild/') or
        item['path'] == 'node_modules/typescript/lib/typescript.js'] + external
    helpers.sort(key=lambda item: item['path'].encode('utf-16-be'))
    producer_json = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    helper_digest = hashlib.sha256(producer_json(helpers)).hexdigest()
    if (producer_json(manifest.get('helperInventory')) != producer_json(helpers) or
            manifest.get('helperClosureSha256') != helper_digest or helper_digest != config['closure']['helperClosureSha256']):
        raise ContractError('explicit native/helper inventory mismatch')
    if read_regular(manifest_path, 4 * 1024 * 1024, owner=0) != raw_manifest:
        raise ContractError('distribution authority changed during verification')
    return manifest


def cohort_observation(value, config, expected, target, *, allow_target_absent=False):
    """Strict proposed d174 v1 consumer. Native producer binds executing facts privately."""
    if (type(value) is not dict or set(value) != {'version', 'consistency', 'observationEpoch', 'enclosing', 'entries'} or
            type(value['version']) is not int or value['version'] != 1 or value['consistency'] != 'coherent' or
            type(value['observationEpoch']) is not int or value['observationEpoch'] < 0):
        raise ContractError('cohort observation uncertain')
    enclosing = value['enclosing']
    if (type(enclosing) is not dict or set(enclosing) != {'serverId', 'incarnation', 'distributionBuildId', 'closure'} or
            enclosing['serverId'] != config['serverId'] or enclosing['incarnation'] != config['daemonIncarnation'] or
            enclosing['distributionBuildId'] != config['distributionBuildId'] or
            closure_identity(enclosing['closure']) != config['closure']):
        raise ContractError('enclosing execution identity mismatch')
    daemon = {'role': 'daemon', 'enabled': True, 'loaded': True,
              'distributionBuildId': enclosing['distributionBuildId'], 'closure': enclosing['closure']}
    if expected.get('paseo') != daemon: raise ContractError('protected daemon cohort mismatch')
    entries = value['entries']
    if type(entries) is not list or len(entries) > 1000: raise ContractError('invalid complete cohort inventory')
    ids = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {'pluginId', 'registration', 'enabled', 'journal', 'loaded', 'execution'}:
            raise ContractError('invalid cohort entry')
        plugin = entry['pluginId']
        if type(plugin) is not str or not plugin or plugin in ids or plugin == 'paseo':
            raise ContractError('duplicate or invalid cohort ID')
        ids.add(plugin)
        registration, loaded, execution = entry['registration'], entry['loaded'], entry['execution']
        if registration is not None and type(registration) is not dict: raise ContractError('invalid cohort registration')
        if entry['enabled'] is not None and type(entry['enabled']) is not bool: raise ContractError('invalid enabled observation')
        if loaded is not None:
            if (type(loaded) is not dict or loaded.get('pluginId') != plugin or
                    type(loaded.get('activationGeneration')) is not int or loaded['activationGeneration'] < 1 or
                    type(loaded.get('pid')) is not int or loaded['pid'] <= 0 or
                    type(loaded.get('processStartToken')) is not str or not loaded['processStartToken'] or
                    type(loaded.get('startedAt')) is not str or not loaded['startedAt']):
                raise ContractError('invalid actual loaded receipt')
            if (type(execution) is not dict or set(execution) != {'contract', 'incarnation', 'distributionBuildId', 'closure'} or
                    execution['contract'] != 'native-passive-contract-1' or type(execution['incarnation']) is not str or
                    not execution['incarnation'] or type(execution['distributionBuildId']) is not str or not execution['distributionBuildId']):
                raise ContractError('loaded host execution proof absent')
            closure_identity(execution['closure'])
            if execution['incarnation'] != loaded['processStartToken']:
                raise ContractError('execution and loaded incarnation mismatch')
            journal = entry['journal']
            if (type(journal) is not dict or type(journal.get('generation')) is not int or journal['generation'] < 0 or
                    journal.get('currentReceipt') != loaded):
                raise ContractError('loaded/native journal identity incoherent')
        elif execution is not None: raise ContractError('execution without loaded host')
        if plugin not in expected:
            if loaded is not None or entry['enabled'] is True: raise ContractError('unexpected active cohort member')
            continue
        if plugin == target:
            if not allow_target_absent and (loaded is None or entry['enabled'] is not True):
                raise ContractError('target not running')
            continue
        stable = {'enabled': entry['enabled'], 'loaded': loaded is not None, 'registration': registration,
                  'receipt': None if loaded is None else {k: loaded.get(k) for k in ('sourcePath', 'snapshotRoot', 'snapshotSha256', 'serverBundleSha256')},
                  'execution': None if execution is None else {k: execution[k] for k in ('contract', 'distributionBuildId', 'closure')}}
        if expected[plugin] != stable: raise ContractError('protected non-target cohort mismatch')
    if not (set(expected) - {'paseo'}) <= ids: raise ContractError('incomplete protected cohort')
    return value


class NativeFacade:
    """Actual bounded retained CLI transport; qualification/status coupling still absent.

    No source/dev/PATH fallback. supported remains false until native owners publish
    and implement genuine qualified status/feature metadata for this exact bridge.
    """
    def __init__(self, reader=None, root=None):
        self.reader = reader or read_enrollment
        self.root = root or locations()[1]
        self.token = None
        self.reservation = None
        self.uncertain = False
        self.verified = False
        self.target = None
        self.render = None
        self.bridge_binding = None
        self.operation = 'activate'
        self.recovery_inspection = False

    def supported(self):
        if self.uncertain: return False
        try:
            self.cohort_status(allow_target_absent=True)
            authority = self._call(['daemon', 'maintenance', 'status']).get('authority')
            config = self._transport()
            if (type(authority) is not dict or authority.get('schemaVersion') != 1 or authority.get('qualified') is not True or
                    authority.get('serverId') != config['serverId'] or authority.get('daemonIncarnation') != config['daemonIncarnation'] or
                    type(authority.get('features')) is not dict or
                    authority['features'].get('maintenanceReservationV1') is not True or
                    authority['features'].get('maintenancePluginOperationV1') is not True):
                raise ContractError('native enclosing operation authority unavailable')
            return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def cohort_status(self, *, allow_target_absent=False):
        row = self.reader(); config = self._transport()
        return cohort_observation(self._call(['plugin', 'cohort-status']), config, row['cohort'], row['component'], allow_target_absent=allow_target_absent)

    def prepare(self, row, identity, render, *, recovery=False):
        self.transaction_row = row
        self.target = identity
        self.render = render
        self.recovery_inspection = recovery
        if recovery: self.operation = 'recover'

    def _transport(self):
        config = self.reader()['native']
        if type(config) is not dict: raise ContractError('retained native bridge unavailable')
        binding = digest(config)
        if self.bridge_binding is not None and self.bridge_binding != binding:
            self.uncertain = True
            raise ContractError('retained native bridge changed during transaction')
        verify_transport_distribution(config)
        for key in ('node', 'cli'):
            item = config[key]; path = Path(item['path'])
            data = read_regular(path, 256 * 1024 * 1024, owner=0)
            if path.stat().st_mode & 0o222 or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ContractError('retained native bridge identity mismatch')
        self.bridge_binding = binding
        return config

    def _call(self, arguments, token=None):
        config = self._transport()
        args = [config['node']['path'], config['cli']['path'], *arguments, '--json']
        env = {'PATH': str(Path(config['node']['path']).parent) + ':/usr/bin:/bin',
               'HOME': pwd.getpwuid(os.getuid()).pw_dir}
        if token is not None and not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ContractError('invalid private owner token')
        with subprocess.Popen(args, stdin=subprocess.PIPE if token is not None else subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as proc:
            deadline = time.monotonic() + 30
            data = bytearray()
            try:
                if token is not None:
                    # Only <=44 bytes to a private anonymous pipe, never argv/env/file path.
                    proc.stdin.write((token + '\n').encode('ascii')); proc.stdin.close()
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining): raise ContractError('native transport timed out')
                        chunk = os.read(proc.stdout.fileno(), min(65536, 1024 * 1024 + 1 - len(data)))
                        if not chunk: break
                        data.extend(chunk)
                        if len(data) > 1024 * 1024: raise ContractError('native transport output too large')
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise ContractError('native transport timed out')
                try: code = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired as error: raise ContractError('native transport timed out') from error
                if code: raise ContractError('native transport refused')
                # Native CLI --json contract is one BARE JSON result, not an RPC envelope.
                return parse(data.decode())
            except Exception:
                if self.reservation is not None: self.uncertain = True
                raise
            finally:
                if proc.poll() is None: proc.kill()
                proc.wait()

    def list_observations(self):
        return self._call(['plugin', 'ls'])

    def managed_status(self, plugin_id, *, allow_target_absent=False):
        return coherent_native_status(self._call(['plugin', 'managed-status', plugin_id]), plugin_id, allow_target_absent=allow_target_absent)

    def _identity_args(self):
        config = self._transport()
        return ['--expected-server-id', config['serverId'], '--expected-daemon-incarnation', config['daemonIncarnation']]

    def _reservation_args(self):
        if not self.reservation or not self.token: raise ContractError('native private reservation absent')
        return ['--generation', str(self.reservation['generation']), '--transaction-id', self.reservation['transactionId'], *self._identity_args()]

    @__import__('contextlib').contextmanager
    def reserve(self):
        if self.supported() is not True or not self.target:
            raise ContractError('native qualified reservation unavailable')
        row = self.transaction_row
        generation = row['generation'] + 1
        tx = digest({'group': row['policy']['compatibility_group'], 'generation': generation, 'target': self.target})
        self.reservation = {'generation': generation, 'transactionId': tx}
        self.verified = False
        try:
            result = self._call(['daemon', 'maintenance', 'begin', '--generation', str(generation), '--transaction-id', tx, *self._identity_args()])
            if (type(result) is not dict or result.get('state') != 'held' or result.get('recoveryRequired') is not False or
                    result.get('generation') != generation or result.get('transactionId') != tx or
                    type(result.get('ownerToken')) is not str or not re.fullmatch('[A-Za-z0-9_-]{43}', result['ownerToken'])):
                raise ContractError('native begin uncertain')
            self.token = result['ownerToken']
            yield True
        except BaseException:
            self.uncertain = True
            raise
        finally:
            # Journal can return recovery_required without raising. Therefore context
            # exit NEVER sends END. Controller acknowledges only a committed verified result.
            pass

    def finish(self):
        if not self.verified or self.uncertain or not self.token:
            raise ContractError('native release not verified')
        result = self._call(['daemon', 'maintenance', 'end', *self._reservation_args(), '--owner-token-fd', '0'], self.token)
        if type(result) is not dict or result.get('state') != 'idle' or result.get('recoveryRequired') is not False:
            self.uncertain = True
            raise ContractError('native end uncertain')
        self.token = None; self.reservation = None

    def preflight(self, record):
        return self.supported() is True and self.token is not None and not self.uncertain

    def observe(self, cohort):
        if self.uncertain: raise ContractError('native execution uncertain')
        facts = self.cohort_status(allow_target_absent=self.recovery_inspection)
        if canonical(self.reader()['cohort']) != canonical(cohort): raise ContractError('protected cohort changed')
        target = self.reader()['component']
        entry = next(item for item in facts['entries'] if item['pluginId'] == target)
        loaded = entry['loaded']; execution = entry['execution']
        if loaded is None or entry['enabled'] is not True:
            if not self.recovery_inspection: raise ContractError('target runtime receipt unavailable')
            # Independent absent-state identity, never a fabricated baseline receipt.
            # Journal.recover inspects it; strict verification is restored after recovery.
            return 'native-target-absent:v1:' + digest({'pluginId': target, 'registration': entry['registration'],
                'enabled': entry['enabled'], 'journal': entry['journal']})
        paths = sorted((self.root / 'records').iterdir())
        if not paths or len(paths) > 100: raise ContractError('retained release inventory unavailable')
        matches = []
        for path in paths:
            identity = path.stem
            if path.suffix != '.json' or not re.fullmatch('[a-f0-9]{64}', identity): raise ContractError('invalid retained release path')
            record = parse(read_regular(path).decode())
            receipt = Receipt(base64.b64decode(record['receipt'], validate=True))
            if receipt.sha256 != identity: raise ContractError('retained release identity corruption')
            profile = record['policy'].get('native_passive_profile')
            if type(profile) is not dict: continue
            root = self.root / 'snapshots' / record['payload_sha256']
            if (record['expected']['component'] != target or loaded.get('sourcePath') != str(root / 'plugins' / target) or
                    loaded.get('snapshotRoot') != str(root) or loaded.get('snapshotSha256') != record['evidence']['native_tree_sha256'] or
                    loaded.get('serverBundleSha256') != record['evidence']['server_bundle_sha256'] or
                    execution['closure'] != {k: profile.get(k) for k in ('runtimeClosureSha256', 'helperClosureSha256', 'qualificationSha256')}):
                continue
            payload = read_regular(self.root / 'payloads' / record['payload_sha256'])
            validate(receipt, record['expected'], record['policy'], artifact=payload)
            if tree_hash(root) != loaded['snapshotSha256']: raise ContractError('actual runtime snapshot drift')
            matches.append(identity)
        if len(matches) != 1: raise ContractError('runtime receipt mapping missing or ambiguous')
        return matches[0]

    def _operation(self, kind, identity, record):
        if self.supported() is not True or self.render is None or identity != self.target:
            raise ContractError('native held operation unavailable')
        status = self.managed_status(record['expected']['component'], allow_target_absent=kind == 'recover' and self.recovery_inspection)
        rendered = self.render(identity, status, self.operation)
        grant = rendered['authorization']
        result = self._call(['daemon', 'maintenance', 'plugin-operation', '--operation', kind,
            *self._reservation_args(), '--plugin-id', rendered['pluginId'], '--path', grant['sourcePath'],
            '--expected-path', rendered['expectedPath'], '--expected-generation', str(grant['expectedGeneration']),
            '--snapshot-sha256', grant['snapshotSha256'], '--server-bundle-sha256', grant['serverBundleSha256'],
            '--owner-token-fd', '0'], self.token)
        config = self._transport()
        if (type(result) is not dict or result.get('serverId') != config['serverId'] or
                result.get('daemonIncarnation') != config['daemonIncarnation'] or
                type(result.get('nativeGeneration')) is not int or type(result.get('plugin')) is not dict or
                result['plugin'].get('id') != rendered['pluginId'] or result['plugin'].get('enabled') is not True or
                result['plugin'].get('status') != 'running'):
            self.uncertain = True
            raise ContractError('native operation identity uncertain')
        loaded = result['plugin'].get('loaded')
        if (type(loaded) is not dict or loaded.get('sourcePath') != grant['sourcePath'] or
                loaded.get('snapshotRoot') != grant['snapshotRoot'] or loaded.get('snapshotSha256') != grant['snapshotSha256'] or
                loaded.get('serverBundleSha256') != grant['serverBundleSha256'] or not loaded.get('processStartToken') or
                type(loaded.get('pid')) is not int or not loaded.get('startedAt')):
            self.uncertain = True
            raise ContractError('native loaded receipt uncertain')
        return result

    def activate(self, identity, record):
        self.operation = 'activate'
        self._operation('replace', identity, record)
    def recover(self, identity, record):
        self.operation = 'recover'
        self._operation('recover', identity, record)
        self.recovery_inspection = False  # subsequent receipt/cohort verification is strict
    def verify(self, identity, record):
        self._operation('verify', identity, record)
        self.verified = True
        return True


class Controller:
    """Ports are trusted in-process injection ONLY. CLI cannot select a port."""
    def __init__(self, reader=read_enrollment, evaluator=None, native=None, root=None):
        self.reader = reader
        self.evaluator = evaluator or GitHubEvaluation()
        self.native = native or NativeFacade(reader, root)
        self.selection = None
        self.fresh_attestations = {}
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

    def select_latest(self):
        """Protected workflow output contract, ancestry order, no operation grants."""
        row = self.reader()
        self.selection = None
        self.fresh_attestations = {}
        if row['discovery']['enabled'] is not True:
            raise ContractError('protected evaluator discovery not enabled')
        ev = evaluation(row)
        calls = 0
        def api(endpoint):
            nonlocal calls
            calls += 1
            if calls > 80: raise ContractError('discovery API budget exceeded')
            response = self.evaluator.api(endpoint)
            if type(response) is not dict: raise ContractError('malformed discovery metadata')
            return response
        quota = api('rate_limit')
        resources = quota.get('resources')
        core = resources.get('core') if type(resources) is dict else None
        remaining = core.get('remaining') if type(core) is dict else None
        if type(remaining) is not int: raise ContractError('malformed quota inventory')
        if remaining < 500:
            raise ContractError('discovery API quota held')
        repo = api('repos/' + row['repository'])
        if repo.get('id') != row['repository_id']: raise ContractError('source repository changed')
        ref_path = 'repos/' + row['repository'] + '/git/ref/heads/master'
        def master():
            ref = api(ref_path)
            obj = ref.get('object')
            if type(obj) is not dict: raise ContractError('malformed master object')
            if (ref.get('ref') != 'refs/heads/master' or obj.get('type') != 'commit' or
                    type(obj.get('sha')) is not str or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', obj.get('sha', ''))):
                raise ContractError('invalid master identity')
            return obj['sha']
        latest = master()
        comparisons = {}
        def ancestor(older, newer):
            if older == newer: return True
            key = (older, newer)
            if key not in comparisons:
                result = api('repos/' + row['repository'] + '/compare/' + older + '...' + newer)
                base_commit, merge_base = result.get('base_commit'), result.get('merge_base_commit')
                if type(base_commit) is not dict or type(merge_base) is not dict:
                    raise ContractError('malformed ancestry inventory')
                if (base_commit.get('sha') != older or merge_base.get('sha') != older):
                    comparisons[key] = False
                else:
                    comparisons[key] = result.get('status') in ('ahead', 'identical')
            return comparisons[key]
        baseline_commit = row['master_commit']
        baseline_identity = row['previous']
        if self.retained(baseline_identity):
            baseline = parse(read_regular(self.root / 'records' / (baseline_identity + '.json')).decode())
            baseline_commit = baseline['expected']['fork_commit']
        if not ancestor(baseline_commit, latest):
            raise ContractError('master rewind or incomparable baseline')
        selected = None
        if self.retained(baseline_identity):
            selected = {'commit': baseline_commit, 'identity': baseline_identity, 'retained': True}
        base = 'repos/' + ev.repository
        runs = []
        # Complete bounded history after the protected enrolled baseline run. No first-page guessing.
        for page in range(1, 6):
            response = api(f'{base}/actions/workflows/{ev.workflow_id}/runs?per_page=100&page={page}')
            entries = response.get('workflow_runs')
            if type(entries) is not list or any(type(r) is not dict for r in entries):
                raise ContractError('invalid evaluator run inventory')
            if any(type(r.get('id')) is not int or r['id'] <= 0 for r in entries):
                raise ContractError('invalid evaluator run identity')
            runs.extend(r for r in entries if r['id'] > row['discovery']['baseline_run_id'])
            if len(entries) < 100 or any(r.get('id', 0) <= row['discovery']['baseline_run_id'] for r in entries):
                break
        else: raise ContractError('evaluator history exceeds bounded window')
        run_ids = set()
        verified_candidates = 0
        for run in runs:
            if run['id'] in run_ids: raise ContractError('duplicate evaluator run')
            run_ids.add(run['id'])
            if (run.get('head_sha') != ev.evaluator_commit or run.get('status') != 'completed' or
                    run.get('conclusion') != 'success' or run.get('event') != ev.event):
                continue
            attempt = run.get('run_attempt')
            if type(attempt) is not int or attempt <= 0: raise ContractError('invalid evaluator attempt')
            artifacts = api(f"{base}/actions/runs/{run['id']}/artifacts?per_page=100")
            if type(artifacts.get('artifacts')) is not list or type(artifacts.get('total_count')) is not int or artifacts.get('total_count') != len(artifacts['artifacts']) or len(artifacts['artifacts']) >= 100:
                raise ContractError('incomplete artifact inventory')
            if any(type(item) is not dict or type(item.get('name')) is not str for item in artifacts['artifacts']):
                raise ContractError('invalid artifact inventory entry')
            prefix = row['discovery']['artifact_prefix']
            pattern = re.compile(re.escape(prefix) + r'-([a-f0-9]{40}|[a-f0-9]{64})-' + str(run['id']) + '-' + str(attempt))
            matching = [(item, pattern.fullmatch(item.get('name', ''))) for item in artifacts['artifacts']]
            matching = [(item, match) for item, match in matching if match]
            if len(matching) > 1: raise ContractError('duplicate qualification output')
            if not matching: continue  # protected workflow did not qualify this attempt
            item, match = matching[0]; commit = match.group(1)
            if not ancestor(baseline_commit, commit) or not ancestor(commit, latest):
                raise ContractError('incomparable or stale source output')
            if selected and not ancestor(selected['commit'], commit):
                if ancestor(commit, selected['commit']): continue
                raise ContractError('incomparable qualified outputs')
            archive_digest = item.get('digest', '')
            if type(archive_digest) is not str or not re.fullmatch(r'sha256:[a-f0-9]{64}', archive_digest): raise ContractError('artifact digest unavailable')
            verified_candidates += 1
            if verified_candidates > 4: raise ContractError('qualification discovery verification budget exceeded')
            candidate_ev = replace(ev, run_id=run['id'], run_attempt=attempt, artifact_id=item['id'],
                                   artifact_name=item['name'], archive_sha256=archive_digest[7:])
            # First authenticate transport using protected evaluator constraints. Receipt digest
            # discovery is allowed ONLY inside this authenticated exact reviewed workflow output.
            private_directory(self.root); private_directory(self.root / 'archives')
            verified_transport = self.evaluator.verify(candidate_ev, self.root / 'archives')
            archive = read_regular(verified_transport.archive)
            if hashlib.sha256(archive).hexdigest() != candidate_ev.archive_sha256:
                raise ContractError('discovery archive substitution')
            receipt, payload, evidence = unpack_archive(archive)
            source = inspect(payload)
            if source['commit'] != commit: raise ContractError('workflow source output mismatch')
            # Only recipe-defined dynamic fields vary. Candidate JSON does not define policy,
            # feature tests, dependencies, recipe/compiler identity, authority or evaluator.
            expected = dict(row['expected'])
            expected.update(fork_commit=commit, upstream_commit=commit,
                            artifact_sha256=hashlib.sha256(payload).hexdigest())
            protected_evidence = dict(row['evidence'])
            protected_evidence.update(master_commit=commit, native_tree_sha256=payload_tree_hash(payload))
            # Compiled result is a protected evaluator output; all compiler/tool identities remain fixed.
            bundle = evidence.get('server_bundle_sha256')
            if not isinstance(bundle, str) or not re.fullmatch('[a-f0-9]{64}', bundle):
                raise ContractError('missing protected compiler output digest')
            protected_evidence['server_bundle_sha256'] = bundle
            expected['toolchain'] = canonical({'plugin_snapshot_evidence': digest(protected_evidence)}).decode()
            if evidence != protected_evidence: raise ContractError('protected recipe evidence mismatch')
            candidate_ev = replace(candidate_ev, receipt_sha256=receipt.sha256)
            # Re-authenticate exact receipt after bounded protected-output discovery, with metadata
            # rechecks at the exact attempt. No private verification seal is constructed here.
            verified = self.evaluator.verify(candidate_ev, self.root / 'archives')
            validate(receipt, expected, row['policy'], artifact=payload)
            if qualify(payload, 'ade-yolo', receipt, expected, row['policy'], verified, evidence, protected_evidence) != 'QUALIFIED':
                raise ContractError('protected candidate did not qualify')
            record = {'receipt': base64.b64encode(receipt.encoded).decode(),
                      'payload_sha256': expected['artifact_sha256'], 'expected': expected,
                      'policy': row['policy'], 'cohort': row['cohort'],
                      'evidence': evidence}
            if canonical(self.reader()) != canonical(row) or master() != latest:
                raise ContractError('master or enrollment changed during selection')
            immutable(self.root / 'payloads' / expected['artifact_sha256'], payload)
            immutable(self.root / 'records' / (receipt.sha256 + '.json'), canonical(record))
            self.attest(receipt.sha256, candidate_ev)
            self.fresh_attestations[receipt.sha256] = candidate_ev
            if selected and selected['commit'] == commit and selected['identity'] != receipt.sha256:
                raise ContractError('ambiguous qualification identity for source')
            selected = {'commit': commit, 'identity': receipt.sha256, 'retained': True}
        if canonical(self.reader()) != canonical(row) or master() != latest:
            raise ContractError('master or enrollment changed before selection commit')
        self.selection = {'enrollment_sha256': digest(row), 'latest': latest, 'selected': selected}
        return {'status': 'qualified_available' if selected else 'hold', 'latest_discovered': latest,
                'selected_qualified': selected, 'authorized': False,
                'reason': 'no_qualified_ancestor' if not selected else 'protected_evaluator_ancestor'}

    def permits(self, row, operation, identity):
        current = self.reader()
        if canonical(current) != canonical(row): return False
        grant = current['operations'].get(operation)
        if not (type(grant) is dict and grant['allowed'] is True and grant['generation'] == current['generation']):
            return False
        if grant['identity'] == identity: return True
        if grant['identity'] != 'qualified-latest' or not self.selection:
            return False
        selected = self.selection['selected']
        if (not selected or selected['identity'] != identity or self.selection['enrollment_sha256'] != digest(current)):
            return False
        # Current consent permits only the independently selected exact artifact under
        # unchanged protected constraints. New master requires fresh selection.
        return self.discover_master()['discovered'] == self.selection['latest']


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
                  'evidence': evidence}
        immutable(self.root / 'payloads' / record['payload_sha256'], payload)
        immutable(self.root / 'records' / (receipt.sha256 + '.json'), canonical(record))
        self.attest(receipt.sha256, ev)
        return receipt, payload, verified

    def attest(self, identity, evaluation):
        # Stable release identity excludes run-specific provenance. Every authenticated
        # reattestation is retained independently and cannot overwrite another attempt.
        evidence = dict(asdict(evaluation), jobs=list(evaluation.jobs))
        value = {'receipt_sha256': identity, 'evaluation': evidence}
        immutable(self.root / 'attestations' / identity / (digest(value) + '.json'), canonical(value))

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

    def concrete_grant(self, row, identity, native_status, operation='activate'):
        """Pure artifact scope/authorization renderer, never a permission or transport.

        Caller must run under the native private held-operation lease. Native rechecks
        owner/token/reservation/current policy at the actual mutation boundary.
        """
        if operation not in ('activate', 'recover') or not self.permits(row, operation, identity):
            raise ContractError('current concrete operation consent absent')
        if not self.retained(identity): raise ContractError('concrete grant artifact missing')
        status = coherent_native_status(native_status, row['component'], allow_target_absent=operation == 'recover')
        record = parse(read_regular(self.root / 'records' / (identity + '.json')).decode())
        root = self.root / 'snapshots' / record['payload_sha256']
        expected_tree = record['evidence']['native_tree_sha256']
        if tree_hash(root) != expected_tree: raise ContractError('concrete grant tree mismatch')
        profile = record['policy'].get('native_passive_profile')
        required = {'version', 'contract', 'qualificationSha256', 'runtimeClosureSha256', 'helperClosureSha256', 'initialization'}
        if (type(profile) is not dict or set(profile) != required or type(profile['version']) is not int or profile['version'] != 1 or
                profile['contract'] != 'native-passive-contract-1' or profile['initialization'] != 'registration-only' or
                any(type(profile[key]) is not str or not re.fullmatch('[a-f0-9]{64}', profile[key])
                    for key in ('qualificationSha256', 'runtimeClosureSha256', 'helperClosureSha256'))):
            raise ContractError('protected passive execution profile unavailable')
        source = str(root / 'plugins' / row['component'])
        bundle = record['evidence']['server_bundle_sha256']
        if type(bundle) is not str or not re.fullmatch('[a-f0-9]{64}', bundle):
            raise ContractError('protected compiled bundle identity unavailable')
        grant = {'operation': operation, 'expectedGeneration': status['journal']['generation'],
                 'sourcePath': source, 'snapshotRoot': str(root), 'snapshotSha256': expected_tree,
                 'serverBundleSha256': bundle, 'state': 'binary-only',
                 'forbiddenEnvironment': ['ADE_CLAIMS_PY', 'ADE_GIT_GUARD', 'ADE_AGENT_BIN',
                                          'ADE_WS_AUTONAME_PY', 'ADE_PYTHON', 'ADE_REAL_GIT'],
                 'passiveProfile': profile}
        return {'pluginId': row['component'], 'receiptSha256': identity,
                'expectedPath': status['registration']['path'], 'authorization': grant}

    def selected_release(self, row):
        selection = self.select_latest()
        selected = selection['selected_qualified']
        if not selected: raise ContractError('no selected qualified release')
        identity = selected['identity']
        if not self.retained(identity): raise ContractError('selected release unavailable')
        record = parse(read_regular(self.root / 'records' / (identity + '.json')).decode())
        receipt = Receipt(base64.b64decode(record['receipt'], validate=True))
        payload = read_regular(self.root / 'payloads' / record['payload_sha256'])
        # Choose an exact retained attestation, not a run-specific field in the release record.
        attestations = self.root / 'attestations' / identity
        names = sorted(attestations.iterdir())
        if not names or len(names) > 100: raise ContractError('attestation inventory unavailable')
        candidates = []
        trusted = evaluation(row)
        static = ('repository', 'repository_id', 'workflow_id', 'workflow_path', 'evaluator_commit', 'actor_id', 'event', 'jobs', 'workflow_ref')
        # Validate the complete local inventory BEFORE using any fresh attestation.
        # Corruption is never masked as obsolete remote provenance.
        for name in names:
            value = parse(read_regular(name, 1024 * 1024).decode())
            if type(value) is not dict or digest(value) + '.json' != name.name or value.get('receipt_sha256') != identity:
                raise ContractError('attestation identity corruption')
            ev = evaluation({'evaluation': value['evaluation']})
            if all(getattr(ev, key) == getattr(trusted, key) for key in static):
                candidates.append(ev)
        fresh = self.fresh_attestations.get(identity)
        if fresh is not None:
            if fresh not in candidates: raise ContractError('fresh attestation not retained')
            candidates = [fresh]  # exact newly selected attempt, never obsolete digest order
        else:
            # Retained baseline fallback: deterministic newest run/attempt, not hash filename order.
            candidates.sort(key=lambda ev: (ev.run_id, ev.run_attempt, ev.artifact_id), reverse=True)
        if candidates:
            ev = candidates[0]
            # Re-authenticate at transaction boundary. Current-attempt/policy refusal
            # propagates; do not turn every ContractError into try-an-older-attempt.
            verified = self.evaluator.verify(ev, self.root / 'archives')
            if verified.authenticates(receipt) is not True: raise ContractError('selected receipt authentication refused')
            if canonical(self.reader()) != canonical(row) or self.discover_master()['discovered'] != self.selection['latest']:
                raise ContractError('selected release stale before transaction')
            return receipt, payload, verified, record
        raise ContractError('current protected attestation unavailable')

    def tick(self, operation='plan'):
        row = self.reader()
        if operation == 'plan': return self.plan()
        if operation == 'select': return self.select_latest()
        # No acquisition, staging, journal or native mutations on unsupported runtime.
        if self.native.supported() is not True:
            return {'status': 'hold', 'reason': 'native_execution_status_reservation_unsupported', 'authorized': False}
        journal = Journal(self.root / 'journal', row['policy']['compatibility_group'])
        if isinstance(self.native, NativeFacade):
            self.native.prepare(row, row['previous'], lambda identity, status, operation: self.concrete_grant(row, identity, status, operation),
                                recovery=operation == 'recover' and self.permits(row, 'recover', row['previous']) and self.permits(row, 'verify', row['previous']))
        if operation == 'recover':
            # Recovery never depends on candidate CI availability or current candidate retention consent.
            adapters = self.adapters(row, None)
            result = asdict(journal.recover(adapters, generation=row['generation']))
            if result['status'] == 'runtime_verified' and isinstance(self.native, NativeFacade):
                if not self.permits(row, 'verify', row['previous']):
                    self.native.uncertain = True
                    raise ContractError('native recovery release consent revoked')
                self.native.finish()
            return result
        if operation == 'deploy' and row['operations'].get('activate', {}).get('identity') == 'qualified-latest':
            receipt, payload, verified, release = self.selected_release(row)
            expected = release['expected']
        else:
            receipt, payload, verified = self.acquire(row)
            expected = row['expected']
        if isinstance(self.native, NativeFacade):
            self.native.prepare(row, receipt.sha256, lambda identity, status, operation: self.concrete_grant(row, identity, status, operation))
        adapters = self.adapters(row, verified)
        if operation == 'enroll':
            journal.enroll(receipt.sha256, adapters)
            return {'status': 'enrolled', 'identity': receipt.sha256, 'authorized': False}
        if operation != 'deploy': raise ContractError('unsupported operation')
        result = asdict(journal.deploy(receipt, expected, row['policy'], payload, adapters,
                                    previous=row['previous'], generation=row['generation'], migration='binary_only'))
        if result['status'] == 'runtime_verified' and isinstance(self.native, NativeFacade):
            if not self.permits(row, 'verify', receipt.sha256):
                self.native.uncertain = True
                raise ContractError('native release consent revoked')
            self.native.finish()
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'plan', 'tick', 'apply', 'recover'))
    args = parser.parse_args(argv)
    try:
        # No arbitrary path, grant, port or transport override is exposed.
        controller = Controller()
        if args.command == 'apply': result = controller.tick('deploy')
        elif args.command == 'recover': result = controller.tick('recover')
        elif args.command == 'tick': result = controller.select_latest()
        else: result = controller.plan()
        if args.command == 'status': result['status'] = 'hold'; result['reason'] = 'native_execution_status_reservation_unsupported'
        print(canonical(result).decode())
        return 1 if args.command in ('apply', 'recover') and result['status'] != 'runtime_verified' else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(canonical({'status': 'hold', 'reason': type(error).__name__, 'authorized': False}).decode()); return 1


if __name__ == '__main__': raise SystemExit(main())
