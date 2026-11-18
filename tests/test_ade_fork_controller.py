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
               previous='0'*64, generation=0, master_commit=commit, evidence=evidence,
               discovery={'enabled':True,'artifact_prefix':'ade-yolo-qualified','baseline_run_id':40},native=None)
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


def test_automatic_protected_discovery_and_failed_newer_master(fixture,tmp_path):
    """Authenticated fake workflow output plus real source bytes, not live CI qualification."""
    row,receipt,payload,archive=fixture
    # Protected output digest must be a real SHA256 even in a synthetic evaluator fixture.
    evidence=dict(row['evidence'],server_bundle_sha256='e'*64)
    expected=dict(row['expected'],toolchain=c.canonical({'plugin_snapshot_evidence':digest(evidence)}).decode())
    policy=row['policy']
    candidate_receipt=make_receipt(expected,policy,{k:{'status':'passed','contract_digest':digest(v)} for k,v in policy['features'].items()})
    candidate_archive=zip_bytes({'receipt.json':candidate_receipt.encoded,'snapshot.json':payload,'evaluator-evidence.json':c.canonical(evidence)})
    candidate_digest=c.hashlib.sha256(candidate_archive).hexdigest()
    source=row['master_commit']; latest='f'*40
    class Discovery(FakeEvaluator):
        def __init__(self): super().__init__(candidate_archive,candidate_receipt); self.changed=False
        def api(self,endpoint):
            if endpoint=='rate_limit': return {'resources':{'core':{'remaining':4000}}}
            if endpoint=='repos/'+row['repository']: return {'id':row['repository_id']}
            if endpoint.endswith('/git/ref/heads/master'):
                return {'ref':'refs/heads/master','object':{'type':'commit','sha':latest}}
            if '/compare/' in endpoint:
                older,newer=endpoint.split('/compare/')[1].split('...')
                return {'base_commit':{'sha':older},'merge_base_commit':{'sha':older},'status':'ahead'}
            if '/actions/workflows/' in endpoint:
                return {'workflow_runs':[
                    {'id':42,'head_sha':'b'*40,'status':'completed','conclusion':'failure','event':'workflow_dispatch','run_attempt':1},
                    {'id':41,'head_sha':'b'*40,'status':'completed','conclusion':'success','event':'workflow_dispatch','run_attempt':2}]}
            if '/actions/runs/41/artifacts' in endpoint:
                return {'total_count':1,'artifacts':[{'id':61,'name':f'ade-yolo-qualified-{source}-41-2','digest':'sha256:'+candidate_digest}]}
            raise AssertionError(endpoint)
    evaluator=Discovery()
    controller=c.Controller(lambda:row,evaluator,root=tmp_path/'private')
    result=controller.select_latest()
    assert result['latest_discovered']==latest
    assert result['selected_qualified']['commit']==source
    assert result['selected_qualified']['identity']==candidate_receipt.sha256
    assert result['authorized'] is False
    assert controller.retained(candidate_receipt.sha256)
    assert evaluator.calls==2  # transport authentication then exact discovered receipt authentication


def test_discovery_retained_baseline_and_rewind_hold(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row); row['previous']=receipt.sha256
    source=row['master_commit']
    class EmptyDiscovery:
        def __init__(self): self.rewind=False
        def api(self,endpoint):
            if endpoint=='rate_limit':return {'resources':{'core':{'remaining':4000}}}
            if endpoint=='repos/'+row['repository']:return {'id':row['repository_id']}
            if endpoint.endswith('/git/ref/heads/master'):
                return {'ref':'refs/heads/master','object':{'type':'commit','sha':'d'*40}}
            if '/compare/' in endpoint:
                return {'base_commit':{'sha':source},'merge_base_commit':{'sha':'0'*40 if self.rewind else source},'status':'ahead'}
            if '/actions/workflows/' in endpoint:return {'workflow_runs':[]}
            raise AssertionError(endpoint)
    discovery=EmptyDiscovery();controller.evaluator=discovery
    assert controller.select_latest()['selected_qualified']['identity']==receipt.sha256
    discovery.rewind=True
    with pytest.raises(c.ContractError,match='rewind'):controller.select_latest()


