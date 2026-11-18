"""Real local ZIP/Git/filesystem fixtures; fake ports are NOT qualification."""
import base64
from contextlib import contextmanager
from dataclasses import asdict
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import ade_fork_controller as c
import ade_fork_plugins as snapshots
from ade_fork_release import make_receipt, digest


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path / 'source'; repo.mkdir()
    git(repo, 'init', '-q'); git(repo, 'config', 'user.name', 'fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    plugin = repo / 'plugins/ade-yolo'; plugin.mkdir(parents=True)
    (plugin / 'index.server.ts').write_text('export default ()=>()=>{}')
    (plugin / 'paseo-plugin.json').write_text('{}')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'fixture')
    commit = git(repo, 'rev-parse', 'HEAD'); payload = snapshots.produce(repo, commit)
    registry = c.load_policy()
    cohort = {cid: {'fixture': commit} for r in registry if r['compatibility_group'] == 'paseo-runtime' for cid in r['catalog_ids']}
    policy = {'compatibility_group': 'paseo-runtime', 'features': {
        feature: {'assertion': 'synthetic CI port fixture'} for r in registry if r['compatibility_group'] == 'paseo-runtime' for feature in r['required_features']}}
    evidence = dict.fromkeys((*snapshots.TOOLS, 'helper_bindings', 'cold_compatibility',
                             'native_tree_sha256', 'server_bundle_sha256', 'master_commit'), 'fixture-only')
    evidence.update(master_commit=commit, native_tree_sha256=snapshots.payload_tree_hash(payload))
    expected = dict(schema_version=1, component='ade-yolo', upstream_commit=commit, fork_commit=commit,
                    dependencies={key: commit for key in cohort}, patch_manifest_digest=digest([]), applied_patches=[],
                    recipe_revision='protected-fixture', platform='linux',
                    toolchain=c.canonical({'plugin_snapshot_evidence': digest(evidence)}).decode(),
                    artifact_sha256=c.hashlib.sha256(payload).hexdigest(), policy_digest=digest(policy),
                    feature_contract_digest=digest(policy['features']), authority='protected-ci', evaluator='b' * 40)
    receipt = make_receipt(expected, policy, {k: {'status': 'passed', 'contract_digest': digest(v)} for k,v in policy['features'].items()})
    files = {'receipt.json': receipt.encoded, 'snapshot.json': payload, 'evaluator-evidence.json': c.canonical(evidence)}
    archive = zip_bytes(files)
    ev = dict(repository='protected/evaluator', repository_id=20, workflow_id=30,
              workflow_path='.github/workflows/qualify.yml', evaluator_commit='b'*40,
              run_id=40, run_attempt=1, actor_id=50, event='workflow_dispatch', jobs=['qualified'],
              artifact_id=60, artifact_name='qualification-40-1', archive_sha256=c.hashlib.sha256(archive).hexdigest(), receipt_sha256=receipt.sha256)
    row = dict(schema_version=1, component='ade-yolo', channel='master', repository='djbclark/djbclark-ade',
               repository_id=10, cohort=cohort, policy=policy, expected=expected, evaluation=ev,
               operations={op:dict(allowed=True,identity=receipt.sha256,generation=0) for op in c.OPERATIONS},
               previous='0'*64, generation=0, master_commit=commit, evidence=evidence)
    row = c.enrollment(c.canonical(row), registry)
    return row, receipt, payload, archive


def zip_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for key,value in files.items(): z.writestr(key,value)
    return out.getvalue()


class FakeEvaluator:
    def __init__(self, archive, receipt): self.archive=archive; self.receipt=receipt; self.calls=0
    def verify(self, expected, archive_dir):
        self.calls += 1
        path = archive_dir/(expected.archive_sha256+'.zip'); c.immutable(path,self.archive)
        return SimpleNamespace(archive=path, authenticates=lambda r: r.sha256 == self.receipt.sha256)


class FakeNative:
    """Trusted test injection only; no CLI path can instantiate this."""
    def __init__(self, identity): self.identity=identity; self.calls=[]; self.fail=False
    def supported(self): return True
    def observe(self, cohort): return self.identity
    def preflight(self, record): return True
    def activate(self, identity, record):
        self.calls.append(('activate',identity))
        if self.fail: raise RuntimeError('lost acknowledgement')
        self.identity=identity
    def recover(self, identity, record): self.calls.append(('recover',identity)); self.identity=identity
    def verify(self, identity, record): return self.identity==identity
    @contextmanager
    def reserve(self): yield True


def test_real_archive_retention_and_enroll_deploy(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    native=FakeNative(receipt.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),native,tmp_path/'private')
    assert controller.tick('enroll')['status']=='enrolled'
    assert controller.retained(receipt.sha256)
    row['previous']=receipt.sha256
    result=controller.tick('deploy')
    assert result['status']=='runtime_verified' and result['generation']==1
    assert native.calls==[('activate',receipt.sha256)]
    # A stale scheduled job never repeats activation.
    assert controller.tick('deploy')['reason']=='stale_job'
    assert len(native.calls)==1


def test_lost_ack_is_not_retried_and_recovery_is_explicit(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    native=FakeNative(receipt.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),native,tmp_path/'private')
    controller.tick('enroll'); row['previous']=receipt.sha256; native.fail=True
    assert controller.tick('deploy')['status']=='recovery_required'
    row['generation']=1
    for grant in row['operations'].values(): grant['generation']=1
    assert controller.tick('deploy')['reason']=='unfinished_transaction'
    assert len(native.calls)==1
    assert controller.tick('recover')['status']=='runtime_verified'
    assert native.calls[-1]==('recover',receipt.sha256)


