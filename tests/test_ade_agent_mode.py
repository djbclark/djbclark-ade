"""Mock native API/CLI: no mode switches, sends, restarts, installs or state writes."""
import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bin'))
from ade_agent_mode import audit, Refused

class Native:
    def __init__(self):
        self.calls=[]
        self.state={'Id':'agent-1','Provider':'codex','Mode':'auto','AvailableModes':[{'id':'auto'},{'id':'full-access'}],
                    'Archived':False,'Status':'idle'}
        self.rows=[{'provider':'codex','enabled':'Enabled','status':'available','defaultMode':'auto','modes':'Full Access'}]
        self.after=None
    def __call__(self,args):
        self.calls.append(args)
        if 'inspect' in args:
            return copy.deepcopy(self.after if self.after and any('mode' in c for c in self.calls) else self.state)
        if 'ls' in args: return copy.deepcopy(self.rows)
        assert 'mode' in args
        return {'agentId':'agent-','mode':'full-access'}  # ack never proof


def test_default_repair_is_native_read_only_plan():
    n=Native(); result=audit('agent-1',repair=True,call=n)
    assert result['status']=='planned'
    assert all('mode' not in c for c in n.calls)


def test_yes_refuses_without_atomic_live_only_native_mutation():
    n=Native()
    # Even a fake willing to acknowledge/return matching mode cannot cause an
    # apply: the native mutation can race close and reopen the agent.
    n.after={**n.state,'Mode':'full-access'}
    with pytest.raises(Refused,match='atomic live-only'):
        audit('agent-1',repair=True,yes=True,home='/host',call=n)
    assert all(c[:3]==['paseo','--home','/host'] for c in n.calls)
    assert all('mode' not in c for c in n.calls)


@pytest.mark.parametrize('bad',['../x','--help','a b','a/b',''])
def test_invalid_identifier_never_runs_process(bad):
    n=Native()
    with pytest.raises(Refused): audit(bad,repair=True,yes=True,call=n)
    assert n.calls==[]


def test_missing_ids_or_unavailable_provider_never_mutates():
    for patch in [{'enabled':'Disabled'},{'status':'loading'}]:
        n=Native(); n.rows[0].update(patch)
        with pytest.raises(Refused): audit('agent-1',repair=True,yes=True,call=n)
        assert all('mode' not in c for c in n.calls)
    n=Native(); n.state.pop('AvailableModes')
    with pytest.raises(Refused,match='IDs unavailable'): audit('agent-1',repair=True,yes=True,call=n)


@pytest.mark.parametrize('status',['running','closed','error'])
def test_repair_does_not_open_resume_or_interrupt(status):
    n=Native(); n.state['Status']=status
    with pytest.raises(Refused,match='already-live idle'): audit('agent-1',repair=True,yes=True,call=n)
    assert all('mode' not in c for c in n.calls)


def test_restriction_preserved_check_detects_drift_and_correct_state_is_noop():
    n=Native(); n.state['Mode']='plan'
    assert audit('agent-1',repair=True,yes=True,call=n)['status']=='exempt'
    assert len(n.calls)==1
    n=Native(); assert audit('agent-1',call=n)['status']=='drift'
    n=Native(); n.state['Mode']='full-access'
    assert audit('agent-1',repair=True,yes=True,call=n)['status']=='verified'
    assert all('mode' not in c for c in n.calls)

@pytest.mark.parametrize('returncode,output',[(1,'{"Id":"agent-1"}'),(0,'not-json'),(0,'{"error":{"message":"offline"}}')])
def test_native_adapter_rejects_failure_even_with_json(monkeypatch,returncode,output):
    import ade_agent_mode as m
    from types import SimpleNamespace
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=returncode,stdout=output,stderr=''))
    with pytest.raises(Refused): m.native(['paseo','agent','inspect','agent-1','--json'])
