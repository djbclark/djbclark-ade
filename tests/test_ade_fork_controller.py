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
    def prepare(self,context):
        self.context=context
        return c.release.ReservationIntent(12,7,'fixture-server','fixture-incarnation')
    def reserve(self,context,intent): return c.release.BeginResult('held')
    def finish(self,context,intent): self.calls.append(('finish',context.target)); return True
    def released(self,context,intent): return True
    def reuse(self,*args): raise AssertionError('ordinary fake port cannot reuse a bearer')


def test_real_archive_retention_and_noop_is_not_activation(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    native=FakeNative(receipt.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,receipt),native,tmp_path/'private')
    assert controller.tick('enroll')['status']=='enrolled'
    assert controller.retained(receipt.sha256)
    assert controller.tick('deploy')['reason']=='already_verified'
    assert native.calls==[]



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
    assert native.calls==[('activate',new.sha256),('finish',new.sha256)]
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


def test_native_reservation_never_ends_on_uncertain_operation(monkeypatch):
    facade=c.NativeFacade()
    context=c.release.TransactionContext(1,'fixture','deploy',4,5,'a'*32,'b'*64,None,'c'*64,'d'*64)
    intent=c.release.ReservationIntent(12,7,'server','incarnation')
    facade.context=context;facade.intent=intent
    facade.token='s'*43;facade.reservation={'generation':12,'transactionId':context.transaction_id}
    facade.verified=True;facade.uncertain=True
    monkeypatch.setattr(facade,'_call',lambda *args:pytest.fail('uncertain operation cannot END'))
    with pytest.raises(c.ContractError):facade.finish(context,intent)



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
    assert controller.tick('deploy')['reason']=='already_verified'
    assert controller.native.calls==[]
    assert calls==[fresh,fresh]
    # A CURRENT authentication refusal still stops, without falling back to old evidence.
    def revoked(expected,path):raise c.ContractError('current policy refused')
    controller.evaluator.verify=revoked
    with pytest.raises(c.ContractError,match='current policy refused'):controller.selected_release(row)
    # Even when fresh provenance is available, retained corruption must remain fatal.
    corrupt=controller.root/'attestations'/receipt.sha256/(digest(old_value)+'.json')
    corrupt.chmod(0o600);corrupt.write_bytes(b'{}')
    with pytest.raises(c.ContractError,match='corruption'):controller.selected_release(row)


@pytest.mark.parametrize('command,operation', [('apply','deploy'),('recover','recover'),('resume','resume'),('reconcile-release','reconcile-release')])
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
    monkeypatch.setattr(facade,'cohort_status',lambda **options:c.cohort_observation(facts,config,row['cohort'],'ade-yolo',**options))
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
    root=Path('/var/lib')/('ade-controller-unit-'+uuid.uuid4().hex)
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


@pytest.mark.parametrize('restores_child',[True,False])
def test_real_facade_absent_target_recovery_keeps_postverify_strict(cohort_mapping_fixture,monkeypatch,restores_child):
    """Actual facade+Journal, synthetic authenticated wire; no production qualification."""
    row,receipt,stored,config,facts=cohort_mapping_fixture
    row['previous']=receipt.sha256
    target=next(e for e in facts['entries'] if e['pluginId']=='ade-yolo')
    original=c.parse(c.canonical(target['loaded']).decode())
    target['journal']['baseline']={'source':target['registration'],'receipt':original}
    native=c.NativeFacade(lambda:row,stored.root)
    monkeypatch.setattr(native,'_transport',lambda:config)
    calls=[]
    def wire(args,token=None):
        calls.append((args,token))
        if args==['plugin','cohort-status']:return c.parse(c.canonical(facts).decode())
        if args==['daemon','maintenance','status']:
            return {'schemaVersion':1,'state':'idle','generation':None,'reservationGeneration':11,'ready':True,'transactionId':None,'recoveryRequired':False,'authority':{'schemaVersion':1,'qualified':True,'serverId':config['serverId'],
                'daemonIncarnation':config['daemonIncarnation'],
                'features':{'maintenanceReservationV1':True,'maintenancePluginOperationV1':True}}}
        if args==['plugin','managed-status','ade-yolo']:
            return {'version':1,'pluginId':'ade-yolo','consistency':'coherent',
                'registration':target['registration'],'journal':target['journal'],'loaded':target['loaded']}
        if args[:3]==['daemon','maintenance','begin']:
            return dict(native.reservation,state='held',recoveryRequired=False,ownerToken='s'*43)
        if args[:3]==['daemon','maintenance','plugin-operation']:
            assert token=='s'*43
            operation=args[args.index('--operation')+1]
            assert operation in ('recover','verify')
            assert args[args.index('--expected-generation')+1]==str(target['journal']['generation'])
            if operation=='recover':
                loaded=dict(original,activationGeneration=9,processStartToken='recovered-owned-child')
                target['loaded']=loaded;target['enabled']=True
                target['execution']={'contract':'native-passive-contract-1','incarnation':loaded['processStartToken'],
                    'distributionBuildId':'fixture-build','closure':config['closure']}
                target['journal'].update(generation=9,currentReceipt=loaded)
                facts['observationEpoch']+=1
            result={'plugin':{'id':'ade-yolo','enabled':True,'status':'running','loaded':target['loaded']},
                'nativeGeneration':target['journal']['generation'],'maintenance':{'state':'held'},
                'serverId':config['serverId'],'daemonIncarnation':config['daemonIncarnation']}
            if operation=='recover' and not restores_child:
                # An apparent successful response cannot substitute for later actual liveness.
                target['loaded']=None;target['execution']=None
            return result
        if args[:3]==['daemon','maintenance','end']:
            assert token=='s'*43
            return dict(native.reservation,state='idle',recoveryRequired=False,reservationGeneration=native.reservation['generation'])
        raise AssertionError(args)
    monkeypatch.setattr(native,'_call',wire)
    controller=c.Controller(lambda:row,native=native,root=stored.root)
    journal=c.Journal(stored.root/'journal',row['policy']['compatibility_group'])
    journal.enroll(receipt.sha256,controller.adapters(row,None))
    pending=journal.read()
    context=c.release.TransactionContext(1,journal.group,'deploy',0,1,'f'*32,receipt.sha256,None,'e'*64,digest(row))
    intent=c.release.ReservationIntent(10,7,config['serverId'],config['daemonIncarnation'])
    pending.update(generation=1,state='recovery_required',candidate='e'*64,
        transaction={'context':asdict(context),'reservation':asdict(intent)})
    journal.write(pending)
    row['generation']=1
    for grant in row['operations'].values():grant['generation']=1
    # Failed activation/crash: no child, no execution metadata; other cohort remains unchanged.
    target['loaded']=None;target['execution']=None
    assert native.supported() is True  # operation capability, not a fake loaded receipt
    with pytest.raises(c.ContractError):native.observe(row['cohort'])  # ordinary observation strict
    native.recovery_inspection=True
    inspected=native.observe(row['cohort'])
    assert inspected.startswith('native-target-absent:v1:') and inspected!=receipt.sha256
    result=controller.tick('recover')
    operations=[args[args.index('--operation')+1] for args,_ in calls if args[:3]==['daemon','maintenance','plugin-operation']]
    assert operations and operations[0]=='recover',result
    if restores_child:
        assert result['status']=='runtime_verified'
        assert native.observe(row['cohort'])==receipt.sha256
        assert operations==['recover','verify','verify']
        assert any(args[:3]==['daemon','maintenance','end'] for args,_ in calls)
    else:
        assert result['status']=='recovery_required'
        assert not any(args[:3]==['daemon','maintenance','end'] for args,_ in calls)
        assert native.recovery_inspection is False


@pytest.mark.parametrize('enabled',[False,None])
def test_failed_target_state_inspection_does_not_relax_other_cohort(cohort_mapping_fixture,enabled):
    row,_,_,config,facts=cohort_mapping_fixture
    target=next(e for e in facts['entries'] if e['pluginId']=='ade-yolo')
    target.update(loaded=None,execution=None,enabled=enabled)
    assert c.cohort_observation(facts,config,row['cohort'],'ade-yolo',allow_target_absent=True) is facts
    with pytest.raises(c.ContractError):c.cohort_observation(facts,config,row['cohort'],'ade-yolo')
    other=next(e for e in facts['entries'] if e['pluginId']!='ade-yolo')
    other.update(loaded=None,execution=None)
    with pytest.raises(c.ContractError,match='non-target'):c.cohort_observation(facts,config,row['cohort'],'ade-yolo',allow_target_absent=True)


def versioned_rule(row):
    result=c.parse(c.canonical(row).decode());result['schema_version']=2
    result['operations']={key:{'version':1,'grants':[dict(mode='exact',**grant)]} for key,grant in row['operations'].items()}
    return result


def consent_context(row,kind,target,*,verified=None,baseline=None,generation=7):
    return SimpleNamespace(rule_digest=digest(row),group='paseo-runtime',kind=kind,target=target,
        verified=verified or target,baseline=baseline,cas_generation=generation)


@pytest.mark.parametrize('kind,selector,target',[
    ('deploy','qualified-latest','b'),('reconcile','recorded-verified','c'),('verified-rollback','recorded-baseline','a')])
