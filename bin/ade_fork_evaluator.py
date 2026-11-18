"""Protected evaluator producer. Evidence is not consent or GitHub authentication.

Only the fixed reviewed harness may supply runtime/compiler measurements. There
is no CLI input for measurement JSON, a runner path, a command, or an allow flag.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile

from ade_fork_plugins import produce, inspect, payload_tree_hash, tree_hash
from ade_fork_release import ContractError, canonical, digest, make_receipt, parse, validate
from ade_forks import load_policy

ROOT = Path(__file__).resolve().parents[1]
RECIPE = 'tests/fixtures/fork-coupled/evaluator-recipe.json'
HARNESS = 'tests/fixtures/fork-coupled/native-acceptance.mjs'
LIMIT = 96 * 1024 * 1024
REPORT_LIMIT = 4 * 1024 * 1024
DOMAINS = {'compiler', 'runtime', 'helpers', 'cohort', 'features'}
EVIDENCE = {'python', 'git', 'node', 'paseo_compiler', 'helper_bindings',
            'cold_compatibility', 'native_tree_sha256', 'server_bundle_sha256', 'master_commit'}
NATIVE = {'source_sha', 'distribution_sha256', 'node_sha256', 'compiler_sha256',
          'entry_sha256', 'sdk_sha256', 'activity_sha256', 'helpers'}


def full_sha(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise ContractError('bounded full source SHA required')
    return value


def positive(value):
    if type(value) is not int or not 0 < value <= 9007199254740991:
        raise ContractError('bounded positive integer required')
    return value


def hash_id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ContractError('SHA256 identity required')
    return value


def read_file(path, limit=LIMIT, *, tool=False):
    """Owned regular no-follow, bounded stable read; private session paths only."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ContractError('unsafe measured path')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.absolute().parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = nxt
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_uid not in ((0, os.getuid()) if tool else (os.getuid(),)) or before.st_mode & 0o022 or before.st_size > limit:
                raise ContractError('unsafe measured file')
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if len(data) > limit or len(data) != before.st_size or stamp(before) != stamp(after) or stamp(before) != stamp(current):
                raise ContractError('unstable measured file')
            return data
    finally:
        os.close(parent)


def file_hash(path, *, system_tool=False):
    path = Path(path).absolute()
    real = path.resolve(strict=True)
    if not system_tool and (real != path or real.stat().st_mode & 0o222):
        raise ContractError('native execution artifact must be sealed/canonical')
    return hashlib.sha256(read_file(real, 256 * 1024 * 1024, tool=True)).hexdigest()


def command(argv, cwd, env, timeout=600, limit=REPORT_LIMIT):
    """Fixed argv only; sanitized environment, bounded output/deadline, no shell."""
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, start_new_session=True) as process:
        data = bytearray(); deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as events:
                events.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not events.select(remaining):
                        raise ContractError('protected measurement command timed out')
                    chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(data)))
                    if not chunk: break
                    data.extend(chunk)
                    if len(data) > limit: raise ContractError('measurement output exceeds bound')
            remaining = deadline - time.monotonic()
            if remaining <= 0 or process.wait(timeout=remaining) != 0:
                raise ContractError('protected measurement command failed')
            return bytes(data)
        finally:
            if process.poll() is None:
                # This is our disposable evaluator command, never a production daemon.
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def clean_env(home, git_path):
    return {'PATH': str(Path(git_path).parent) + ':/usr/bin:/bin', 'HOME': str(home),
            'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1'}


def reviewed_checkout(root, expected, env):
    full_sha(expected)
    actual = command(['git', '--no-replace-objects', 'rev-parse', 'HEAD'], root, env).decode().strip()
    if actual != expected or command(['git', 'status', '--porcelain', '--untracked-files=all'], root, env):
        raise ContractError('reviewed evaluator checkout changed or dirty')


def catalog_contract():
    rows = [row for row in load_policy() if row['compatibility_group'] == 'paseo-runtime']
    return ({cid for row in rows for cid in row['catalog_ids']},
            {feature for row in rows for feature in row['required_features']})


