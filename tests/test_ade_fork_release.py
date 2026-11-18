"""Fake adapters exercise evidence and crash/recovery boundaries, without live state."""
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location('ade_fork_release', Path(__file__).resolve().parents[1] / 'bin/ade_fork_release.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


@pytest.fixture
def evidence():
    artifact = b'exact artifact'
    policy = {'compatibility_group': 'compatible-pilot', 'features': {'sessions': {'assertion': 'new writes survive recovery', 'revision': 1}}}
    bindings = dict(schema_version=1, component='pilot', upstream_commit='a' * 40,
                    fork_commit='b' * 40, dependencies={'lib': 'c' * 40},
                    patch_manifest_digest=m.digest({'patch': 'content'}), applied_patches=['fix-1'],
                    recipe_revision='recipe-commit', platform='linux-x86_64', toolchain='python-3',
                    artifact_sha256=hashlib.sha256(artifact).hexdigest(), policy_digest=m.digest(policy),
                    feature_contract_digest=m.digest(policy['features']), authority='protected-ci', evaluator='v1')
    results = {k: {'contract_digest': m.digest(v), 'status': 'passed'} for k, v in policy['features'].items()}
    return artifact, policy, bindings, results


def receipt(e):
    return m.make_receipt(e[2], e[1], e[3])


class Fake:
    def __init__(self, policy):
        self.actual = 'old'
        self.artifacts = {'old': b'old'}
        self.current_policy = policy
        self.calls = []
        self.allowed = True
        self.busy = False
        self.fail = None
        self.crash = False
        self.authenticated = True
        self.adapter = m.Adapters(self.observe, self.preflight, self.stage, self.activate,
                                  self.verify, self.recover, lambda t: t in self.artifacts,
                                  authority=lambda op, t: self.allowed,
                                  authenticate=lambda r: self.authenticated,
                                  policy=lambda: self.current_policy, reserve=self.reserve)

    @contextmanager
    def reserve(self):
        yield not self.busy

    def observe(self):
        self.calls.append('observe')
        return self.actual

    def preflight(self, target):
        self.calls.append('preflight')
        return self.fail != 'preflight'

    def stage(self, target, artifact):
        self.calls.append('stage')
        self.artifacts[target] = artifact
        if self.fail == 'policy':
            self.current_policy = {}
        if self.fail == 'stage':
            raise RuntimeError('stage failed')

    def activate(self, target):
        self.calls.append('activate')
        self.actual = target
        if self.crash:
            raise SystemExit('process death')
        if self.fail == 'activate':
            raise RuntimeError('lost acknowledgement')

    def verify(self, target):
        self.calls.append('verify')
        return self.fail != 'verify' and self.actual == target

    def recover(self, target):
        self.calls.append('recover')
        if self.fail == 'recover':
            raise RuntimeError('recovery failed')
        self.actual = target


@pytest.fixture
def deployment(tmp_path, evidence):
    f = Fake(evidence[1])
    j = m.Journal(tmp_path / 'journal', 'compatible-pilot')
    j.enroll('old', f.adapter)
    return j, f


def deploy(j, f, e, **kw):
    args = dict(previous='old', generation=0, migration='binary_only')
    args.update(kw)
    return j.deploy(receipt(e), e[2], e[1], e[0], f.adapter, **args)


def test_receipt_exact_and_immutable(evidence):
    r = receipt(evidence)
    m.validate(r, evidence[2], evidence[1], artifact=evidence[0])
    original = r.encoded
    evidence[2]['platform'] = 'other'
    assert r.encoded == original
    with pytest.raises(m.ContractError):
        m.validate(r, evidence[2], evidence[1], artifact=evidence[0])


@pytest.mark.parametrize('key', sorted(m.FIELDS))
def test_every_binding_is_protected(evidence, key):
    r = receipt(evidence)
    changed = copy.deepcopy(evidence[2])
    changed[key] = {'x': 'd' * 40} if key == 'dependencies' else ['other'] if key == 'applied_patches' else 2 if key == 'schema_version' else 'changed'
    with pytest.raises(m.ContractError):
        m.validate(r, changed, evidence[1], artifact=evidence[0])


@pytest.mark.parametrize('status', ['missing', 'skipped', 'pending', 'failed', 'green'])
def test_no_claimed_green(evidence, status):
    evidence[3]['sessions']['status'] = status
    with pytest.raises(m.ContractError):
        m.validate(receipt(evidence), evidence[2], evidence[1], artifact=evidence[0])


def test_deleted_and_weakened_features(evidence):
    r = receipt(evidence)
    evidence[3].clear()
    with pytest.raises(m.ContractError):
        m.validate(receipt(evidence), evidence[2], evidence[1], artifact=evidence[0])
    evidence[1]['features']['sessions'] = {'assertion': 'always true'}
    with pytest.raises(m.ContractError):
        m.validate(r, evidence[2], evidence[1], artifact=evidence[0])


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), {1: 'x'}, (1, 2), object()])
def test_non_json_rejected(bad):
    with pytest.raises(m.ContractError):
        m.digest(bad)