def test_v2_finite_explicit_selector_table(fixture,kind,selector,target):
    row,*_=fixture;row=versioned_rule(row)
    identity=target*64
    operation='activate' if kind=='deploy' else 'recover'
    for op in (operation,'verify'):
        row['operations'][op]={'version':1,'grants':[{'mode':'standing','allowed':True,'selectors':[selector]}]}
    c.enrollment(c.canonical(row),c.load_policy())
    ctx=consent_context(row,kind,identity,verified='c'*64,baseline='a'*64)
    assert c.rule_allows(row,operation,identity,ctx,selected_current=True)
    assert c.rule_allows(row,'verify',identity,ctx,selected_current=True)
    assert not c.rule_allows(row,operation,'f'*64,ctx,selected_current=True)


def test_recorded_baseline_never_authorizes_verified_reconciliation(fixture):
    row,*_=fixture;row=versioned_rule(row)
    row['operations']['recover']={'version':1,'grants':[{'mode':'standing','allowed':True,'selectors':['recorded-baseline']}]}
    ctx=consent_context(row,'reconcile','b'*64,verified='b'*64,baseline='a'*64)
    assert not c.rule_allows(row,'recover','b'*64,ctx)


@pytest.mark.parametrize('kind',['resume','reconcile-release'])
def test_resume_release_and_verify_require_exact_grants(fixture,kind):
    row,*_=fixture;row=versioned_rule(row);identity='a'*64
    row['operations'][kind]={'version':1,'grants':[{'mode':'exact','allowed':True,'identity':identity,'generation':7}]}
    row['operations']['verify']={'version':1,'grants':[{'mode':'standing','allowed':True,'selectors':['recorded-baseline','recorded-verified','qualified-latest']}]}
    ctx=consent_context(row,kind,identity,baseline=identity)
    assert c.rule_allows(row,kind,identity,ctx)
    assert not c.rule_allows(row,'verify',identity,ctx,selected_current=True)
    row['operations']['verify']['grants'].append({'mode':'exact','allowed':True,'identity':identity,'generation':7})
    ctx=consent_context(row,kind,identity,baseline=identity)
    assert c.rule_allows(row,'verify',identity,ctx)
    ctx.cas_generation=8
    assert not c.rule_allows(row,kind,identity,ctx)


def test_matching_denial_wins_and_legacy_generation_not_widened(fixture):
    row,receipt,*_=fixture;legacy=c.parse(c.canonical(row).decode())
    ctx=consent_context(legacy,'deploy',receipt.sha256,generation=1)
    assert not c.rule_allows(legacy,'activate',receipt.sha256,ctx)
    row=versioned_rule(row)
    row['operations']['activate']={'version':1,'grants':[
        {'mode':'standing','allowed':True,'selectors':['qualified-latest']},
        {'mode':'exact','allowed':False,'identity':receipt.sha256,'generation':7}]}
    ctx=consent_context(row,'deploy',receipt.sha256)
    assert not c.rule_allows(row,'activate',receipt.sha256,ctx,selected_current=True)
    ctx.cas_generation=8
    assert c.rule_allows(row,'activate',receipt.sha256,ctx,selected_current=True)


@pytest.mark.parametrize('bad',['empty','duplicate','wildcard','nonliteral','unknown','standing-resume','too-many'])
def test_strict_versioned_grants_schema(fixture,bad):
    row,*_=fixture;row=versioned_rule(row)
    wrapper=row['operations']['activate'];grant=wrapper['grants'][0]
    if bad=='empty':wrapper['grants']=[]
    elif bad=='duplicate':wrapper['grants'].append(dict(grant))
    elif bad=='wildcard':wrapper['grants']=[{'mode':'standing','allowed':True,'selectors':['*']}]
    elif bad=='nonliteral':grant['allowed']=1
    elif bad=='unknown':grant['unprotected']=True
    elif bad=='standing-resume':row['operations']['resume']={'version':1,'grants':[{'mode':'standing','allowed':True,'selectors':['recorded-verified']}]}
    elif bad=='too-many':wrapper['grants']=[dict(grant,generation=i) for i in range(33)]
    with pytest.raises(c.ContractError):c.enrollment(c.canonical(row),c.load_policy())


def test_recorded_reconciliation_consent_does_not_query_latest_master(fixture,monkeypatch):
    row,receipt,*_=fixture;row=versioned_rule(row)
    for operation in ('recover','verify'):
        selectors=['recorded-verified'] if operation=='recover' else ['qualified-latest','recorded-verified']
        row['operations'][operation]={'version':1,'grants':[{'mode':'standing','allowed':True,'selectors':selectors}]}
    controller=c.Controller(lambda:row)
    controller.context=consent_context(row,'reconcile',receipt.sha256,verified=receipt.sha256)
    controller.selection={'enrollment_sha256':digest(row),'latest':row['master_commit'],'selected':{'identity':receipt.sha256}}
    monkeypatch.setattr(controller,'discover_master',lambda:pytest.fail('reconciliation must not depend on candidate discovery'))
    assert controller.permits(row,'recover',receipt.sha256)
    assert controller.permits(row,'verify',receipt.sha256)


@pytest.mark.parametrize('case',['typed-busy','generic','stdout','other-operation','malformed'])
def test_retained_cli_typed_busy_only_not_messages_or_idle(tmp_path,monkeypatch,case):
    script=tmp_path/'native-begin.py'
    error={'error':{'code':'MAINTENANCE_KNOWN_BUSY','message':'Maintenance reservation refused'}}
    if case=='generic':error={'error':{'message':'MAINTENANCE_KNOWN_BUSY'}}
    if case=='malformed':error={'error':{'code':'MAINTENANCE_KNOWN_BUSY','message':'Maintenance reservation refused','extra':True}}
    program='import sys,json\n'
    if case=='stdout':program+='print(json.dumps({"state":"idle"}))\n'
    program+='print('+repr(c.json.dumps(error))+',file=sys.stderr)\nsys.exit(1)\n'
    script.write_text(program)
    native=c.NativeFacade()
    monkeypatch.setattr(native,'_transport',lambda:{'node':{'path':sys.executable},'cli':{'path':str(script)}})
    args=['daemon','maintenance','begin' if case!='other-operation' else 'end']
    expected=c.NativeKnownBusy if case=='typed-busy' else c.ContractError
    with pytest.raises(expected) as caught:native._call(args)
    assert isinstance(caught.value,c.NativeKnownBusy)==(case=='typed-busy')


def test_native_reservation_counter_is_explicit_and_distinct():
    config={'serverId':'fixed-server','daemonIncarnation':'fixed-incarnation'}
    status={'schemaVersion':1,'state':'idle','generation':None,'reservationGeneration':40,'ready':True,'recoveryRequired':False,
        'authority':{'schemaVersion':1,'qualified':True,**config,
            'features':{'maintenanceReservationV1':True,'maintenancePluginOperationV1':True}}}
    plugin={'journal':{'generation':8},'loaded':{'activationGeneration':2}}
    assert c.native_reservation_plan(status,config,plugin)=={'native_generation':41,'plugin_generation':8,
        'server_id':'fixed-server','daemon_incarnation':'fixed-incarnation'}
    # Neither outer Journal generation nor loaded generation is a reservation counter.
    del status['reservationGeneration']
    with pytest.raises(c.ContractError):c.native_reservation_plan(status,config,plugin)
    status['reservationGeneration']=0
    assert c.native_reservation_plan(status,config,plugin)['native_generation']==1
    for key,value in [('ready',False),('state','held'),('recoveryRequired',True),('reservationGeneration',None)]:
        invalid=dict(status,**{key:value})
        with pytest.raises(c.ContractError):c.native_reservation_plan(invalid,config,plugin)


def test_controller_standing_repeats_rollback_hold_and_exact_resume(fixture,tmp_path,monkeypatch):
    """Journal+real retained bytes with synthetic ports, never production qualification."""
    row,first,payload,archive=fixture
    native=FakeNative(first.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,first),native,tmp_path/'private')
    controller.tick('enroll')
    row['schema_version']=2
    row['operations']={op:{'version':1,'grants':[{'mode':'standing','allowed':True,
        'selectors':sorted(c.STANDING_SELECTORS[op])}]} for op in ('retain','preflight','stage','activate','recover','verify')}
    c.validate_operations(row)
    original_rule=digest(row)
    def candidate(recipe):
        record=c.parse(c.read_regular(controller.root/'records'/(first.sha256+'.json')).decode())
        record['expected']['recipe_revision']=recipe
        receipt=make_receipt(record['expected'],row['policy'],{k:{'status':'passed','contract_digest':digest(v)} for k,v in row['policy']['features'].items()})
        record['receipt']=base64.b64encode(receipt.encoded).decode()
        c.immutable(controller.root/'records'/(receipt.sha256+'.json'),c.canonical(record))
        def selected(rule):
            controller.selection={'enrollment_sha256':digest(rule),'latest':rule['master_commit'],
                'selected':{'identity':receipt.sha256,'commit':rule['master_commit']}}
            return receipt,payload,SimpleNamespace(authenticates=lambda actual:actual.sha256==receipt.sha256),record
        monkeypatch.setattr(controller,'selected_release',selected)
        return receipt
    monkeypatch.setattr(controller,'discover_master',lambda:{'discovered':row['master_commit']})
    second=candidate('standing-B')
    assert controller.tick('deploy')['status']=='runtime_verified'
    third=candidate('standing-C')
    assert controller.tick('deploy')['status']=='runtime_verified'
    journal=controller.journal
    assert journal.read()['generation']==2 and journal.read()['baseline']==second.sha256
    assert digest(row)==original_rule  # no protected generation rewrite for standing consent
    assert controller.tick('recover')['status']=='runtime_verified'
    assert native.identity==second.sha256
    assert journal.read()['promotion_hold'] is True and journal.read()['baseline'] is None
    assert controller.tick('deploy')['reason']=='promotion_hold'
    assert controller.tick('resume')['status']=='hold'  # standing verify cannot authorize resume
    cas=journal.read()['generation']
    exact={'mode':'exact','allowed':True,'identity':second.sha256,'generation':cas}
    row['operations']['resume']={'version':1,'grants':[exact]}
    row['operations']['verify']['grants'].append(exact)
    c.validate_operations(row)
    before=list(native.calls)
    assert controller.tick('resume')['reason']=='resumed'
    assert native.calls==before  # no reservation, END, or binary operation on resume
    assert journal.read()['generation']==cas+1
    assert controller.tick('deploy')['status']=='runtime_verified'
    assert native.identity==third.sha256