def test_production_unsupported_does_no_acquisition(fixture,tmp_path):
    row,receipt,_,archive=fixture
    evaluator=FakeEvaluator(archive,receipt)
    controller=c.Controller(lambda:row,evaluator,root=tmp_path/'never')
    assert controller.tick('deploy')['status']=='hold'
    assert evaluator.calls==0 and not (tmp_path/'never').exists()


@pytest.mark.parametrize('kind',['duplicate','escape','symlink','fifo','extra','expansion'])
def test_archive_rejection(fixture,kind,monkeypatch):
    _,receipt,payload,archive=fixture
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for name,content in [('receipt.json',receipt.encoded),('snapshot.json',payload),('evaluator-evidence.json',b'{}')]:
            info=zipfile.ZipInfo(name)
            if kind=='symlink' and name=='snapshot.json': info.external_attr=(stat.S_IFLNK|0o777)<<16
            if kind=='fifo' and name=='snapshot.json': info.external_attr=(stat.S_IFIFO|0o600)<<16
            z.writestr(info,content)
        if kind=='duplicate': z.writestr('receipt.json',receipt.encoded)
        if kind=='escape': z.writestr('../escape',b'x')
        if kind=='extra': z.writestr('extra',b'x')
    if kind=='expansion': monkeypatch.setattr(c,'LIMIT',8)
    with pytest.raises(c.ContractError): c.unpack_archive(out.getvalue())


def test_fifo_symlink_and_corrupt_retention(fixture,tmp_path):
    path=tmp_path/'fifo'; os.mkfifo(path)
    with pytest.raises(c.ContractError): c.read_regular(path)
    path.unlink(); path.symlink_to('/etc/passwd')
    with pytest.raises(OSError): c.read_regular(path)
    row,receipt,_,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),FakeNative(receipt.sha256),tmp_path/'private')
    controller.acquire(row)
    record=controller.root/'records'/(receipt.sha256+'.json'); record.chmod(0o600); record.write_bytes(b'{}')
    assert not controller.retained(receipt.sha256)
    with pytest.raises(c.ContractError): controller.acquire(row)


def test_scoped_authority_revocation_and_master_signal(fixture,tmp_path):
    row,receipt,_,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),FakeNative(receipt.sha256),tmp_path/'private')
    row['operations']['retain']['allowed']=False
    with pytest.raises(c.ContractError,match='consent'): controller.acquire(row)
    assert not controller.root.exists()
    class Discovery:
        def api(self,endpoint):
            if endpoint.endswith('/git/ref/heads/master'):
                return {'ref':'refs/heads/master','object':{'type':'commit','sha':'c'*40}}
            return {'id':row['repository_id']}
    controller.evaluator=Discovery()
    assert controller.discover_master()['status']=='hold'
    assert controller.discover_master()['authorized'] is False


def test_enrollment_rejects_omitted_cohort_and_nonliteral_consent(fixture):
    row,*_=fixture
    bad=c.parse(c.canonical(row).decode()); bad['cohort'].pop(next(iter(bad['cohort'])))
    with pytest.raises(c.ContractError): c.enrollment(c.canonical(bad),c.load_policy())
    bad=c.parse(c.canonical(row).decode()); bad['operations']['activate']['allowed']=1
    with pytest.raises(c.ContractError): c.enrollment(c.canonical(bad),c.load_policy())


def test_native_status_cas_does_not_use_loaded_generation():
    value={'version':1,'pluginId':'ade-yolo','consistency':'coherent',
           'registration':{'path':'/baseline'},'journal':{'generation':8,'phase':'held',
           'baseline':{'fixture':True},'currentReceipt':{'fixture':True}},
           'loaded':{'activationGeneration':2}}
    assert c.coherent_native_status(value,'ade-yolo')['journal']['generation']==8
    value['consistency']='uncertain'
    with pytest.raises(c.ContractError): c.coherent_native_status(value,'ade-yolo')


def test_distinct_baseline_and_candidate_fake_port_transaction(fixture,tmp_path):
    """Two qualification identities for real retained bytes; no runtime closure proof."""
    row,receipt,payload,archive=fixture
    baseline=c.parse(c.canonical(row).decode())
    baseline['expected']['recipe_revision']='older-protected-recipe'
    policy=baseline['policy']
    old_receipt=make_receipt(baseline['expected'],policy,
        {k:{'status':'passed','contract_digest':digest(v)} for k,v in policy['features'].items()})
    old_archive=zip_bytes({'receipt.json':old_receipt.encoded,'snapshot.json':payload,
                           'evaluator-evidence.json':c.canonical(baseline['evidence'])})
    baseline['evaluation']['receipt_sha256']=old_receipt.sha256
    baseline['evaluation']['archive_sha256']=c.hashlib.sha256(old_archive).hexdigest()
    for grant in baseline['operations'].values(): grant['identity']=old_receipt.sha256
    current=[baseline]
    native=FakeNative(old_receipt.sha256)
    controller=c.Controller(lambda:current[0],FakeEvaluator(old_archive,old_receipt),native,tmp_path/'private')
    controller.tick('enroll')
    current[0]=row; row['previous']=old_receipt.sha256
    controller.evaluator=FakeEvaluator(archive,receipt)
    assert controller.tick('deploy')['status']=='runtime_verified'
    assert native.identity==receipt.sha256 != old_receipt.sha256
    assert controller.retained(old_receipt.sha256) and controller.retained(receipt.sha256)


def test_archive_substitution_holds_before_records(fixture,tmp_path):
    row,receipt,_,archive=fixture
    evaluator=FakeEvaluator(archive+b'substituted',receipt)
    controller=c.Controller(lambda:row,evaluator,FakeNative(receipt.sha256),tmp_path/'private')
    with pytest.raises(c.ContractError,match='substituted'): controller.acquire(row)
    assert not (controller.root/'records').exists()