def test_discovery_rechecks_policy_before_commit(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    current=[row]
    class Changed:
        def api(self,endpoint):
            if endpoint=='rate_limit':return {'resources':{'core':{'remaining':4000}}}
            if endpoint=='repos/'+row['repository']:return {'id':row['repository_id']}
            if endpoint.endswith('/git/ref/heads/master'):
                return {'ref':'refs/heads/master','object':{'type':'commit','sha':row['master_commit']}}
            if '/actions/workflows/' in endpoint:
                current[0]=dict(row,discovery=dict(row['discovery'],enabled=False))
                return {'workflow_runs':[]}
            raise AssertionError(endpoint)
    controller=c.Controller(lambda:current[0],Changed(),root=tmp_path/'never')
    with pytest.raises(c.ContractError,match='enrollment changed'):controller.select_latest()
    assert not controller.root.exists()


def test_discovery_ancestry_with_real_git_objects(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    repo=tmp_path/'source'; baseline=git(repo,'rev-parse','HEAD')
    (repo/'next').write_text('next');git(repo,'add','.');git(repo,'commit','-qm','descendant')
    descendant=git(repo,'rev-parse','HEAD')
    git(repo,'checkout','-q','--detach',baseline)
    (repo/'other').write_text('other');git(repo,'add','.');git(repo,'commit','-qm','incomparable')
    other=git(repo,'rev-parse','HEAD')
    class RealGitComparisons:
        def __init__(self):self.head=descendant
        def api(self,endpoint):
            if endpoint=='rate_limit':return {'resources':{'core':{'remaining':4000}}}
            if endpoint=='repos/'+row['repository']:return {'id':row['repository_id']}
            if endpoint.endswith('/git/ref/heads/master'):
                return {'ref':'refs/heads/master','object':{'type':'commit','sha':self.head}}
            if '/compare/' in endpoint:
                older,newer=endpoint.split('/compare/')[1].split('...')
                common=git(repo,'merge-base',older,newer)
                return {'base_commit':{'sha':older},'merge_base_commit':{'sha':common},'status':'ahead' if common==older else 'diverged'}
            if '/actions/workflows/' in endpoint:return {'workflow_runs':[]}
            raise AssertionError(endpoint)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row);row['previous']=receipt.sha256
    observations=RealGitComparisons();controller.evaluator=observations
    assert controller.select_latest()['selected_qualified']['commit']==baseline
    # A later enrolled baseline cannot be falsely relabelled as an unrelated branch.
    record_path=controller.root/'records'/(receipt.sha256+'.json')
    record=c.parse(c.read_regular(record_path).decode());record['expected']['fork_commit']=descendant
    record_path.chmod(0o600);record_path.write_bytes(c.canonical(record))
    # Corrupting retained identity invalidates it; use trusted enrollment baseline for the graph check.
    row['master_commit']=descendant;observations.head=other
    with pytest.raises(c.ContractError,match='incomparable'):controller.select_latest()


def test_same_release_two_authenticated_attestations(fixture,tmp_path):
    row,receipt,_,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row)
    stable=c.read_regular(controller.root/'records'/(receipt.sha256+'.json'))
    row['evaluation'].update(run_id=41,run_attempt=2,artifact_id=61,artifact_name='qualification-41-2')
    controller.acquire(row)
    assert c.read_regular(controller.root/'records'/(receipt.sha256+'.json'))==stable
    assert len(list((controller.root/'attestations'/receipt.sha256).glob('*.json')))==2
    assert controller.retained(receipt.sha256)


@pytest.mark.parametrize('bad_endpoint,bad_value',[
    ('quota',None),('quota',{'resources':None}),('quota',{'resources':{'core':None}}),
    ('runs',{'workflow_runs':[None]}),('runs',{'workflow_runs':[7]}),
    ('master',{'ref':'refs/heads/master','object':None}),
])
def test_malformed_inventory_always_contract_hold(fixture,tmp_path,bad_endpoint,bad_value):
    row,*_=fixture
    class Malformed:
        def api(self,endpoint):
            if endpoint=='rate_limit':
                return bad_value if bad_endpoint=='quota' else {'resources':{'core':{'remaining':4000}}}
            if endpoint=='repos/'+row['repository']:return {'id':row['repository_id']}
            if endpoint.endswith('/git/ref/heads/master'):
                return bad_value if bad_endpoint=='master' else {'ref':'refs/heads/master','object':{'type':'commit','sha':row['master_commit']}}
            if '/actions/workflows/' in endpoint:return bad_value
            raise AssertionError(endpoint)
    controller=c.Controller(lambda:row,Malformed(),root=tmp_path/'never')
    with pytest.raises(c.ContractError):controller.select_latest()
    assert not controller.root.exists()


