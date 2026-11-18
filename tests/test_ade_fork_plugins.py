"""Offline CI fixtures only; never run plugin installs or a daemon."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import ade_fork_plugins as p


def command(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


@pytest.fixture
def source(tmp_path):
    command(tmp_path, 'init', '-q')
    command(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    command(tmp_path, 'config', 'user.name', 'Fixture')
    (tmp_path / 'helper').write_text('exact bytes\n')
    command(tmp_path, 'add', 'helper')
    command(tmp_path, 'commit', '-qm', 'fixture')
    return tmp_path, command(tmp_path, 'rev-parse', 'HEAD')


def test_exact_and_dirty_ignored(source):
    root, commit = source
    first = p.produce(root, commit)
    (root / 'helper').write_text('dirty')
    (root / 'untracked').write_text('ignored')
    assert p.produce(root, commit) == first
    assert base64.b64decode(p.inspect(first)['files'][0]['content']) == b'exact bytes\n'


def test_stage_retention_and_native_hash(source, tmp_path):
    payload = p.produce(*source); digest = p.payload_tree_hash(payload)
    root = p.stage(payload, tmp_path / 'store', digest)
    assert p.tree_hash(root) == digest
    assert p.stage(payload, tmp_path / 'store', digest) == root
    (root / 'helper').chmod(0o644)
    (root / 'helper').write_text('corruption')
    with pytest.raises(p.ContractError):
        p.stage(payload, tmp_path / 'store', digest)


@pytest.mark.parametrize('kind', ['escape', 'duplicate', 'content', 'mode', 'overlap'])
def test_reject_before_writing(source, tmp_path, kind):
    payload = json.loads(p.produce(*source)); row = payload['files'][0]
    if kind == 'escape': row['path'] = '../escape'
    if kind == 'duplicate': payload['files'].append(dict(row))
    if kind == 'content': row['content'] = base64.b64encode(b'substitution').decode()
    if kind == 'mode': row['mode'] = 0o777
    if kind == 'overlap':
        other = dict(row); other['path'] = 'helper/child'; payload['files'].append(other)
    with pytest.raises(p.ContractError):
        p.stage(p.canonical(payload), tmp_path / 'never', '0' * 64)
    assert not (tmp_path / 'never').exists()


def test_unsafe_link(source):
    root, _ = source
    (root / 'escape').symlink_to('/etc/passwd')
    command(root, 'add', 'escape'); command(root, 'commit', '-qm', 'link')
    with pytest.raises(p.ContractError):
        p.produce(root, command(root, 'rev-parse', 'HEAD'))


def test_substituted_tree(source, tmp_path):
    with pytest.raises(p.ContractError):
        p.stage(p.produce(*source), tmp_path / 'never', '0' * 64)
    assert not (tmp_path / 'never').exists()


def test_missing_helpers_hold(source):
    payload = p.produce(*source)
    assert p.qualify(payload, 'ade-claim', None, {'fork_commit': source[1]}, {}, None, {}, {}) == 'HOLD'


def test_cold_plugin_behavior_from_sealed_source(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    payload = p.produce(repo, command(repo, 'rev-parse', 'HEAD'))
    root = p.stage(payload, tmp_path / 'store', p.payload_tree_hash(payload))
    for plugin in p.PLUGINS:
        subprocess.run(['node', '--test', *map(str, (root / 'plugins' / plugin / 'server').glob('*.test.mjs'))], check=True)
    # Python helper binding survives normal plugins/ID/../../bin layout.
    assert (root / 'plugins/ade-window-name/../../bin/ade_ws_names.py').is_file()
    assert (root / 'libexec/agent-bin/git').is_file()
    assert not (root / 'libexec/agent-bin/git').is_symlink()


@pytest.mark.parametrize('mutation', ['missing', 'toolchain', 'cold', 'binding'])
def test_evidence_mismatch_holds(source, mutation):
    root, _ = source
    plugin = root / 'plugins/ade-yolo'; plugin.mkdir(parents=True)
    (plugin / 'index.server.ts').write_text('export {}')
    (plugin / 'paseo-plugin.json').write_text('{}')
    command(root, 'add', 'plugins'); command(root, 'commit', '-qm', 'plugin')
    commit = command(root, 'rev-parse', 'HEAD'); payload = p.produce(root, commit)
    protected = dict.fromkeys((*p.TOOLS, 'helper_bindings', 'cold_compatibility',
                             'native_tree_sha256', 'server_bundle_sha256', 'master_commit'), 'identity')
    protected['master_commit'] = commit
    protected['native_tree_sha256'] = p.payload_tree_hash(payload)
    evidence = dict(protected)
    expected = {'fork_commit': commit, 'toolchain': p.canonical({'plugin_snapshot_evidence': p.sha(p.canonical(protected))}).decode()}
    if mutation == 'missing': del evidence['python']
    if mutation == 'toolchain': evidence['node'] = 'other-node'
    if mutation == 'cold': evidence['cold_compatibility'] = False
    if mutation == 'binding': expected['toolchain'] = p.canonical({'plugin_snapshot_evidence': '0' * 64}).decode()
    assert p.qualify(payload, 'ade-yolo', None, expected, {}, None, evidence, protected) == 'HOLD'


def test_positive_qualification_real_core_receipt(source):
    """Trusted synthetic evaluator only; this is no claim of real plugin closure."""
    from ade_fork_release import digest, make_receipt
    from types import SimpleNamespace
    root, _ = source
    plugin = root / 'plugins/ade-yolo'; plugin.mkdir(parents=True)
    (plugin / 'index.server.ts').write_text('export {}')
    (plugin / 'paseo-plugin.json').write_text('{}')
    command(root, 'add', 'plugins'); command(root, 'commit', '-qm', 'plugin')
    commit = command(root, 'rev-parse', 'HEAD'); payload = p.produce(root, commit)
    evidence = dict.fromkeys((*p.TOOLS, 'helper_bindings', 'cold_compatibility',
                             'native_tree_sha256', 'server_bundle_sha256', 'master_commit'), 'synthetic-fixture')
    evidence.update(master_commit=commit, native_tree_sha256=p.payload_tree_hash(payload))
    policy = {'compatibility_group': 'fixture', 'features': {'closure': {'assertion': 'fixture-only'}}}
    expected = dict(schema_version=1, component='ade-yolo', upstream_commit=commit,
                    fork_commit=commit, dependencies={}, applied_patches=[],
                    patch_manifest_digest=digest([]), recipe_revision='fixture', platform='linux',
                    toolchain=p.canonical({'plugin_snapshot_evidence': digest(evidence)}).decode(),
                    artifact_sha256=p.sha(payload), policy_digest=digest(policy),
                    feature_contract_digest=digest(policy['features']), authority='fixture', evaluator='fixture')
    results = {k: {'status': 'passed', 'contract_digest': digest(v)} for k, v in policy['features'].items()}
    receipt = make_receipt(expected, policy, results)
    auth = SimpleNamespace(authenticates=lambda candidate: candidate.sha256 == receipt.sha256)
    assert p.qualify(payload, 'ade-yolo', receipt, expected, policy, auth, evidence, evidence) == 'QUALIFIED'
    denied = SimpleNamespace(authenticates=lambda candidate: False)
    assert p.qualify(payload, 'ade-yolo', receipt, expected, policy, denied, evidence, evidence) == 'HOLD'
    wrong = dict(expected, toolchain=p.canonical({'plugin_snapshot_evidence': '0' * 64}).decode())
    assert p.qualify(payload, 'ade-yolo', receipt, wrong, policy, auth, evidence, evidence) == 'HOLD'


@pytest.mark.parametrize('partial', [False, True])
def test_stalled_git_child_is_bounded_and_reaped(monkeypatch, tmp_path, partial):
    import time
    real_popen = subprocess.Popen
    children = []
    def fake_git(argv, **kwargs):
        assert kwargs['env']['GIT_NO_LAZY_FETCH'] == '1'
        code = ('import os,time; ' + ('os.write(1,b"partial"); ' if partial else '') + 'time.sleep(60)')
        child = real_popen([sys.executable, '-c', code], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(p.subprocess, 'Popen', fake_git)
    monkeypatch.setattr(p, 'GIT_TIMEOUT', 0.2)
    start = time.monotonic()
    with pytest.raises(p.ContractError, match='timed out'):
        p.git(tmp_path, 'cat-file', 'blob', 'a' * 40)
    assert time.monotonic() - start < 5
    assert children[0].returncode is not None


def test_git_output_bound(monkeypatch, tmp_path):
    real_popen = subprocess.Popen
    children = []
    def fake_git(argv, **kwargs):
        child = real_popen([sys.executable, '-c', 'import os,time; os.write(1,b"x"*1024); time.sleep(60)'], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(p.subprocess, 'Popen', fake_git)
    monkeypatch.setattr(p, 'MAX_BYTES', 16)
    with pytest.raises(p.ContractError, match='exceeds bound'):
        p.git(tmp_path, 'cat-file', 'blob', 'a' * 40)
    assert children[0].returncode is not None


def test_sealed_materialized_guard_refuses_foreign_claim(tmp_path, monkeypatch):
    from test_ade_git_guard import base_env, claim, mk_repo
    repo = Path(__file__).resolve().parents[1]
    payload = p.produce(repo, command(repo, 'rev-parse', 'HEAD'))
    snapshot = p.stage(payload, tmp_path / 'store', p.payload_tree_hash(payload))
    state = tmp_path / 'registry'
    monkeypatch.setenv('ADE_STATE_DIR', str(state))
    foreign = mk_repo(tmp_path, state, 'foreign')
    claim(foreign, 'foreign-owner', agent='other-agent')
    env = base_env(state, who='different-claim', ADE_REAL_GIT=__import__('shutil').which('git'), ADE_PYTHON=sys.executable)
    shim = snapshot / 'libexec/agent-bin/git'
    assert not shim.is_symlink()
    before = (foreign / 'f').read_bytes()
    run = subprocess.run([str(shim), 'reset', '--hard', 'HEAD'], cwd=foreign, env=env,
                         text=True, capture_output=True, timeout=20)
    assert run.returncode == 77, run.stderr
    assert 'REFUSED' in run.stderr
    assert 'guard unavailable' not in run.stderr
    assert (foreign / 'f').read_bytes() == before
    # Actual hook install still derives root/libexec/git-hooks from root/bin/__file__.
    clean = tmp_path / 'clean'; clean.mkdir()
    command(clean, 'init', '-q')
    install = subprocess.run([str(snapshot / 'bin/ade-git-guard'), 'install', str(clean)],
                             env=base_env(state, ADE_PYTHON=sys.executable), text=True,
                             capture_output=True, timeout=20)
    assert install.returncode == 0, install.stderr
    assert (clean / '.git/hooks/reference-transaction').is_file()


def test_cold_cjs_entry_context_b_over_old_registration(tmp_path):
    """Actual esbuild CJS fixture, not native compiler/daemon qualification."""
    import os
    esbuild = os.environ.get('ADE_CI_ESBUILD')
    if not esbuild:
        pytest.fail('CI must supply its explicit esbuild binary')
    repo = Path(__file__).resolve().parents[1]
    payload = p.produce(repo, command(repo, 'rev-parse', 'HEAD'))
    snapshot = p.stage(payload, tmp_path / 'store', p.payload_tree_hash(payload))
    for plugin in ('ade-claim', 'ade-window-name'):
        output = tmp_path / (plugin + '.cjs')
        subprocess.run([esbuild, str(snapshot / 'plugins' / plugin / 'index.server.ts'),
                        '--bundle', '--platform=node', '--target=node20', '--format=cjs',
                        '--external:@getpaseo/plugin/server', '--outfile=' + str(output)], check=True, timeout=120)
        script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const original = fs.readFileSync;
let configReads = 0;
fs.readFileSync = function(file, ...args) {
  if (String(file).endsWith('/.paseo/config.json')) {
    configReads++;
    return JSON.stringify({plugins:{[process.argv[3]]:{path:'/old/A/plugins/'+process.argv[3]}}});
  }
  return original.call(this, file, ...args);
};
const plugin = require(process.argv[1]);
const handlers = new Map();
const server = {sourceDirectory: process.argv[2], managedSource: true, addHook(name, fn) {handlers.set(name,fn); return ()=>handlers.delete(name);}};
const off = plugin.default(server);
assert.equal(typeof off, 'function'); assert.ok(handlers.size > 0);
assert.equal(configReads, 0);
off(); assert.equal(handlers.size, 0);
assert.throws(()=>plugin.default({...server,managedSource:"true"}), /Invalid native managedSource/);
assert.throws(()=>plugin.default({...server,sourceDirectory:undefined}), /Managed source directory is required/);
assert.notEqual(fs.statSync(process.argv[4]).mode & 0o222, 0, "fixture checkout is writable");
for (const managedSource of [false, undefined]) {
  const ordinary = {...server, sourceDirectory: process.argv[4], managedSource};
  const stop = plugin.default(ordinary);
  assert.equal(typeof stop, "function");
  assert.ok(handlers.size > 0);
  assert.equal(configReads, 0, "provided unmanaged source binds helpers without stale registration");
  stop(); assert.equal(handlers.size, 0);
}
assert.throws(()=>plugin.default({...server,sourceDirectory:process.argv[4]}));

assert.throws(()=>plugin.default({...server,sourceDirectory:'/missing/B/plugins/'+process.argv[3]}));
process.env.ADE_PYTHON = '/unbound/python';
assert.throws(()=>plugin.default(server), /Unbound managed helper override/);
assert.equal(configReads, 0);
'''
        env = {k: v for k, v in os.environ.items() if k not in ('ADE_CLAIMS_PY', 'ADE_GIT_GUARD', 'ADE_AGENT_BIN', 'ADE_WS_AUTONAME_PY', 'ADE_PYTHON', 'ADE_REAL_GIT')}
        subprocess.run(['node', '-e', script, str(output), str(snapshot / 'plugins' / plugin), plugin, str(repo / 'plugins' / plugin)], env=env, check=True)


def test_managed_helper_argv_bound_to_snapshot(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    payload = p.produce(repo, command(repo, 'rev-parse', 'HEAD'))
    snapshot = p.stage(payload, tmp_path / 'store', p.payload_tree_hash(payload))
    state = tmp_path / 'mode'; state.mkdir(mode=0o700)
    script = r'''
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [root, state] = process.argv.slice(1);
const claim = await import(pathToFileURL(root+'/plugins/ade-claim/server/hook.mjs'));
const naming = await import(pathToFileURL(root+'/plugins/ade-window-name/server/name-lib.mjs'));
const hooks = new Map(); const logs=[];
const server = {addHook(n,f){hooks.set(n,f);return ()=>{};}};
claim.registerAdeClaimHooks(server, {managed:true,pluginRoot:root+'/plugins/ade-claim',
  env:{ADE_CLAIM_DRY_RUN:'1'},stateDir:state,log:s=>logs.push(s),
  spawn:(cmd,args)=>({status:0,stdout:cmd==='git'?'a'.repeat(40):'[]',stderr:''})});
await hooks.get('worktree.create.after')({worktree:{path:state,branch:'fixture',sourceCheckout:'/old/A'}});
assert.ok(logs.some(s=>s.includes(root+'/bin/ade_claims.py')), logs.join('\n'));
assert.ok(logs.some(s=>s.includes(root+'/bin/ade-git-guard')));
let observed;
naming.registerAdeWindowNameHooks(server,{managed:true,pluginRoot:root+'/plugins/ade-window-name',env:{},
  log:()=>{},run:async args=>{observed=args;return {action:'skip'};}});
const agent={id:'fixture-agent',workspaceId:'window',cwd:state,title:'Fix fixture'};
const context={paseo:{workspaces:{ref:()=>({refresh:async()=>({title:null})})},agents:{
 ref:()=>({refresh:async()=>({agent})}),list:async()=>({agents:[agent]})}}};
await hooks.get('agent.create.after')({agent},context);
assert.equal(observed?.script,root+'/bin/ade_ws_autoname.py');
assert.equal(observed?.python,'python3'); // external identity deliberately still HOLD
'''
    subprocess.run(['node', '--input-type=module', '-e', script, str(snapshot), str(state)], check=True)