def recipe_validate(recipe, evaluator_sha):
    fields = {'schema_version', 'evaluator_commit', 'bindings', 'policy', 'evidence',
              'native', 'cohort', 'assertions'}
    if type(recipe) is not dict or set(recipe) != fields or type(recipe['schema_version']) is not int or recipe['schema_version'] != 1 or recipe['evaluator_commit'] != evaluator_sha:
        raise ContractError('invalid protected recipe identity/schema')
    full_sha(evaluator_sha)
    if type(recipe.get('bindings')) is not dict or recipe['bindings'].get('platform') != 'linux':
        raise ContractError('finite Linux recipe required')
    cohort, features = catalog_contract()
    if type(recipe['cohort']) is not dict or set(recipe['cohort']) != cohort or any(type(v) is not dict or not v for v in recipe['cohort'].values()):
        raise ContractError('complete protected cohort required')
    if type(recipe['bindings']) is not dict or type(recipe['policy']) is not dict or type(recipe['policy'].get('features')) is not dict or set(recipe['policy'].get('features', {})) != features or set(recipe['bindings'].get('dependencies', {})) != cohort:
        raise ContractError('complete protected features/dependencies required')
    if recipe['bindings'].get('component') != 'ade-yolo' or recipe['bindings'].get('authority') != 'protected-ci' or recipe['bindings'].get('evaluator') != evaluator_sha:
        raise ContractError('protected evaluator authority mismatch')
    evidence = recipe['evidence']
    if type(evidence) is not dict or set(evidence) != EVIDENCE or any(not v for v in evidence.values()):
        raise ContractError('complete protected evaluator evidence required')
    for name in ('python', 'git', 'node', 'paseo_compiler', 'helper_bindings', 'cold_compatibility'):
        hash_id(evidence[name])
    native = recipe['native']
    if type(native) is not dict or set(native) != NATIVE or type(native['helpers']) is not dict:
        raise ContractError('complete native distribution identity required')
    full_sha(native['source_sha'])
    for name in NATIVE - {'helpers', 'source_sha'}: hash_id(native[name])
    for value in native['helpers'].values(): hash_id(value)
    if evidence['node'] != native['node_sha256'] or evidence['paseo_compiler'] != native['compiler_sha256'] or evidence['helper_bindings'] != digest(native['helpers']):
        raise ContractError('protected tool/helper identities inconsistent')
    assertions = recipe['assertions']
    if type(assertions) is not dict or set(assertions) != DOMAINS:
        raise ContractError('complete protected measurement domains required')
    for domain, names in assertions.items():
        if type(names) is not list or not names or any(type(n) is not str or not n for n in names) or len(set(names)) != len(names):
            raise ContractError('explicit complete assertion identities required')
    if set(assertions['features']) != features:
        raise ContractError('feature assertion coverage incomplete')
    # Validate protected release template too, without inventing candidate results.
    make_receipt(recipe['bindings'], recipe['policy'], {})
    return recipe


def junit_complete(encoded, required):
    if type(encoded) is not bytes or len(encoded) > REPORT_LIMIT or b'<!DOCTYPE' in encoded.upper() or b'<!ENTITY' in encoded.upper():
        raise ContractError('unsafe JUnit report')
    try: root = ET.fromstring(encoded)
    except ET.ParseError as exc: raise ContractError('malformed JUnit report') from exc
    if root.tag not in ('testsuites', 'testsuite'):
        raise ContractError('JUnit suite required')
    cases = list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    if not cases or len(set(names)) != len(names) or set(names) != set(required):
        raise ContractError('missing/extra/duplicate protected assertions')
    if any(next(case.iter(tag), None) is not None for case in cases for tag in ('failure', 'error', 'skipped')):
        raise ContractError('failed or skipped qualification assertion')
    for suite in [n for n in root.iter() if n.tag in ('testsuite', 'testsuites')]:
        counts = ('tests', 'failures', 'errors', 'skipped', 'disabled')
        if suite.tag == 'testsuites' and not any(k in suite.attrib for k in counts):
            if not list(suite) or any(child.tag not in ('testsuite', 'testsuites') for child in suite):
                raise ContractError('incomplete JUnit grouping')
            continue
        expected = len(list(suite.iter('testcase')))
        if not re.fullmatch('[0-9]+', suite.get('tests', '')) or int(suite.get('tests')) != expected:
            raise ContractError('JUnit count inconsistent')
        for key in ('failures', 'errors', 'skipped', 'disabled'):
            value = suite.get(key, '0' if key == 'disabled' else '')
            if not re.fullmatch('[0-9]+', value) or int(value) != 0:
                raise ContractError('JUnit unsuccessful/partial count')
    return len(cases)


