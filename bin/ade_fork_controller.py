"""ADE protected fork controller; finite Linux producer/cohort facts gate execution.

Missing genuine retained transport, qualified closure or current authority holds.
Synthetic CI ports exercise orchestration only and confer no production support.
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
import posixpath
import re
import stat
import selectors
import time
import subprocess
import sys
import tempfile
import types
import zipfile

from ade_fork_ci import Evaluation, GitHubEvaluation
import ade_fork_release as release
from ade_fork_release import Adapters, ContractError, Journal, Receipt, canonical, digest, parse, validate
from ade_fork_plugins import inspect, payload_tree_hash, qualify, stage, tree_hash
from ade_forks import load_policy

LIMIT = 96 * 1024 * 1024
MEMBERS = {'receipt.json', 'snapshot.json', 'evaluator-evidence.json'}
OPERATIONS = {'enroll', 'preflight', 'stage', 'activate', 'verify', 'recover', 'retain', 'resume', 'reconcile-release'}
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


STANDING_SELECTORS = {
    'retain': {'qualified-latest'}, 'preflight': {'qualified-latest'},
    'stage': {'qualified-latest'}, 'activate': {'qualified-latest'},
    'recover': {'recorded-verified', 'recorded-baseline'},
    'verify': {'qualified-latest', 'recorded-verified', 'recorded-baseline'},
}


def validate_operations(row):
    ops = row['operations']
    if type(ops) is not dict or set(ops) - OPERATIONS: raise ContractError('invalid operation consent')
    for operation, value in ops.items():
        if row['schema_version'] == 1:
            if (type(value) is not dict or set(value) != {'allowed', 'identity', 'generation'} or
                    type(value['allowed']) is not bool or type(value['generation']) is not int or value['generation'] != row['generation'] or
                    type(value['identity']) is not str or not (re.fullmatch('[a-f0-9]{64}', value['identity']) or
                    (value['identity'] == 'qualified-latest' and operation in {'retain','preflight','stage','activate','verify'}))):
                raise ContractError('invalid exact legacy consent')
            continue
        if (type(value) is not dict or set(value) != {'version','grants'} or type(value['version']) is not int or value['version'] != 1 or
                type(value['grants']) is not list or not 1 <= len(value['grants']) <= 32):
            raise ContractError('invalid versioned grants wrapper')
        seen = set()
        for grant in value['grants']:
            if type(grant) is not dict or type(grant.get('allowed')) is not bool: raise ContractError('invalid literal grant')
            identity = digest(grant)
            if identity in seen: raise ContractError('duplicate canonical grant')
            seen.add(identity)
            if grant.get('mode') == 'exact':
                if (set(grant) != {'mode','allowed','identity','generation'} or type(grant['identity']) is not str or
                        not re.fullmatch('[a-f0-9]{64}', grant['identity']) or type(grant['generation']) is not int or grant['generation'] < 0):
                    raise ContractError('invalid exact transaction grant')
            elif grant.get('mode') == 'standing':
                selectors = grant.get('selectors')
                if (set(grant) != {'mode','allowed','selectors'} or type(selectors) is not list or not selectors or
                        any(type(item) is not str for item in selectors) or len(selectors) != len(set(selectors)) or
                        not set(selectors) <= STANDING_SELECTORS.get(operation, set())):
                    raise ContractError('invalid finite standing selector')
            else: raise ContractError('invalid consent mode')


def rule_allows(row, operation, identity, context, *, selected_current=False):
    """Pure scope match; context is produced under Journal lock, never candidate JSON."""
    if context is not None and (context.rule_digest != digest(row) or context.group != row['policy']['compatibility_group']):
        return False
    generation = row['generation'] if context is None else context.cas_generation
    value = row['operations'].get(operation)
    if value is None: return False
    if row['schema_version'] == 1:
        return (value['allowed'] is True and value['generation'] == generation and
                (value['identity'] == identity or value['identity'] == 'qualified-latest' and selected_current and
                 (context is None or context.kind == 'deploy')))
    matched = []
    for grant in value['grants']:
        match = False
        if grant['mode'] == 'exact':
            match = grant['identity'] == identity and grant['generation'] == generation
        elif context is not None and context.kind not in ('resume','reconcile-release'):
            for selector in grant['selectors']:
                if selector == 'qualified-latest':
                    match |= context.kind == 'deploy' and context.target == identity and selected_current
                elif selector == 'recorded-verified':
                    match |= context.kind == 'reconcile' and context.target == identity == context.verified
                elif selector == 'recorded-baseline':
                    match |= context.kind == 'verified-rollback' and context.target == identity == context.baseline
        if match: matched.append(grant['allowed'])
    return bool(matched) and all(matched)  # matching explicit denial wins


def enrollment(encoded: bytes, registry: list[dict]) -> dict:
    row = parse(encoded.decode('utf-8'))
    if type(row) is not dict or set(row) != FIELDS or type(row['schema_version']) is not int or row['schema_version'] not in (1, 2):
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
        if (type(native) is not dict or set(native) not in ({'node','cli','serverId','daemonIncarnation','distributionSha256','distributionBuildId','distributionRoot','closure'},
                    {'node','cli','serverId','daemonIncarnation','distributionSha256','distributionBuildId','distributionRoot','closure','cohortVersion'}) or
                    ('cohortVersion' in native and (type(native['cohortVersion']) is not int or native['cohortVersion'] != 2))):
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
    validate_operations(row)
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


def coherent_native_status(value, plugin_id, *, allow_target_absent=False, require_baseline=False):
    """Consumer for proposed ManagedPluginStatus v1; observations grant no support."""
    if (type(value) is not dict or value.get('version') != 1 or value.get('pluginId') != plugin_id or
            value.get('consistency') != 'coherent'):
        raise ContractError('native status uncertain')
    registration, journal, loaded = (value.get(key) for key in ('registration', 'journal', 'loaded'))
    if (type(registration) is not dict or type(journal) is not dict or (type(loaded) is not dict and not (allow_target_absent and loaded is None)) or
            type(journal.get('generation')) is not int or journal['generation'] < 0 or
            journal.get('phase') not in ('ready', 'activating', 'replacing', 'held') or
            (require_baseline and type(journal.get('baseline')) is not dict) or
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


BUILTIN_IDS = ('antigravity-provider','claude-usage-source','codex-usage-source','copilot-usage-source',
    'cursor-usage-source','fx-provider','grok-usage-source','hoplite-provider','kimi-usage-source',
    'minimax-usage-source','muse-provider','opencode-go-usage-source','worktree-include','zai-usage-source')
BUILTIN_RECIPE = {'schemaVersion':1,'contract':'builtin-in-process-v1',
    'sdkKeys':['@getpaseo/plugin','@getpaseo/plugin/server','@getpaseo/plugin/server/provider',
               '@getpaseo/plugin/server/acp','@getpaseo/plugin/server/usage','zod'],
    'privateBindings':['@getpaseo/plugin/internal/activity','@getpaseo/plugin/internal/builtin-helper'],
    'nodeKeys':['node:fs','node:fs/promises','node:os','node:path','node:crypto','node:readline','node:util',
                'node:timers/promises','node:sqlite','node:child_process'],
    'globals':{'process':'captured-node-process-finite-getBuiltinModule-v1','fetch':'captured-node-fetch-v1',
               'timers':'captured-node-timers-v1','dynamicImport':'finite-table-promise-v1','childProcess':'scoped-execFile-only-v1'}}


def builtin_json(value):
    """Mirror committed canonicalBuiltinJson; no new identity algorithm."""
    def check(item):
        if item is None or type(item) is bool: return
        if type(item) is int and abs(item) <= 2**53-1: return
        if type(item) is str:
            item.encode('utf8',errors='strict'); return
        if type(item) is list:
            for child in item: check(child)
            return
        if type(item) is dict:
            for key,child in item.items():
                if type(key) is not str: raise ContractError('invalid builtin canonical key')
                check(key); check(child)
            return
        raise ContractError('invalid builtin canonical data')
    try:
        check(value)
        return canonical(value)
    except UnicodeError as error: raise ContractError('invalid builtin canonical Unicode') from error


def read_native_host_policy():
    """Fixed producer enrollment path; no CLI/env transport or policy overrides."""
    home=Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    path=home/'.local/state/djbclark-ade/forks/paseo-qualified-host-policy.json'
    for current in (path,*path.parents):
        st=current.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid not in (0,os.getuid()) or st.st_mode & 0o022:
            raise ContractError('unsafe qualified host policy ancestry')
        if current==home:break
    raw=read_regular(path,65536,owner=path.lstat().st_uid)
    policy=parse(raw.decode())
    if (type(policy) is not dict or type(policy.get('schemaVersion')) is not int or policy['schemaVersion'] != 1 or
            type(policy.get('qualifications')) is not list or len(policy['qualifications'])>100):
        raise ContractError('invalid current native host policy')
    if any(type(row) is not dict for row in policy['qualifications']): raise ContractError('invalid native host qualification row')
    return policy,hashlib.sha256(raw).hexdigest()


FINITE_GIT_ARGV = {'lsFiles':['ls-files','--others','--ignored','--exclude-from=.worktreeinclude','-z'],
                   'checkIgnore':['check-ignore','--stdin','-z']}
FINITE_GIT_TOOLS = {'git':'runtime/git','observer':'runtime/git-observer','gate':'runtime/git-gate.so'}


def finite_git_profile(value):
    """Mirror9b62 strict G DATA parser; no helper/config/readset qualification."""
    def exact(item,keys):
        if type(item) is not dict or set(item)!=set(keys):raise ContractError('invalid finiteGit keys')
        return item
    def text(item):
        if type(item) is not str or '\0' in item:raise ContractError('invalid finiteGit text')
        try:
            item.encode('utf8',errors='strict')
            if len(item.encode('utf-16-le'))//2>4096:raise ContractError('finiteGit text bound')
        except UnicodeError as error:raise ContractError('invalid finiteGit Unicode') from error
        return item
    def absolute(item):
        text(item)
        normalized=posixpath.normpath(item)
        if normalized.startswith('//'):normalized='/'+normalized.lstrip('/')
        if item.endswith('/') and normalized!='/':normalized+='/'
        if not item.startswith('/') or normalized!=item:raise ContractError('invalid finiteGit absolute path')
        return item
    def sha(item):
        if type(item) is not str or not re.fullmatch('[a-f0-9]{64}',item):raise ContractError('invalid finiteGit digest')
    def sequence(item,maximum):
        if type(item) is not list or len(item)>maximum:raise ContractError('finiteGit list bound')
        return item
    def ordered_unique(items):
        return all(before.encode('utf8')<after.encode('utf8') for before,after in zip(items,items[1:]))
    profile=exact(value,('schemaVersion','recipeSha256','recipe'))
    if type(profile['schemaVersion']) is not int or profile['schemaVersion']!=1:raise ContractError('unsupported finiteGit schema')
    sha(profile['recipeSha256'])
    recipe=exact(profile['recipe'],('contract','distributionManifestSha256','systemClosureSha256','tools','argv',
        'repository','environment','configRoots','includes','files','protectedAbsent'))
    if recipe['contract']!='worktree-include-git-config-v1':raise ContractError('unsupported finiteGit contract')
    sha(recipe['distributionManifestSha256']);sha(recipe['systemClosureSha256'])
    if type(recipe['tools']) is not dict or recipe['tools']!=FINITE_GIT_TOOLS or type(recipe['argv']) is not dict or recipe['argv']!=FINITE_GIT_ARGV:
        raise ContractError('finiteGit literal tools/argv mismatch')
    repository=exact(recipe['repository'],('cwd','gitDirectory','layout'))
    absolute(repository['cwd']);absolute(repository['gitDirectory'])
    if repository['layout']!='direct-dotgit-v1' or repository['gitDirectory']!=repository['cwd']+'/.git':
        raise ContractError('unsupported finiteGit repository layout')
    environment=recipe['environment']
    if type(environment) is not dict or len(environment)>32:raise ContractError('finiteGit environment bound')
    for key,item in environment.items():
        if type(key) is not str or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}',key):raise ContractError('invalid finiteGit environment name')
        text(item)
    if len(builtin_json(environment))>32768:raise ContractError('finiteGit environment bytes bound')
    roots=exact(recipe['configRoots'],('system','global','local'))
    for item in roots.values():absolute(item)
    if (roots['local']!=repository['gitDirectory']+'/config' or roots['system']!=environment.get('GIT_CONFIG_SYSTEM') or
            roots['global']!=environment.get('GIT_CONFIG_GLOBAL')):raise ContractError('finiteGit original config roots mismatch')
    includes=sequence(recipe['includes'],32)
    for edge in includes:
        exact(edge,('from','to'));absolute(edge['from']);absolute(edge['to'])
    files=sequence(recipe['files'],64);total=0
    for row in files:
        exact(row,('path','mode','size','sha256'));absolute(row['path']);sha(row['sha256'])
        if (type(row['mode']) is not int or row['mode']!=0o444 or type(row['size']) is not int or not 0<=row['size']<=1048576):
            raise ContractError('invalid finiteGit file identity')
        total+=row['size']
    absent=sequence(recipe['protectedAbsent'],64)
    for item in absent:absolute(item)
    paths=[row['path'] for row in files];known=set(paths)
    if (not ordered_unique(paths) or not ordered_unique(absent) or total>8*1048576 or any(item in known for item in absent) or
            any(item not in known for item in roots.values()) or any(edge['from'] not in known or edge['to'] not in known for edge in includes)):
        raise ContractError('incomplete or duplicate finiteGit config coverage')
    encoded=builtin_json(recipe)
    if len(encoded)>65536 or hashlib.sha256(encoded).hexdigest()!=profile['recipeSha256']:
        raise ContractError('finiteGit canonical recipe digest/bound mismatch')
    return parse(canonical(profile).decode())


SHERPA_RECORD = 'native-provenance/sherpa-addon-adaptation.json'
SHERPA_MEMBER = 'node_modules/sherpa-onnx-linux-x64/sherpa-onnx.node'
SHERPA_ORIGINAL = 'c139574c7a2323710bdd647c5ee27c200669fa4f65f205d8b04eda12a63fece2'
SHERPA_REVISION = '86d3d00e28c22c102fb7d01c7b62fdc4e7a69f1b'
SHERPA_DEPENDENCIES = (
    ('libsherpa-onnx-c-api.so',5558624,'a1675fd6d4cb726db0bbed629325c1f871387ddcdba668529601ea1af02e300e'),
    ('libsherpa-onnx-cxx-api.so',224984,'ce4dd50ab292b2d33c258af894ee5bb39b3ca7000977d2420716864a3fcaaf4f'),
    ('libonnxruntime.so',23665137,'7a6019216c8b6194101291ab8cd1ad9803f087306b10f6f0ef384c52fe879138'))
# Independently fetched immutable primary text identities; source data, not approval.
SHERPA_SOURCES = (
    ('sherpa-LICENSE.txt','k2-fsa/sherpa-onnx',SHERPA_REVISION,'LICENSE',11358,'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'),
    ('sherpa-cmake.txt','k2-fsa/sherpa-onnx',SHERPA_REVISION,'scripts/node-addon-api/CMakeLists.txt',2721,'6f1c24f3539e6b29f90ff24f26c17a8132054247b85e140e37a8c79fcfb9c98d'),
    ('sherpa-publish.txt','k2-fsa/sherpa-onnx',SHERPA_REVISION,'.github/scripts/node-addon/run.sh',1313,'c87cec7dbe4bcfb93a602ede19948cde0052c695d88e860c35f8fedff5e2a54d'),
    ('sherpa-cpu-session.txt','k2-fsa/sherpa-onnx',SHERPA_REVISION,'sherpa-onnx/csrc/session.cc',12252,'eb68f2f1700924e7c70b0b5cca99beac300bd79616b10b62e1ef423b237d7fa8'),
    ('sherpa-ort-recipe.txt','k2-fsa/sherpa-onnx',SHERPA_REVISION,'cmake/onnxruntime-linux-x86_64.cmake',2785,'cda3b8e81009ae0d412d32b74ef9771b434a594bf8f02dfd18ee36fd4212a157'),
    ('ort-provider-bridge.txt','csukuangfj/onnxruntime','a83fc4d58cb48eb68890dd689f94f28288cf2278','onnxruntime/core/session/provider_bridge_ort.cc',187818,'43a225c2ba2dc315a4dbc482eafd5f03592b47f4be616fdb37640e2e33ead4e1'),
    ('ort-posix-loader.txt','csukuangfj/onnxruntime','a83fc4d58cb48eb68890dd689f94f28288cf2278','onnxruntime/core/platform/posix/env.cc',21269,'caefd940d3aab8fff978e448084948ad47268c36353a768ae3b77340a10b2bdb'),
    ('ort-custom-ops.txt','csukuangfj/onnxruntime','a83fc4d58cb48eb68890dd689f94f28288cf2278','onnxruntime/core/session/abi_session_options.cc',16639,'4f722caf98e04fd6b64fa6201d9f9a91c4e74e4cecb8a31a7f3645061f01fc64'))


def sherpa_adaptation_record(raw,manifest):
    """522ba78 strict finite DATA; never parses/adapts/loads an ELF or grants admission."""
    def fail(): raise ContractError('invalid copied Sherpa record or manifest binding')
    def exact(value,keys):
        if type(value) is not dict or set(value)!=set(keys):fail()
        return value
    def number(value,maximum=2**53-1):
        if type(value) is not int or not 0<=value<=maximum:fail()
    def text(value,maximum=4096):
        if type(value) is not str or '\0' in value:fail()
        try:
            if len(value.encode('utf8'))>maximum:fail()
        except UnicodeError:fail()
    def sha(value):
        if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):fail()
    def sequence(value,maximum):
        if type(value) is not list or len(value)>maximum:fail()
        return value
    def file_identity(value,path,maximum):
        exact(value,('path','mode','size','sha256'));number(value['size'],maximum);sha(value['sha256'])
        if (type(value['mode']) is not int or value['mode']!=0o444 or value['path']!=path or
                files.get(path)!=value or helpers.get(path)!=value):fail()
        return value
    def metadata(value,size):
        exact(value,('dynamicNames','versionNames','executableLoads','header','programs','sections','dynamicTags'))
        for key in ('dynamicNames','versionNames'):
            for item in sequence(value[key],131072):text(item)
        header=exact(value['header'],('identity','entry','flags'))
        if (type(header['identity']) is not str or not re.fullmatch('[a-f0-9]{48}',header['identity']) or
                not header['identity'].startswith('7f454c46020101') or header['identity'][32:40]!='03003e00'):fail()
        number(header['entry']);number(header['flags'],2**32-1)
        for row in sequence(value['programs'],128):
            exact(row,('type','flags','offset','address','fileSize','memorySize','alignment'))
            for item in row.values():number(item)
            if row['offset']+row['fileSize']>size or row['fileSize']>row['memorySize'] or row['type']==3:fail()
            if row['type']==1 and row['flags']&3==3:fail()
        if not value['programs']:fail()
        for row in sequence(value['sections'],512):
            exact(row,('nameOffset','type','flags','address','offset','size','alignment','entrySize','name','loadFlags','relro','sha256'))
            for key in ('nameOffset','type','flags','address','offset','size','alignment','entrySize'):number(row[key])
            text(row['name'])
            if type(row['relro']) is not bool:fail()
            for item in sequence(row['loadFlags'],128):number(item,7)
            if row['type']==8:
                if row['sha256'] is not None:fail()
            else:
                sha(row['sha256'])
                if row['offset']+row['size']>size:fail()
        if not value['sections']:fail()
        for row in sequence(value['executableLoads'],128):
            exact(row,('address','fileSize','memorySize','flags','sha256'));sha(row['sha256'])
            for key in ('address','fileSize','memorySize','flags'):number(row[key])
            if row['fileSize']>size or row['fileSize']>row['memorySize'] or row['flags']&3!=1:fail()
        if not value['executableLoads']:fail()
        for row in sequence(value['dynamicTags'],65536):
            exact(row,('tag','value'));number(row['tag'])
            if row['tag'] in (1,14,15,29):text(row['value'])
            else:number(row['value'])
        return value
    if type(raw) is not bytes or not 0<len(raw)<=4*1024*1024:fail()
    try:record=parse(raw.decode('utf8'))
    except (ValueError,UnicodeError,RecursionError) as error:raise ContractError('invalid copied Sherpa JSON') from error
    try:
        if builtin_json(record)!=raw:fail()
    except RecursionError as error:raise ContractError('copied Sherpa JSON nesting bound') from error
    exact(record,('schemaVersion','recipeId','recipeSha256','recipe','output'))
    if type(record['schemaVersion']) is not int or record['schemaVersion']!=1 or record['recipeId']!='sherpa-onnx-linux-x64-1.12.28-origin-v1':fail()
    sha(record['recipeSha256'])
    files={};helpers={}
    for key,target in (('files',files),('helperInventory',helpers)):
        for row in sequence(manifest.get(key),22000):
            if type(row) is not dict or type(row.get('path')) is not str or row['path'] in target:fail()
            target[row['path']]=row
    identity=files.get(SHERPA_RECORD)
    file_identity(identity,SHERPA_RECORD,4*1024*1024)
    if identity['size']!=len(raw) or identity['sha256']!=hashlib.sha256(raw).hexdigest():fail()
    recipe=exact(record['recipe'],('package','member','original','transformation','sources','dependencies'))
    if (recipe['package']!={'name':'sherpa-onnx-linux-x64','version':'1.12.28',
            'integrity':'sha512-+7ZwpAqQYz5fjNQ13F9+sR11zKo6+HhOa1OvT+F4g4PjmoCS1o3YYQqT4JZuLeNRWAY6kKn4IXGWLx93K+OV7A==',
            'sourceRevision':SHERPA_REVISION} or recipe['member']!=SHERPA_MEMBER or
            hashlib.sha256(builtin_json(recipe)).hexdigest()!=record['recipeSha256']):fail()
    before=exact(recipe['original'],('sha256','size','provenance','metadata'))
    if type(before['size']) is not int or before['size']!=840296 or before['sha256']!=SHERPA_ORIGINAL:fail()
    file_identity(before['provenance'],'native-provenance/sherpa-addon-original.gz',2*1024*1024)
    tool=exact(recipe['transformation'],('tool','argv','toolSha256','toolSize','toolVersion','toolProvenance'))
    if tool['tool']!='patchelf' or tool['argv']!=['--set-rpath','$ORIGIN',SHERPA_MEMBER]:fail()
    sha(tool['toolSha256']);number(tool['toolSize'],16*1024*1024);text(tool['toolVersion'],4096)
    if not tool['toolSize'] or not re.fullmatch(r'patchelf [^\s\x00-\x1f]+',tool['toolVersion']):fail()
    file_identity(tool['toolProvenance'],'native-provenance/patchelf-build-tool.gz',17*1024*1024)
    sources=sequence(recipe['sources'],8)
    if len(sources)!=8:fail()
    for row,(name,repo,revision,member,size,digest) in zip(sources,SHERPA_SOURCES):
        exact(row,('url','sha256','retained'))
        if row['url']!=f'https://raw.githubusercontent.com/{repo}/{revision}/{member}' or row['sha256']!=digest:fail()
        retained=file_identity(row['retained'],'native-provenance/'+name,1024*1024)
        if retained['size']!=size or retained['sha256']!=digest:fail()
    dependencies=sequence(recipe['dependencies'],3)
    if len(dependencies)!=3:fail()
    closure=manifest.get('systemClosure')
    if type(closure) is not dict or type(closure.get('loaderResolution')) is not dict:fail()
    layout=closure['loaderResolution'].get('elf')
    if type(layout) is not list:fail()
    elfs={}
    for row in layout:
        if type(row) is not dict or type(row.get('member')) is not str or row['member'] in elfs:fail()
        elfs[row['member']]=row
    for row,(name,size,digest) in zip(dependencies,SHERPA_DEPENDENCIES):
        exact(row,('path','sha256','size','metadata'));path='node_modules/sherpa-onnx-linux-x64/'+name
        if row['path']!=path or type(row['size']) is not int or row['size']!=size or row['sha256']!=digest:fail()
        actual=files.get(path)
        if type(actual) is not dict or actual.get('mode') not in (0o444,0o555) or actual.get('size')!=size or actual.get('sha256')!=digest or helpers.get(path)!=actual:fail()
        compact=exact(row['metadata'],('machine','interpreter','needed','rpath','runpath','soname'))
        if type(compact['machine']) is not int or compact['machine']!=62 or compact['interpreter'] is not None:fail()
        for key in ('needed','rpath','runpath'):
            for item in sequence(compact[key],128):text(item)
        if compact['soname'] is not None:text(compact['soname'])
        if elfs.get(path)!={'member':path,**compact}:fail()
    output=exact(record['output'],('sha256','size','metadata'));sha(output['sha256']);number(output['size'],2*1024*1024)
    actual=files.get(SHERPA_MEMBER)
    if (not output['size'] or type(actual) is not dict or actual.get('mode') not in (0o444,0o555) or
            actual.get('size')!=output['size'] or actual.get('sha256')!=output['sha256'] or helpers.get(SHERPA_MEMBER)!=actual):fail()
    old=metadata(before['metadata'],840296);new=metadata(output['metadata'],output['size'])
    tags=lambda meta,tag:[row['value'] for row in meta['dynamicTags'] if row['tag']==tag]
    if (tags(old,29)!=['$ORIGIN:/home/runner/work/sherpa-onnx/sherpa-onnx/build/install/lib:'] or
            tags(new,29)!=['$ORIGIN'] or tags(old,15) or tags(new,15) or tags(old,14)!=['sherpa-onnx.node'] or
            tags(old,1)!=['libsherpa-onnx-c-api.so','libstdc++.so.6','libgcc_s.so.1','libc.so.6']):fail()
    for key in ('header','dynamicNames','versionNames','executableLoads'):
        if old[key]!=new[key]:fail()
    stable_tags=lambda meta:[row for row in meta['dynamicTags'] if row['tag'] not in (5,10,29)]
    if stable_tags(old)!=stable_tags(new):fail()
    allocated=lambda meta:sorted([{key:row[key] for key in ('name','type','flags','address','size','alignment','entrySize','sha256','loadFlags','relro')}
        for row in meta['sections'] if row['flags']&2 and row['name'] not in ('.dynstr','.dynamic')],key=lambda row:row['name'])
    protection=lambda meta:[{key:row[key] for key in ('name','flags','loadFlags','relro')} for row in meta['sections'] if row['name'] in ('.dynstr','.dynamic')]
    programs=lambda meta:[{key:row[key] for key in ('type','flags','address','memorySize')} for row in meta['programs'] if row['type'] in (7,0x6474e551,0x6474e552,0x6474e553)]
    if allocated(old)!=allocated(new) or protection(old)!=protection(new) or programs(old)!=programs(new):fail()
    if elfs.get(SHERPA_MEMBER)!={'member':SHERPA_MEMBER,'machine':62,'interpreter':None,
            'needed':tags(new,1),'rpath':[],'runpath':['$ORIGIN'],'soname':'sherpa-onnx.node'}:fail()
    table=manifest.get('builtinModuleTable')
    if type(table) is not dict or table.get('recipe')!={**BUILTIN_RECIPE,'copiedSherpaAddonRecipeSha256':identity['sha256']}:fail()
    return record


def verify_sherpa_adaptation(manifest,root):
    """Read measured sealed provenance only; never executes the recorded tool/input."""
    rows=[row for row in manifest['files'] if row['path']==SHERPA_RECORD]
    if not rows:
        table=manifest.get('builtinModuleTable')
        if type(table) is dict and type(table.get('recipe')) is dict and 'copiedSherpaAddonRecipeSha256' in table['recipe']:
            raise ContractError('copied Sherpa record missing')
        return None
    raw=read_regular(root/SHERPA_RECORD,4*1024*1024,owner=0)
    record=sherpa_adaptation_record(raw,manifest)
    # Bounded gzip data verification, single stream, no paths/extraction or ELF resolver.
    import zlib
    recipe=record['recipe']
    for identity,size,digest in ((recipe['original']['provenance'],840296,SHERPA_ORIGINAL),
            (recipe['transformation']['toolProvenance'],recipe['transformation']['toolSize'],recipe['transformation']['toolSha256'])):
        compressed=read_regular(root/identity['path'],identity['size'],owner=0)
        if len(compressed)!=identity['size'] or hashlib.sha256(compressed).hexdigest()!=identity['sha256']:
            raise ContractError('copied Sherpa compressed provenance mismatch')
        try:
            decoder=zlib.decompressobj(31);data=decoder.decompress(compressed,size+1)
            if len(data)!=size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or hashlib.sha256(data).hexdigest()!=digest:
                raise ContractError('copied Sherpa uncompressed provenance mismatch')
        except zlib.error as error:raise ContractError('invalid copied Sherpa gzip provenance') from error
    return record


def builtin_manifest_identities(manifest,config,host_policy):
    """Map verified manifest bytes plus current protected native profiles, never wire."""
    rows=[row for row in host_policy['qualifications'] if row.get('immutableRoot')==config['distributionRoot']]
    if len(rows)!=1: raise ContractError('ambiguous or absent protected native qualification')
    row=rows[0]
    if (row.get('immutabilityAdapter') != 'linux-root-owned-retained-v1' or
            row.get('manifestSha256') != config['distributionSha256'] or
            row.get('distributionBuildId') != config['distributionBuildId'] or
            row.get('qualificationSha256') != config['closure']['qualificationSha256']):
        raise ContractError('current native host identity mismatch')
    profiles=row.get('builtinProfiles')
    if type(profiles) is not list or len(profiles)!=14: raise ContractError('all14 protected builtin profiles required')
    by_id={}
    for profile in profiles:
        fields={'id','sourceSha256','serverBundleSha256','moduleTableSha256','activityContract','profileSha256'}
        if (type(profile) is not dict or set(profile) not in (fields,fields|{'finiteGit'}) or
                type(profile['id']) is not str or profile['id'] not in BUILTIN_IDS or profile['id'] in by_id or
                profile['activityContract'] != 'builtin-in-process-v1' or
                any(type(profile[key]) is not str or not re.fullmatch('[a-f0-9]{64}',profile[key])
                    for key in ('sourceSha256','serverBundleSha256','moduleTableSha256','profileSha256'))):
            raise ContractError('invalid protected builtin profile')
        if 'finiteGit' in profile:
            if profile['id']!='worktree-include':raise ContractError('finiteGit profile belongs only to worktree-include')
            finite_git_profile(profile['finiteGit'])
        by_id[profile['id']]=profile
    files={item['path']:item for item in manifest['files']}
    recipe=dict(BUILTIN_RECIPE)
    if SHERPA_RECORD in files:
        verify_sherpa_adaptation(manifest,Path(config['distributionRoot']))
        recipe['copiedSherpaAddonRecipeSha256']=files[SHERPA_RECORD]['sha256']
    table={'schemaVersion':1,'recipe':recipe,'runtimeSha256':manifest['runtime']['sha256'],
           'daemonSha256':files.get('daemon.mjs',{}).get('sha256'),'externalLibraries':manifest['externalLibraries']}
    if 'systemClosure' in manifest or 'systemClosureSha256' in manifest:
        system_closure_metadata(manifest)
        table['systemClosureSha256']=manifest['systemClosureSha256']
    table_sha=hashlib.sha256(builtin_json(table)).hexdigest()
    if (manifest.get('builtinPlugins') != list(BUILTIN_IDS) or manifest.get('builtinModuleTable') != table or
            manifest.get('moduleTableSha256') != table_sha or type(manifest.get('builtinArtifacts')) is not list or
            len(manifest['builtinArtifacts'])!=14):
        raise ContractError('actual builtin module table/inventory mismatch')
    result={}
    keys={'moduleTableSha256','sourceIdentityPath','id','sourceSha256','serverBundleSha256',
          'originalServerBundleSha256','factoryPath','manifestPath','metafilePath','moduleImports'}
    for plugin,artifact in zip(BUILTIN_IDS,manifest['builtinArtifacts']):
        prefix='builtin-compiled/'+plugin
        profile=by_id[plugin]
        if 'finiteGit' in profile:
            recipe=finite_git_profile(profile['finiteGit'])['recipe']
            if (recipe['distributionManifestSha256']!=config['distributionSha256'] or
                    recipe['systemClosureSha256']!=manifest.get('systemClosureSha256')):
                raise ContractError('finiteGit actual distribution/system closure mismatch')
            for role,member in FINITE_GIT_TOOLS.items():
                tool=files.get(member)
                if type(tool) is not dict or tool.get('mode') not in ((0o555,) if role in ('git','observer') else (0o444,0o555)):
                    raise ContractError('finiteGit actual retained tool identity missing')
        if (type(artifact) is not dict or set(artifact)!=keys or artifact['id']!=plugin or
                artifact['moduleTableSha256']!=table_sha or
                artifact['factoryPath']!=prefix+'/server.factory.js' or artifact['manifestPath']!=prefix+'/manifest.json' or
                artifact['metafilePath']!=prefix+'/metafile.json' or artifact['sourceIdentityPath']!=prefix+'/source-identity.json' or
                type(artifact['moduleImports']) is not list or len(artifact['moduleImports'])>1000 or
                any(type(item) is not str for item in artifact['moduleImports']) or
                files.get(artifact['factoryPath'],{}).get('sha256')!=artifact['serverBundleSha256'] or
                files.get(prefix+'/server-original.js',{}).get('sha256')!=artifact['originalServerBundleSha256'] or
                files.get(artifact['sourceIdentityPath'],{}).get('sha256')!=artifact['sourceSha256'] or
                artifact['manifestPath'] not in files or artifact['metafilePath'] not in files or
                'builtin-plugins/'+plugin+'/paseo-plugin.json' not in files or
                any(artifact[key]!=profile[key] for key in ('sourceSha256','serverBundleSha256','moduleTableSha256'))):
            raise ContractError('retained builtin artifact/profile mismatch')
        result[plugin]={'kind':'builtin-in-process','contract':'builtin-in-process-v1',
            'distributionBuildId':config['distributionBuildId'],'sourcePath':str(Path(config['distributionRoot'])/'builtin-plugins'/plugin),
            **{key:profile[key] for key in ('sourceSha256','serverBundleSha256','moduleTableSha256','profileSha256')},'closure':config['closure']}
    return result


def system_closure_metadata(manifest):
    """Mirror cf96 structural/backing cross references; never approves a namespace."""
    def exact(value,keys):
        if type(value) is not dict or set(value)!=set(keys):raise ContractError('invalid systemClosure keys')
        return value
    def text(value):
        if type(value) is not str or not 1<=len(value)<=4096 or '\0' in value:raise ContractError('invalid systemClosure text')
        try:value.encode('utf8',errors='strict')
        except UnicodeError as error:raise ContractError('invalid systemClosure Unicode') from error
        return value
    def path(value,absolute):
        text(value)
        if posixpath.isabs(value)!=absolute or posixpath.normpath(value)!=value or any(part in ('.','..') for part in value.split('/')):
            raise ContractError('unsafe systemClosure path')
        return value
    def sequence(value,maximum):
        if type(value) is not list or len(value)>maximum:raise ContractError('systemClosure bound exceeded')
        return value
    def number(value,maximum):
        if type(value) is not int or not 0<=value<=maximum:raise ContractError('invalid systemClosure integer')
    def sha(value):
        if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):raise ContractError('invalid systemClosure digest')
    def unique(values):
        if len(values)!=len(set(values)):raise ContractError('duplicate systemClosure identity')
    closure=exact(manifest.get('systemClosure'),('schemaVersion','profile','loaderResolution'))
    if type(closure['schemaVersion']) is not int or closure['schemaVersion']!=1 or closure['profile']!='linux-retained-system-closure-v1':
        raise ContractError('unsupported systemClosure profile')
    sha(manifest.get('systemClosureSha256'))
    if hashlib.sha256(builtin_json(closure)).hexdigest()!=manifest['systemClosureSha256']:
        raise ContractError('canonical systemClosure digest mismatch')
    layout=exact(closure['loaderResolution'],('schemaVersion','policy','elf','interpreters','aliases','searchDirectories','hwcaps','cache','preload'))
    if type(layout['schemaVersion']) is not int or layout['schemaVersion']!=1 or layout['policy']!='glibc-pinned-cache-existing-layout-v1':
        raise ContractError('unsupported loader resolution policy')
    if layout['hwcaps']!={'policy':'no-relevant-hwcaps-v1'} or layout['preload']!={'path':'/etc/ld.so.preload','state':'absent'}:
        raise ContractError('unsupported loader selection/preload policy')
    files=manifest.get('files')
    if type(files) is not list or any(type(row) is not dict or type(row.get('path')) is not str for row in files):
        raise ContractError('invalid systemClosure file inventory')
    unique([row['path'] for row in files]);by_path={row['path']:row for row in files}
    external=sequence(manifest.get('externalLibraries'),128);total=0
    for row in external:
        exact(row,('path','retainedPath','mode','size','sha256'));path(row['path'],True);path(row['retainedPath'],False)
        if type(row['mode']) is not int or row['mode'] not in (0o444,0o555):raise ContractError('unsealed retained external mode')
        number(row['size'],536870912);sha(row['sha256']);total+=row['size']
        if row['retainedPath']!='system-closure/elf/'+row['path'][1:]:raise ContractError('retained external path binding mismatch')
    unique([row['path'] for row in external]);unique([row['retainedPath'] for row in external])
    if not external or total>536870912:raise ContractError('retained external payload bound')
    elfs=sequence(layout['elf'],512)
    for row in elfs:
        exact(row,('member','machine','interpreter','needed','rpath','runpath','soname'));path(row['member'],False)
        if type(row['machine']) is not int or row['machine'] not in (62,183):raise ContractError('unsupported ELF machine')
        for key in ('interpreter','soname'):
            if row[key] is not None:text(row[key])
        for key in ('needed','rpath','runpath'):
            for item in sequence(row[key],128):text(item)
        if row['member'] not in by_path:raise ContractError('ELF member absent from retained inventory')
    unique([row['member'] for row in elfs])
    interpreters=sequence(layout['interpreters'],32)
    for row in interpreters:
        exact(row,('request','target'));path(row['request'],True);path(row['target'],True)
        if not any(item['path']==row['target'] and item['mode']==0o555 for item in external):
            raise ContractError('retained ELF interpreter unavailable')
    unique([row['request'] for row in interpreters])
    directories=sequence(layout['searchDirectories'],64)
    for row in directories:
        exact(row,('kind','path'))
        if row['kind'] not in ('system','retained'):raise ContractError('invalid loader search kind')
        path(row['path'],row['kind']=='system')
    unique([(row['kind'],row['path']) for row in directories])
    aliases=sequence(layout['aliases'],512)
    for row in aliases:
        exact(row,('path','target','linkText'));path(row['path'],True);path(row['target'],True);text(row['linkText'])
        if not any(item['path']==row['target'] for item in external) and not any(item['kind']=='system' and item['path']==row['target'] for item in directories):
            raise ContractError('unbound loader alias target')
    unique([row['path'] for row in aliases])
    cache=exact(layout['cache'],('path','retainedPath','mode','size','sha256','entries'))
    if cache['path']!='/etc/ld.so.cache' or cache['retainedPath']!='system-closure/loader/ld.so.cache' or type(cache['mode']) is not int or cache['mode']!=0o444:
        raise ContractError('unsupported retained loader cache')
    number(cache['size'],16777216);sha(cache['sha256'])
    for row in sequence(cache['entries'],2048):
        exact(row,('soname','path','target','flags','hwcap'));text(row['soname']);path(row['path'],True);path(row['target'],True)
        if type(row['flags']) is not int or abs(row['flags'])>2**53-1 or row['hwcap']!='0':raise ContractError('unsupported loader cache selection')
    for row in [*external,cache]:
        expected={'path':row['retainedPath'],**{key:row[key] for key in ('mode','size','sha256')}}
        if by_path.get(row['retainedPath'])!=expected:raise ContractError('retained system backing cross-reference mismatch')
    return closure


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
    retained_system=type(manifest) is dict and ('systemClosure' in manifest or 'systemClosureSha256' in manifest)
    if retained_system:system_closure_metadata(manifest)
    if (type(manifest) is not dict or manifest.get('schemaVersion') != 2 or manifest.get('profile') != 'enclosing-daemon-v2' or
            manifest.get('distributionBuildId') != config['distributionBuildId'] or
            manifest.get('entries') != {'daemon':'daemon.mjs','pluginChild':'plugin-child-entry.mjs','compiler':'compiler-entry.mjs','terminal':'terminal-entry.mjs'}):
        raise ContractError('unsupported enclosing distribution manifest')
    binding_keys = sorted(['@getpaseo/plugin/internal/activity','@getpaseo/plugin','@getpaseo/plugin/server',
        '@getpaseo/plugin/server/provider','@getpaseo/plugin/server/acp','@getpaseo/plugin/server/usage',
        '@getpaseo/client','@getpaseo/client/internal/daemon-client','@getpaseo/protocol/binary-frames/index','zod'])
    adapted=type(manifest.get('files')) is list and any(type(row) is dict and row.get('path')==SHERPA_RECORD for row in manifest['files'])
    if adapted:binding_keys=sorted([*binding_keys,'@getpaseo/plugin/internal/builtin-helper'])
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
        if retained_system:
            verify({'path':item['retainedPath'],**{key:item[key] for key in ('mode','size','sha256')}})
        else:verify(item, True)
        if item['path'] in external_names: raise ContractError('duplicate external library')
        external_names.add(item['path'])
    helpers = [item for item in files if item['path'].startswith('runtime/') or
        (adapted and (item['path'].startswith(('system-closure/','native-provenance/')) or re.search(r'\.so(?:\.[0-9]+)*$',item['path']))) or
        re.search(r'(?:compiler|terminal)-(?:entry|code)\.mjs$', item['path']) or item['path'].endswith('.node') or
        item['path'].endswith('spawn-helper') or item['path'].startswith('node_modules/esbuild/') or
        item['path'] == 'node_modules/typescript/lib/typescript.js'] + external
    helpers.sort(key=lambda item: item['path'].encode('utf-16-be'))
    producer_json = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    helper_digest = hashlib.sha256(producer_json(helpers)).hexdigest()
    if (producer_json(manifest.get('helperInventory')) != producer_json(helpers) or
            manifest.get('helperClosureSha256') != helper_digest or helper_digest != config['closure']['helperClosureSha256']):
        raise ContractError('explicit native/helper inventory mismatch')
    verify_sherpa_adaptation(manifest,root)
    if read_regular(manifest_path, 4 * 1024 * 1024, owner=0) != raw_manifest:
        raise ContractError('distribution authority changed during verification')
    return manifest


# Independently reviewed native389/d8 source identities, not supplied by artifact JSON.
# A changed helper requires a separately reviewed adapter source update.
READONLY_NAMESPACE_SHA256 = '605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7'
READONLY_NAMESPACE_SIZE = 52756
READONLY_NAMESPACE_IDENTITIES = frozenset({
    (READONLY_NAMESPACE_SIZE, READONLY_NAMESPACE_SHA256),
    (53480, '4f9164025314df755116ed09330a9d2c5d7b0d7ad3bc18c9abd28345b99001cf'),
})


def verify_readonly_namespace(config, manifest):
    """Invoke only the fixed packaged port from two reviewed sources; no resolver copy."""
    if type(manifest) is not dict:
        if config.get('cohortVersion')==2:raise ContractError('verified V2 transport manifest absent')
        return
    if 'systemClosure' not in manifest and 'systemClosureSha256' not in manifest:return
    root=Path(config['distributionRoot'])
    member='system-closure/namespace-bootstrap.py'
    rows=[row for row in manifest['files'] if row['path']==member]
    if (len(rows)!=1 or rows[0]['mode']!=0o444 or type(rows[0].get('size')) is not int or type(rows[0].get('sha256')) is not str or
            (rows[0]['size'],rows[0].get('sha256')) not in READONLY_NAMESPACE_IDENTITIES):
        raise ContractError('independently reviewed namespace verifier identity required')
    path=protected_root_path(root/member)
    if stat.S_IMODE(path.lstat().st_mode)!=0o444:raise ContractError('namespace verifier actual mode mismatch')
    source=read_regular(path,rows[0]['size'],owner=0)
    if (len(source),hashlib.sha256(source).hexdigest())!=(rows[0]['size'],rows[0]['sha256']):
        raise ContractError('namespace verifier member identity mismatch')
    name='_ade_retained_namespace_'+rows[0]['sha256']
    module=types.ModuleType(name)
    module.__file__=str(path)
    previous=sys.modules.get(name)
    sys.modules[name]=module  # dataclass introspection requires the exact executing module.
    try:
        # Definitions-only, measured shared helper. Never __main__/Admin/launch dispatch.
        exec(compile(source,str(path),'exec'),module.__dict__)
        verify=getattr(module,'verify_existing_namespace',None)
        if not callable(verify) or verify(str(root),config['distributionSha256']) is not None:
            raise ContractError('readonly namespace verification refused')
        if read_regular(path,rows[0]['size'],owner=0)!=source or stat.S_IMODE(path.lstat().st_mode)!=0o444:
            raise ContractError('namespace verifier source changed during check')
    except BaseException as error:
        # Every helper refusal/exception is HOLD, never an authority/result object.
        raise ContractError('actual readonly namespace verification refused') from error
    finally:
        if previous is None:sys.modules.pop(name,None)
        else:sys.modules[name]=previous


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

def cohort_v2_observation(value, config, expected, target, manifest_identities, *, allow_target_absent=False):
    """Pure V2 qualification parser, NOT a producer or transport authority factory.

    manifest_identities must be independently extracted from verified actual manifest
    bytes by the trusted producer adapter. That production mapping is not available
    yet; callers must HOLD rather than copying identities from wire or enrollment.
    Returns original tagged V2 data; directory unwrapping is private validation only.
    """
    if type(config.get('cohortVersion')) is not int or config['cohortVersion'] != 2:
        raise ContractError('protected cohort V2 opt-in required')
    if (type(value) is not dict or set(value) != {'version','consistency','observationEpoch','enclosing','entries'} or
            type(value['version']) is not int or value['version'] != 2 or value['consistency'] != 'coherent' or
            type(value['observationEpoch']) is not int or not 0 <= value['observationEpoch'] < 2**53 or
            type(value['entries']) is not list or len(value['entries']) > 1000):
        raise ContractError('cohort V2 observation uncertain')
    builtin_expected = {key:record for key,record in expected.items()
                        if type(record) is dict and record.get('kind') == 'builtin-in-process'}
    if (len(builtin_expected) != 14 or target in builtin_expected or 'paseo' in builtin_expected or
            type(manifest_identities) is not dict or set(manifest_identities) != set(builtin_expected)):
        raise ContractError('complete independently verified builtin inventory required')
    loaded_keys = {'kind','pluginId','instanceId','enclosingIncarnation','sourcePath','sourceSha256',
                   'serverBundleSha256','moduleTableSha256','profileSha256','closure'}
    stable_keys = (loaded_keys - {'pluginId','instanceId','enclosingIncarnation'}) | {'contract','distributionBuildId'}
    seen=set(); builtin_seen=set(); instances=set(); directories=[]
    for entry in value['entries']:
        if type(entry) is not dict or type(entry.get('pluginId')) is not str or not entry['pluginId']:
            raise ContractError('invalid V2 cohort ID')
        plugin=entry['pluginId']
        if plugin in seen or plugin == 'paseo': raise ContractError('duplicate V2 cohort ID')
        seen.add(plugin)
        if entry.get('kind') == 'directory':
            if (set(entry) != {'kind','pluginId','registration','enabled','journal','loaded','execution'} or plugin in builtin_expected):
                raise ContractError('invalid V2 directory tag')
            loaded=entry['loaded']; execution=entry['execution']
            if loaded is not None and (type(loaded) is not dict or set(loaded) != {'kind','receipt'} or loaded['kind'] != 'plugin-child'):
                raise ContractError('invalid V2 child loaded tag')
            if execution is not None and (type(execution) is not dict or
                    set(execution) != {'kind','contract','incarnation','distributionBuildId','closure'} or execution['kind'] != 'plugin-child'):
                raise ContractError('invalid V2 child execution tag')
            directories.append(dict(pluginId=plugin,registration=entry['registration'],enabled=entry['enabled'],journal=entry['journal'],
                loaded=None if loaded is None else loaded['receipt'],
                execution=None if execution is None else {key:item for key,item in execution.items() if key != 'kind'}))
        elif entry.get('kind') == 'builtin-in-process':
            if (set(entry) != {'kind','pluginId','registration','enabled','loaded','execution'} or plugin not in builtin_expected or
                    entry['enabled'] is not True):
                raise ContractError('unexpected or disabled builtin cohort member')
            builtin_seen.add(plugin)
            loaded=entry['loaded']; execution=entry['execution']
            if (type(loaded) is not dict or set(loaded) != loaded_keys or type(execution) is not dict or
                    set(execution) != loaded_keys | {'contract','distributionBuildId'} or
                    any(loaded.get(key) != execution.get(key) for key in loaded_keys) or
                    loaded['kind'] != 'builtin-in-process' or loaded['pluginId'] != plugin or
                    execution['contract'] != 'builtin-in-process-v1' or execution['distributionBuildId'] != config['distributionBuildId'] or
                    loaded['enclosingIncarnation'] != config['daemonIncarnation'] or
                    type(loaded['instanceId']) is not str or not loaded['instanceId'] or loaded['instanceId'] in instances):
                raise ContractError('actual builtin instance/execution mismatch')
            instances.add(loaded['instanceId'])
            if any(type(loaded[key]) is not str or not re.fullmatch('[a-f0-9]{64}',loaded[key])
                   for key in ('sourceSha256','serverBundleSha256','moduleTableSha256','profileSha256')):
                raise ContractError('qualified builtin nonnull profile/digests required')
            if closure_identity(loaded['closure']) != config['closure']:
                raise ContractError('builtin enclosing closure mismatch')
            source=str(Path(config['distributionRoot'])/'builtin-plugins'/plugin)
            if (plugin in ('.','..') or '/' in plugin or '\\' in plugin or
                    entry['registration'] != {'path':source} or loaded['sourcePath'] != source):
                raise ContractError('builtin SAME distribution source path required')
            stable={key:execution[key] for key in stable_keys}
            protected={'kind':'builtin-in-process','enabled':True,'loaded':True,
                       'registration':{'path':source},'execution':stable}
            if builtin_expected[plugin] != protected or manifest_identities[plugin] != stable:
                raise ContractError('builtin protected/manifest identity mismatch')
        else:
            raise ContractError('unsupported V2 cohort kind')
    if builtin_seen != set(builtin_expected): raise ContractError('incomplete V2 builtin cohort')
    # Reuse unchanged directory validation/CAS rules; no fake builtin child/journal.
    directory_expected={key:record for key,record in expected.items() if key not in builtin_expected}
    cohort_observation(dict(value,version=1,entries=directories),config,directory_expected,target,allow_target_absent=allow_target_absent)
    return value



def native_reservation_plan(status, config, plugin):
    """Read-only exact native counter snapshot. Null/old generation is never zero."""
    if (type(status) is not dict or type(status.get('schemaVersion')) is not int or status['schemaVersion'] != 1 or
            status.get('state') != 'idle' or status.get('recoveryRequired') is not False or status.get('ready') is not True or
            type(status.get('reservationGeneration')) is not int or not 0 <= status['reservationGeneration'] < 2**53 - 1):
        raise ContractError('qualified native idle reservation unavailable')
    authority = status.get('authority')
    if (type(authority) is not dict or authority.get('qualified') is not True or
            authority.get('serverId') != config['serverId'] or authority.get('daemonIncarnation') != config['daemonIncarnation'] or
            type(authority.get('features')) is not dict or authority['features'].get('maintenanceReservationV1') is not True or
            authority['features'].get('maintenancePluginOperationV1') is not True):
        raise ContractError('native reservation authority unavailable')
    generation = plugin['journal']['generation']
    if type(generation) is not int or not 0 <= generation < 2**53:
        raise ContractError('native plugin CAS unavailable')
    return {'native_generation': status['reservationGeneration'] + 1, 'plugin_generation': generation,
            'server_id': config['serverId'], 'daemon_incarnation': config['daemonIncarnation']}


class NativeKnownBusy(ContractError):
    """Only the retained native CLI's authoritative typed BEGIN refusal."""


