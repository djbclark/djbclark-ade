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


@pytest.mark.parametrize('provider,mode', [
    ('claude', 'bypassPermissions'), ('codex', 'full-access'),
    ('antigravity', 'full-access'), ('copilot', 'allow-all'),
])
def test_plan_launch_config_handles_label_only_and_structured_catalogs(provider, mode):
    labels = {'provider': provider, 'enabled': 'Enabled', 'status': 'available', 'modes': 'Default, Full access'}
    plan = y.plan_launch_config(provider, labels)
    assert plan['status'] == 'ready' and plan['mode_id'] == mode and plan['evidence'] == 'source-pending-readback'
    assert y.verify_unattended_snapshot(plan, snapshot(provider, mode), agent_id='agent-1')['ok']
    assert y.plan_launch_config(provider, labels, requested='plan')['status'] == 'exempt'
    structured = catalog(provider, [mode, 'plan'])
    assert y.plan_launch_config(provider, structured)['evidence'] == 'source-and-catalog'
    assert y.plan_launch_config(provider, structured, requested='plan')['status'] == 'exempt'
    assert y.plan_launch_config(provider, structured, requested='read-only')['status'] == 'unavailable'


@pytest.mark.parametrize('provider,modes', [
    ('pi', ''), ('pi', []), ('cursor', 'Agent, Plan, Ask'), ('hermes', 'Default, Accept Edits'),
    ('opencode', 'Default'), ('omp', 'Full'),
])
def test_plan_launch_config_refuses_modeless_unsupported_and_retired(provider, modes):
    row = {'provider': provider, 'enabled': 'Enabled', 'status': 'available', 'modes': modes}
    assert y.plan_launch_config(provider, row)['status'] == 'unavailable'
    assert y.plan_launch_config(provider, row, requested='plan')['status'] == 'unavailable'


@pytest.mark.parametrize('retired', sorted(y.RETIRED_PROVIDERS) + ['OpenCode', 'OPENCODE', 'AGY', 'OMP', 'Grok', 'Crush'])
@pytest.mark.parametrize('requested', [None, 'plan'])
def test_retired_providers_refused_even_with_restrictive_mode_and_any_case(retired, requested):
    assert y.plan_unattended_config(retired, catalog(retired, ['plan']), requested=requested)['status'] == 'unavailable'
    assert y.plan_launch_config(retired, catalog(retired, ['plan']), requested=requested)['status'] == 'unavailable'
    with pytest.raises(y.ModeUnavailable):
        y.resolve_launch_mode(f'{retired}/x', requested=requested)


@pytest.mark.parametrize('placeholder', ['', '   ', '-', ' - ', ',', ' , ', '-,-', ' -, - '])
@pytest.mark.parametrize('requested', [None, 'plan'])
def test_plan_launch_config_refuses_placeholder_or_punctuation_label_strings(placeholder, requested):
    row = {'provider': 'claude', 'enabled': 'Enabled', 'status': 'available', 'modes': placeholder}
    assert y.plan_launch_config('claude', row, requested=requested)['status'] == 'unavailable'


@pytest.mark.parametrize('bad_modes', [
    [{'id': 'plan'}, {'id': 'plan'}],
    [{'id': 'plan'}, 'bad'],
    [{'id': 'plan'}, {'id': ''}],
    [{'id': 'plan'}, {'label': 'Plan'}],
])
def test_plan_launch_config_refuses_malformed_or_duplicate_structured_catalog_even_when_exempt(bad_modes):
    row = {'provider': 'claude', 'enabled': True, 'status': 'ready', 'modes': bad_modes}
    assert y.plan_launch_config('claude', row, requested='plan')['status'] == 'unavailable'


@pytest.mark.parametrize('bad_requested', ['', 'auto', 'foo', 'bypassPermissions', 'full-access'])
def test_plan_launch_config_rejects_non_restrictive_requested_uniformly(bad_requested):
    structured = catalog('claude', ['bypassPermissions', 'auto', 'plan'])
    labels = {'provider': 'claude', 'enabled': 'Enabled', 'status': 'available', 'modes': 'Auto, Plan, Bypass'}
    for row in (structured, labels):
        plan = y.plan_launch_config('claude', row, requested=bad_requested)
        assert plan['status'] == 'unavailable' and plan['reason'] == 'unsupported requested mode'