def test_real_facade_success_callbacks_return_none(monkeypatch):
    native=c.NativeFacade()
    monkeypatch.setattr(native,'_operation',lambda *args:{'plugin':{'id':'fixture'}})
    assert native.activate('a'*64,{}) is None
    assert native.recover('a'*64,{}) is None


@pytest.mark.parametrize('outcome',['throw','dict'])
def test_controller_unconfirmed_native_outcome_is_sticky(fixture,tmp_path,outcome):
    row,baseline,payload,archive=fixture
    class Unconfirmed(FakeNative):
        def activate(self,identity,record):
            self.calls.append(('activate',identity))
            if outcome=='throw':raise RuntimeError('lost ACK')
            return {'outcome':'known_failed_held','reason':'compiler_error'}
    native=Unconfirmed(baseline.sha256)
    controller=c.Controller(lambda:row,FakeEvaluator(archive,baseline),native,tmp_path/'private')
    controller.tick('enroll')
    expected=dict(row['expected'],recipe_revision='unconfirmed-candidate')
    candidate=make_receipt(expected,row['policy'],{k:{'status':'passed','contract_digest':digest(v)} for k,v in row['policy']['features'].items()})
    candidate_archive=zip_bytes({'receipt.json':candidate.encoded,'snapshot.json':payload,'evaluator-evidence.json':c.canonical(row['evidence'])})
    row['expected']=expected
    row['evaluation'].update(receipt_sha256=candidate.sha256,archive_sha256=c.hashlib.sha256(candidate_archive).hexdigest())
    for grant in row['operations'].values():grant['identity']=candidate.sha256
    controller.evaluator=FakeEvaluator(candidate_archive,candidate)
    assert controller.tick('deploy')['status']=='recovery_required'
    assert controller.journal.read()['state']=='reservation_unknown'
    before=list(native.calls)
    assert controller.tick('recover')['reason']=='reservation_unknown'
    assert native.calls==before


def test_known_held_wire_requires_feature_live_bearer_and_exact_baseline(cohort_mapping_fixture,monkeypatch):
    """Actual facade parser with synthetic wire; does NOT mint native driver authority."""
    row,receipt,stored,config,facts=cohort_mapping_fixture
    native=c.NativeFacade(lambda:row,stored.root)
    monkeypatch.setattr(native,'_transport',lambda:config)
    target=next(e for e in facts['entries'] if e['pluginId']=='ade-yolo')
    context=c.release.TransactionContext(1,row['policy']['compatibility_group'],'deploy',0,1,'a'*32,receipt.sha256,None,'b'*64,digest(row))
    intent=c.release.ReservationIntent(12,8,config['serverId'],config['daemonIncarnation'])
    native.bind(row,context,None)
    native.intent=intent;native.original_native=(context,intent)
    native.reservation={'generation':12,'transactionId':context.transaction_id};native.token='s'*43;native.plugin_generation=8
    record=c.parse(c.read_regular(stored.root/'records'/(receipt.sha256+'.json')).decode())
    root=stored.root/'snapshots'/record['payload_sha256']
    baseline={'path':str(root/'plugins/ade-yolo'),'snapshotSha256':record['evidence']['native_tree_sha256'],
              'serverBundleSha256':record['evidence']['server_bundle_sha256']}
    target.update(loaded=None,execution=None)
    target['journal']['generation']=9
    restriction={'pluginId':'ade-yolo','baseline':baseline,'nativeGeneration':9,'phase':'recover-required'}
    status={'state':'held','reservationGeneration':12,'generation':12,'transactionId':context.transaction_id,
        'recoveryRequired':True,'recoveryOnly':restriction,'authority':{'qualified':True,'serverId':config['serverId'],
            'daemonIncarnation':config['daemonIncarnation'],'features':{'maintenanceKnownFailedHeldV1':True}}}
    result={'outcome':'known_failed_held','reason':'compiler_error','pluginId':'ade-yolo','nativeGeneration':9,
        'current':{'registration':{'path':target['registration']['path'],'enabled':True},'loaded':None},
        'baseline':baseline,'maintenance':status,'serverId':config['serverId'],'daemonIncarnation':config['daemonIncarnation']}
    monkeypatch.setattr(native,'_call',lambda args:status)
    monkeypatch.setattr(native,'cohort_status',lambda **kwargs:facts)
    observation=native._accept_known_held(result,context.target,record)
    assert type(observation) is c.release.KnownFailedHeld and observation.plugin_generation==9
    native.token=None
    with pytest.raises(c.ContractError):native._accept_known_held(result,context.target,record)
    assert native.uncertain is True


@pytest.fixture
def cohort_v2_fixture(cohort_mapping_fixture):
    """Synthetic independently separated manifest/host/wire identities; no runtime proof."""
    row,receipt,stored,old_config,facts=cohort_mapping_fixture
    config=dict(old_config,cohortVersion=2,distributionRoot='/retained/fixture-distribution')
    expected=c.parse(c.canonical(row['cohort']).decode())
    value=c.parse(c.canonical(facts).decode());value['version']=2
    for entry in value['entries']:
        entry['kind']='directory'
        if entry['loaded'] is not None:entry['loaded']={'kind':'plugin-child','receipt':entry['loaded']}
        if entry['execution'] is not None:entry['execution']['kind']='plugin-child'
    manifests={}
    for index in range(14):
        plugin=f'builtin-{index:02d}'
        source=config['distributionRoot']+'/builtin-plugins/'+plugin
        stable={'kind':'builtin-in-process','contract':'builtin-in-process-v1','distributionBuildId':config['distributionBuildId'],
                'sourcePath':source,'sourceSha256':digest(['source',plugin]),'serverBundleSha256':digest(['bundle',plugin]),
                'moduleTableSha256':digest(['modules',plugin]),'profileSha256':digest(['profile',plugin]),'closure':config['closure']}
        manifests[plugin]=c.parse(c.canonical(stable).decode())
        expected[plugin]={'kind':'builtin-in-process','enabled':True,'loaded':True,'registration':{'path':source},
                          'execution':c.parse(c.canonical(stable).decode())}
        loaded={key:item for key,item in stable.items() if key not in ('contract','distributionBuildId')}
        loaded.update(pluginId=plugin,instanceId=f'actual-instance-{index}',enclosingIncarnation=config['daemonIncarnation'])
        execution=dict(loaded,contract='builtin-in-process-v1',distributionBuildId=config['distributionBuildId'])
        value['entries'].append({'kind':'builtin-in-process','pluginId':plugin,'registration':{'path':source},
                                'enabled':True,'loaded':loaded,'execution':execution})
    return value,config,expected,manifests


def test_v2_pure_parser_keeps_real_builtin_shape_and_v1_strict(cohort_v2_fixture):
    value,config,expected,manifests=cohort_v2_fixture
    assert c.cohort_v2_observation(value,config,expected,'ade-yolo',manifests) is value
    assert all('journal' not in entry and 'pid' not in entry['loaded'] and 'activationGeneration' not in entry['loaded']
               for entry in value['entries'] if entry['kind']=='builtin-in-process')
    with pytest.raises(c.ContractError):c.cohort_observation(value,config,expected,'ade-yolo')
    unopted=dict(config);unopted.pop('cohortVersion')
    with pytest.raises(c.ContractError,match='opt-in'):c.cohort_v2_observation(value,unopted,expected,'ade-yolo',manifests)


@pytest.mark.parametrize('mutation',['null-profile','missing-execution','wrong-instance','duplicate-instance','duplicate-id',
    'missing-builtin','extra-builtin','wrong-root','forged-wire-and-host','wrong-tag','fake-journal','child-tag','uncertain'])