@pytest.mark.parametrize('bad', ['{"x":1,"x":2}', '{"x":NaN}', 'oops'])
def test_bad_json(bad):
    with pytest.raises(m.ContractError):
        m.parse(bad)


def test_wrong_artifact(evidence):
    with pytest.raises(m.ContractError):
        m.validate(receipt(evidence), evidence[2], evidence[1], artifact=b'wrong')
    with pytest.raises(m.ContractError):
        m.validate(receipt(evidence), evidence[2], evidence[1], artifact_digest='0' * 64)


def test_success_and_retention(deployment, evidence):
    j, f = deployment
    assert deploy(j, f, evidence).status == 'runtime_verified'
    assert j.read()['verified'] == receipt(evidence).sha256
    assert f.artifacts['old'] == b'old'
    assert j.read()['generation'] == 1
    assert deploy(j, f, evidence).reason == 'stale_job'


@pytest.mark.parametrize('mode,reason', [('permission', 'permission_preflight'), ('busy', 'busy'), ('auth', 'unauthenticated_evidence'), ('reservation', 'reservation_required'), ('artifact', 'recovery_artifact_missing')])
def test_holds_without_mutation(deployment, evidence, mode, reason):
    j, f = deployment
    before = j.path.read_bytes()
    if mode == 'permission': f.allowed = False
    if mode == 'busy': f.busy = True
    if mode == 'auth': f.authenticated = False
    if mode == 'reservation': f.adapter.reserve = None
    if mode == 'artifact': f.artifacts.clear()
    assert deploy(j, f, evidence).reason == reason
    assert j.path.read_bytes() == before
    assert 'activate' not in f.calls


def test_defaults_deny(deployment, evidence):
    j, f = deployment
    f.adapter.authority = m.Adapters.__dataclass_fields__['authority'].default
    assert deploy(j, f, evidence).status == 'hold'


def test_unsafe_migration_and_dry_run(deployment, evidence, tmp_path):
    j, f = deployment
    assert deploy(j, f, evidence, migration='snapshot_restore').reason == 'unsafe_migration'
    untouched = m.Journal(tmp_path / 'absent', 'compatible-pilot')
    calls = list(f.calls)
    assert deploy(untouched, f, evidence, dry_run=True).status == 'dry_run'
    assert not untouched.directory.exists()
    assert f.calls == calls


@pytest.mark.parametrize('failure', ['preflight', 'stage', 'activate', 'verify', 'policy'])
def test_failure_preserves_last_verified(deployment, evidence, failure):
    j, f = deployment
    f.fail = failure
    assert deploy(j, f, evidence).status == 'recovery_required'
    assert j.read()['verified'] == 'old'
    count = f.calls.count('activate')
    assert deploy(j, f, evidence, generation=1).status == 'recovery_required'
    assert f.calls.count('activate') == count
    if failure == 'policy': assert count == 0


def test_process_crash_then_explicit_recovery_new_generation(deployment, evidence):
    j, f = deployment
    f.crash = True
    with pytest.raises(SystemExit): deploy(j, f, evidence)
    assert j.read()['state'] == 'activate'
    assert f.actual == receipt(evidence).sha256
    assert deploy(j, f, evidence, generation=1).status == 'recovery_required'
    assert f.calls.count('activate') == 1
    assert j.recover(f.adapter, generation=1).status == 'runtime_verified'
    assert j.read()['generation'] == 2
    assert j.read()['verified'] == f.actual == 'old'
    assert j.recover(f.adapter, generation=1).reason == 'stale_job'


