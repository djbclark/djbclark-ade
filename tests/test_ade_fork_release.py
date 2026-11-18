"""Fake adapters exercise evidence and crash/recovery boundaries, without live state."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location('ade_fork_release', Path(__file__).resolve().parents[1] / 'bin/ade_fork_release.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
RULE = 'e' * 64


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
        self.contexts = []
        self.native_counter = 40
        self.plugin_counter = 9
        self.release_failure = False
        self.idle_proven = True
        self.adapter = m.Adapters(self.observe, self.preflight, self.stage, self.activate,
                                  self.verify, self.recover, lambda t: t in self.artifacts,
                                  authority=lambda op, t: self.allowed,
                                  authenticate=lambda r: self.authenticated,
                                  policy=lambda: self.current_policy, reserve=self.reserve,
                                   prepare=self.prepare, finish=self.finish, released=self.released)

    def prepare(self, context):
        self.contexts.append(context)
        return m.ReservationIntent(self.native_counter + 1, self.plugin_counter, 'server', 'incarnation')

    def reserve(self, context, intent):
        self.calls.append('begin')
        if self.busy: return m.BeginResult('busy')
        self.native_counter = intent.native_generation
        return m.BeginResult('held')

    def finish(self, context, intent):
        self.calls.append('end')
        if self.release_failure: raise RuntimeError('lost END response')
        return True

    def released(self, context, intent):
        self.calls.append('released')
        return self.idle_proven

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
    args = dict(previous='old', generation=0, migration='binary_only', rule_digest=RULE)
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


@pytest.mark.parametrize('mode,reason', [('permission', 'permission_preflight'), ('auth', 'unauthenticated_evidence'), ('reservation', 'reservation_required'), ('artifact', 'recovery_artifact_missing')])
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
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).status == 'runtime_verified'
    assert j.read()['generation'] == 2
    assert j.read()['verified'] == f.actual == 'old'
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).reason == 'stale_job'


def test_drift_and_recovery_failure(deployment, evidence):
    j, f = deployment
    f.actual = 'foreign'
    assert deploy(j, f, evidence).reason == 'runtime_drift'
    f.actual = 'old'
    f.fail = 'activate'
    deploy(j, f, evidence)
    f.fail = 'recover'
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).status == 'recovery_required'
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
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).status == 'hold'
    assert 'recover' not in f.calls
    f.artifacts['old'] = b'old'
    f.allowed = False
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).status == 'hold'


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
        if row['state'] == 'verified_held' and row['verified'] != 'old' and not failed:
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
    assert j.recover(f.adapter, rule_digest=RULE, generation=1).status == 'runtime_verified'
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


# All adapters below are synthetic orchestration fixtures, never native acceptance.
def next_evidence(evidence, content):
    e = copy.deepcopy(evidence)
    e = (content, e[1], e[2], e[3])
    e[2]['artifact_sha256'] = hashlib.sha256(content).hexdigest()
    return e


def promote(j, f, e):
    row = j.read()
    return deploy(j, f, e, previous=row['verified'], generation=row['generation'])


def rollback(j, f, target='old', **kw):
    args = dict(generation=j.read()['generation'], rollback_target=target, rule_digest=RULE)
    args.update(kw)
    return j.recover(f.adapter, **args)


def test_rotation_failed_c_preserves_b_and_a(deployment, evidence):
    j, f = deployment
    assert promote(j, f, evidence).status == 'runtime_verified'
    b = receipt(evidence).sha256
    assert j.read()['baseline'] == 'old'
    f.fail = 'activate'
    assert promote(j, f, next_evidence(evidence, b'C')).status == 'recovery_required'
    assert (j.read()['verified'], j.read()['baseline']) == (b, 'old')
    f.fail = None
    assert j.recover(f.adapter, generation=2, rule_digest=RULE).status == 'runtime_verified'
    assert (j.read()['verified'], j.read()['baseline']) == (b, 'old')
    assert f.contexts[-1].kind == 'reconcile'
    assert f.contexts[-1].target == b
    assert set(f.artifacts) >= {'old', b, receipt(next_evidence(evidence, b'C')).sha256}


def test_explicit_rollback_consumes_baseline_requires_distinct_resume(deployment, evidence):
    j, f = deployment
    promote(j, f, evidence)
    b = receipt(evidence).sha256
    assert rollback(j, f).status == 'runtime_verified'
    assert j.read()['verified'] == f.actual == 'old'
    assert j.read()['baseline'] is None and j.read()['promotion_hold'] is True
    assert promote(j, f, evidence).reason == 'promotion_hold'
    before_calls = list(f.calls)
    f.adapter.authority = lambda op, identity: op != 'resume'
    assert j.resume(f.adapter, generation=2, rule_digest=RULE).status == 'hold'
    assert f.calls.count('begin') == before_calls.count('begin')
    f.adapter.authority = lambda op, identity: True
    assert j.resume(f.adapter, generation=1, rule_digest=RULE).reason == 'stale_job'
    assert j.resume(f.adapter, generation=2, rule_digest=RULE).reason == 'resumed'
    assert j.read()['generation'] == 3 and j.read()['promotion_hold'] is False
    assert promote(j, f, evidence).status == 'runtime_verified'
    assert b in f.artifacts and 'old' in f.artifacts


@pytest.mark.parametrize('target', [None, 'arbitrary', '', 'other-retained'])
def test_healthy_default_or_nonbaseline_never_restarts(deployment, evidence, target):
    j, f = deployment
    promote(j, f, evidence)
    before = j.path.read_bytes()
    f.artifacts['other-retained'] = b'other'
    assert rollback(j, f, target).status == 'hold'
    assert j.path.read_bytes() == before
    assert 'recover' not in f.calls


@pytest.mark.parametrize('operation', ['recover', 'verify'])
def test_rollback_grants_are_independent_and_current(deployment, evidence, operation):
    j, f = deployment
    promote(j, f, evidence)
    before = j.path.read_bytes()
    f.adapter.authority = lambda op, identity: op != operation
    assert rollback(j, f).status == 'hold'
    assert j.path.read_bytes() == before
    assert 'recover' not in f.calls


def test_no_baseline_on_enrollment_and_no_arbitrary_retained_rollback(deployment):
    j, f = deployment
    assert j.read()['baseline'] is None
    assert rollback(j, f, 'retained').reason == 'rollback_target_not_baseline'


@pytest.mark.parametrize('state', ['recover', 'verified_held'])
def test_interrupted_rollback_keeps_direction(deployment, evidence, monkeypatch, state):
    j, f = deployment
    promote(j, f, evidence)
    original = j.write
    def crash(row):
        if row['state'] == state:
            if state == 'recover': original(row)
            raise SystemExit('process terminated')
        original(row)
    monkeypatch.setattr(j, 'write', crash)
    with pytest.raises(SystemExit): rollback(j, f)
    row = j.read()
    assert row['transaction']['context']['kind'] == 'verified-rollback'
    assert row['transaction']['context']['target'] == 'old'
    monkeypatch.setattr(j, 'write', original)
    # Default reconciliation resumes the durable rollback target, never verified B.
    assert j.recover(f.adapter, generation=2, rule_digest=RULE).status == 'runtime_verified'
    assert f.actual == j.read()['verified'] == 'old'
    assert j.read()['baseline'] is None and j.read()['promotion_hold']


def test_busy_consumes_only_journal_sequence_no_end_or_native_increment(deployment, evidence):
    j, f = deployment
    f.busy = True
    assert promote(j, f, evidence).reason == 'busy'
    assert j.read()['generation'] == 1
    assert j.read()['verified'] == 'old' and j.read()['baseline'] is None
    assert j.read()['transaction'] is None
    assert f.native_counter == 40 and f.plugin_counter == 9
    assert 'end' not in f.calls
    f.busy = False
    assert promote(j, f, evidence).status == 'runtime_verified'
    c = f.contexts[-1]
    assert (c.cas_generation, c.generation) == (1, 2)
    assert f.native_counter == 41 and f.plugin_counter == 9


@pytest.mark.parametrize('outcome', [True, False, None, 'busy', {'status': 'busy'}, m.BeginResult('other')])
def test_untyped_or_unknown_begin_retains_durable_intent(deployment, evidence, outcome):
    j, f = deployment
    def begin(c, r):
        row = j.read()
        assert row['state'] == 'reservation_intent'
        assert row['transaction'] == {'context': m.asdict(c), 'reservation': m.asdict(r)}
        assert (r.native_generation, r.plugin_generation) == (41, 9)
        return outcome
    f.adapter.reserve = begin
    assert promote(j, f, evidence).reason == 'reservation_unknown'
    row = j.read()
    assert row['state'] == 'reservation_unknown' and row['generation'] == 1
    before = j.path.read_bytes()
    assert j.recover(f.adapter, generation=1, rule_digest=RULE).reason == 'reservation_unknown'
    assert j.path.read_bytes() == before
    assert not set(f.calls) & {'activate', 'recover', 'end'}


def test_begin_exception_cannot_be_permission_to_fallback(deployment, evidence):
    j, f = deployment
    def fail(c, r): raise RuntimeError('busy')  # Generic message is not typed authority.
    f.adapter.reserve = fail
    assert promote(j, f, evidence).reason == 'reservation_unknown'
    assert j.read()['transaction'] is not None
    assert 'end' not in f.calls and 'activate' not in f.calls


@pytest.mark.parametrize('where', ['before-intent', 'after-intent', 'after-begin'])
def test_reservation_crash_boundaries(deployment, evidence, monkeypatch, where):
    j, f = deployment
    write = j.write
    def crash_write(row):
        if row['state'] == 'reservation_intent' and where != 'after-begin':
            if where == 'after-intent': write(row)
            raise SystemExit('crash')
        write(row)
    monkeypatch.setattr(j, 'write', crash_write)
    def crash_begin(c, r):
        assert j.read()['state'] == 'reservation_intent'
        raise SystemExit('BEGIN lost')
    f.adapter.reserve = crash_begin
    with pytest.raises(SystemExit): promote(j, f, evidence)
    if where == 'before-intent':
        assert j.read()['generation'] == 0
    else:
        assert j.read()['state'] == 'reservation_intent'
        assert j.recover(f.adapter, generation=1, rule_digest=RULE).reason == 'reservation_unknown'
    assert not set(f.calls) & {'activate', 'recover', 'end'}


def test_release_loss_never_rolls_back_or_replays_end(deployment, evidence):
    j, f = deployment
    f.release_failure = True
    assert promote(j, f, evidence).status == 'release_uncertain'
    row = j.read()
    assert row['verified'] == f.actual == receipt(evidence).sha256
    assert row['baseline'] == 'old'
    assert row['state'] == 'release_uncertain'
    assert j.recover(f.adapter, generation=1, rule_digest=RULE).reason == 'release_reconciliation_required'
    assert promote(j, f, next_evidence(evidence, b'C')).reason == 'unfinished_transaction'
    f.idle_proven = False
    assert j.reconcile_release(f.adapter, generation=1, rule_digest=RULE).status == 'hold'
    f.idle_proven = True
    f.adapter.authority = lambda op, identity: op != 'reconcile-release'
    assert j.reconcile_release(f.adapter, generation=1, rule_digest=RULE).status == 'hold'
    f.adapter.authority = lambda op, identity: True
    assert j.reconcile_release(f.adapter, generation=1, rule_digest=RULE).reason == 'release_reconciled'
    assert j.read()['generation'] == 2
    assert f.calls.count('end') == 1 and 'recover' not in f.calls
    assert j.read()['baseline'] == 'old'


@pytest.mark.parametrize('state', ['release_intent', 'runtime_verified'])
def test_release_commit_crash_never_allows_binary_recovery(deployment, evidence, monkeypatch, state):
    j, f = deployment
    write = j.write
    def fail(row):
        if row['state'] == state and row['verified'] != 'old':
            if state == 'release_intent': write(row)
            raise SystemExit('lost process')
        write(row)
    monkeypatch.setattr(j, 'write', fail)
    with pytest.raises(SystemExit): promote(j, f, evidence)
    assert j.read()['state'] == 'release_intent'
    assert j.recover(f.adapter, generation=1, rule_digest=RULE).reason == 'release_reconciliation_required'
    assert 'recover' not in f.calls
    assert f.calls.count('end') == (1 if state == 'runtime_verified' else 0)


@pytest.mark.parametrize('field,value', [
    ('schema_version', 1), ('schema_version', True), ('baseline', []), ('baseline', ''),
    ('baseline', 'old'), ('promotion_hold', 1), ('generation', True), ('transaction', {}),
    ('candidate', 'unexpected'), ('state', []),
])
def test_strict_schema_no_legacy_reconstruction(deployment, field, value):
    j, f = deployment
    row = j.read(); row[field] = value; j.write(row)
    with pytest.raises(m.ContractError): j.read()


@pytest.mark.parametrize('missing', ['schema_version', 'baseline', 'transaction', 'promotion_hold'])
def test_missing_schema_fields_hold_without_invention(deployment, missing):
    j, f = deployment
    row = j.read(); del row[missing]; j.write(row)
    before = j.path.read_bytes()
    with pytest.raises(m.ContractError): j.read()
    assert j.path.read_bytes() == before


@pytest.mark.parametrize('hook', ['prepare', 'reserve', 'finish'])
def test_old_adapters_fail_closed(deployment, evidence, hook):
    j, f = deployment
    setattr(f.adapter, hook, None)
    before = j.path.read_bytes()
    assert promote(j, f, evidence).reason == 'reservation_required'
    assert j.path.read_bytes() == before


@pytest.mark.parametrize('rule', [None, '', 'x' * 64, True])
def test_missing_or_malformed_rule_context_denies(deployment, evidence, rule):
    j, f = deployment
    assert deploy(j, f, evidence, rule_digest=rule).reason == 'reservation_required'
    assert j.read()['generation'] == 0


def test_contexts_frozen_and_no_secret_fields(deployment, evidence):
    j, f = deployment
    promote(j, f, evidence)
    c = f.contexts[-1]
    with pytest.raises(AttributeError): c.target = 'substitution'
    assert c.rule_digest == RULE and c.baseline is None and c.verified == 'old'
    assert 'token' not in j.path.read_text().lower()


def test_stale_cas_has_no_prepare_or_callbacks(deployment, evidence):
    j, f = deployment
    promote(j, f, evidence)
    before = j.path.read_bytes(); calls = list(f.calls); plans = list(f.contexts)
    assert deploy(j, f, evidence).reason == 'stale_job'
    assert rollback(j, f, generation=0).reason == 'stale_job'
    assert j.path.read_bytes() == before and f.calls == calls and f.contexts == plans



def test_concurrent_fresh_cas_has_one_winner(deployment, evidence):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    j, f = deployment
    barrier = Barrier(2)
    def contender():
        other = m.Journal(j.directory, j.group)
        barrier.wait(timeout=10)
        return deploy(other, f, evidence)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(contender) for _ in range(2)]
        outcomes = [job.result(timeout=20) for job in jobs]
    assert sorted(x.status for x in outcomes) == ['hold', 'runtime_verified']
    assert any(x.reason == 'stale_job' for x in outcomes)
    assert j.read()['generation'] == 1 and j.read()['baseline'] == 'old'
    assert f.calls.count('activate') == f.calls.count('end') == 1


@pytest.mark.parametrize('field,value', [
    ('kind', []), ('generation', True), ('generation', 99), ('cas_generation', -1),
    ('transaction_id', 'candidate'), ('rule_digest', None), ('target', ''),
    ('verified', 'substitution'), ('baseline', 'invented'), ('group', 'other'),
])
def test_corrupt_transaction_context_never_reconstructed(deployment, evidence, field, value):
    j, f = deployment
    f.fail = 'activate'
    promote(j, f, evidence)
    row = j.read(); row['transaction']['context'][field] = value; j.write(row)
    before = j.path.read_bytes()
    with pytest.raises(m.ContractError): j.recover(f.adapter, generation=1, rule_digest=RULE)
    assert j.path.read_bytes() == before and 'recover' not in f.calls


@pytest.mark.parametrize('field,value', [
    ('native_generation', 0), ('native_generation', True), ('plugin_generation', -1),
    ('plugin_generation', True), ('server_id', ''), ('daemon_incarnation', None),
])
def test_corrupt_reservation_intent_never_guesses_counters(deployment, evidence, field, value):
    j, f = deployment
    f.fail = 'activate'
    promote(j, f, evidence)
    row = j.read(); row['transaction']['reservation'][field] = value; j.write(row)
    with pytest.raises(m.ContractError): j.read()
    assert 'recover' not in f.calls


def test_revoked_after_reservation_cannot_activate_or_end(deployment, evidence):
    j, f = deployment
    begin = f.adapter.reserve
    def revoke(c, r):
        result = begin(c, r); f.allowed = False; return result
    f.adapter.reserve = revoke
    assert promote(j, f, evidence).status == 'recovery_required'
    assert j.read()['state'] == 'recovery_required'
    assert not set(f.calls) & {'activate', 'end'}


def test_revoked_during_resume_verification_keeps_hold(deployment, evidence):
    j, f = deployment
    promote(j, f, evidence); rollback(j, f)
    verify = f.adapter.verify
    def revoke(t):
        result = verify(t); f.allowed = False; return result
    f.adapter.verify = revoke
    before = j.path.read_bytes()
    assert j.resume(f.adapter, generation=2, rule_digest=RULE).status == 'hold'
    assert j.path.read_bytes() == before


def test_release_observation_cannot_relabel_original_transaction(deployment, evidence):
    j, f = deployment
    f.release_failure = True
    promote(j, f, evidence)
    original = j.read()['transaction']
    def observe_release(c, r):
        assert m.asdict(c) == original['context']
        assert m.asdict(r) == original['reservation']
        assert f.contexts[-1].kind == 'reconcile-release'
        assert f.contexts[-1].rule_digest == 'f' * 64
        f.allowed = False  # revocation during native status wait
        return True
    f.adapter.released = observe_release
    assert j.reconcile_release(f.adapter, generation=1, rule_digest='f' * 64).status == 'hold'
    assert j.read()['transaction'] == original
    assert f.calls.count('end') == 1