class NativeFacade:
    """Bounded retained Linux CLI transport with independent manifest/cohort checks.

    Exact native facts gate each operation; missing producer/API facts hold.
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
        self.context = None
        self.intent = None
        self.original_native = None
        self.known_held = None
        self.read_only_reconciliation = False
        self.host_policy_binding = None
        self.builtin_identities = None
        self.transport_manifest = None

    def supported(self):
        if self.uncertain and not getattr(self, 'read_only_reconciliation', False): return False
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
        if config.get('cohortVersion') == 2:
            # Committed56faaa CLI independently gates server_info observation availability.
            # This feature is not readiness; full manifest/profile/cohort checks still apply.
            value=self._call(['plugin','cohort-v2-status'])
            config=self._transport()  # recheck native policy/retained bytes after transport await
            cohort_v2_observation(value,config,row['cohort'],row['component'],self.builtin_identities,
                                  allow_target_absent=allow_target_absent)
            directories=[]
            for entry in value['entries']:
                if entry['kind']!='directory':continue
                directories.append(dict(pluginId=entry['pluginId'],registration=entry['registration'],enabled=entry['enabled'],journal=entry['journal'],
                    loaded=None if entry['loaded'] is None else entry['loaded']['receipt'],
                    execution=None if entry['execution'] is None else {key:item for key,item in entry['execution'].items() if key!='kind'}))
            # Internal directory view only after validating the COMPLETE tagged union.
            return dict(value,entries=directories,builtinEntries=[entry for entry in value['entries'] if entry['kind']=='builtin-in-process'])
        return cohort_observation(self._call(['plugin', 'cohort-status']), config, row['cohort'], row['component'], allow_target_absent=allow_target_absent)

    def bind(self, row, context, render, *, recovery=False, origin=None):
        self.transaction_row = row
        self.context = context
        self.target = context.target
        self.render = render
        self.recovery_inspection = recovery
        self.read_only_reconciliation = context.kind == 'reconcile-release'
        if origin is not None:
            if self.known_held is not None and self.original_native != origin:
                raise ContractError('private original held identity differs from Journal origin')
            self.original_native = origin
        self.operation = 'recover' if context.kind in ('reconcile','verified-rollback') else 'activate'

    def prepare(self, context):
        try:return self._prepare_bound(context)
        except Exception:
            if self.known_held is not None and context.kind in ('reconcile','verified-rollback'):
                self.uncertain=True;self.known_held=None
            raise

    def _prepare_bound(self, context):
        """Read-only native plan; Journal persists this exact intent BEFORE reserve."""
        if context != self.context or digest(self.reader()) != context.rule_digest:
            raise ContractError('protected rule/context changed before native planning')
        facts = self.cohort_status(allow_target_absent=self.recovery_inspection)
        plugin = next(item for item in facts['entries'] if item['pluginId'] == self.transaction_row['component'])
        status = self._call(['daemon','maintenance','status'])
        config = self._transport()
        if self.known_held is not None and context.kind in ('reconcile','verified-rollback'):
            if not self.token or self.uncertain or not self.original_native:
                raise ContractError('same-held recovery capability unavailable')
            old_context, old_intent = self.original_native
            self._check_same_held(status, old_context, old_intent, plugin)
            generation = plugin['journal']['generation']
            plan = {'native_generation':old_intent.native_generation,'plugin_generation':generation,
                    'server_id':old_intent.server_id,'daemon_incarnation':old_intent.daemon_incarnation}
        else:
            plan = native_reservation_plan(status, config, plugin)
        self.intent = release.ReservationIntent(**plan)
        if digest(self.reader()) != context.rule_digest: raise ContractError('protected rule changed during native planning')
        return self.intent

    def _transport(self):
        config = self.reader()['native']
        if type(config) is not dict: raise ContractError('retained native bridge unavailable')
        binding = digest(config)
        if self.bridge_binding is not None and self.bridge_binding != binding:
            self.uncertain = True
            raise ContractError('retained native bridge changed during transaction')
        manifest=verify_transport_distribution(config)
        if config.get('cohortVersion') == 2:
            host_policy,host_binding=read_native_host_policy()
            if self.host_policy_binding is not None and host_binding!=self.host_policy_binding:
                self.uncertain=True
                raise ContractError('native protected host policy changed during facade lifetime')
            inventory=Path(config['distributionRoot'])/'builtin-plugins'
            actual_ids=sorted(path.name for path in inventory.iterdir() if path.is_dir())
            if actual_ids!=list(BUILTIN_IDS):raise ContractError('actual builtin directory inventory mismatch')
            identities=builtin_manifest_identities(manifest,config,host_policy)
            self.builtin_identities=identities
            self.host_policy_binding=host_binding
        for key in ('node', 'cli'):
            item = config[key]; path = Path(item['path'])
            data = read_regular(path, 256 * 1024 * 1024, owner=0)
            if path.stat().st_mode & 0o222 or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ContractError('retained native bridge identity mismatch')
        self.bridge_binding = binding
        self.transport_manifest = manifest
        return config

    def _call(self, arguments, token=None):
        config = self._transport()
        args = [config['node']['path'], config['cli']['path'], *arguments, '--json']
        env = {'PATH': str(Path(config['node']['path']).parent) + ':/usr/bin:/bin',
               'HOME': pwd.getpwuid(os.getuid()).pw_dir}
        if token is not None and not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise ContractError('invalid private owner token')
        # Last synchronous check before exec: shared port verifies CURRENT namespace.
        verify_readonly_namespace(config,self.transport_manifest)
        with subprocess.Popen(args, stdin=subprocess.PIPE if token is not None else subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as proc:
            deadline = time.monotonic() + 30
            data = bytearray()
            errors = bytearray()
            try:
                if token is not None:
                    # Only <=44 bytes to a private anonymous pipe, never argv/env/file path.
                    proc.stdin.write((token + '\n').encode('ascii')); proc.stdin.close()
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ, (data, 1024 * 1024))
                    selector.register(proc.stderr, selectors.EVENT_READ, (errors, 16384))
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0: raise ContractError('native transport timed out')
                        events = selector.select(remaining)
                        if not events: raise ContractError('native transport timed out')
                        for key, _ in events:
                            buffer, bound = key.data
                            chunk = os.read(key.fileobj.fileno(), min(65536, bound + 1 - len(buffer)))
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            buffer.extend(chunk)
                            if len(buffer) > bound: raise ContractError('native transport output too large')
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise ContractError('native transport timed out')
                try: code = proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired as error: raise ContractError('native transport timed out') from error
                if code:
                    if not data and arguments[:3] == ['daemon', 'maintenance', 'begin']:
                        try: refusal = parse(errors.decode())
                        except (ValueError, UnicodeError): refusal = None
                        if refusal == {'error': {'code': 'MAINTENANCE_KNOWN_BUSY', 'message': 'Maintenance reservation refused'}}:
                            raise NativeKnownBusy('authoritative native known busy')
                    raise ContractError('native transport refused')
                # Native CLI --json contract is one BARE JSON result, not an RPC envelope.
                return parse(data.decode())
            except NativeKnownBusy:
                raise
            except Exception:
                if self.reservation is not None: self.uncertain = True
                raise
            finally:
                if proc.poll() is None: proc.kill()
                proc.wait()

    def status_observation(self, cohort):
        """Stable read-only current identity; never reservation or mutation authority."""
        if self.uncertain:raise ContractError('native observation uncertain')
        config=self._transport()
        before=self.cohort_status()
        target=next((item for item in before['entries'] if item['pluginId']==self.reader()['component']),None)
        if target is None or type(target['journal']) is not dict or target['journal'].get('phase')!='ready':
            raise ContractError('native target journal not ready')
        observed=self.observe(cohort)
        maintenance=self._call(['daemon','maintenance','status'])
        authority=maintenance.get('authority') if type(maintenance) is dict else None
        features=authority.get('features') if type(authority) is dict else None
        if (type(maintenance) is not dict or type(maintenance.get('schemaVersion')) is not int or maintenance['schemaVersion']!=1 or
                maintenance.get('state')!='idle' or maintenance.get('recoveryRequired') is not False or maintenance.get('recoveryOnly') is not None or
                type(maintenance.get('reservationGeneration')) is not int or not 0<=maintenance['reservationGeneration']<2**53 or
                type(authority) is not dict or type(authority.get('schemaVersion')) is not int or authority['schemaVersion']!=1 or authority.get('qualified') is not True or
                type(features) is not dict or any(type(features.get(key)) is not bool for key in ('maintenanceReservationV1','maintenancePluginOperationV1')) or
                authority.get('serverId')!=config['serverId'] or authority.get('daemonIncarnation')!=config['daemonIncarnation']):
            raise ContractError('native qualified idle observation unavailable')
        # Ordinary activity can make promotion unavailable without changing the
        # already executing identity. No readiness/feature bit grants status authority.
        after=self.cohort_status()
        current=self._call(['daemon','maintenance','status'])
        if canonical(before)!=canonical(after) or canonical(maintenance)!=canonical(current):
            raise ContractError('native observation changed')
        return observed

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

    def reserve(self, context, intent):
        if context != self.context or intent != self.intent or self.supported() is not True:
            raise ContractError('native prepared reservation unavailable')
        # Recheck the exact original read-only plan, never rescope a changed counter.
        facts = self.cohort_status(allow_target_absent=self.recovery_inspection)
        plugin = next(item for item in facts['entries'] if item['pluginId'] == self.transaction_row['component'])
        current = native_reservation_plan(self._call(['daemon','maintenance','status']), self._transport(), plugin)
        if release.ReservationIntent(**current) != intent: raise ContractError('native reservation plan stale')
        self.reservation = {'generation':intent.native_generation,'transactionId':context.transaction_id}
        self.plugin_generation = intent.plugin_generation
        self.verified = False
        try:
            result = self._call(['daemon','maintenance','begin', *self._reservation_args_without_token(context, intent)])
        except NativeKnownBusy:
            self.reservation = None
            return release.BeginResult('busy')
        except Exception:
            self.uncertain = True
            raise
        if type(result) is dict and type(result.get('ownerToken')) is str and re.fullmatch('[A-Za-z0-9_-]{43}', result['ownerToken']):
            self.token = result['ownerToken']
        if (type(result) is not dict or result.get('state') != 'held' or result.get('recoveryRequired') is not False or
                result.get('generation') != intent.native_generation or result.get('transactionId') != context.transaction_id or not self.token):
            self.uncertain = True
            raise ContractError('native begin uncertain')
        self.original_native = (context, intent)
        return release.BeginResult('held')

    def _reservation_args_without_token(self, context, intent):
        config = self._transport()
        if config['serverId'] != intent.server_id or config['daemonIncarnation'] != intent.daemon_incarnation:
            raise ContractError('native reservation identity changed')
        return ['--generation',str(intent.native_generation),'--transaction-id',context.transaction_id,*self._identity_args()]

    def finish(self, context, intent):
        if context != self.context or intent != self.intent or not self.verified or self.uncertain or not self.token:
            raise ContractError('native release not verified')
        result = self._call(['daemon','maintenance','end',*self._reservation_args(),'--owner-token-fd','0'],self.token)
        if (type(result) is not dict or result.get('state') != 'idle' or result.get('recoveryRequired') is not False or
                result.get('reservationGeneration') != intent.native_generation or
                result.get('transactionId') != self.reservation['transactionId']):
            self.uncertain = True
            raise ContractError('native end uncertain')
        self.token = None; self.reservation = None; self.known_held = None
        return True

    def released(self, original_context, original_intent):
        if not self.context or self.context.kind != 'reconcile-release': return False
        native_context, native_intent = self.original_native or (original_context, original_intent)
        status = self._call(['daemon','maintenance','status'])
        config = self._transport()
        if (type(status) is not dict or status.get('state') != 'idle' or status.get('recoveryRequired') is not False or
                status.get('ready') is not True or status.get('reservationGeneration') != native_intent.native_generation or
                status.get('transactionId') != native_context.transaction_id or
                config['serverId'] != native_intent.server_id or config['daemonIncarnation'] != native_intent.daemon_incarnation):
            return False
        authority = status.get('authority')
        if (type(authority) is not dict or authority.get('qualified') is not True or
                authority.get('serverId') != native_intent.server_id or authority.get('daemonIncarnation') != native_intent.daemon_incarnation):
            return False
        return self.observe(self.transaction_row['cohort']) == self.context.target

    def _check_same_held(self, status, original_context, original_intent, plugin, *, phase='recover-required'):
        # Current metadata can confirm, never create, the same-process private eligibility.
        restriction = status.get('recoveryOnly') if type(status) is dict else None
        if (not self.known_held or not self.token or self.uncertain or type(restriction) is not dict or
                status.get('state') not in ('held','recovery-required') or status.get('recoveryRequired') is not True or
                status.get('generation') != original_intent.native_generation or status.get('reservationGeneration') != original_intent.native_generation or
                status.get('transactionId') != original_context.transaction_id or
                restriction.get('pluginId') != self.transaction_row['component'] or restriction.get('phase') != phase or
                restriction.get('nativeGeneration') != plugin['journal']['generation'] or
                restriction.get('baseline') != self.known_held['baseline']):
            raise ContractError('same-held recovery restriction unavailable')
        config = self._transport()
        authority = status.get('authority')
        if (config['serverId'] != original_intent.server_id or config['daemonIncarnation'] != original_intent.daemon_incarnation or
                type(authority) is not dict or authority.get('qualified') is not True or
                authority.get('serverId') != original_intent.server_id or authority.get('daemonIncarnation') != original_intent.daemon_incarnation or
                type(authority.get('features')) is not dict or authority['features'].get('maintenanceHeldRecoveryV1') is not True or
                digest(self.reader()) != self.context.rule_digest):
            raise ContractError('same-held native incarnation or authority changed')

    def can_attempt_same_held_recovery(self):
        # No metadata/installed flag creates this private SAME-process capability.
        return bool(self.known_held and self.token and self.original_native and self.reservation and not self.uncertain)

    def _scoped_recovery_supported(self, kind):
        if (kind not in ('recover','verify') or not self.can_attempt_same_held_recovery() or not self.context or
                self.context.kind not in ('reconcile','verified-rollback') or self.context.target!=self.target):
            return False
        facts=self.cohort_status(allow_target_absent=kind=='recover')
        plugin=next(entry for entry in facts['entries'] if entry['pluginId']==self.transaction_row['component'])
        original_context,original_intent=self.original_native
        if (self.reservation != {'generation':original_intent.native_generation,'transactionId':original_context.transaction_id} or
                plugin['journal']['generation']!=self.plugin_generation):
            raise ContractError('scoped recovery original tuple or plugin CAS changed')
        self._check_same_held(self._call(['daemon','maintenance','status']),original_context,original_intent,plugin,
                              phase='recover-required' if kind=='recover' else 'verify-required')
        return True

    def reuse(self, context, intent, original_context, original_intent):
        if (context != self.context or intent != self.intent or self.original_native != (original_context,original_intent) or
                not self.known_held or not self.token or self.uncertain or self.target != context.target or
                intent.native_generation != original_intent.native_generation or intent.server_id != original_intent.server_id or
                intent.daemon_incarnation != original_intent.daemon_incarnation):
            raise ContractError('same live bearer reuse unavailable')
        facts = self.cohort_status(allow_target_absent=True)
        plugin = next(item for item in facts['entries'] if item['pluginId'] == self.transaction_row['component'])
        self._check_same_held(self._call(['daemon','maintenance','status']),original_context,original_intent,plugin)
        if plugin['journal']['generation'] != intent.plugin_generation: raise ContractError('same-held plugin CAS stale')
        self.reservation = {'generation':original_intent.native_generation,'transactionId':original_context.transaction_id}
        self.plugin_generation = intent.plugin_generation
        self.verified = False
        return release.BeginResult('held')

    def preflight(self, record):
        return self.supported() is True and self.token is not None and not self.uncertain

    def observe(self, cohort):
        if self.uncertain and not getattr(self, 'read_only_reconciliation', False): raise ContractError('native execution uncertain')
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
        try:
            return self._operation_bound(kind,identity,record)
        except Exception:
            # A throw/lost ACK can never retain the confirmed same-held reuse lane.
            self.uncertain = True
            self.known_held = None
            raise

    def _operation_bound(self, kind, identity, record):
        available=self.supported() is True
        if not available:available=self._scoped_recovery_supported(kind)
        if not available or self.render is None or identity != self.target:
            raise ContractError('native held operation unavailable')
        status = self.managed_status(record['expected']['component'], allow_target_absent=kind == 'recover' and self.recovery_inspection)
        if status['journal']['generation'] != self.plugin_generation: raise ContractError('prepared plugin CAS changed')
        rendered = self.render(identity, status, self.operation)
        grant = rendered['authorization']
        result = self._call(['daemon', 'maintenance', 'plugin-operation', '--operation', kind,
            *self._reservation_args(), '--plugin-id', rendered['pluginId'], '--path', grant['sourcePath'],
            '--expected-path', rendered['expectedPath'], '--expected-generation', str(grant['expectedGeneration']),
            '--snapshot-sha256', grant['snapshotSha256'], '--server-bundle-sha256', grant['serverBundleSha256'],
            '--owner-token-fd', '0'], self.token)
        if type(result) is dict and result.get('outcome') == 'known_failed_held':
            return self._accept_known_held(result, identity, record)
        config = self._transport()
        if (type(result) is not dict or set(result) != {'plugin','nativeGeneration','maintenance','serverId','daemonIncarnation'} or result.get('serverId') != config['serverId'] or
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
        self.plugin_generation = result['nativeGeneration']
        if kind=='verify' and self.known_held is not None:
            status=self._call(['daemon','maintenance','status'])
            authority=status.get('authority') if type(status) is dict else None
            if (type(authority) is not dict or authority.get('qualified') is not True or
                    authority.get('serverId')!=config['serverId'] or authority.get('daemonIncarnation')!=config['daemonIncarnation'] or
                    status.get('state')!='held' or status.get('recoveryRequired') is not False or status.get('recoveryOnly') is not None or
                    status.get('reservationGeneration')!=self.reservation['generation'] or
                    status.get('transactionId')!=self.reservation['transactionId']):
                raise ContractError('scoped recovery verification restriction not durably cleared')
            self.known_held=None
        return result

    def _accept_known_held(self, result, identity, record):
        # Only the authenticated retained CLI normal alternative, never an exception.
        # Descriptive JSON is insufficient without this object's existing live bearer.
        required = {'outcome','reason','pluginId','nativeGeneration','current','baseline',
                    'maintenance','serverId','daemonIncarnation'}
        if (set(result) != required or result['reason'] not in ('compiler_error','initialization_rejected') or
                not hasattr(release,'KnownFailedHeld') or not self.token or self.uncertain or
                not self.original_native or not self.context or self.operation not in ('activate','recover') or result['pluginId'] != self.transaction_row['component'] or
                type(result['nativeGeneration']) is not int or result['nativeGeneration'] < self.plugin_generation):
            self.uncertain = True
            raise ContractError('known-held alternative unsupported or ambiguous')
        config = self._transport()
        if result['serverId'] != config['serverId'] or result['daemonIncarnation'] != config['daemonIncarnation']:
            self.uncertain = True
            raise ContractError('known-held identity changed')
        baseline_id = self.context.verified if self.context.kind == 'deploy' else self.context.target
        baseline_record = parse(read_regular(self.root/'records'/(baseline_id+'.json')).decode())
        retained_receipt = Receipt(base64.b64decode(baseline_record['receipt'],validate=True))
        payload = read_regular(self.root/'payloads'/baseline_record['payload_sha256'])
        validate(retained_receipt,baseline_record['expected'],baseline_record['policy'],artifact=payload)
        if retained_receipt.sha256 != baseline_id: raise ContractError('known-held retained baseline corrupt')
        baseline_root = self.root/'snapshots'/baseline_record['payload_sha256']
        baseline = {'path':str(baseline_root/'plugins'/result['pluginId']),
                    'snapshotSha256':baseline_record['evidence']['native_tree_sha256'],
                    'serverBundleSha256':baseline_record['evidence']['server_bundle_sha256']}
        if result['baseline'] != baseline or tree_hash(baseline_root) != baseline['snapshotSha256']:
            self.uncertain = True
            raise ContractError('known-held baseline binding mismatch')
        fresh = self._call(['daemon','maintenance','status'])
        facts = self.cohort_status(allow_target_absent=True)
        plugin = next(e for e in facts['entries'] if e['pluginId'] == result['pluginId'])
        expected_current = {'registration':None if plugin['registration'] is None else
                            {'path':plugin['registration']['path'],'enabled':plugin['enabled']},'loaded':plugin['loaded']}
        restriction = {'pluginId':result['pluginId'],'baseline':baseline,
                       'nativeGeneration':result['nativeGeneration'],'phase':'recover-required'}
        for status in (result['maintenance'],fresh):
            authority = status.get('authority') if type(status) is dict else None
            if (type(authority) is not dict or authority.get('qualified') is not True or
                    authority.get('serverId') != config['serverId'] or authority.get('daemonIncarnation') != config['daemonIncarnation'] or
                    type(authority.get('features')) is not dict or not (authority['features'].get('maintenanceKnownFailedHeldV1') is True or
                        authority['features'].get('maintenanceHeldRecoveryV1') is True) or
                    status.get('state') not in ('held','recovery-required') or status.get('recoveryRequired') is not True or
                    status.get('generation') != self.reservation['generation'] or
                    status.get('reservationGeneration') != self.reservation['generation'] or
                    status.get('transactionId') != self.reservation['transactionId'] or status.get('recoveryOnly') != restriction):
                self.uncertain = True
                raise ContractError('known-held fresh restriction unavailable')
        if (result['current'] != expected_current or plugin['journal']['generation'] != result['nativeGeneration'] or
                digest(self.reader()) != self.context.rule_digest):
            self.uncertain = True
            raise ContractError('known-held current facts changed')
        self.known_held = {'baseline':baseline}
        self.plugin_generation = result['nativeGeneration']
        return release.KnownFailedHeld(result['reason'],result['nativeGeneration'])

    def activate(self, identity, record):
        self.operation = 'activate'
        result = self._operation('replace', identity, record)
        if type(result) is getattr(release, 'KnownFailedHeld', None): return result
    def recover(self, identity, record):
        self.operation = 'recover'
        result = self._operation('recover', identity, record)
        if type(result) is getattr(release, 'KnownFailedHeld', None): return result
        self.recovery_inspection = False  # subsequent receipt/cohort verification is strict
    def verify(self, identity, record):
        if self.context and self.context.kind in ('resume','reconcile-release'):
            return self.supported() is True and self.observe(self.transaction_row['cohort']) == identity
        result = self._operation('verify', identity, record)
        if type(result) is getattr(release,'KnownFailedHeld',None):
            self.uncertain = True
            raise ContractError('verify cannot return a known failure alternative')
        self.verified = True
        return True


class Controller:
    """Ports are trusted in-process injection ONLY. CLI cannot select a port."""
    def __init__(self, reader=read_enrollment, evaluator=None, native=None, root=None):
        self.reader = reader
        self.evaluator = evaluator or GitHubEvaluation()
        self.native = native or NativeFacade(reader, root)
        self.context = None
        self.selection = None
        self.fresh_attestations = {}
        self.root = Path(root) if root is not None else locations()[1]

    def status(self):
        """Read existing Journal and actual native observations; creates nothing."""
        result={'status':'hold','authorized':False,'observation_only':True}
        try:
            row=parse(canonical(self.reader()).decode())
            result.update(component=row['component'],channel=row['channel'])
            group=row['policy']['compatibility_group']
            if type(group) is not str or not group:raise ContractError('protected group unavailable')
        except (OSError,ValueError,TypeError,KeyError):return dict(result,reason='protected_enrollment_unavailable')
        journal=Journal(self.root/'journal',group)
        try:
            original=read_regular(journal.path,1024*1024)
            current=journal.read()
            if canonical(current)!=original:raise ContractError('noncanonical or changed Journal')
        except (OSError,ValueError,TypeError,KeyError):return dict(result,reason='journal_unavailable')
        result.update(generation=current['generation'],verified=current['verified'],journal_state=current['state'],promotion_hold=current['promotion_hold'])
        if current['state']!='runtime_verified':return dict(result,reason='journal_unsettled')
        if not self.retained(current['verified']):return dict(result,reason='verified_artifact_unavailable')
        if not isinstance(self.native,NativeFacade):return dict(result,reason='native_observer_unavailable')
        try:observed=self.native.status_observation(row['cohort'])
        except (OSError,ValueError,TypeError,KeyError):return dict(result,reason='native_observation_unavailable')
        if observed!=current['verified']:return dict(result,reason='native_identity_mismatch',observed=observed)
        try:
            if (canonical(self.reader())!=canonical(row) or read_regular(journal.path,1024*1024)!=original or
                    canonical(journal.read())!=original or not self.retained(current['verified'])):
                return dict(result,reason='state_changed_during_status')
        except (OSError,ValueError,TypeError,KeyError):return dict(result,reason='state_changed_during_status')
        return dict(result,status='runtime_verified',reason='retained_verified_matches_current_native',observed=observed)

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
        selected_current = False
        value = current['operations'].get(operation)
        candidate_scope = (value is not None and ((current['schema_version'] == 1 and value['identity'] == 'qualified-latest') or
            (current['schema_version'] == 2 and any(grant['mode'] == 'standing' and 'qualified-latest' in grant['selectors'] for grant in value['grants']))))
        if self.selection and candidate_scope and (self.context is None or self.context.kind == 'deploy'):
            selected = self.selection['selected']
            if (selected and selected['identity'] == identity and self.selection['enrollment_sha256'] == digest(current)):
                selected_current = self.discover_master()['discovered'] == self.selection['latest']
        return rule_allows(current, operation, identity, self.context, selected_current=selected_current)


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

    def adapters(self, row, verified, *, recovery=False):
        native = self.native
        if native.supported() is not True and not (recovery and isinstance(native,NativeFacade) and native.can_attempt_same_held_recovery()):
            raise ContractError('native execution producer/status/reservation unsupported')
        def record(identity):
            if not self.retained(identity): raise ContractError('retained evidence unavailable')
            return parse(read_regular(self.root / 'records' / (identity + '.json')).decode())
        def staging(identity, payload):
            r = record(identity)
            if hashlib.sha256(payload).hexdigest() != r['payload_sha256']: raise ContractError('staging substitution')
            stage(payload, self.root / 'snapshots', payload_tree_hash(payload))
        def prepare(context):
            # Called by Journal while its existing lock owns the actual CAS/context.
            if digest(self.reader()) != context.rule_digest or digest(row) != context.rule_digest:
                raise ContractError('current protected rule changed')
            self.context = context
            if isinstance(native, NativeFacade):
                pending = self.journal.read().get('transaction')
                origin = None
                if pending:
                    original = pending.get('origin', pending)
                    origin = (release.TransactionContext(**original['context']),
                              release.ReservationIntent(**original['reservation']))
                recovery = (context.kind in ('reconcile','verified-rollback') and
                            self.permits(row,'recover',context.target) and self.permits(row,'verify',context.target))
                native.bind(row,context,lambda identity,status,operation: self.concrete_grant(row,identity,status,operation),
                            recovery=recovery,origin=origin)
            return native.prepare(context)
        kwargs = dict(
            observe=lambda: native.observe(row['cohort']),
            preflight=lambda identity: native.preflight(record(identity)),
            stage=staging,
            activate=lambda identity: native.activate(identity, record(identity)),
            verify=lambda identity: native.verify(identity, record(identity)),
            recover=lambda identity: native.recover(identity, record(identity)),
            retained=self.retained,
            authority=lambda operation, identity: self.permits(row, operation, identity),
            authenticate=verified.authenticates if verified is not None else lambda receipt: False,
            policy=lambda: self.reader()['policy'], prepare=prepare,reserve=native.reserve,
            finish=native.finish,released=native.released)
        if 'reuse' in Adapters.__dataclass_fields__:
            kwargs['reuse'] = native.reuse
        return Adapters(**kwargs)

    def concrete_grant(self, row, identity, native_status, operation='activate'):
        """Pure artifact scope/authorization renderer, never a permission or transport.

        Caller must run under the native private held-operation lease. Native rechecks
        owner/token/reservation/current policy at the actual mutation boundary.
        """
        if operation not in ('activate', 'recover') or not self.permits(row, operation, identity):
            raise ContractError('current concrete operation consent absent')
        if not self.retained(identity): raise ContractError('concrete grant artifact missing')
        status = coherent_native_status(native_status, row['component'], allow_target_absent=operation == 'recover', require_baseline=operation == 'recover')
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
        if operation == 'recover':
            baseline = status['journal']['baseline']
            saved = baseline['receipt']
            if (baseline['source'].get('path') != source or saved.get('sourcePath') != source or
                    saved.get('snapshotRoot') != str(root) or saved.get('snapshotSha256') != expected_tree or
                    saved.get('serverBundleSha256') != bundle):
                raise ContractError('native retained baseline differs from authorized target')
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
        self.context = None
        if operation == 'plan': return self.plan()
        if operation == 'select': return self.select_latest()
        if not hasattr(release, 'TransactionContext'):
            return {'status':'hold','reason':'journal_transaction_context_unsupported','authorized':False}
        if operation == 'reconcile-release' and isinstance(self.native,NativeFacade):
            self.native.read_only_reconciliation = True
        if self.native.supported() is not True and not (operation=='recover' and isinstance(self.native,NativeFacade) and self.native.can_attempt_same_held_recovery()):
            return {'status': 'hold', 'reason': 'native_execution_status_reservation_unsupported', 'authorized': False}
        self.journal = Journal(self.root / 'journal', row['policy']['compatibility_group'])
        rule_digest = digest(row)
        if operation in ('recover','resume','reconcile-release'):
            current = self.journal.read()
            adapters = self.adapters(row,None,recovery=operation=='recover')
            if operation == 'recover':
                # Only the Journal's recorded baseline can be an explicit healthy rollback.
                rollback = current['baseline'] if current['state'] == 'runtime_verified' else None
                result = self.journal.recover(adapters,generation=current['generation'],rollback_target=rollback,rule_digest=rule_digest)
            elif operation == 'resume':
                result = self.journal.resume(adapters,generation=current['generation'],rule_digest=rule_digest)
            else:
                result = self.journal.reconcile_release(adapters,generation=current['generation'],rule_digest=rule_digest)
            if operation == 'reconcile-release' and result.status == 'runtime_verified' and isinstance(self.native,NativeFacade):
                # Only SAME Journal's authorized stable-idle reconciliation settles uncertainty.
                self.native.token=None; self.native.reservation=None
                self.native.uncertain=False; self.native.known_held=None
                self.native.read_only_reconciliation=False
            return asdict(result)
        selected = row['schema_version'] == 2 or row['operations'].get('activate',{}).get('identity') == 'qualified-latest'
        if operation == 'deploy' and selected:
            receipt,payload,verified,record = self.selected_release(row)
            expected = record['expected']
        else:
            receipt,payload,verified = self.acquire(row)
            expected = row['expected']
        adapters = self.adapters(row,verified)
        if operation == 'enroll':
            self.journal.enroll(receipt.sha256,adapters)
            return {'status':'enrolled','identity':receipt.sha256,'authorized':False}
        if operation != 'deploy': raise ContractError('unsupported operation')
        current = self.journal.read()
        return asdict(self.journal.deploy(receipt,expected,row['policy'],payload,adapters,
            previous=current['verified'],generation=current['generation'],migration='binary_only',rule_digest=rule_digest))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'plan', 'tick', 'apply', 'recover', 'resume', 'reconcile-release'))
    args = parser.parse_args(argv)
    try:
        # No arbitrary path, grant, port or transport override is exposed.
        controller = Controller()
        if args.command == 'apply': result = controller.tick('deploy')
        elif args.command in ('recover','resume','reconcile-release'): result = controller.tick(args.command)
        elif args.command == 'tick': result = controller.select_latest()
        elif args.command == 'status': result = controller.status()
        else: result = controller.plan()
        print(canonical(result).decode())
        return 1 if args.command in ('apply','recover','resume','reconcile-release') and result['status'] != 'runtime_verified' else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(canonical({'status': 'hold', 'reason': type(error).__name__, 'authorized': False}).decode()); return 1


if __name__ == '__main__': raise SystemExit(main())