def test_drift_and_recovery_failure(deployment, evidence):
    j, f = deployment
    f.actual = 'foreign'
    assert deploy(j, f, evidence).reason == 'runtime_drift'
    f.fail = 'recover'
    assert j.recover(f.adapter, generation=0).status == 'recovery_required'
    assert j.read()['verified'] == 'old'


def test_group_mismatch(deployment):
    j, f = deployment
    row = j.read()
    row['group'] = 'different'
    j.write(row)
    with pytest.raises(m.ContractError): j.read()


def test_forged_receipt_not_authorization(deployment, evidence):
    j, f = deployment
    f.adapter.authenticate = lambda r: False
    assert deploy(j, f, evidence).reason == 'unauthenticated_evidence'
    f.adapter.authenticate = lambda r: 'green'
    assert deploy(j, f, evidence).reason == 'unauthenticated_evidence'


def test_revocation_after_stage(deployment, evidence):
    j, f = deployment
    stage = f.adapter.stage
    def revoke(target, artifact):
        stage(target, artifact)
        f.allowed = False
    f.adapter.stage = revoke
    assert deploy(j, f, evidence).reason == 'authority_revoked'
    assert f.actual == 'old'
    assert 'activate' not in f.calls


def test_durable_intent_visible_to_adapter(deployment, evidence):
    j, f = deployment
    activate = f.adapter.activate
    def inspect(target):
        row = j.read()
        assert row['state'] == 'activate'
        assert row['generation'] == 1
        assert row['verified'] == 'old'
        activate(target)
    f.adapter.activate = inspect
    assert deploy(j, f, evidence).status == 'runtime_verified'


def test_recovery_missing_artifact_and_permission(deployment, evidence):
    j, f = deployment
    f.fail = 'activate'
    deploy(j, f, evidence)
    f.artifacts.pop('old')
    assert j.recover(f.adapter, generation=1).status == 'hold'
    assert 'recover' not in f.calls
    f.artifacts['old'] = b'old'
    f.allowed = False
    assert j.recover(f.adapter, generation=1).status == 'hold'


def test_changed_group_is_rejected(deployment, evidence):
    j, f = deployment
    other = m.Journal(j.directory, 'incompatible')
    with pytest.raises(m.ContractError, match='group'):
        deploy(other, f, evidence)


@pytest.mark.parametrize('after_replace', [False, True])
def test_final_commit_failure_recovers_previous_baseline(deployment, evidence, monkeypatch, after_replace):
    j, f = deployment
    original_write = j.write
    failed = False

    def fail_final(row):
        nonlocal failed
        if row['state'] == 'runtime_verified' and row['verified'] != 'old' and not failed:
            failed = True
            if after_replace:
                original_write(row)
                assert j.read()['verified'] == receipt(evidence).sha256
            raise OSError('final journal commit acknowledgement lost')
        original_write(row)

    monkeypatch.setattr(j, 'write', fail_final)
    outcome = deploy(j, f, evidence)
    assert failed
    assert outcome.status == 'recovery_required'
    assert f.actual == receipt(evidence).sha256
    row = j.read()
    assert row['verified'] == 'old'
    assert row['candidate'] == receipt(evidence).sha256
    assert row['state'] == 'recovery_required'
    assert row['generation'] == 1
    assert j.recover(f.adapter, generation=1).status == 'runtime_verified'
    assert f.actual == 'old'
    assert j.read()['verified'] == 'old'
    assert j.read()['generation'] == 2
    assert f.artifacts['old'] == b'old'


def test_invalid_receipt_utf8_is_contract_error(evidence):
    with pytest.raises(m.ContractError, match='UTF-8'):
        m.validate(m.Receipt(b'\xff'), evidence[2], evidence[1], artifact=evidence[0])


def test_array_journal_state_is_contract_error(deployment):
    j, f = deployment
    row = j.read()
    row['state'] = []
    j.write(row)
    with pytest.raises(m.ContractError, match='journal state'):
        j.read()