def test_qualified_latest_deploy_uses_selected_record_not_fixed_candidate(fixture,tmp_path,monkeypatch):
    row,receipt,payload,archive=fixture
    native=FakeNative(receipt.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),native,tmp_path/'private')
    controller.tick('enroll')
    row['previous']=receipt.sha256
    # A new evaluated recipe identity is distinct from the original fixed candidate.
    expected=dict(row['expected'],recipe_revision='new-reviewed-fixture-recipe')
    policy=row['policy']
    new=make_receipt(expected,policy,{k:{'status':'passed','contract_digest':digest(v)} for k,v in policy['features'].items()})
    record=c.parse(c.read_regular(controller.root/'records'/(receipt.sha256+'.json')).decode())
    record.update(receipt=base64.b64encode(new.encoded).decode(),expected=expected)
    c.immutable(controller.root/'records'/(new.sha256+'.json'),c.canonical(record))
    ev=c.replace(c.evaluation(row),receipt_sha256=new.sha256)
    controller.attest(new.sha256,ev)
    class Auth:
        def verify(self,ev,path):return SimpleNamespace(authenticates=lambda r:r.sha256==new.sha256)
    controller.evaluator=Auth()
    for op in ('preflight','stage','activate','verify'):
        row['operations'][op]['identity']='qualified-latest'
    def select():
        selected={'commit':row['master_commit'],'identity':new.sha256,'retained':True}
        controller.selection={'enrollment_sha256':digest(row),'latest':row['master_commit'],'selected':selected}
        return {'selected_qualified':selected}
    monkeypatch.setattr(controller,'select_latest',select)
    monkeypatch.setattr(controller,'discover_master',lambda:{'discovered':row['master_commit']})
    monkeypatch.setattr(controller,'acquire',lambda row:pytest.fail('old fixed candidate acquisition must not run'))
    result=controller.tick('deploy')
    assert result['status']=='runtime_verified'
    assert native.identity==new.sha256 != receipt.sha256
    assert native.calls==[('activate',new.sha256)]
    # Current-policy mismatch cannot preserve a derived concrete grant.
    old=dict(row)
    row['operations']['activate']['allowed']=False
    assert not controller.permits(old,'activate',new.sha256)


def test_qualified_latest_requires_selected_current_master(fixture,tmp_path):
    row,receipt,*_=fixture
    row['operations']['activate']['identity']='qualified-latest'
    controller=c.Controller(lambda:row,root=tmp_path/'private')
    assert not controller.permits(row,'activate',receipt.sha256)
    controller.selection={'enrollment_sha256':digest(row),'latest':row['master_commit'],
                          'selected':{'identity':receipt.sha256,'commit':row['master_commit']}}
    controller.discover_master=lambda:{'discovered':'f'*40}
    assert not controller.permits(row,'activate',receipt.sha256)


def test_concrete_grant_missing_protected_passive_profile_holds(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row)
    snapshots.stage(payload,controller.root/'snapshots',snapshots.payload_tree_hash(payload))
    status={'version':1,'pluginId':'ade-yolo','consistency':'coherent',
            'registration':{'path':'/old/A'},'journal':{'generation':8,'phase':'ready',
            'baseline':{'source':{}},'currentReceipt':{'fixture':True}},'loaded':{'activationGeneration':2}}
    with pytest.raises(c.ContractError,match='passive'):controller.concrete_grant(row,receipt.sha256,status)