@dataclass(frozen=True)
class Output:
    name: str
    receipt: bytes
    snapshot: bytes
    evidence: bytes

    def members(self):
        return {'receipt.json': self.receipt, 'snapshot.json': self.snapshot,
                'evaluator-evidence.json': self.evidence}

    def archive(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in sorted(self.members().items()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3; info.external_attr = (stat.S_IFREG | 0o444) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, value)
        if len(out.getvalue()) > LIMIT or sum(map(len, self.members().values())) > LIMIT:
            raise ContractError('qualification archive exceeds bounds')
        return out.getvalue()


def finish(recipe, payload, observations, reports, *, evaluator_sha, source_sha, run_id, attempt, launch_id):
    """Trusted in-process protected harness handoff ONLY, never JSON authentication.

    The protected caller must own the independently launched runtime. Production
    CLI obtains these objects only from its fixed reviewed child launch below.
    """
    recipe_validate(recipe, evaluator_sha); full_sha(source_sha)
    positive(run_id); positive(attempt)
    source = inspect(payload)
    if source['commit'] != source_sha or type(launch_id) is not str or not launch_id:
        raise ContractError('source/session binding mismatch')
    fields = {'schema_version', 'launch_id', 'evaluator_commit', 'source_commit',
              'native', 'compiler', 'runtime', 'helpers', 'cohort'}
    if type(observations) is not dict or set(observations) != fields or type(observations['schema_version']) is not int or observations['schema_version'] != 1:
        raise ContractError('invalid protected measurement schema')
    if (observations['launch_id'] != launch_id or observations['evaluator_commit'] != evaluator_sha or observations['source_commit'] != source_sha or canonical(observations['native']) != canonical(recipe['native']) or canonical(observations['helpers']) != canonical(recipe['native']['helpers']) or canonical(observations['cohort']) != canonical(recipe['cohort'])):
        raise ContractError('runtime/source/compiler/helper/full-cohort substitution')
    compiler = observations['compiler']
    if type(compiler) is not dict or set(compiler) != {'source_sha', 'entry_sha256', 'server_bundle_sha256', 'cold_invocations', 'cold_bundle_sha256', 'worker_incarnations', 'worker_thread_ids'}:
        raise ContractError('compiler measurement incomplete')
    if compiler['source_sha'] != recipe['native']['source_sha'] or compiler['entry_sha256'] != recipe['native']['compiler_sha256'] or type(compiler['cold_invocations']) is not int or compiler['cold_invocations'] != 2:
        raise ContractError('actual protected cold compiler measurements required')
    hash_id(compiler['server_bundle_sha256'])
    if compiler['cold_bundle_sha256'] != [compiler['server_bundle_sha256']] * 2:
        raise ContractError('both actual cold compiler outputs must agree')
    tokens, threads = compiler['worker_incarnations'], compiler['worker_thread_ids']
    if type(tokens) is not list or len(tokens) != 2 or any(type(t) is not str or not t for t in tokens) or len(set(tokens)) != 2 or type(threads) is not list or len(threads) != 2 or any(type(t) is not int for t in threads) or len(set(threads)) != 2:
        raise ContractError('independent owned compiler incarnations required')
    for thread in threads: positive(thread)
    runtime = observations['runtime']
    if type(runtime) is not dict or set(runtime) != {'distribution_sha256', 'node_sha256', 'entry_sha256', 'sdk_sha256', 'activity_sha256', 'pid', 'start_token', 'incarnation'}:
        raise ContractError('qualified enclosing runtime measurement incomplete')
    for key in ('distribution_sha256', 'node_sha256', 'entry_sha256', 'sdk_sha256', 'activity_sha256'):
        if runtime[key] != recipe['native'][key]: raise ContractError('qualified runtime identity mismatch')
    positive(runtime['pid'])
    if any(type(runtime[k]) is not str or not runtime[k] for k in ('start_token', 'incarnation')):
        raise ContractError('actual runtime process/incarnation observations required')
    if type(reports) is not dict or set(reports) != DOMAINS:
        raise ContractError('all protected reports required')
    for domain in sorted(DOMAINS): junit_complete(reports[domain], recipe['assertions'][domain])
    evidence = dict(recipe['evidence'], master_commit=source_sha,
                    native_tree_sha256=payload_tree_hash(payload), server_bundle_sha256=compiler['server_bundle_sha256'])
    bindings = dict(recipe['bindings'], fork_commit=source_sha, upstream_commit=source_sha,
                    artifact_sha256=hashlib.sha256(payload).hexdigest(),
                    toolchain=canonical({'plugin_snapshot_evidence': digest(evidence)}).decode())
    if bindings['authority'] != 'protected-ci' or bindings['evaluator'] != evaluator_sha or bindings['component'] != 'ade-yolo':
        raise ContractError('protected evaluator/authority identity mismatch')
    results = {name: {'contract_digest': digest(contract), 'status': 'passed'}
               for name, contract in recipe['policy']['features'].items()}
    receipt = make_receipt(bindings, recipe['policy'], results)
    validate(receipt, bindings, recipe['policy'], artifact=payload)
    output = Output(f'ade-yolo-qualified-{source_sha}-{run_id}-{attempt}', receipt.encoded, payload, canonical(evidence))
    output.archive()  # fully validate before publishing ANY member
    return output


def measure_source(repo, commit):
    """Real immutable Git object snapshot; never runs candidate source/build scripts."""
    return produce(Path(repo), full_sha(commit))


def check_native(native, expected):
    """Known finite artifact identities, before launch and after measurements."""
    node = native / 'runtime/node'
    if file_hash(node) != expected['node_sha256']:
        raise ContractError('qualified retained Node unavailable')
    if hashlib.sha256(read_file(Path(str(native) + '.manifest.json'))).hexdigest() != expected['distribution_sha256']:
        raise ContractError('qualified distribution manifest mismatch')
    for file, key in [('role.cjs', 'entry_sha256'), ('compiler-code.mjs', 'compiler_sha256')]:
        if file_hash(native / file) != expected[key]:
            raise ContractError('protected native entry substituted')
    return node


def evaluate(source_sha, evaluator_sha, run_id, attempt, *, root=ROOT):
    """Fixed protected launch; missing genuine producer/harness means HOLD/no output."""
    full_sha(source_sha); full_sha(evaluator_sha); positive(run_id); positive(attempt)
    if sys.platform != 'linux': raise ContractError('finite Linux evaluator only')
    root = Path(root).resolve(strict=True)
    work = root.parent / f'fork-evaluator-{run_id}-{attempt}'
    if work.exists(): raise ContractError('evaluator work directory already exists')
    work.mkdir(mode=0o700)
    git_path = shutil.which('git')
    if not git_path: raise ContractError('Git unavailable')
    env = clean_env(work, git_path)
    reviewed_checkout(root, evaluator_sha, env)
    recipe = parse(read_file(root / RECIPE, REPORT_LIMIT).decode())
    tracked_recipe = command(['git', 'show', f'{evaluator_sha}:{RECIPE}'], root, env)
    if canonical(recipe) != tracked_recipe:
        raise ContractError('protected recipe bytes must be canonical/tracked')
    # Reviewed source has no circular self-commit literal. These are the only
    # evaluator placeholders, resolved from independently checked Git/CI identity.
    if type(recipe) is not dict or type(recipe.get('bindings')) is not dict or recipe.get('evaluator_commit') != '@evaluator' or recipe.get('bindings', {}).get('evaluator') != '@evaluator':
        raise ContractError('protected evaluator placeholder required')
    recipe['evaluator_commit'] = evaluator_sha
    recipe['bindings']['evaluator'] = evaluator_sha
    recipe_validate(recipe, evaluator_sha)
    for name, executable in (('python', sys.executable), ('git', git_path)):
        if file_hash(executable, system_tool=True) != recipe['evidence'][name]: raise ContractError('protected tool substituted')
    # Source staging is pure Git object work; no npm scripts from the candidate.
    source_program = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
                      'from ade_fork_plugins import produce;'
                      'sys.stdout.buffer.write(produce(Path(sys.argv[2]),sys.argv[3]))')
    payload = command([sys.executable, '-I', '-c', source_program, str(root / 'bin'),
                       str(root.parent / 'candidate'), source_sha], root, env, limit=LIMIT)
    from ade_fork_plugins import stage
    source_root = stage(payload, work / 'snapshots', payload_tree_hash(payload))
    native = root.parent / 'qualified-native'
    node = check_native(native, recipe['native'])
    # Existing real owned compiler worker is invoked through the fixed root-owned
    # coupled fixture/daemon owner, never by a candidate-selected compiler command.
    harness = read_file(root / HARNESS, REPORT_LIMIT)
    tracked = command(['git', 'show', f'{evaluator_sha}:{HARNESS}'], root, env)
    if harness != tracked: raise ContractError('protected harness checkout substituted')
    launch_id = uuid.uuid4().hex
    request = {'schema_version': 1, 'launch_id': launch_id, 'evaluator_commit': evaluator_sha,
               'source_commit': source_sha, 'source_root': str(source_root), 'native_root': str(native),
               'work_root': str(work), 'native': recipe['native'], 'cohort': recipe['cohort'],
               'assertions': recipe['assertions']}
    request_path = work / 'request.json'; request_path.write_bytes(canonical(request)); request_path.chmod(0o400)
    # Child receives no Actions/GitHub/cloud credentials or candidate-selected env.
    raw = command([str(node), str(root / HARNESS), str(request_path)], root, env, timeout=1200)
    observations = parse(raw.decode())
    reports = {domain: read_file(work / (domain + '.xml'), REPORT_LIMIT) for domain in DOMAINS}
    for index in (1, 2):
        bundle = read_file(work / f'compiled-server-{index}.cjs')
        if observations.get('compiler', {}).get('server_bundle_sha256') != hashlib.sha256(bundle).hexdigest():
            raise ContractError('cold compiled output bytes substituted')
    reviewed_checkout(root, evaluator_sha, env)
    check_native(native, recipe['native'])
    if tree_hash(source_root) != payload_tree_hash(payload):
        raise ContractError('sealed candidate source changed during measurement')
    for name, executable in (('python', sys.executable), ('git', git_path)):
        if file_hash(executable, system_tool=True) != recipe['evidence'][name]:
            raise ContractError('measurement tool changed during assessment')
    output = finish(recipe, payload, observations, reports, evaluator_sha=evaluator_sha,
                    source_sha=source_sha, run_id=run_id, attempt=attempt, launch_id=launch_id)
    directory = root.parent / 'qualified-output'
    directory.mkdir(mode=0o700)  # must be absent, never overwrite partial/old evidence
    try:
        for name, value in output.members().items():
            fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(value); stream.flush(); os.fsync(stream.fileno())
    except BaseException:
        shutil.rmtree(directory)
        raise
    return {'status': 'emitted', 'artifact_name': output.name, 'receipt_sha256': hashlib.sha256(output.receipt).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source-sha', required=True)
    args = parser.parse_args(argv)
    try:
        if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'djbclark/djbclark-ade' or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
            raise ContractError('protected evaluator workflow context required')
        result = evaluate(args.source_sha, os.environ.get('GITHUB_SHA', ''),
                          positive(int(os.environ.get('GITHUB_RUN_ID', '0'))), positive(int(os.environ.get('GITHUB_RUN_ATTEMPT', '0'))))
        print(canonical(result).decode())
        return 0
    except (ContractError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(canonical({'status': 'HOLD', 'reason': type(exc).__name__, 'qualified_output': False}).decode())
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
