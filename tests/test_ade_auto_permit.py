"""Exercise the actual CLI against a fake paseo; never contacts a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "bin/ade-auto-permit"
LEAD = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
MID = "44444444-4444-4444-8444-444444444444"


def run_fake(tmp_path, scenario, *args):
    (tmp_path / "scenario.json").write_text(json.dumps(scenario))
    fake = tmp_path / "paseo"
    fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root = Path(os.environ['FAKE_ROOT'])
a = sys.argv[1:-1]
s = json.loads((root/'scenario.json').read_text())
with (root/'calls.jsonl').open('a') as f: f.write(json.dumps(a)+'\\n')
if a[:2] == ['permit', 'ls']:
    if s.get('bad_list'): print('bad'); sys.exit(0)
    print(json.dumps(s['requests']))
elif a[:2] == ['agent','inspect']:
    parent = s.get('parents', {}).get(a[2])
    if parent == 'error': sys.exit(1)
    print(json.dumps({'Id': a[2], 'ParentAgentId':parent}))
elif a[0] == 'ls': print(json.dumps([{'id':x} for x in s.get('labelled',[])]))
elif a[:2] == ['permit','allow']:
    if s.get('allow_error'): sys.exit(1)
    print(json.dumps([{'agentId':a[2],'requestId':a[3],'result':'allowed'}]))
else: sys.exit(9)
""")
    fake.chmod(0o755)
    result = subprocess.run([sys.executable, str(SCRIPT), '--lead', LEAD,
                             '--log', str(tmp_path/'audit.jsonl'), *args],
                            env={**os.environ, 'PATH':str(tmp_path)+os.pathsep+os.environ['PATH'],
                                 'FAKE_ROOT':str(tmp_path)}, capture_output=True, text=True, timeout=10)
    calls = [json.loads(x) for x in (tmp_path/'calls.jsonl').read_text().splitlines()] if (tmp_path/'calls.jsonl').exists() else []
    return result, calls


def req(agent, rid='request'):
    return {'agentId':agent, 'id':rid, 'description':'SECRET must never enter audit'}


def test_descendants_and_foreign(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD),req(OTHER),req(LEAD)],
                                      'parents':{CHILD:MID, MID:LEAD}})
    assert result.returncode == 0, result.stderr
    assert [c for c in calls if c[:2] == ['permit','allow']] == [['permit','allow',CHILD,'request']]
    audit = (tmp_path/'audit.jsonl').read_text()
    assert 'SECRET' not in audit
    assert 'outside-scope' in audit and 'allowed' in audit


def test_label_qualifies_unrelated(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)],'labelled':[OTHER]},
                            '--ade-label','ade.task=wave')
    assert result.returncode == 0
    assert ['ls','-a','-g','--label','ade.task=wave'] in calls
    assert ['permit','allow',OTHER,'request'] in calls


def test_cycle_and_failed_inspect_never_allow(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD),req(OTHER)],
                                      'parents':{CHILD:MID,MID:CHILD,OTHER:'error'}})
    assert result.returncode == 1
    assert not any(c[:2] == ['permit','allow'] for c in calls)


def test_bad_list_fails_closed(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[],'bad_list':True})
    assert result.returncode == 1
    assert len(calls) == 1


def test_unconfirmed_allow_audited(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD)],'parents':{CHILD:LEAD},'allow_error':True})
    assert result.returncode == 1
    audit = [json.loads(x) for x in (tmp_path/'audit.jsonl').read_text().splitlines()]
    assert [x['decision'] for x in audit] == ['allow-attempt','error']


def test_watch_is_bounded(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[]}, '--watch','--interval','0.01','--duration','0.05')
    assert result.returncode == 0
    assert calls and all(c == ['permit','ls'] for c in calls)


def test_reject_foreign_selector(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)]}, '--ade-label','team=ade')
    assert result.returncode == 2
    assert not calls


def test_duplicate_and_option_request(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD),req(CHILD),req(CHILD,'--all')],
                                      'parents':{CHILD:LEAD}})
    assert result.returncode == 1
    assert sum(c[:2] == ['permit','allow'] for c in calls) == 1