def test_concrete_grant_binds_exact_tree_and_native_cas(fixture,tmp_path):
    row,_,payload,_=fixture
    policy=dict(row['policy'],native_passive_profile=dict(version=1,contract='native-passive-contract-1',
        qualificationSha256='1'*64,runtimeClosureSha256='2'*64,helperClosureSha256='3'*64,initialization='registration-only'))
    evidence=dict(row['evidence'],server_bundle_sha256='4'*64)
    expected=dict(row['expected'],policy_digest=digest(policy),
        toolchain=c.canonical({'plugin_snapshot_evidence':digest(evidence)}).decode())
    receipt=make_receipt(expected,policy,{k:{'status':'passed','contract_digest':digest(v)} for k,v in policy['features'].items()})
    archive=zip_bytes({'receipt.json':receipt.encoded,'snapshot.json':payload,'evaluator-evidence.json':c.canonical(evidence)})
    row.update(policy=policy,evidence=evidence,expected=expected)
    row['evaluation'].update(receipt_sha256=receipt.sha256,archive_sha256=c.hashlib.sha256(archive).hexdigest())
    for grant in row['operations'].values():grant['identity']=receipt.sha256
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row)
    root=snapshots.stage(payload,controller.root/'snapshots',snapshots.payload_tree_hash(payload))
    status={'version':1,'pluginId':'ade-yolo','consistency':'coherent',
            'registration':{'path':'/old/A'},'journal':{'generation':8,'phase':'ready',
            'baseline':{'source':{}},'currentReceipt':{'fixture':True}},'loaded':{'activationGeneration':2}}
    grant=controller.concrete_grant(row,receipt.sha256,status)
    assert grant['authorization']['expectedGeneration']==8
    assert grant['authorization']['sourcePath']==str(root/'plugins/ade-yolo')
    assert grant['expectedPath']=='/old/A'
    assert 'ownerToken' not in c.canonical(grant).decode()


def test_real_facade_private_fd_transport_and_nonzero_refusal(tmp_path,monkeypatch):
    """Execute a disposable CLI fixture through production bounded pipe code in CI."""
    script=tmp_path/'bridge.py'
    script.write_text('import json,sys\nvalue=sys.stdin.read()\nassert "s"*43 not in sys.argv\nprint(json.dumps({"tokenBytes":len(value.strip()),"args":sys.argv[1:]}))\n')
    facade=c.NativeFacade()
    monkeypatch.setattr(facade,'_transport',lambda:{'node':{'path':sys.executable},'cli':{'path':str(script)}})
    result=facade._call(['fixture','--owner-token-fd','0'],'s'*43)
    assert result['tokenBytes']==43
    assert result['args']==['fixture','--owner-token-fd','0','--json']
    script.write_text('import sys\nprint("{\\"state\\":\\"idle\\"}")\nsys.exit(1)\n')
    with pytest.raises(c.ContractError,match='refused'):facade._call(['fixture'])


def test_native_reservation_context_never_ends_implicitly(monkeypatch):
    facade=c.NativeFacade()
    facade.prepare({'generation':1,'policy':{'compatibility_group':'fixture'}},'a'*64,None)
    monkeypatch.setattr(facade,'supported',lambda:True)
    monkeypatch.setattr(facade,'_identity_args',lambda:[])
    calls=[]
    def invoke(args,token=None):
        calls.append(args)
        return {'state':'held','recoveryRequired':False,'generation':2,
                'transactionId':facade.reservation['transactionId'],'ownerToken':'s'*43}
    monkeypatch.setattr(facade,'_call',invoke)
    with facade.reserve():facade.verified=True
    assert len(calls)==1 and 'begin' in calls[0]
    assert facade.token=='s'*43
    facade.uncertain=True
    with pytest.raises(c.ContractError):facade.finish()
    assert len(calls)==1


