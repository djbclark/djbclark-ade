"""Protected emitter unit fixtures. Runtime/daemon observations below are SYNTHETIC.

Real Git snapshots, ZIPs, JUnit parsing and child-process bounds are exercised;
none of these fixtures is a qualified Paseo runtime or uploaded qualification.
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import ade_fork_evaluator as e
from ade_fork_controller import unpack_archive
from ade_fork_release import Receipt, canonical, digest, validate


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def junit(names):
    import xml.etree.ElementTree as ET
    root = ET.Element('testsuite', tests=str(len(names)), failures='0', errors='0', skipped='0')
    for name in names: ET.SubElement(root, 'testcase', name=name)
    return ET.tostring(root)


@pytest.fixture
def synthetic(tmp_path):
    root = tmp_path / 'candidate'; root.mkdir()
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'Synthetic evaluator unit fixture')
    git(root, 'config', 'user.email', 'synthetic@example.invalid')
    plugin = root / 'plugins/ade-yolo'; plugin.mkdir(parents=True)
    (plugin / 'index.server.ts').write_text('export default () => ({ hooks: {} });')
    (plugin / 'paseo-plugin.json').write_text('{"id":"ade-yolo"}')
    (root / 'helper').write_text('retained exact source bytes')
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'synthetic unit source')
    sha = git(root, 'rev-parse', 'HEAD'); payload = e.measure_source(root, sha)
    ids, features = e.catalog_contract()
    policy = {'compatibility_group': 'paseo-runtime', 'features': {key: {'assertion': 'synthetic-unit-' + key} for key in features}}
    evaluator = 'a' * 40
    native = {key: digest({'synthetic': key}) for key in e.NATIVE - {'source_sha', 'helpers'}}
    native.update(source_sha='b' * 40, helpers={'bound-python-helper': 'c' * 64})
    evidence = {key: digest({'synthetic': key}) for key in e.EVIDENCE}
    evidence.update(node=native['node_sha256'], paseo_compiler=native['compiler_sha256'],
                    helper_bindings=digest(native['helpers']), master_commit=sha,
                    native_tree_sha256=e.payload_tree_hash(payload))
    bindings = dict(schema_version=1, component='ade-yolo', upstream_commit=sha, fork_commit=sha,
                    dependencies={key: 'd' * 40 for key in ids}, patch_manifest_digest=digest([]),
                    applied_patches=[], recipe_revision='protected-synthetic-unit-recipe-v1',
                    platform='linux', toolchain='synthetic-template', artifact_sha256=hashlib.sha256(payload).hexdigest(),
                    policy_digest=digest(policy), feature_contract_digest=digest(policy['features']),
                    authority='protected-ci', evaluator=evaluator)
    recipe = dict(schema_version=1, evaluator_commit=evaluator, bindings=bindings, policy=policy,
                  evidence=evidence, native=native, cohort={key: {'identity': digest({'synthetic-cohort': key}), 'enabled': False, 'loaded': False} for key in ids},
                  assertions={domain: ['synthetic-unit-' + domain] for domain in e.DOMAINS})
    recipe['assertions']['features'] = sorted(features)
    runtime = {key: native[key] for key in ('distribution_sha256', 'node_sha256', 'entry_sha256', 'sdk_sha256', 'activity_sha256')}
    runtime.update(pid=123, start_token='synthetic-process-start', incarnation='synthetic-daemon-incarnation')
    observations = dict(schema_version=1, launch_id='synthetic-owned-launch', evaluator_commit=evaluator,
                        source_commit=sha, native=copy.deepcopy(native), helpers=copy.deepcopy(native['helpers']),
                        cohort=copy.deepcopy(recipe['cohort']), runtime=runtime,
                        compiler={'source_sha': native['source_sha'], 'entry_sha256': native['compiler_sha256'],
                                  'server_bundle_sha256': hashlib.sha256(b'synthetic compiled bytes').hexdigest(),
                                  'cold_invocations': 2, 'cold_bundle_sha256': [hashlib.sha256(b'synthetic compiled bytes').hexdigest()] * 2, 'worker_incarnations': ['synthetic-worker-A', 'synthetic-worker-B'],
                                  'worker_thread_ids': [1, 2]})
    reports = {domain: junit(names) for domain, names in recipe['assertions'].items()}
    return root, recipe, payload, observations, reports


def finish(data):
    _, recipe, payload, observations, reports = data
    return e.finish(recipe, payload, observations, reports,
                    evaluator_sha=recipe['evaluator_commit'], source_sha=e.inspect(payload)['commit'],
                    run_id=12345, attempt=2, launch_id='synthetic-owned-launch')


def test_real_source_archive_and_controller_schema_with_synthetic_runtime(synthetic):
    output = finish(synthetic)
    _, recipe, payload, _, _ = synthetic
    receipt, decoded, evidence = unpack_archive(output.archive())
    assert decoded == payload and set(evidence) == e.EVIDENCE
    bindings = e.parse(receipt.encoded.decode())['bindings']
    validate(receipt, bindings, recipe['policy'], artifact=payload)
    assert bindings['toolchain'] == canonical({'plugin_snapshot_evidence': digest(evidence)}).decode()
    assert output.name == 'ade-yolo-qualified-' + e.inspect(payload)['commit'] + '-12345-2'
    with zipfile.ZipFile(io.BytesIO(output.archive())) as archive:
        assert set(archive.namelist()) == {'receipt.json', 'snapshot.json', 'evaluator-evidence.json'}
        assert all(not row.is_dir() for row in archive.infolist())
    # No runtime authentication seal is constructed by the producer.
    assert not hasattr(receipt, 'authenticates')


def test_source_commit_ignores_candidate_dirty_build_claims(synthetic):
    root, _, payload, _, _ = synthetic
    (root / 'helper').write_text('candidate claimed allowed=true')
    (root / 'evaluator-evidence.json').write_text('{"allowed":true}')
    assert e.measure_source(root, e.inspect(payload)['commit']) == payload


@pytest.mark.parametrize('mutation', [
    lambda r: r['cohort'].pop(next(iter(r['cohort']))),
    lambda r: next(iter(r['cohort'].values())).pop('loaded'),
    lambda r: next(iter(r['cohort'].values())).update(enabled=0),
    lambda r: r['bindings']['dependencies'].clear(),
    lambda r: r['policy']['features'].clear(),
    lambda r: r['evidence'].update(node='fake-node'),
    lambda r: r['native'].update(compiler_sha256='0' * 64),
    lambda r: r['assertions'].pop('runtime'),
    lambda r: r['assertions'].update(features=[]),
    lambda r: r.update(evaluator_commit='0' * 40),
])
def test_incomplete_or_inconsistent_protected_recipe_holds(synthetic, mutation):
    _, recipe, _, _, _ = synthetic
    mutation(recipe)
    with pytest.raises(e.ContractError): finish(synthetic)


@pytest.mark.parametrize('mutation', [
    lambda o: o.pop('runtime'), lambda o: o.update(allowed=True),
    lambda o: o.update(launch_id='candidate-owned-launch'),
    lambda o: o.update(evaluator_commit='f' * 40), lambda o: o.update(source_commit='f' * 40),
    lambda o: o['native'].update(distribution_sha256='f' * 64),
    lambda o: o['compiler'].update(entry_sha256='f' * 64),
    lambda o: o['compiler'].update(cold_invocations=1),
    lambda o: o['compiler'].update(cold_bundle_sha256=['f' * 64] * 2),
    lambda o: o['compiler'].update(cold_invocations=True),
    lambda o: o['compiler'].update(worker_incarnations=['same', 'same']),
    lambda o: o['compiler'].update(worker_thread_ids=[1, 1]),
    lambda o: o['runtime'].update(pid=True), lambda o: o['runtime'].update(start_token=''),
    lambda o: o['runtime'].update(sdk_sha256='f' * 64),
    lambda o: o['runtime'].update(activity_sha256='f' * 64),
    lambda o: o['helpers'].clear(), lambda o: o['cohort'].clear(),
    lambda o: next(iter(o['cohort'].values())).update(enabled=0),
])
def test_independent_substitutions_never_emit(synthetic, mutation):
    mutation(synthetic[3])
    with pytest.raises(e.ContractError): finish(synthetic)


@pytest.mark.parametrize('kind', ['missing-domain', 'skip', 'failure', 'error', 'wrong-count', 'missing-count', 'missing-case', 'extra-case', 'duplicate', 'partial-header', 'entity'])
def test_assertion_completeness_holds(synthetic, kind):
    _, recipe, _, _, reports = synthetic
    domain = 'runtime'; name = recipe['assertions'][domain][0]
    if kind == 'missing-domain': reports.pop(domain)
    elif kind == 'skip': reports[domain] = reports[domain].replace(b' />', b'><skipped /></testcase>')
    elif kind == 'failure': reports[domain] = reports[domain].replace(b' />', b'><failure /></testcase>')
    elif kind == 'error': reports[domain] = reports[domain].replace(b' />', b'><error /></testcase>')
    elif kind == 'wrong-count': reports[domain] = reports[domain].replace(b'tests="1"', b'tests="2"')
    elif kind == 'missing-count': reports[domain] = reports[domain].replace(b'tests="1" ', b'')
    elif kind == 'missing-case': reports[domain] = junit([])
    elif kind == 'extra-case': reports[domain] = junit([name, 'unexpected'])
    elif kind == 'duplicate': reports[domain] = junit([name, name])
    elif kind == 'partial-header': reports[domain] = b'<testsuites tests="1">' + reports[domain] + b'</testsuites>'
    elif kind == 'entity': reports[domain] = b'<!DOCTYPE x [<!ENTITY x "boom">]>' + reports[domain]
    with pytest.raises(e.ContractError): finish(synthetic)


def test_corrupted_source_independent_of_valid_runtime(synthetic):
    root, recipe, payload, observations, reports = synthetic
    broken = bytearray(payload); broken[-1] ^= 1
    with pytest.raises(e.ContractError): finish((root, recipe, bytes(broken), observations, reports))
    assert finish(synthetic).snapshot == payload  # separately restored valid baseline


def test_real_node_junit_positive_and_independent_count_corruption(tmp_path):
    probe = tmp_path / 'snapshot.test.mjs'
    probe.write_text("import {test} from 'node:test';import assert from 'node:assert/strict';import {createHash} from 'node:crypto';test('real-byte-hash',()=>assert.equal(createHash('sha256').update('abc').digest('hex'),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'));\n")
    result = subprocess.run(['node', '--test', '--test-reporter=junit', str(probe)], capture_output=True, check=True)
    # Node's current raw reporter emits count-free testsuites + comments. The
    # production gate correctly refuses that incomplete header. This protected
    # TEST adapter reads actual runner totals before building concrete JUnit.
    import re
    import xml.etree.ElementTree as ET
    with pytest.raises(e.ContractError): e.junit_complete(result.stdout, ['real-byte-hash'])
    def count(name):
        match = re.search(rb'<!-- ' + name.encode() + rb' ([0-9]+) -->', result.stdout)
        assert match is not None
        return int(match.group(1))
    assert count('cancelled') == 0 and count('todo') == 0
    assert count('pass') == count('tests')
    root = ET.Element('testsuite', tests=str(count('tests')), failures=str(count('fail')),
                      errors=str(count('cancelled')), skipped=str(count('skipped')))
    for case in ET.fromstring(result.stdout).iter('testcase'):
        root.append(case)
    checked = ET.tostring(root)
    assert e.junit_complete(checked, ['real-byte-hash']) == 1
    with pytest.raises(e.ContractError):
        e.junit_complete(checked.replace(b'tests="1"', b'tests="99"'), ['real-byte-hash'])



@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'public', 'directory'])
def test_unsafe_measurement_files(tmp_path, kind):
    file = tmp_path / 'evidence'
    if kind == 'symlink': file.symlink_to('/etc/passwd')
    elif kind == 'fifo': os.mkfifo(file)
    elif kind == 'public': file.write_bytes(b'{}'); file.chmod(0o666)
    else: file.mkdir()
    with pytest.raises((e.ContractError, OSError)): e.read_file(file)


def test_sanitized_child_command_and_output_bounds(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'synthetic-secret-never-forward')
    env = e.clean_env(tmp_path, shutil.which('git'))
    output = e.command([sys.executable, '-c', 'import os;print("GITHUB_TOKEN" in os.environ)'], tmp_path, env)
    assert output.strip() == b'False'
    with pytest.raises(e.ContractError):
        e.command([sys.executable, '-c', 'print("x"*1000)'], tmp_path, env, limit=32)


def test_unreviewed_checkout_and_no_cli_measurement_grant(synthetic, tmp_path, monkeypatch, capsys):
    root, _, _, _, _ = synthetic
    sha = git(root, 'rev-parse', 'HEAD'); env = e.clean_env(tmp_path, shutil.which('git'))
    e.reviewed_checkout(root, sha, env)
    (root / 'helper').write_text('substituted')
    with pytest.raises(e.ContractError): e.reviewed_checkout(root, sha, env)
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    assert e.main(['--source-sha', sha]) == 78
    assert json.loads(capsys.readouterr().out)['qualified_output'] is False
    with pytest.raises(SystemExit): e.main(['--source-sha', sha, '--measurements', 'candidate.json'])



def test_actual_protected_source_runner_holds_before_missing_native(synthetic, tmp_path):
    """Real isolated Git/snapshot runner; deliberately NO native/daemon stand-in."""
    candidate, recipe, payload, _, _ = synthetic
    root = tmp_path / 'evaluator'; (root / 'bin').mkdir(parents=True)
    git(root, 'init', '-q'); git(root, 'config', 'user.name', 'Protected source runner fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    for name in ('ade_fork_plugins.py', 'ade_fork_release.py'):
        shutil.copyfile(e.ROOT / 'bin' / name, root / 'bin' / name)
    protected = copy.deepcopy(recipe)
    protected['evaluator_commit'] = '@evaluator'; protected['bindings']['evaluator'] = '@evaluator'
    protected['evidence']['python'] = e.file_hash(sys.executable, system_tool=True)
    protected['evidence']['git'] = e.file_hash(shutil.which('git'), system_tool=True)
    file = root / e.RECIPE; file.parent.mkdir(parents=True); file.write_bytes(canonical(protected))
    git(root, 'add', '.'); git(root, 'commit', '-qm', 'protected fixture recipe/source')
    evaluator_sha = git(root, 'rev-parse', 'HEAD')
    with pytest.raises((e.ContractError, OSError)):
        e.evaluate(e.inspect(payload)['commit'], evaluator_sha, 77, 1, root=root)
    work = tmp_path / 'fork-evaluator-77-1'
    staged = list((work / 'snapshots').iterdir())
    assert len(staged) == 1 and (staged[0] / 'helper').read_text() == 'retained exact source bytes'
    assert not (tmp_path / 'qualified-output').exists()
    assert not (work / 'request.json').exists()  # never launched an unqualified runtime


def test_native_input_symlinks_and_mutability_refused(tmp_path):
    native = tmp_path / 'node'; native.write_bytes(b'exact retained binary'); native.chmod(0o444)
    assert e.file_hash(native) == hashlib.sha256(b'exact retained binary').hexdigest()
    alias = tmp_path / 'alias'; alias.symlink_to(native)
    with pytest.raises(e.ContractError): e.file_hash(alias)
    native.chmod(0o644)
    with pytest.raises(e.ContractError): e.file_hash(native)



def test_native_artifact_substitution_is_independent_of_manifest(tmp_path):
    """Real file identities only; these synthetic files are never executed."""
    root = tmp_path / 'qualified-native'; (root / 'runtime').mkdir(parents=True)
    expected = {}
    for relative, key in [('runtime/node', 'node_sha256'), ('role.cjs', 'entry_sha256'), ('compiler-code.mjs', 'compiler_sha256')]:
        file = root / relative; file.write_bytes(('synthetic-' + relative).encode()); file.chmod(0o444)
        expected[key] = e.file_hash(file)
    manifest = Path(str(root) + '.manifest.json'); manifest.write_bytes(b'synthetic manifest, no runtime capability')
    expected['distribution_sha256'] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert e.check_native(root, expected) == root / 'runtime/node'
    compiler = root / 'compiler-code.mjs'; before = compiler.read_bytes()
    compiler.chmod(0o644); compiler.write_bytes(b'substituted compiler bytes'); compiler.chmod(0o444)
    with pytest.raises(e.ContractError): e.check_native(root, expected)
    compiler.chmod(0o644); compiler.write_bytes(before); compiler.chmod(0o444)
    assert e.check_native(root, expected) == root / 'runtime/node'
    manifest.write_bytes(b'different manifest')
    with pytest.raises(e.ContractError): e.check_native(root, expected)