def test_v2_negative_identity_matrix(cohort_v2_fixture,mutation):
    value,config,expected,manifests=cohort_v2_fixture
    builtins=[entry for entry in value['entries'] if entry['kind']=='builtin-in-process']
    entry=builtins[0]
    if mutation=='null-profile':
        entry['loaded']['profileSha256']=None;entry['execution']['profileSha256']=None
        expected[entry['pluginId']]['execution']['profileSha256']=None
        manifests[entry['pluginId']]['profileSha256']=None
    elif mutation=='missing-execution':entry['execution']=None
    elif mutation=='wrong-instance':entry['execution']['instanceId']='other-instance'
    elif mutation=='duplicate-instance':
        builtins[1]['loaded']['instanceId']=entry['loaded']['instanceId']
        builtins[1]['execution']['instanceId']=entry['loaded']['instanceId']
    elif mutation=='duplicate-id':value['entries'].append(entry)
    elif mutation=='missing-builtin':value['entries'].remove(entry)
    elif mutation=='extra-builtin':
        extra=c.parse(c.canonical(entry).decode());extra['pluginId']='unexpected-active-builtin';value['entries'].append(extra)
    elif mutation=='wrong-root':
        entry['registration']['path']='/mutable/builtin-plugins/'+entry['pluginId']
        entry['loaded']['sourcePath']=entry['registration']['path'];entry['execution']['sourcePath']=entry['registration']['path']
    elif mutation=='forged-wire-and-host':
        entry['loaded']['moduleTableSha256']='e'*64;entry['execution']['moduleTableSha256']='e'*64
        expected[entry['pluginId']]['execution']['moduleTableSha256']='e'*64  # independent manifest still refuses
    elif mutation=='wrong-tag':entry['kind']='directory'
    elif mutation=='fake-journal':entry['journal']={'generation':1}
    elif mutation=='child-tag':
        directory=next(entry for entry in value['entries'] if entry['kind']=='directory')
        directory['loaded']['kind']='builtin-in-process'
    elif mutation=='uncertain':value={'version':2,'consistency':'uncertain','reason':'incomplete'}
    with pytest.raises(c.ContractError):c.cohort_v2_observation(value,config,expected,'ade-yolo',manifests,allow_target_absent=True)


def test_v2_requires_independent_manifest_inventory(cohort_v2_fixture):
    value,config,expected,manifests=cohort_v2_fixture
    with pytest.raises(c.ContractError):c.cohort_v2_observation(value,config,expected,'ade-yolo',{})
    manifests.pop(next(iter(manifests)))
    with pytest.raises(c.ContractError):c.cohort_v2_observation(value,config,expected,'ade-yolo',manifests)


def test_v2_opt_in_does_not_fall_back_to_v1_transport(cohort_v2_fixture,monkeypatch):
    _,config,_,_=cohort_v2_fixture
    native=c.NativeFacade(lambda:{'cohort':{},'component':'ade-yolo'})
    monkeypatch.setattr(native,'_transport',lambda:config)
    calls=[]
    def unavailable(args):
        calls.append(args)
        raise c.ContractError('actual V2 unavailable')
    monkeypatch.setattr(native,'_call',unavailable)
    assert native.supported() is False
    assert calls==[['plugin','cohort-v2-status']]


@pytest.fixture
def builtin_manifest_fixture():
    """Canonical producer shape, synthetic file digests; no native process qualification."""
    config={'distributionRoot':'/retained/native','distributionBuildId':'native-fixture',
        'distributionSha256':'1'*64,'closure':{'runtimeClosureSha256':'1'*64,'helperClosureSha256':'2'*64,'qualificationSha256':'3'*64}}
    files=[]
    def identity(path):
        item={'path':path,'size':10,'mode':0o444,'sha256':digest(path)}
        files.append(item);return item
    runtime=identity('runtime/node');daemon=identity('daemon.mjs')
    table={'schemaVersion':1,'recipe':c.BUILTIN_RECIPE,'runtimeSha256':runtime['sha256'],'daemonSha256':daemon['sha256'],'externalLibraries':[]}
    table_sha=c.hashlib.sha256(c.builtin_json(table)).hexdigest()
    artifacts=[];profiles=[]
    for plugin in c.BUILTIN_IDS:
        prefix='builtin-compiled/'+plugin
        factory=identity(prefix+'/server.factory.js');original=identity(prefix+'/server-original.js')
        source=identity(prefix+'/source-identity.json')
        identity(prefix+'/manifest.json');identity(prefix+'/metafile.json');identity('builtin-plugins/'+plugin+'/paseo-plugin.json')
        artifacts.append({'id':plugin,'moduleTableSha256':table_sha,'sourceIdentityPath':source['path'],'sourceSha256':source['sha256'],
            'serverBundleSha256':factory['sha256'],'originalServerBundleSha256':original['sha256'],'factoryPath':factory['path'],
            'manifestPath':prefix+'/manifest.json','metafilePath':prefix+'/metafile.json','moduleImports':[]})
        profiles.append({'id':plugin,'sourceSha256':source['sha256'],'serverBundleSha256':factory['sha256'],
            'moduleTableSha256':table_sha,'activityContract':'builtin-in-process-v1','profileSha256':digest(['protected-profile',plugin])})
    manifest={'files':files,'runtime':runtime,'externalLibraries':[],'builtinPlugins':list(c.BUILTIN_IDS),
        'builtinArtifacts':artifacts,'builtinModuleTable':table,'moduleTableSha256':table_sha}
    policy={'schemaVersion':1,'qualifications':[{'immutableRoot':config['distributionRoot'],'immutabilityAdapter':'linux-root-owned-retained-v1',
        'manifestSha256':config['distributionSha256'],'distributionBuildId':config['distributionBuildId'],
        'qualificationSha256':config['closure']['qualificationSha256'],'builtinProfiles':profiles}]}
    return manifest,config,policy


def test_actual_builtin_manifest_profile_mapping_uses_adapted_factory(builtin_manifest_fixture):
    manifest,config,policy=builtin_manifest_fixture
    identities=c.builtin_manifest_identities(manifest,config,policy)
    assert set(identities)==set(c.BUILTIN_IDS)
    for plugin,artifact in zip(c.BUILTIN_IDS,manifest['builtinArtifacts']):
        assert identities[plugin]['sourcePath']==config['distributionRoot']+'/builtin-plugins/'+plugin
        assert identities[plugin]['serverBundleSha256']==artifact['serverBundleSha256']!=artifact['originalServerBundleSha256']
        assert identities[plugin]['moduleTableSha256']==manifest['moduleTableSha256']


@pytest.mark.parametrize('mutation',['missing-profile','null-profile','duplicate-profile','wrong-current-row','wrong-bundle',
    'original-substitution','wrong-table','wrong-recipe','source-file','factory-path','inventory','duplicate-host-row'])
def test_manifest_profile_mapping_refusals(builtin_manifest_fixture,mutation):
    manifest,config,policy=builtin_manifest_fixture
    row=policy['qualifications'][0];artifact=manifest['builtinArtifacts'][0]
    if mutation=='missing-profile':row['builtinProfiles'].pop()
    elif mutation=='null-profile':row['builtinProfiles'][0]['profileSha256']=None
    elif mutation=='duplicate-profile':row['builtinProfiles'][1]=row['builtinProfiles'][0]
    elif mutation=='wrong-current-row':row['manifestSha256']='a'*64
    elif mutation=='wrong-bundle':row['builtinProfiles'][0]['serverBundleSha256']='a'*64
    elif mutation=='original-substitution':
        artifact['serverBundleSha256']=artifact['originalServerBundleSha256']
        row['builtinProfiles'][0]['serverBundleSha256']=artifact['originalServerBundleSha256']
    elif mutation=='wrong-table':manifest['moduleTableSha256']='a'*64
    elif mutation=='wrong-recipe':manifest['builtinModuleTable']=dict(manifest['builtinModuleTable'],recipe={})
    elif mutation=='source-file':manifest['files']=[item for item in manifest['files'] if item['path']!=artifact['sourceIdentityPath']]
    elif mutation=='factory-path':artifact['factoryPath']='builtin-compiled/other/server.factory.js'
    elif mutation=='inventory':manifest['builtinPlugins']=manifest['builtinPlugins'][:-1]
    elif mutation=='duplicate-host-row':policy['qualifications'].append(row)
    with pytest.raises(c.ContractError):c.builtin_manifest_identities(manifest,config,policy)


def test_v2_facade_validates_complete_tagged_union_before_directory_view(cohort_v2_fixture,monkeypatch):
    value,config,expected,identities=cohort_v2_fixture
    row={'cohort':expected,'component':'ade-yolo'}
    native=c.NativeFacade(lambda:row)
    native.builtin_identities=identities
    monkeypatch.setattr(native,'_transport',lambda:config)
    calls=[]
    def wire(args):
        calls.append(args);assert args==['plugin','cohort-v2-status'];return value
    monkeypatch.setattr(native,'_call',wire)
    view=native.cohort_status()
    assert len(view['builtinEntries'])==14 and all('journal' not in item for item in view['builtinEntries'])
    assert all('activationGeneration' in item['loaded'] for item in view['entries'])
    value['entries'].pop()
    with pytest.raises(c.ContractError):native.cohort_status(allow_target_absent=True)
    assert all(args==['plugin','cohort-v2-status'] for args in calls)


def test_native_host_policy_fixed_account_path_and_safe_ancestry(tmp_path,monkeypatch):
    home=tmp_path/'real-account';home.mkdir(mode=0o700)
    path=home/'.local/state/djbclark-ade/forks/paseo-qualified-host-policy.json'
    path.parent.mkdir(parents=True)
    raw=c.canonical({'schemaVersion':1,'qualifications':[]})
    path.write_bytes(raw);path.chmod(0o600)
    monkeypatch.setattr(c.pwd,'getpwuid',lambda uid:SimpleNamespace(pw_dir=str(home)))
    monkeypatch.setenv('HOME',str(tmp_path/'untrusted-env-home'))
    policy,binding=c.read_native_host_policy()
    assert policy=={'schemaVersion':1,'qualifications':[]} and binding==c.hashlib.sha256(raw).hexdigest()
    path.chmod(0o666)
    with pytest.raises(c.ContractError,match='ancestry'):c.read_native_host_policy()
    path.chmod(0o600);path.write_bytes(c.canonical({'schemaVersion':1,'qualifications':[None]}))
    with pytest.raises(c.ContractError,match='row'):c.read_native_host_policy()
    path.unlink();path.symlink_to(home/'other-policy.json')
    with pytest.raises(c.ContractError):c.read_native_host_policy()