def test_selected_release_uses_fresh_attempt_not_first_digest(fixture,tmp_path,monkeypatch):
    row,receipt,payload,archive=fixture
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row)
    old=c.evaluation(row)
    old_value={'receipt_sha256':receipt.sha256,'evaluation':dict(asdict(old),jobs=list(old.jobs))}
    # Find a valid later attempt whose filename sorts AFTER obsolete attempt1.
    for artifact in range(61,500):
        fresh=c.replace(old,run_attempt=2,artifact_id=artifact,artifact_name='qualification-40-2')
        fresh_value={'receipt_sha256':receipt.sha256,'evaluation':dict(asdict(fresh),jobs=list(fresh.jobs))}
        if digest(old_value)<digest(fresh_value):break
    else:pytest.fail('fixture could not arrange obsolete-first digest order')
    controller.attest(receipt.sha256,fresh)
    calls=[]
    class CurrentAttempt:
        def verify(self,expected,path):
            calls.append(expected)
            if expected.run_attempt!=2:raise c.ContractError('obsolete/expired attempt')
            return SimpleNamespace(authenticates=lambda actual:actual.sha256==receipt.sha256)
    controller.evaluator=CurrentAttempt()
    def selected():
        controller.selection={'latest':row['master_commit'],'enrollment_sha256':digest(row),
            'selected':{'identity':receipt.sha256,'commit':row['master_commit']}}
        controller.fresh_attestations={receipt.sha256:fresh}
        return {'selected_qualified':controller.selection['selected']}
    monkeypatch.setattr(controller,'select_latest',selected)
    monkeypatch.setattr(controller,'discover_master',lambda:{'discovered':row['master_commit']})
    assert controller.selected_release(row)[0].sha256==receipt.sha256
    assert calls==[fresh]
    controller.native=FakeNative(receipt.sha256)
    row['previous']=receipt.sha256
    journal=c.Journal(controller.root/'journal',row['policy']['compatibility_group'])
    journal.enroll(receipt.sha256,controller.adapters(row,SimpleNamespace(authenticates=lambda actual:True)))
    for operation in ('preflight','stage','activate','verify'):
        row['operations'][operation]['identity']='qualified-latest'
    assert controller.tick('deploy')['status']=='runtime_verified'
    assert controller.native.calls==[('activate',receipt.sha256)]
    assert calls==[fresh,fresh]
    # A CURRENT authentication refusal still stops, without falling back to old evidence.
    def revoked(expected,path):raise c.ContractError('current policy refused')
    controller.evaluator.verify=revoked
    with pytest.raises(c.ContractError,match='current policy refused'):controller.selected_release(row)
    # Even when fresh provenance is available, retained corruption must remain fatal.
    corrupt=controller.root/'attestations'/receipt.sha256/(digest(old_value)+'.json')
    corrupt.chmod(0o600);corrupt.write_bytes(b'{}')
    with pytest.raises(c.ContractError,match='corruption'):controller.selected_release(row)


@pytest.mark.parametrize('command,operation', [('apply','deploy'),('recover','recover')])
def test_fixed_cli_explicit_transaction_dispatch(monkeypatch,capsys,command,operation):
    calls=[]
    class Transaction:
        def tick(self,value):
            calls.append(value)
            return {'status':'hold','reason':'native_execution_status_reservation_unsupported','authorized':False}
    monkeypatch.setattr(c,'Controller',Transaction)
    assert c.main([command])==1
    assert calls==[operation]
    assert c.parse(capsys.readouterr().out)['status']=='hold'
    with pytest.raises(SystemExit):c.main([command,'--policy','/candidate/grant'])


