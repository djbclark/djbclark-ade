"""Exact native catalogs and effective readback, never provider-label inference."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import paseo_yolo as y


def catalog(provider='claude', modes=None, **kw):
    return dict(provider=provider, enabled=True, status='ready',
                modes=[{'id': m} for m in (modes if modes is not None else ['auto', 'bypassPermissions'])], **kw)


def snapshot(provider='claude', mode='bypassPermissions', **kw):
    return dict(Id='agent-1', Provider=provider, Mode=mode, Archived=False, Status='idle',
                AvailableModes=[{'id': mode}], **kw)


@pytest.mark.parametrize('provider,mode', [('claude','bypassPermissions'), ('codex','full-access'), ('antigravity','full-access'), ('copilot','allow-all')])
def test_source_mode_requires_native_membership(provider, mode):
    plan = y.plan_unattended_config(provider, catalog(provider,[mode]))
    assert plan['status'] == 'ready' and plan['mode_id'] == mode
    assert y.verify_unattended_snapshot(plan, snapshot(provider,mode), agent_id='agent-1')['ok']
    assert y.plan_unattended_config(provider, catalog(provider,['default']))['status'] == 'unavailable'


@pytest.mark.parametrize('provider', ['cursor','pi','hermes','muse','unknown','omp','opencode'])
def test_static_launcher_never_uses_default_or_foreign_mode(provider):
    with pytest.raises(y.ModeUnavailable):
        y.resolve_launch_mode(provider, requested='bypassPermissions', fallback='default')


@pytest.mark.parametrize('patch', [{'enabled':False}, {'status':'loading'}, {'modes':'Full Access'}, {'modes':[{'label':'Full Access'}]}, {'modes':[{'id':'full-access'},{'id':'full-access'}]}, {'provider':'claude'}])
def test_inconclusive_catalog_refuses(patch):
    row = catalog('codex',['full-access']); row.update(patch)
    assert y.plan_unattended_config('codex',row)['status'] == 'unavailable'


def test_cursor_requires_real_advertised_control_and_readback():
    row=catalog('cursor', [], defaultModeId=None)
    assert y.plan_unattended_config('cursor',row)['status']=='unavailable'
    plan=y.plan_unattended_config('cursor',row,controls={'controls':[{'type':'toggle','key':'auto_accept'}]})
    assert plan['status']=='ready' and plan['mode_id'] is None
    assert not y.verify_unattended_snapshot(plan,snapshot('cursor',None))['ok']
    assert y.verify_unattended_snapshot(plan,snapshot('cursor',None,options={'auto_accept':True}))['ok']


@pytest.mark.parametrize('field,value', [('Id','other'), ('Provider','codex'), ('Mode','auto'), ('Archived',True), ('Status','closed'), ('AvailableModes',[])])
def test_readback_catches_drift_or_missing_evidence(field,value):
    plan=y.plan_unattended_config('claude',catalog())
    state=snapshot(); state[field]=value
    assert not y.verify_unattended_snapshot(plan,state,agent_id='agent-1')['ok']


def test_explicit_restriction_is_exempt_but_still_requires_exact_live_readback():
    plan=y.plan_unattended_config('claude',catalog(),requested='plan')
    assert plan['status']=='exempt'
    assert y.verify_unattended_snapshot(plan,snapshot(mode='plan'))['ok']
    assert not y.verify_unattended_snapshot(plan,snapshot())['ok']
    critical=y.plan_unattended_config('claude',catalog(),scope='external-security-critical')
    assert not y.verify_unattended_snapshot(critical,snapshot())['ok']


def test_malformed_ready_plan_cannot_be_success():
    assert not y.verify_unattended_snapshot({'status':'ready','provider':'claude'},snapshot())['ok']