@pytest.fixture
def retained_system_fixture():
    """Exact cf96 metadata with synthetic payload identities, no namespace assertion."""
    external={'path':'/usr/lib/ld-fixture.so','retainedPath':'system-closure/elf/usr/lib/ld-fixture.so',
              'mode':0o555,'size':7,'sha256':digest('retained-loader')}
    cache={'path':'/etc/ld.so.cache','retainedPath':'system-closure/loader/ld.so.cache','mode':0o444,
           'size':3,'sha256':digest('cache'),'entries':[]}
    closure={'schemaVersion':1,'profile':'linux-retained-system-closure-v1','loaderResolution':{
        'schemaVersion':1,'policy':'glibc-pinned-cache-existing-layout-v1',
        'elf':[{'member':'runtime/node','machine':62,'interpreter':'/lib/ld-fixture.so','needed':['lib-fixture.so'],
                'rpath':[],'runpath':[],'soname':None}],
        'interpreters':[{'request':'/lib/ld-fixture.so','target':external['path']}],
        'aliases':[{'path':'/lib/ld-fixture.so','target':external['path'],'linkText':external['path']}],
        'searchDirectories':[{'kind':'system','path':'/usr/lib'}],
        'hwcaps':{'policy':'no-relevant-hwcaps-v1'},'cache':cache,
        'preload':{'path':'/etc/ld.so.preload','state':'absent'}}}
    files=[{'path':row['retainedPath'],**{key:row[key] for key in ('mode','size','sha256')}} for row in (external,cache)]
    files.append({'path':'runtime/node','mode':0o555,'size':9,'sha256':digest('node')})
    return {'files':files,'externalLibraries':[external],'systemClosure':closure,'systemClosureSha256':digest(closure)}


def test_cf96_retained_system_metadata_and_module_table_binding(retained_system_fixture,builtin_manifest_fixture):
    retained=retained_system_fixture
    assert c.system_closure_metadata(retained) is retained['systemClosure']
    manifest,config,policy=builtin_manifest_fixture
    manifest['externalLibraries']=retained['externalLibraries']
    manifest['files']+=retained['files'][:2]
    manifest['systemClosure']=retained['systemClosure'];manifest['systemClosureSha256']=retained['systemClosureSha256']
    table=dict(manifest['builtinModuleTable'],externalLibraries=manifest['externalLibraries'],systemClosureSha256=manifest['systemClosureSha256'])
    table_sha=c.hashlib.sha256(c.builtin_json(table)).hexdigest()
    manifest.update(builtinModuleTable=table,moduleTableSha256=table_sha)
    for row in [*manifest['builtinArtifacts'],*policy['qualifications'][0]['builtinProfiles']]:row['moduleTableSha256']=table_sha
    assert len(c.builtin_manifest_identities(manifest,config,policy))==14
    manifest['builtinModuleTable'].pop('systemClosureSha256')
    with pytest.raises(c.ContractError):c.builtin_manifest_identities(manifest,config,policy)


@pytest.mark.parametrize('mutation',['digest','wrong-backing','host-only','duplicate-target','missing-cache','special-mode',
    'path-escape','alias-unbound','null-layout','hwcap','preload','too-many-elf','missing-elf-member'])
def test_retained_system_metadata_refusals(retained_system_fixture,mutation):
    manifest=retained_system_fixture;layout=manifest['systemClosure']['loaderResolution']
    if mutation=='digest':manifest['systemClosureSha256']='f'*64
    elif mutation=='wrong-backing':manifest['externalLibraries'][0]['sha256']='f'*64
    elif mutation=='host-only':manifest['externalLibraries'][0].pop('retainedPath')
    elif mutation=='duplicate-target':manifest['externalLibraries'].append(manifest['externalLibraries'][0])
    elif mutation=='missing-cache':manifest['files']=manifest['files'][::2]
    elif mutation=='special-mode':manifest['externalLibraries'][0]['mode']=0o777
    elif mutation=='path-escape':manifest['externalLibraries'][0]['retainedPath']='system-closure/../escape'
    elif mutation=='alias-unbound':layout['aliases'][0]['target']='/unbound/loader'
    elif mutation=='null-layout':manifest['systemClosure']['loaderResolution']=None
    elif mutation=='hwcap':layout['cache']['entries']=[{'soname':'libfixture','path':'/usr/lib/libfixture','target':'/usr/lib/libfixture','flags':1,'hwcap':'1'}]
    elif mutation=='preload':layout['preload']['state']='present'
    elif mutation=='too-many-elf':layout['elf']*=513
    elif mutation=='missing-elf-member':layout['elf'][0]['member']='missing/member'
    if mutation!='digest':manifest['systemClosureSha256']=digest(manifest['systemClosure'])
    with pytest.raises(c.ContractError):c.system_closure_metadata(manifest)


def test_same_live_facade_scoped_recovery_uses_one_begin_and_original_tuple(cohort_mapping_fixture,tmp_path,monkeypatch):
    """Actual facade+Journal with synthetic authenticated2410 wire, NOT native proof."""
    row,baseline,stored,config,facts=cohort_mapping_fixture
    target=next(entry for entry in facts['entries'] if entry['pluginId']=='ade-yolo')
    baseline_loaded=c.parse(c.canonical(target['loaded']).decode())
    baseline_source=dict(target['registration'])
    target['journal']['baseline']={'source':baseline_source,'receipt':baseline_loaded}
    native=c.NativeFacade(lambda:row,stored.root)
    monkeypatch.setattr(native,'_transport',lambda:config)
    trace=[];state={'failed':False,'restriction':None,'begins':0,'ends':0}
    def status():
        reservation=native.reservation
        return {'schemaVersion':1,'state':'recovery-required' if state['restriction'] else ('held' if reservation else 'idle'),
            'generation':reservation['generation'] if reservation else None,'reservationGeneration':12 if reservation else 11,
            'transactionId':reservation['transactionId'] if reservation else None,'ready':not state['failed'],
            'recoveryRequired':bool(state['restriction']),'recoveryOnly':state['restriction'],
            'authority':{'schemaVersion':1,'qualified':True,'serverId':config['serverId'],'daemonIncarnation':config['daemonIncarnation'],
                'features':{'maintenanceReservationV1':True,'maintenancePluginOperationV1':not state['failed'],
                            'maintenanceKnownFailedHeldV1':False,'maintenanceHeldRecoveryV1':True}}}
    def wire(args,token=None):
        if args==['plugin','cohort-status']:return c.parse(c.canonical(facts).decode())
        if args==['daemon','maintenance','status']:return status()
        if args==['plugin','managed-status','ade-yolo']:
            return {'version':1,'pluginId':'ade-yolo','consistency':'coherent','registration':target['registration'],
                    'journal':target['journal'],'loaded':target['loaded']}
        if args[:3]==['daemon','maintenance','begin']:
            state['begins']+=1
            return dict(native.reservation,state='held',recoveryRequired=False,ownerToken='s'*43)
        if args[:3]==['daemon','maintenance','end']:
            assert token=='s'*43 and state['restriction'] is None
            state['ends']+=1
            return dict(native.reservation,state='idle',reservationGeneration=12,recoveryRequired=False)
        assert args[:3]==['daemon','maintenance','plugin-operation'] and token=='s'*43
        kind=args[args.index('--operation')+1]
        trace.append((kind,args[args.index('--generation')+1],args[args.index('--transaction-id')+1],args[args.index('--expected-generation')+1]))
        if kind=='replace':
            target.update(registration={'source':'directory','path':args[args.index('--path')+1],'enabled':True},loaded=None,execution=None)
            target['journal'].update(generation=9,currentReceipt=None)
            state['failed']=True
            baseline_binding={'path':baseline_loaded['sourcePath'],'snapshotSha256':baseline_loaded['snapshotSha256'],
                              'serverBundleSha256':baseline_loaded['serverBundleSha256']}
            state['restriction']={'pluginId':'ade-yolo','baseline':baseline_binding,'nativeGeneration':9,'phase':'recover-required'}
            return {'outcome':'known_failed_held','reason':'initialization_rejected','pluginId':'ade-yolo','nativeGeneration':9,
                'current':{'registration':{'path':target['registration']['path'],'enabled':True},'loaded':None},
                'baseline':baseline_binding,'maintenance':status(),'serverId':config['serverId'],'daemonIncarnation':config['daemonIncarnation']}
        if kind=='recover':
            assert state['restriction']['phase']=='recover-required'
            loaded=dict(baseline_loaded,activationGeneration=77,processStartToken='recovered-real-child-fixture')
            target.update(registration=baseline_source,enabled=True,loaded=loaded,
                execution={'contract':'native-passive-contract-1','incarnation':loaded['processStartToken'],
                           'distributionBuildId':config['distributionBuildId'],'closure':config['closure']})
            target['journal'].update(generation=10,currentReceipt=loaded)
            state['restriction']=dict(state['restriction'],nativeGeneration=10,phase='verify-required')
        else:
            assert kind=='verify'
            state['restriction']=None;state['failed']=False
        return {'plugin':{'id':'ade-yolo','enabled':True,'status':'running','loaded':target['loaded']},'nativeGeneration':target['journal']['generation'],
            'maintenance':status(),'serverId':config['serverId'],'daemonIncarnation':config['daemonIncarnation']}
    monkeypatch.setattr(native,'_call',wire)
    controller=c.Controller(lambda:row,native=native,root=stored.root)
    journal=c.Journal(stored.root/'journal',row['policy']['compatibility_group'])
    journal.enroll(baseline.sha256,controller.adapters(row,None))
    repo=tmp_path/'source'
    (repo/'plugins/ade-yolo/index.server.ts').write_text('export default ()=>{throw Error("synthetic initialized failure")}')
    git(repo,'add','.');git(repo,'commit','-qm','candidate fixture')
    commit=git(repo,'rev-parse','HEAD');payload=snapshots.produce(repo,commit)
    evidence=dict(row['evidence'],master_commit=commit,native_tree_sha256=snapshots.payload_tree_hash(payload))
    expected=dict(row['expected'],fork_commit=commit,upstream_commit=commit,artifact_sha256=c.hashlib.sha256(payload).hexdigest(),
                  toolchain=c.canonical({'plugin_snapshot_evidence':digest(evidence)}).decode())
    candidate=make_receipt(expected,row['policy'],{key:{'status':'passed','contract_digest':digest(value)} for key,value in row['policy']['features'].items()})
    archive=zip_bytes({'receipt.json':candidate.encoded,'snapshot.json':payload,'evaluator-evidence.json':c.canonical(evidence)})
    row.update(expected=expected,evidence=evidence,master_commit=commit)
    row['evaluation'].update(receipt_sha256=candidate.sha256,archive_sha256=c.hashlib.sha256(archive).hexdigest())
    for grant in row['operations'].values():grant['identity']=candidate.sha256
    controller.evaluator=FakeEvaluator(archive,candidate)
    assert controller.tick('deploy')['status']=='known_failed_held'
    original=journal.read()['transaction']['origin']
    assert native.supported() is False and native.can_attempt_same_held_recovery()
    row['generation']=1
    for grant in row['operations'].values():grant.update(identity=baseline.sha256,generation=1)
    result=controller.tick('recover')
    assert result['status']=='runtime_verified',result
    assert result['generation']==2 and journal.read()['verified']==baseline.sha256
    assert state['begins']==1 and state['ends']==1
    assert [entry[0] for entry in trace]==['replace','recover','verify','verify']
    assert {entry[1] for entry in trace}=={'12'}
    assert {entry[2] for entry in trace}=={original['context']['transaction_id']}
    assert [entry[3] for entry in trace]==['8','9','10','10']
    assert native.known_held is None and native.token is None