@pytest.fixture
def cohort_mapping_fixture(fixture,tmp_path):
    """Synthetic wire facts for parser/retained-byte unit tests, NOT producer proof."""
    row,_,payload,_=fixture
    closure={'qualificationSha256':'1'*64,'runtimeClosureSha256':'2'*64,'helperClosureSha256':'3'*64}
    profile=dict(version=1,contract='native-passive-contract-1',initialization='registration-only',**closure)
    policy=dict(row['policy'],native_passive_profile=profile)
    evidence=dict(row['evidence'],server_bundle_sha256='4'*64)
    expected=dict(row['expected'],policy_digest=digest(policy),
        toolchain=c.canonical({'plugin_snapshot_evidence':digest(evidence)}).decode())
    receipt=make_receipt(expected,policy,{k:{'status':'passed','contract_digest':digest(v)} for k,v in policy['features'].items()})
    archive=zip_bytes({'receipt.json':receipt.encoded,'snapshot.json':payload,'evaluator-evidence.json':c.canonical(evidence)})
    row.update(policy=policy,evidence=evidence,expected=expected)
    row['evaluation'].update(receipt_sha256=receipt.sha256,archive_sha256=c.hashlib.sha256(archive).hexdigest())
    for grant in row['operations'].values():grant['identity']=receipt.sha256
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),root=tmp_path/'private')
    controller.acquire(row)
    snapshot=snapshots.stage(payload,controller.root/'snapshots',snapshots.payload_tree_hash(payload))
    config={'serverId':'fixture-server','daemonIncarnation':'fixture-daemon',
            'distributionBuildId':'fixture-build','closure':closure}
    enclosing={'serverId':config['serverId'],'incarnation':config['daemonIncarnation'],
               'distributionBuildId':config['distributionBuildId'],'closure':closure}
    entries=[]
    for plugin in set(row['cohort'])-{'paseo'}:
        root=str(snapshot) if plugin=='ade-yolo' else '/qualified/'+plugin
        source=root+'/plugins/'+plugin
        loaded={'pluginId':plugin,'sourcePath':source,'snapshotRoot':root,
                'snapshotSha256':evidence['native_tree_sha256'],'serverBundleSha256':evidence['server_bundle_sha256'],
                'activationGeneration':2,'pid':123,'processStartToken':'receipt-'+plugin,'startedAt':'2026-11-18T00:00:00Z'}
        execution={'contract':'native-passive-contract-1','incarnation':'receipt-'+plugin,
                   'distributionBuildId':'fixture-build','closure':closure}
        registration={'source':'directory','path':source,'enabled':True}
        entry={'pluginId':plugin,'registration':registration,'enabled':True,
               'journal':{'generation':8,'phase':'held','currentReceipt':loaded},'loaded':loaded,'execution':execution}
        entries.append(entry)
        row['cohort'][plugin]={'enabled':True,'loaded':True,'registration':registration,
            'receipt':{k:loaded[k] for k in ('sourcePath','snapshotRoot','snapshotSha256','serverBundleSha256')},
            'execution':{k:execution[k] for k in ('contract','distributionBuildId','closure')}}
    row['cohort']['paseo']={'role':'daemon','enabled':True,'loaded':True,'distributionBuildId':'fixture-build','closure':closure}
    facts={'version':1,'consistency':'coherent','observationEpoch':9,'enclosing':enclosing,'entries':entries}
    return row,receipt,controller,config,facts


def test_cohort_parser_and_retained_receipt_map(cohort_mapping_fixture,monkeypatch):
    row,receipt,controller,config,facts=cohort_mapping_fixture
    assert c.cohort_observation(facts,config,row['cohort'],'ade-yolo') is facts
    facade=c.NativeFacade(lambda:row,controller.root)
    monkeypatch.setattr(facade,'cohort_status',lambda:c.cohort_observation(facts,config,row['cohort'],'ade-yolo'))
    assert facade.observe(row['cohort'])==receipt.sha256
    target=next(e for e in facts['entries'] if e['pluginId']=='ade-yolo')
    # Native CAS is8 while loaded generation2; identity matching does not rewrite either.
    assert target['journal']['generation']==8 and target['loaded']['activationGeneration']==2
    target['execution']['closure']=dict(config['closure'],qualificationSha256='f'*64)
    with pytest.raises(c.ContractError,match='ambiguous'):facade.observe(row['cohort'])


@pytest.mark.parametrize('change',['omitted','extra-active','enclosing','state','execution','journal'])
def test_cohort_refusals(cohort_mapping_fixture,change):
    row,_,_,config,facts=cohort_mapping_fixture
    if change=='omitted':facts['entries'].pop()
    elif change=='extra-active':
        entry=dict(facts['entries'][0],pluginId='unexpected')
        entry['loaded']=dict(entry['loaded'],pluginId='unexpected');entry['journal']=dict(entry['journal'],currentReceipt=entry['loaded'])
        facts['entries'].append(entry)
    elif change=='enclosing':facts['enclosing']['incarnation']='replaced-daemon'
    elif change=='state':
        entry=next(e for e in facts['entries'] if e['pluginId']!='ade-yolo');entry['enabled']=False
    elif change=='execution':facts['entries'][0]['execution']=None
    elif change=='journal':facts['entries'][0]['journal']['currentReceipt']={}
    with pytest.raises(c.ContractError):c.cohort_observation(facts,config,row['cohort'],'ade-yolo')