@pytest.mark.parametrize('missing',['token','known','origin','uncertain'])
def test_scoped_availability_cannot_create_same_live_capability(missing):
    native=c.NativeFacade()
    native.token='s'*43;native.known_held={'baseline':{}};native.original_native=('context','intent')
    native.reservation={'generation':12,'transactionId':'original'}
    if missing=='token':native.token=None
    elif missing=='known':native.known_held=None
    elif missing=='origin':native.original_native=None
    else:native.uncertain=True
    assert not native.can_attempt_same_held_recovery()
    assert native._scoped_recovery_supported('recover') is False
    assert native._scoped_recovery_supported('replace') is False


def test_same_held_prepare_uncertainty_discards_private_reuse(monkeypatch):
    native=c.NativeFacade()
    native.known_held={'baseline':{}};native.token='s'*43
    native.reservation={'generation':12,'transactionId':'original'};native.original_native=('context','intent')
    def unavailable(context):raise c.ContractError('fresh native observation uncertain')
    monkeypatch.setattr(native,'_prepare_bound',unavailable)
    with pytest.raises(c.ContractError):native.prepare(SimpleNamespace(kind='reconcile'))
    assert native.uncertain and native.known_held is None and not native.can_attempt_same_held_recovery()


def readonly_port_fixture(tmp_path,source):
    """Synthetic measured protocol helper; never production namespace qualification."""
    root=tmp_path/'retained';path=root/'system-closure/namespace-bootstrap.py'
    path.parent.mkdir(parents=True);path.write_bytes(source);path.chmod(0o444)
    config={'distributionRoot':str(root),'distributionSha256':'a'*64,'cohortVersion':2}
    manifest={'systemClosure':{},'files':[{'path':'system-closure/namespace-bootstrap.py','mode':0o444,
        'size':len(source),'sha256':c.hashlib.sha256(source).hexdigest()}]}
    return config,manifest,path


def allow_synthetic_readonly_bytes(monkeypatch):
    original=c.read_regular
    monkeypatch.setattr(c,'protected_root_path',lambda path:Path(path))
    monkeypatch.setattr(c,'read_regular',lambda path,limit=c.LIMIT,**kwargs:original(path,limit,owner=os.getuid()))


def committed_readonly_source():
    source_path=Path(__file__).resolve().parents[1]/'native-readonly-source/packages/server/scripts/qualified-system-namespace.py'
    if not source_path.is_file():
        if os.environ.get('ADE_CI_REQUIRE_NATIVE_READONLY_SOURCE')=='1':pytest.fail('required exact native source absent')
        pytest.skip('exact native source is exercised in dedicated controller workflow')
    source=source_path.read_bytes()
    assert len(source)==52756
    assert c.hashlib.sha256(source).hexdigest()=='605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7'
    assert c.READONLY_NAMESPACE_SIZE==52756
    assert c.READONLY_NAMESPACE_SHA256=='605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7'
    return source


def test_actual_committed_readonly_import_refusal_and_module_cleanup(tmp_path,monkeypatch):
    source=committed_readonly_source()
    config,manifest,path=readonly_port_fixture(tmp_path,source)
    allow_synthetic_readonly_bytes(monkeypatch)
    name='_ade_retained_namespace_'+c.READONLY_NAMESPACE_SHA256
    previous=c.types.ModuleType(name)
    monkeypatch.setitem(sys.modules,name,previous)
    with pytest.raises(c.ContractError) as caught:c.verify_readonly_namespace(config,manifest)
    # The accepted real function is entered, with the actual packaged __file__;
    # this fixture lacks its real manifest/root-owned/private mount proof.
    cause=caught.value.__cause__
    assert type(cause).__name__=='Hold' and type(cause).__module__==name
    assert str(cause)=='unprotected-ancestor'
    assert sys.modules[name] is previous


@pytest.mark.parametrize('source',[
    b'import os\ndef dataclass(cls):\n    os.chdir("/")\n    return cls\n@dataclass\nclass Probe:\n    """review module rebinding"""\ndef verify_existing_namespace(root,digest):return None\n',
    b'import os\ndef property(fn):\n    os.chdir("/")\n    return fn\nclass Probe:\n    @property\n    def value(self):return None\n',
    b'import os\nclass Probe:\n    def property(fn):\n        os.chdir("/")\n        return fn\n    @property\n    def value(self):return None\n',
    b'import os\nclass Probe:\n    def __class_getitem__(cls,key):\n        os.chdir("/")\n        return None\ndef eager(value=Probe[0]):pass\n',
    b'import os\nclass Probe:\n    def __class_getitem__(cls,key):\n        os.chdir("/")\n        return None\ndef eager(value:Probe[0]):pass\n',
    b'def verify_existing_namespace(root,digest):return {"ready":True}\n',
    b'def verify_existing_namespace(root,digest):return True\n',
    b'def verify_existing_namespace(root,digest):return None\n',
])
def test_manifest_matching_unreviewed_helper_refuses_before_compile_or_effect(tmp_path,monkeypatch,source):
    source=source+b'\n'+b' '*(52756-len(source)-1)
    assert len(source)==52756
    config,manifest,path=readonly_port_fixture(tmp_path,source)
    assert manifest['files'][0]['sha256']==c.hashlib.sha256(path.read_bytes()).hexdigest()
    allow_synthetic_readonly_bytes(monkeypatch)
    compiled=[];executed=[]
    def compile_spy(*args,**kwargs):compiled.append(True);raise RuntimeError('compile must not be reached')
    def exec_spy(*args,**kwargs):executed.append(True);raise RuntimeError('exec must not be reached')
    monkeypatch.setattr(c,'compile',compile_spy,raising=False)
    monkeypatch.setattr(c,'exec',exec_spy,raising=False)
    with pytest.raises(c.ContractError,match='independently reviewed'):c.verify_readonly_namespace(config,manifest)
    assert compiled==[] and executed==[]


@pytest.mark.parametrize('change',['substitute','mode','member','v2-no-manifest'])
def test_readonly_port_authentication_precedes_import(tmp_path,monkeypatch,change):
    config,manifest,path=readonly_port_fixture(tmp_path,b'raise AssertionError("unverified source must not execute")\n')
    allow_synthetic_readonly_bytes(monkeypatch)
    if change=='substitute':manifest['files'][0]['sha256']='f'*64
    elif change=='mode':manifest['files'][0]['mode']=0o555
    elif change=='member':manifest['files'][0]['path']='other.py'
    else:manifest=None
    with pytest.raises(c.ContractError):c.verify_readonly_namespace(config,manifest)


@pytest.mark.parametrize('change',['bytes','mode'])
def test_accepted_manifest_identity_does_not_hide_changed_member_bytes(tmp_path,monkeypatch,change):
    source=committed_readonly_source()
    config,manifest,path=readonly_port_fixture(tmp_path,source)
    allow_synthetic_readonly_bytes(monkeypatch)
    path.chmod(0o600)
    if change=='bytes':path.write_bytes(source[:-1]+bytes([source[-1]^1]));path.chmod(0o444)
    compiled=[]
    def compile_spy(*args,**kwargs):compiled.append(True);raise RuntimeError('must not compile substituted source')
    monkeypatch.setattr(c,'compile',compile_spy,raising=False)
    with pytest.raises(c.ContractError,match='mismatch'):c.verify_readonly_namespace(config,manifest)
    assert compiled==[]


def test_readonly_port_last_check_refusal_never_starts_cli(monkeypatch):
    facade=c.NativeFacade()
    config={'node':{'path':'/retained/runtime/node'},'cli':{'path':'/retained/cli-entry.mjs'}}
    monkeypatch.setattr(facade,'_transport',lambda:config)
    calls=[]
    def refuse(config,manifest):calls.append('readonly-final');raise c.ContractError('namespace changed')
    monkeypatch.setattr(c,'verify_readonly_namespace',refuse)
    monkeypatch.setattr(c.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('CLI cannot start after namespace refusal'))
    with pytest.raises(c.ContractError):facade._call(['daemon','maintenance','status'])
    assert calls==['readonly-final']


@pytest.fixture
def readonly_status_fixture(cohort_mapping_fixture,monkeypatch):
    """Real retained bytes + existing Journal + facade, synthetic read wire ONLY."""
    row,receipt,stored,config,facts=cohort_mapping_fixture
    target=next(entry for entry in facts['entries'] if entry['pluginId']=='ade-yolo')
    target['journal']['phase']='ready'
    native=c.NativeFacade(lambda:row,stored.root)
    monkeypatch.setattr(native,'_transport',lambda:config)
    maintenance={'schemaVersion':1,'state':'idle','reservationGeneration':12,'generation':None,'transactionId':None,
        'ready':False,'recoveryRequired':False,'authority':{'schemaVersion':1,'qualified':True,'serverId':config['serverId'],
            'daemonIncarnation':config['daemonIncarnation'],'features':{'maintenanceReservationV1':True,'maintenancePluginOperationV1':False}}}
    calls=[]
    def wire(args,token=None):
        assert token is None,'status must not send a private owner bearer'
        calls.append(args)
        if args==['plugin','cohort-status']:return c.parse(c.canonical(facts).decode())
        if args==['daemon','maintenance','status']:return c.parse(c.canonical(maintenance).decode())
        pytest.fail('status attempted non-read native command')
    monkeypatch.setattr(native,'_call',wire)
    controller=c.Controller(lambda:row,native=native,root=stored.root)
    journal=c.Journal(stored.root/'journal',row['policy']['compatibility_group'])
    # Unit fixture enrollment only; status below never invokes enrollment/adapters.
    journal.enroll(receipt.sha256,c.Adapters(observe=lambda:receipt.sha256,preflight=lambda identity:False,
        stage=lambda *args:None,activate=lambda *args:None,verify=lambda identity:False,recover=lambda *args:None,
        retained=controller.retained,authority=lambda operation,identity:operation=='enroll'))
    return controller,journal,row,receipt,facts,maintenance,calls


def test_status_current_verified_is_truthful_readonly_observation(readonly_status_fixture,monkeypatch):
    controller,journal,row,receipt,facts,maintenance,calls=readonly_status_fixture
    before={path.relative_to(controller.root):path.read_bytes() for path in controller.root.rglob('*') if path.is_file()}
    monkeypatch.setattr(c.Journal,'write',lambda *args:pytest.fail('status cannot write Journal'))
    monkeypatch.setattr(c.Journal,'locked',lambda *args:pytest.fail('status cannot create/acquire transaction lock'))
    monkeypatch.setattr(controller,'adapters',lambda *args,**kwargs:pytest.fail('status cannot obtain transaction adapters'))
    monkeypatch.setattr(controller,'acquire',lambda *args:pytest.fail('status cannot acquire/evaluate candidates'))
    result=controller.status()
    assert result['status']=='runtime_verified' and result['verified']==result['observed']==receipt.sha256
    assert result['authorized'] is False and result['observation_only'] is True
    # Current executing identity can be verified while ordinary work blocks apply.
    assert maintenance['ready'] is False and maintenance['authority']['features']['maintenancePluginOperationV1'] is False
    assert {tuple(args) for args in calls}=={('plugin','cohort-status'),('daemon','maintenance','status')}
    assert {path.relative_to(controller.root):path.read_bytes() for path in controller.root.rglob('*') if path.is_file()}==before


@pytest.mark.parametrize('mutation',['missing-journal','corrupt-journal','noncanonical-journal','missing-retained','raw-flag-only',
    'missing-cohort','wrong-loaded','unqualified','wrong-incarnation','native-held','native-unknown','target-held','changed-epoch','missing-features','bool-schema'])
def test_status_missing_mismatched_unknown_facts_hold(readonly_status_fixture,monkeypatch,mutation):
    controller,journal,row,receipt,facts,maintenance,calls=readonly_status_fixture
    if mutation=='missing-journal':journal.path.unlink()
    elif mutation=='corrupt-journal':journal.path.write_bytes(b'{}')
    elif mutation=='noncanonical-journal':journal.path.write_bytes(journal.path.read_bytes()+b'\n')
    elif mutation=='missing-retained':(controller.root/'records'/(receipt.sha256+'.json')).unlink()
    elif mutation=='raw-flag-only':facts.clear();facts.update(qualified=True)
    elif mutation=='missing-cohort':facts['entries'].pop()
    elif mutation=='wrong-loaded':next(item for item in facts['entries'] if item['pluginId']=='ade-yolo')['loaded']['snapshotSha256']='f'*64
    elif mutation=='unqualified':maintenance['authority']['qualified']=False
    elif mutation=='wrong-incarnation':maintenance['authority']['daemonIncarnation']='other'
    elif mutation=='native-held':maintenance['state']='held'
    elif mutation=='native-unknown':maintenance['recoveryRequired']=True
    elif mutation=='target-held':next(item for item in facts['entries'] if item['pluginId']=='ade-yolo')['journal']['phase']='held'
    elif mutation=='missing-features':maintenance['authority'].pop('features')
    elif mutation=='bool-schema':maintenance['authority']['schemaVersion']=True
    else:
        original=controller.native.cohort_status
        def changed(**kwargs):
            facts['observationEpoch']+=1
            return original(**kwargs)
        monkeypatch.setattr(controller.native,'cohort_status',changed)
    assert controller.status()['status']=='hold'


def test_status_identity_and_policy_changes_refuse(readonly_status_fixture,monkeypatch):
    controller,journal,row,receipt,facts,maintenance,calls=readonly_status_fixture
    # This tests controller comparison independently of the strict native parser.
    monkeypatch.setattr(controller.native,'status_observation',lambda cohort:'f'*64)
    assert controller.status()['reason']=='native_identity_mismatch'
    def revoked(cohort):
        row['operations']['activate']['allowed']=False
        return receipt.sha256
    monkeypatch.setattr(controller.native,'status_observation',revoked)
    assert controller.status()['reason']=='state_changed_during_status'


def test_status_absent_store_creates_nothing(fixture,tmp_path):
    row,receipt,payload,archive=fixture
    root=tmp_path/'absent'
    controller=c.Controller(lambda:row,native=FakeNative(receipt.sha256),root=root)
    assert controller.status()['reason']=='journal_unavailable'
    assert not root.exists()


def test_cli_status_dispatch_does_not_overwrite_verified_observation(monkeypatch,capsys):
    class Observation:
        def status(self):return {'status':'runtime_verified','reason':'retained_verified_matches_current_native','authorized':False}
        def plan(self):pytest.fail('status cannot use candidate planning')
    monkeypatch.setattr(c,'Controller',Observation)
    assert c.main(['status'])==0
    assert c.parse(capsys.readouterr().out)['status']=='runtime_verified'


def test_status_unsettled_journal_never_observes_or_recovers(readonly_status_fixture,monkeypatch):
    controller,journal,row,receipt,facts,maintenance,calls=readonly_status_fixture
    current=journal.read()
    context=c.release.TransactionContext(1,journal.group,'deploy',0,1,'b'*32,receipt.sha256,None,'c'*64,digest(row))
    intent=c.release.ReservationIntent(12,8,'fixture-server','fixture-daemon')
    current.update(generation=1,state='reservation_unknown',candidate=context.target,
                   transaction={'context':asdict(context),'reservation':asdict(intent)})
    journal.write(current)
    monkeypatch.setattr(controller.native,'status_observation',lambda *args:pytest.fail('unsettled Journal cannot become verified from metadata'))
    result=controller.status()
    assert result['status']=='hold' and result['reason']=='journal_unsettled'
    assert calls==[] and journal.read()==current