def test_real_facade_supported_requires_complete_proof(monkeypatch):
    facade=c.NativeFacade()
    monkeypatch.setattr(facade,'cohort_status',lambda:(_ for _ in ()).throw(c.ContractError('native private producer missing')))
    assert facade.supported() is False


def test_cohort_rejects_old_execution_incarnation(cohort_mapping_fixture):
    row,_,_,config,facts=cohort_mapping_fixture
    facts['entries'][0]['execution']['incarnation']='stale-owned-child'
    with pytest.raises(c.ContractError,match='incarnation'):c.cohort_observation(facts,config,row['cohort'],'ade-yolo')


def test_python_preexec_manifest_verifier_real_protected_inventory(tmp_path):
    """CI-only root-owned disposable tree, no Node execution or runtime qualification."""
    import uuid
    if sys.platform!='linux':pytest.fail('finite adapter regression requires Linux CI')
    root=Path('/opt')/('ade-controller-unit-'+uuid.uuid4().hex)
    staging=tmp_path/'distribution';staging.mkdir()
    paths=['runtime/node','runtime/esbuild','cli-entry.mjs','daemon.mjs','plugin-child-entry.mjs','compiler-entry.mjs','terminal-entry.mjs']
    files=[]
    for name in sorted(paths):
        path=staging/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(('unit '+name).encode())
        mode=0o555 if name.startswith('runtime/') else 0o444;path.chmod(mode)
        files.append({'path':name,'mode':mode,'size':path.stat().st_size,'sha256':c.hashlib.sha256(path.read_bytes()).hexdigest()})
    helpers=sorted([item for item in files if item['path'].startswith('runtime/') or item['path'] in ('compiler-entry.mjs','terminal-entry.mjs')],key=lambda i:i['path'])
    producer_json=lambda value:c.json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    helper_sha=c.hashlib.sha256(producer_json(helpers)).hexdigest()
    manifest={'schemaVersion':2,'profile':'enclosing-daemon-v2','distributionBuildId':'unit-build','files':files,
              'runtime':next(x for x in files if x['path']=='runtime/node'),
              'esbuild':next(x for x in files if x['path']=='runtime/esbuild'),'externalLibraries':[],
              'helperInventory':helpers,'helperClosureSha256':helper_sha,
              'entries':{'daemon':'daemon.mjs','pluginChild':'plugin-child-entry.mjs','compiler':'compiler-entry.mjs','terminal':'terminal-entry.mjs'},
              'bindingKeys':sorted(['@getpaseo/plugin/internal/activity','@getpaseo/plugin','@getpaseo/plugin/server',
                '@getpaseo/plugin/server/provider','@getpaseo/plugin/server/acp','@getpaseo/plugin/server/usage',
                '@getpaseo/client','@getpaseo/client/internal/daemon-client','@getpaseo/protocol/binary-frames/index','zod'])}
    raw=producer_json(manifest);manifest_file=tmp_path/'manifest';manifest_file.write_bytes(raw);manifest_file.chmod(0o444)
    def sudo(*args):subprocess.run(['sudo','-k','-n',*map(str,args)],check=True,timeout=30)
    try:
        sudo('cp','-a',staging,root);sudo('cp',manifest_file,str(root)+'.manifest.json')
        sudo('chown','-R','0:0',root);sudo('chown','0:0',str(root)+'.manifest.json')
        sudo('chmod','555',root,root/'runtime');sudo('chmod','444',str(root)+'.manifest.json')
        sha=c.hashlib.sha256(raw).hexdigest()
        config={'distributionRoot':str(root),'distributionSha256':sha,'distributionBuildId':'unit-build',
                'closure':{'runtimeClosureSha256':sha,'helperClosureSha256':helper_sha,'qualificationSha256':'a'*64},
                'node':{'path':str(root/'runtime/node')},'cli':{'path':str(root/'cli-entry.mjs')}}
        assert c.verify_transport_distribution(config)['distributionBuildId']=='unit-build'
        sudo('chmod','644',root/'cli-entry.mjs')
        with pytest.raises(c.ContractError,match='mismatch'):c.verify_transport_distribution(config)
    finally:
        sudo('rm','-rf','--',root,str(root)+'.manifest.json')