@pytest.fixture
def finite_git_fixture(tmp_path):
    """Meaningful config/source DATA fixture; no Git read-set/admission proof."""
    repo=tmp_path/'immutable-source';(repo/'.git').mkdir(parents=True)
    configs=tmp_path/'original-config';(configs/'includes').mkdir(parents=True)
    roots={'system':str(configs/'system.gitconfig'),'global':str(configs/'global.gitconfig'),'local':str(repo/'.git/config')}
    included=str(configs/'includes/base.gitconfig');excludes=str(configs/'original-excludes')
    bodies={roots['system']:f'[safe]\n directory = {repo}\n',
        roots['global']:f'[include]\n path = includes/base.gitconfig\n[include]\n path = includes/base.gitconfig\n[core]\n excludesFile = {excludes}\n',
        included:'[core]\n fsmonitor = false\n',roots['local']:'[core]\n repositoryFormatVersion = 0\n bare = false\n',
        excludes:'*.private\n',str(repo/'.git/HEAD'):'ref: refs/heads/master\n',str(repo/'.worktreeinclude'):'*.private\n'}
    files=[]
    for name,body in bodies.items():
        path=Path(name);path.write_text(body);path.chmod(0o444);raw=path.read_bytes()
        files.append({'path':name,'mode':0o444,'size':len(raw),'sha256':c.hashlib.sha256(raw).hexdigest()})
    recipe={'contract':'worktree-include-git-config-v1','distributionManifestSha256':'1'*64,'systemClosureSha256':'2'*64,
        'tools':dict(c.FINITE_GIT_TOOLS),'argv':c.parse(c.canonical(c.FINITE_GIT_ARGV).decode()),
        'repository':{'cwd':str(repo),'gitDirectory':str(repo/'.git'),'layout':'direct-dotgit-v1'},
        'environment':{'HOME':c.pwd.getpwuid(os.getuid()).pw_dir,'PATH':'/usr/bin:/bin',
                       'GIT_CONFIG_SYSTEM':roots['system'],'GIT_CONFIG_GLOBAL':roots['global']},
        'configRoots':roots,'includes':[{'from':roots['global'],'to':included},{'from':roots['global'],'to':included}],
        'files':sorted(files,key=lambda row:row['path'].encode()),
        'protectedAbsent':sorted([str(repo/'.git/commondir'),str(repo/'.git/config.worktree')],key=lambda item:item.encode())}
    return {'schemaVersion':1,'recipeSha256':c.hashlib.sha256(c.builtin_json(recipe)).hexdigest(),'recipe':recipe}


def test_finite_git_G_meaningful_config_data_preserves_original_roots_order(finite_git_fixture,monkeypatch):
    value=finite_git_fixture
    monkeypatch.setattr(c,'read_regular',lambda *args,**kwargs:pytest.fail('DATA parse must not pretend to audit config files'))
    monkeypatch.setattr(c.subprocess,'Popen',lambda *args,**kwargs:pytest.fail('DATA parse must not start Git/Node'))
    result=c.finite_git_profile(value)
    assert result==value and result is not value
    recipe=result['recipe']
    assert recipe['configRoots']['system']==recipe['environment']['GIT_CONFIG_SYSTEM']
    assert recipe['configRoots']['global']==recipe['environment']['GIT_CONFIG_GLOBAL']
    assert recipe['configRoots']['local']==recipe['repository']['cwd']+'/.git/config'
    assert len(recipe['includes'])==2 and recipe['includes'][0]==recipe['includes'][1]
    assert result['recipeSha256']==c.hashlib.sha256(c.builtin_json(recipe)).hexdigest()


@pytest.mark.parametrize('mutation',['wrapper-field','recipe-field','schema-bool','digest','argv','tool','gitfile','system-env',
    'missing-root','missing-include','duplicate-file','unsorted-file','duplicate-absent','overlap','mode','size','total-size',
    'invalid-env-name','nul-env','surrogate-env','env-count','env-bytes','path-traversal','too-many-includes','recipe-bytes'])
def test_finite_git_G_strict_refusals(finite_git_fixture,mutation):
    value=finite_git_fixture;r=value['recipe']
    if mutation=='wrapper-field':value['allowed']=True
    elif mutation=='recipe-field':r['profileSha256']='f'*64
    elif mutation=='schema-bool':value['schemaVersion']=True
    elif mutation=='digest':value['recipeSha256']='f'*64
    elif mutation=='argv':r['argv']['lsFiles'].append('--recurse-submodules')
    elif mutation=='tool':r['tools']['git']='/usr/bin/git'
    elif mutation=='gitfile':r['repository']['layout']='gitfile'
    elif mutation=='system-env':r['environment']['GIT_CONFIG_SYSTEM']='/other/system'
    elif mutation=='missing-root':r['files']=[row for row in r['files'] if row['path']!=r['configRoots']['system']]
    elif mutation=='missing-include':r['includes'][0]['to']='/missing/include'
    elif mutation=='duplicate-file':r['files'].append(r['files'][0])
    elif mutation=='unsorted-file':r['files'].reverse()
    elif mutation=='duplicate-absent':r['protectedAbsent'].append(r['protectedAbsent'][0])
    elif mutation=='overlap':r['protectedAbsent']=[r['files'][0]['path']]
    elif mutation=='mode':r['files'][0]['mode']=0o644
    elif mutation=='size':r['files'][0]['size']=1048577
    elif mutation=='total-size':
        for index in range(9):r['files'].append({'path':f'/retained/config-{index}','mode':0o444,'size':1048576,'sha256':'f'*64})
        r['files'].sort(key=lambda row:row['path'].encode())
    elif mutation=='invalid-env-name':r['environment']['LD-NAME']='value'
    elif mutation=='nul-env':r['environment']['EXTRA']='bad\0value'
    elif mutation=='surrogate-env':r['environment']['EXTRA']='\ud800'
    elif mutation=='env-count':r['environment'].update({f'EXTRA_{index}':'x' for index in range(33)})
    elif mutation=='env-bytes':r['environment'].update({f'EXTRA_{index}':'x'*4096 for index in range(9)})
    elif mutation=='path-traversal':r['files'][0]['path']='/config/../escape'
    elif mutation=='too-many-includes':r['includes']*=17
    elif mutation=='recipe-bytes':
        for index in range(32):r['files'].append({'path':'/'+str(index)+'x'*2000,'mode':0o444,'size':0,'sha256':'f'*64})
        r['files'].sort(key=lambda row:row['path'].encode())
    if mutation not in ('digest','surrogate-env'):
        value['recipeSha256']=c.hashlib.sha256(c.builtin_json(r)).hexdigest()
    with pytest.raises(c.ContractError):c.finite_git_profile(value)


def finite_git_retained_mapping(manifest,config,policy,retained,finite):
    manifest['externalLibraries']=retained['externalLibraries'];manifest['files']+=retained['files'][:2]
    manifest['systemClosure']=retained['systemClosure'];manifest['systemClosureSha256']=retained['systemClosureSha256']
    for role,member in c.FINITE_GIT_TOOLS.items():
        manifest['files'].append({'path':member,'mode':0o444 if role=='gate' else 0o555,'size':10,'sha256':digest(member)})
    table=dict(manifest['builtinModuleTable'],externalLibraries=manifest['externalLibraries'],systemClosureSha256=manifest['systemClosureSha256'])
    sha=c.hashlib.sha256(c.builtin_json(table)).hexdigest();manifest.update(builtinModuleTable=table,moduleTableSha256=sha)
    for row in [*manifest['builtinArtifacts'],*policy['qualifications'][0]['builtinProfiles']]:row['moduleTableSha256']=sha
    finite['recipe'].update(distributionManifestSha256=config['distributionSha256'],systemClosureSha256=manifest['systemClosureSha256'])
    finite['recipeSha256']=c.hashlib.sha256(c.builtin_json(finite['recipe'])).hexdigest()


def test_finite_git_optional_only_worktree_profile_and_actual_retained_binding(builtin_manifest_fixture,retained_system_fixture,finite_git_fixture):
    manifest,config,policy=builtin_manifest_fixture
    finite_git_retained_mapping(manifest,config,policy,retained_system_fixture,finite_git_fixture)
    baseline=c.builtin_manifest_identities(manifest,config,policy)
    assert len(baseline)==14
    profiles=policy['qualifications'][0]['builtinProfiles']
    target=next(row for row in profiles if row['id']=='worktree-include')
    old_profile=target['profileSha256']
    target['finiteGit']=finite_git_fixture
    assert c.builtin_manifest_identities(manifest,config,policy)==baseline
    assert target['profileSha256']==old_profile!=finite_git_fixture['recipeSha256']
    target.pop('finiteGit')
    assert c.builtin_manifest_identities(manifest,config,policy)==baseline
    profiles[0]['finiteGit']=finite_git_fixture
    with pytest.raises(c.ContractError,match='only'):c.builtin_manifest_identities(manifest,config,policy)


@pytest.mark.parametrize('mutation',['distribution','system-closure','missing-tool','unsealed-tool','profile-alias'])
def test_finite_git_mapping_never_substitutes_manifest_tools_or_parent_approval(builtin_manifest_fixture,retained_system_fixture,finite_git_fixture,mutation):
    manifest,config,policy=builtin_manifest_fixture
    finite_git_retained_mapping(manifest,config,policy,retained_system_fixture,finite_git_fixture)
    target=next(row for row in policy['qualifications'][0]['builtinProfiles'] if row['id']=='worktree-include')
    target['finiteGit']=finite_git_fixture
    if mutation=='distribution':finite_git_fixture['recipe']['distributionManifestSha256']='f'*64
    elif mutation=='system-closure':finite_git_fixture['recipe']['systemClosureSha256']='f'*64
    elif mutation=='missing-tool':manifest['files']=[row for row in manifest['files'] if row['path']!='runtime/git-observer']
    elif mutation=='unsealed-tool':next(row for row in manifest['files'] if row['path']=='runtime/git')['mode']=0o755
    else:target['finiteGit']={'schemaVersion':1,'profileSha256':target['profileSha256'],'recipe':finite_git_fixture['recipe']}
    if mutation in ('distribution','system-closure'):
        finite_git_fixture['recipeSha256']=c.hashlib.sha256(c.builtin_json(finite_git_fixture['recipe'])).hexdigest()
    with pytest.raises(c.ContractError):c.builtin_manifest_identities(manifest,config,policy)
