"""Exercise the actual CLI against a fake paseo; never contacts a daemon."""
import json
import os
import runpy
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
elif a[0] == 'ls' and '--label' not in a:
    if s.get('bad_local'): print('bad'); sys.exit(0)
    ids = s['local'] if 'local' in s else sorted({r['agentId'] for r in s.get('requests', []) if isinstance(r, dict) and 'agentId' in r})
    print(json.dumps([{'id':x, 'provider':s.get('providers', {}).get(x, 'claude/sonnet')} for x in ids]))
elif a[0] == 'ls': print(json.dumps([{'id':x} for x in s.get('labelled',{}).get(a[a.index('--label')+1], [])]))
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


def req(agent, rid='request', name='Bash'):
    return {'agentId':agent, 'id':rid, 'name':name, 'description':'SECRET must never enter audit'}


# Every question/plan name Paseo's providers emit (read from its source, 2026-11-13) plus run-together spellings.
PROVIDER_QUESTIONS = ['AskUserQuestion', 'ExitPlanMode', 'CodexPlanApproval', 'CodexMcpElicitation', 'request_user_input',
                      'request_user_input_async', 'question', 'Pi ask_user', 'Pi ask_user_question', 'Pi select', 'Pi input',
                      'Pi editor', 'Pi confirm', 'OMP ask', 'OMP select', 'OMP input', 'OMP editor', 'OMP confirm',
                      'switch_mode', 'set_mode', 'mcp__x__AskUserQuestion', 'MCPElicitation', 'UIConfirm', 'askuserquestion',
                      'exitplanmode', 'Exit_Planmode', 'userinput', 'HTTPQuestion']
TOOL_NAMES = ['Bash', 'Read', 'Edit', 'Write', 'Task', 'WebFetch', 'NotebookEdit', 'mcp__graft__graft_find_code',
              'mcp__paseo__browser_select', 'Explanation']


def test_descendants_and_foreign(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD),req(OTHER),req(LEAD)],
                                      'parents':{CHILD:MID, MID:LEAD}})
    assert result.returncode == 0, result.stderr
    assert [c for c in calls if c[:2] == ['permit','allow']] == [['permit','allow',CHILD,'request']]
    audit = (tmp_path/'audit.jsonl').read_text()
    assert 'SECRET' not in audit
    assert 'outside-scope' in audit and 'allowed' in audit


def test_label_qualifies_unrelated(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)],'labelled':{'ade.task=wave':[OTHER]}},
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
    assert calls and all(c in (['permit','ls'], ['ls','-a','-g'], ['ls','-a','-g','--label',f'ade.lead={LEAD}']) for c in calls)


def test_reject_foreign_selector(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)]}, '--ade-label','team=ade')
    assert result.returncode == 2
    assert not calls


def test_duplicate_and_option_request(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD),req(CHILD),req(CHILD,'--all')],
                                      'parents':{CHILD:LEAD}})
    assert result.returncode == 1
    assert sum(c[:2] == ['permit','allow'] for c in calls) == 1


def test_lead_is_excluded_even_when_labelled(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(LEAD)], 'labelled':{'ade.task=wave':[LEAD], f'ade.lead={LEAD}':[LEAD]},
                                      'parents':{LEAD:'error'}}, '--ade-label','ade.task=wave')
    assert result.returncode == 0
    assert not any(c[:2] in (['agent','inspect'], ['permit','allow']) for c in calls)
    assert 'outside-scope' in (tmp_path/'audit.jsonl').read_text()
    # An ancestry check on the lead itself must also avoid inspecting its parents.
    module = runpy.run_path(str(SCRIPT))
    assert module['descendant'](LEAD, LEAD, {}) is False


def test_watch_checks_deadline_before_each_sweep(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    main = module['main']
    clock = [0.0]
    swept = []
    monkeypatch.setattr(main.__globals__['time'], 'monotonic', lambda: clock[0])
    monkeypatch.setattr(main.__globals__['time'], 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    monkeypatch.setitem(main.__globals__, 'sweep', lambda *args: swept.append(clock[0]) or 0)
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--lead', LEAD, '--log', str(tmp_path/'audit.jsonl'),
                                    '--watch', '--interval', '10', '--duration', '1'])
    assert main() == 0
    assert swept == [0.0]  # No second sweep after sleep reaches the deadline.
    assert clock[0] == 1.0


def audit_rows(tmp_path):
    return [json.loads(x) for x in (tmp_path/'audit.jsonl').read_text().splitlines()]


def test_lead_label_approves_top_level_worker(tmp_path):
    # Env-stripped worker: no parent link to the lead, but labelled ade.lead=<lead>.
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:None},
                                      'labelled':{f'ade.lead={LEAD}':[OTHER]}})
    assert result.returncode == 0, result.stderr
    assert ['ls','-a','-g','--label',f'ade.lead={LEAD}'] in calls
    assert ['permit','allow',OTHER,'request'] in calls
    rows_ = audit_rows(tmp_path)
    assert [(r['decision'], r['reason']) for r in rows_] == [('allow-attempt','lead-label'), ('allowed','lead-label')]
    assert all(r['agent'] == OTHER for r in rows_)


def test_label_naming_another_lead_is_skipped(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:None},
                                      'labelled':{f'ade.lead={MID}':[OTHER]}})
    assert result.returncode == 0, result.stderr
    assert ['ls','-a','-g','--label',f'ade.lead={LEAD}'] in calls  # the lead label was really checked
    assert not any(c[:2] == ['permit','allow'] for c in calls)
    assert [(r['decision'], r['reason']) for r in audit_rows(tmp_path)] == [('skip','outside-scope')]


def test_unlabelled_non_descendant_is_skipped(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:None}})
    assert result.returncode == 0, result.stderr
    assert ['ls','-a','-g','--label',f'ade.lead={LEAD}'] in calls  # the lead label was really checked
    assert not any(c[:2] == ['permit','allow'] for c in calls)
    assert [(r['decision'], r['reason']) for r in audit_rows(tmp_path)] == [('skip','outside-scope')]


def allows(calls):
    return [c for c in calls if c[:2] == ['permit', 'allow']]


def test_all_local_approves_unrelated_agent_and_lead(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER), req(LEAD)], 'parents':{OTHER:None},
                                      'local':[OTHER, LEAD]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert allows(calls) == [['permit','allow',OTHER,'request'], ['permit','allow',LEAD,'request']]
    assert ['ls','-a','-g'] in calls
    assert all('--host' not in c for c in calls)
    assert {(r['decision'], r['reason']) for r in audit_rows(tmp_path)} == {('allow-attempt','all-local'), ('allowed','all-local')}
    assert 'SECRET' not in (tmp_path/'audit.jsonl').read_text()


def test_all_local_keeps_existing_reasons(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD), req(OTHER, 'r2')],
                                      'parents':{CHILD:LEAD, OTHER:None},
                                      'labelled':{f'ade.lead={LEAD}':[OTHER]}, 'local':[CHILD, OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert {(r['agent'], r['reason']) for r in audit_rows(tmp_path) if r['decision'] == 'allowed'} == \
        {(CHILD, 'descendant'), (OTHER, 'lead-label')}


def test_all_local_survives_failed_inspect(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:'error'}, 'local':[OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert allows(calls) == [['permit','allow',OTHER,'request']]


def test_remote_or_unlisted_agent_not_included(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:None}, 'local':[CHILD]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert not allows(calls)
    assert [(r['decision'], r['reason']) for r in audit_rows(tmp_path)] == [('skip','outside-scope')]


def test_without_flag_unrelated_agent_still_skipped(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'parents':{OTHER:None}, 'local':[OTHER]})
    assert not allows(calls)


def test_bad_local_listing_fails_closed(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER)], 'local':[OTHER], 'bad_local':True}, '--all-local')
    assert result.returncode == 1
    assert not allows(calls)


def test_operator_questions_never_approved_in_any_mode(tmp_path):
    import itertools
    names = ['AskUserQuestion', 'ExitPlanMode', 'EnterPlanMode', 'plan_approval', 'request_user_input', 'ask_user']
    for i, (mode, name) in enumerate(itertools.product(['all', 'descendant', 'label'], names)):
        d = tmp_path / f'case{i}'
        d.mkdir()
        scenario = {'requests':[req(CHILD, 'q', name), req(LEAD, 'q2', name)], 'parents':{CHILD:LEAD},
                    'labelled':{'ade.task=wave':[CHILD]}, 'local':[CHILD, LEAD]}
        extra = {'all':['--all-local'], 'descendant':[], 'label':['--ade-label','ade.task=wave']}[mode]
        result, calls = run_fake(d, scenario, *extra)
        assert result.returncode == 0, result.stderr
        assert not allows(calls), (mode, name)
        assert [r['reason'] for r in audit_rows(d)] == ['operator-question'] * 2


def test_non_tool_kind_and_unknown_name_are_skipped(tmp_path):
    odd = [dict(req(OTHER, 'k1'), kind='question'), dict(req(OTHER, 'k2'), kind='plan'),
           {'agentId':OTHER, 'id':'k3', 'description':'no name'}, req(OTHER, 'k4', ''), req(OTHER, 'k5', None)]
    result, calls = run_fake(tmp_path, {'requests':odd, 'local':[OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert not allows(calls)
    ok = dict(req(OTHER, 'k6'), kind='tool')
    (tmp_path / 'ok').mkdir()
    result, calls = run_fake(tmp_path / 'ok', {'requests':[ok], 'local':[OTHER]}, '--all-local')
    assert allows(calls) == [['permit','allow',OTHER,'k6']]


def test_provider_question_names_are_never_tools():
    module = runpy.run_path(str(SCRIPT))
    for name in PROVIDER_QUESTIONS:
        assert module['operator_question']({'name': name}), name
    for name in TOOL_NAMES:
        assert not module['operator_question']({'name': name}), name


def test_provider_questions_not_allowed_end_to_end(tmp_path):
    reqs = [req(OTHER, f'q{i:02d}', n) for i, n in enumerate(PROVIDER_QUESTIONS)]
    result, calls = run_fake(tmp_path, {'requests':reqs, 'local':[OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert not allows(calls)


def test_prefix_colliding_request_id_is_never_allowed(tmp_path):
    reqs = [req(OTHER, 'permission-1'), req(OTHER, 'permission-12', 'AskUserQuestion'), req(CHILD, 'x')]
    result, calls = run_fake(tmp_path, {'requests':reqs, 'local':[OTHER, CHILD]}, '--all-local')
    assert result.returncode == 1
    assert allows(calls) == [['permit','allow',CHILD,'x']]  # permission-1 is ambiguous, the question stays pending
    assert [r['reason'] for r in audit_rows(tmp_path) if r['decision'] == 'skip'] == ['ambiguous-request-id', 'operator-question']


def test_paseo_host_env_is_not_forwarded(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    seen = []
    class Done:
        returncode, stdout = 0, '[]'
    monkeypatch.setenv('PASEO_HOST', 'tcp://remote.example:1')
    monkeypatch.setitem(module['call'].__globals__, 'subprocess',
                        type('S', (), {'run': staticmethod(lambda argv, **kw: seen.append(kw['env']) or Done),
                                       'TimeoutExpired': TimeoutError}))
    assert module['call'](['ls', '-a', '-g']) == []
    assert seen and 'PASEO_HOST' not in seen[0]


EXTRA_QUESTIONS = ['plan_exit', 'ReviewPlan', 'prompt_user', 'show_dialog', 'get_approval', 'approve_change', 'choose_one',
                   'pick_choice', 'give_answer', 'enterplanmode', 'planapproval', 'switchmode', 'requestinput', 'askuser',
                   'choose_db', 'exitplan', 'enterplan']


def test_extra_question_shapes_and_tokens():
    module = runpy.run_path(str(SCRIPT))
    for name in EXTRA_QUESTIONS:
        assert module['operator_question']({'name': name}), name


def test_acp_and_unknown_providers_are_left_for_the_operator(tmp_path):
    for i, prov in enumerate(['cursor-acp/auto', 'kimi-acp', 'copilot', 'hermes/x', 'zai/glm', '', None]):
        d = tmp_path / f'p{i}'
        d.mkdir()
        scenario = {'requests':[req(OTHER, 'r', 'other'), req(CHILD, 'r', 'Which database should we use?')],
                    'parents':{OTHER:None, CHILD:LEAD}, 'providers':{OTHER:prov, CHILD:prov}}
        result, calls = run_fake(d, scenario, '--all-local')
        assert result.returncode == 0, result.stderr
        assert not allows(calls), prov
        assert {r['reason'] for r in audit_rows(d)} == {'unclassified-provider'}


def test_known_providers_all_approved(tmp_path):
    provs = {OTHER:'codex/gpt', CHILD:'opencode/x'}
    result, calls = run_fake(tmp_path, {'requests':[req(OTHER), req(CHILD)], 'parents':{CHILD:LEAD, OTHER:None},
                                      'providers':provs}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert len(allows(calls)) == 2


def test_unclassified_provider_in_descendant_and_label_modes(tmp_path):
    for i, extra in enumerate([[], ['--ade-label', 'ade.task=wave']]):
        d = tmp_path / f'm{i}'
        d.mkdir()
        result, calls = run_fake(d, {'requests':[req(CHILD)], 'parents':{CHILD:LEAD}, 'labelled':{'ade.task=wave':[CHILD]},
                                    'providers':{CHILD:'copilot'}}, *extra)
        assert result.returncode == 0, result.stderr
        assert not allows(calls)
        assert [r['reason'] for r in audit_rows(d)] == ['unclassified-provider']


def test_agent_missing_from_listing_is_outside_scope_in_every_mode(tmp_path):
    result, calls = run_fake(tmp_path, {'requests':[req(CHILD)], 'parents':{CHILD:LEAD}, 'local':[OTHER]})
    assert not allows(calls)
    assert [r['reason'] for r in audit_rows(tmp_path)] == ['outside-scope']


# Real tool names that earlier substring/token rules held back (2026-11-14): Claude Code built-ins, Paseo-style MCP
# tools whose names carry prompt/mode/plan/ask/select words, and Codex/OpenCode/OMP tool names.
FALSE_POSITIVES = ['Task', 'TaskStop', 'TaskOutput', 'Agent', 'Skill', 'ToolSearch', 'EnterWorktree', 'ExitWorktree',
                   'CronCreate', 'SendMessage', 'CodexBash', 'CodexFileChange', 'external_directory', 'bash', 'edit',
                   'task_user', 'Explanation', 'mcp__paseo__create_agent', 'mcp__paseo__list_agents', 'mcp__paseo__browser_select', 'mcp__x__ask_gemini',
                   'mcp__plan-server__list_items', 'mcp__x__approve_pull_request', 'mcp__x__task_user_list',
                   'mcp__claude_ai_Gmail__create_draft', 'mcp__x__Ask']
# Anything that is a question, plan or mode approval or elicitation must still be skipped, MCP-wrapped or not.
# Malformed `mcp__` names (no server or tool segment) are skipped; a name that is not exactly lower-case `mcp__` gets the full rules.
STILL_QUESTIONS = ['AskUserQuestion', 'ExitPlanMode', 'EnterPlanMode', 'request_user_input', 'CodexMcpElicitation',
                   'CodexPlanApproval', 'switch_mode', 'question', 'Pi ask_user', 'Pi select', 'OMP ask', 'OMP confirm',
                   'mcp__x__AskUserQuestion', 'mcp__paseo__progress_question_ask', 'mcp__x__ask_user',
                   'mcp__x__elicitation', 'mcp__x__request_user_input', 'mcp__x__plan_approval', 'mcp__x__exit_plan_mode',
                   'mcp__paseo__respond_to_permission', 'mcp__paseo__set_agent_mode', 'mcp__paseo__send_agent_prompt',
                   'mcp__x__Send-Agent-Prompt', 'CODEXMCPELICITATION', 'codexplanapproval', 'requestuserinput', 'getuserinput',
                   'mcp__ask', 'mcp____mode', 'mcp__x__', 'mcp__', 'MCP__x__ask']


def test_false_positive_names_are_tool_prompts_with_no_rule():
    module = runpy.run_path(str(SCRIPT))
    for name in FALSE_POSITIVES:
        assert module['classify']({'name': name}) is None, name
    for name in STILL_QUESTIONS:
        assert module['classify']({'name': name}) is not None, name


def test_stems_start_on_word_boundaries_only():
    module = runpy.run_path(str(SCRIPT))
    assert module['classify']({'name': 'ask_user'}) == 'stem:askuser'
    assert module['classify']({'name': 'AskUser'}) == 'stem:askuser'
    assert module['classify']({'name': 'task_user'}) is None  # "askuser" inside "taskuser" is not a boundary
    assert module['classify']({'name': 'exitplanmode'}) == 'stem:exitplan'
    assert module['classify']({'name': 'CODEXMCPELICITATION'}) == 'stem:elicit'  # long stems match inside the run-together name
    assert module['classify']({'name': 'Exit_Planmode'}) == 'stem:exitplan'
    assert module['classify']({'name': 'x', 'kind': 'question'}) == 'kind'
    assert module['classify']({'name': None}) == 'missing-name'
    assert module['classify']({'name': 7}) == 'missing-name'


def test_audit_rows_record_tool_name_and_rule_but_no_arguments(tmp_path):
    reqs = [req(OTHER, 'a', 'Bash'), req(OTHER, 'b', 'mcp__paseo__send_agent_prompt'),
            req(OTHER, 'c', 'AskUserQuestion'), req(OTHER, 'd', 'Pi select'), req(CHILD, 'e', 'Bash'),
            req(LEAD, 'f', 'mcp__x__' + 'y' * 300)]
    result, calls = run_fake(tmp_path, {'requests': reqs, 'local': [OTHER, LEAD], 'providers': {OTHER: 'claude/x', LEAD: 'claude/x'}},
                             '--all-local')
    assert result.returncode == 0, result.stderr
    rows_ = audit_rows(tmp_path)
    assert [(r['request'], r['decision'], r['tool'], r['rule']) for r in rows_] == [
        ('a', 'allow-attempt', 'Bash', None), ('a', 'allowed', 'Bash', None),
        ('b', 'skip', 'mcp__paseo__send_agent_prompt', 'hold:send_agent_prompt'),
        ('c', 'skip', 'AskUserQuestion', 'stem:question'), ('d', 'skip', 'Pi select', 'ui-token:select'),
        ('e', 'skip', '<redacted>', None), ('f', 'allow-attempt', '<redacted>', None), ('f', 'allowed', '<redacted>', None)]
    assert [r['reason'] for r in rows_ if r['decision'] == 'skip'] == ['operator-question'] * 3 + ['outside-scope']
    assert 'SECRET' not in (tmp_path / 'audit.jsonl').read_text()
    assert all(set(r) == {'time', 'decision', 'reason', 'agent', 'request', 'tool', 'rule'} for r in rows_)


def test_free_text_acp_titles_are_never_logged(tmp_path):
    title = 'Run curl -H "Authorization: Bearer SECRET-TOKEN" https://example.invalid'
    reqs = [req(OTHER, 'a', title), req(CHILD, 'b', 'Bash')]
    result, calls = run_fake(tmp_path, {'requests': reqs, 'local': [OTHER, CHILD],
                                        'providers': {OTHER: 'cursor-acp/auto', CHILD: 'claude/x'}}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert [(r['request'], r['reason'], r['tool']) for r in audit_rows(tmp_path) if r['decision'] == 'skip'] == \
        [('a', 'unclassified-provider', '<redacted>')]
    assert 'SECRET-TOKEN' not in (tmp_path / 'audit.jsonl').read_text()
    module = runpy.run_path(str(SCRIPT))
    assert module['tool_name']({'name': title}, 'claude') == '<redacted>'  # not an identifier even for a classified provider
    assert module['tool_name']({'name': 'OMP ask'}, 'omp') == 'OMP ask'
    assert module['tool_name']({'name': 'Bash'}, 'copilot') == '<redacted>'
    assert module['tool_name']({'name': 7}, 'claude') is None


def test_unnamed_and_non_string_names_log_a_null_tool_and_stay_pending(tmp_path):
    odd = [{'agentId': OTHER, 'id': 'n1', 'description': 'SECRET'}, req(OTHER, 'n2', 7)]
    result, calls = run_fake(tmp_path, {'requests': odd, 'local': [OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert not allows(calls)
    assert [(r['tool'], r['rule'], r['reason']) for r in audit_rows(tmp_path)] == [(None, 'missing-name', 'operator-question')] * 2


def test_false_positive_and_question_names_end_to_end(tmp_path):
    reqs = [req(OTHER, f'f{i:02d}', n) for i, n in enumerate(FALSE_POSITIVES)] + \
           [req(OTHER, f'q{i:02d}', n) for i, n in enumerate(STILL_QUESTIONS)]
    result, calls = run_fake(tmp_path, {'requests': reqs, 'local': [OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert [c[3] for c in allows(calls)] == [f'f{i:02d}' for i in range(len(FALSE_POSITIVES))]
    skipped = [r for r in audit_rows(tmp_path) if r['decision'] == 'skip']
    assert [r['request'] for r in skipped] == [f'q{i:02d}' for i in range(len(STILL_QUESTIONS))]
    assert all(r['rule'] for r in skipped)


# Round 2 (lead's re-review of 9ddda3ec): tools that act on another agent's cards, mode or turn are held under ANY prefix.
HELD = ['paseo_respond_to_permission', 'paseo_set_agent_mode', 'paseo_send_agent_prompt', 'paseo_update_agent',
        'mcp__paseo__update_agent', 'mcp__paseo__send_terminal_keys', 'mcp__paseo__cancel_agent', 'mcp__paseo__kill_agent',
        'mcp__paseo__archive_agent', 'mcp__paseo__create_schedule', 'mcp__paseo__create_heartbeat',
        'mcp__paseo__respondToPermission', 'mcp__paseo___respond_to_permission', 'mcp__paseo__respond_to_permission ',
        'mcp__paseo__RESPOND_TO_PERMISSION', 'respond-to-permission', 'Paseo Respond To Permission', 'paseo_sendTerminalKeys']
NOT_HELD = ['mcp__paseo__create_agent', 'mcp__paseo__list_agents', 'mcp__paseo__delete_schedule', 'paseo_echo_context',
            'mcp__paseo__get_agent_status', 'paseo_list_agents', 'Bash', 'mcp__paseo__browser_select']


def test_hold_tools_match_by_trailing_words_under_any_prefix():
    module = runpy.run_path(str(SCRIPT))
    for name in HELD:
        rule = module['classify']({'name': name})
        assert rule and rule.startswith('hold:'), (name, rule)
    for name in ['paseo_respond_to_permission', 'paseo_update_agent', 'mcp__paseo__update_agent', 'mcp__paseo__kill_agent',
                 'mcp__paseo__respondToPermission', 'mcp__paseo___respond_to_permission', 'mcp__paseo__respond_to_permission ']:
        assert module['classify']({'name': name}).startswith('hold:'), name
    for name in NOT_HELD:
        assert module['classify']({'name': name}) is None, name


def test_held_tools_never_approved_end_to_end_for_each_classified_provider(tmp_path):
    for i, prov in enumerate(['claude/x', 'opencode/x', 'codex/x']):
        d = tmp_path / f'p{i}'
        d.mkdir()
        reqs = [req(OTHER, f'h{j:02d}', n) for j, n in enumerate(HELD)] + [req(OTHER, 'ok', 'paseo_echo_context')]
        result, calls = run_fake(d, {'requests': reqs, 'local': [OTHER], 'providers': {OTHER: prov}}, '--all-local')
        assert result.returncode == 0, result.stderr
        assert [c[3] for c in allows(calls)] == ['ok']


def test_credential_looking_names_are_redacted_in_the_log(tmp_path):
    module = runpy.run_path(str(SCRIPT))
    for name in ['ghp_' + 'A' * 36, 'gho_abcdef', 'github_pat_11ABC', 'sk-proj-abc123', 'xoxb-12345', 'mcp__x__' + 'a1B2' * 10,
                 'deadbeef' * 5, 'a' * 33]:
        assert module['tool_name']({'name': name}, 'claude') == '<redacted>', name
    for name in ['Bash', 'Task-x', 'mcp__plugin_figma_figma__get_design_context', 'mcp__ask-thing', 'TaskStop', 'Pi select']:
        assert module['tool_name']({'name': name}, 'claude') == name, name
    secret = 'ghp_' + 'Z' * 36
    result, calls = run_fake(tmp_path, {'requests': [req(OTHER, 'c', secret)], 'local': [OTHER]}, '--all-local')
    assert result.returncode == 0, result.stderr
    assert secret not in (tmp_path / 'audit.jsonl').read_text()
    assert [r['tool'] for r in audit_rows(tmp_path)] == ['<redacted>'] * 2


def test_unused_max_tool_constant_is_gone():
    assert 'MAX_TOOL' not in runpy.run_path(str(SCRIPT))


# The 41 core tools Paseo registers (packages/server/src/server/agent/tools/paseo-tools.ts, 2026-11-14), each held or approved
# on purpose, plus its 22 conditional browser tools (browser-tools/tools.ts), all approved. A hand list: a new Paseo tool
# is approved until it is added here and to HOLD_TOOLS.
PASEO_HELD = ['archive_agent', 'archive_workspace', 'cancel_agent', 'create_heartbeat', 'create_schedule', 'kill_agent',
              'kill_terminal', 'respond_to_permission', 'resume_schedule', 'run_schedule_once', 'send_agent_prompt',
              'send_terminal_keys', 'set_agent_mode', 'update_agent', 'update_schedule']
PASEO_APPROVED = ['capture_terminal', 'create_agent', 'create_terminal', 'create_workspace', 'delete_heartbeat',
                  'delete_schedule', 'get_agent_activity', 'get_agent_status', 'inspect_provider', 'inspect_schedule',
                  'list_agents', 'list_hosts', 'list_models', 'list_pending_permissions', 'list_profiles', 'list_providers',
                  'list_schedules', 'list_terminals', 'list_workspace_scripts', 'list_workspaces', 'pause_schedule',
                  'rename_workspace', 'schedule_logs', 'speak', 'start_workspace_script', 'stop_workspace_script']


def test_every_paseo_tool_is_classified_in_each_naming_scheme():
    assert len(PASEO_HELD) + len(PASEO_APPROVED) == 41 and not set(PASEO_HELD) & set(PASEO_APPROVED)
    module = runpy.run_path(str(SCRIPT))
    for tool in PASEO_HELD:
        for name in (f'mcp__paseo__{tool}', f'paseo_{tool}', f'paseo-host_{tool}', f'mcp__paseo-host__{tool}'):
            assert module['classify']({'name': name}) == f'hold:{tool}', name
    for tool in PASEO_APPROVED:
        for name in (f'mcp__paseo__{tool}', f'paseo_{tool}', f'paseo-host_{tool}', f'mcp__paseo-host__{tool}'):
            assert module['classify']({'name': name}) is None, name


PASEO_BROWSER = ['list_tabs', 'new_tab', 'snapshot', 'click', 'fill', 'wait', 'type', 'keypress', 'navigate', 'screenshot',
                 'upload', 'select', 'drag', 'logs', 'evaluate', 'scroll', 'resize', 'close_tab', 'back', 'forward', 'reload', 'hover']


def test_paseo_browser_tools_are_approved_on_purpose():
    assert len(PASEO_BROWSER) == 22
    module = runpy.run_path(str(SCRIPT))
    for tool in PASEO_BROWSER:
        assert module['classify']({'name': f'mcp__paseo__browser_{tool}'}) is None, tool
    # OpenCode's `paseo_browser_select` is held only by the Pi/OMP `select` word, which fails closed.
    assert module['classify']({'name': 'paseo_browser_select'}) == 'ui-token:select'


def test_plan_mode_stem_catches_a_run_together_mcp_tool():
    module = runpy.run_path(str(SCRIPT))
    assert module['classify']({'name': 'mcp__x__set_plan_mode'}) == 'stem:planmode'


def test_hold_matches_suffixed_pluralised_and_run_together_variants():
    module = runpy.run_path(str(SCRIPT))
    for name in ['mcp__paseo__respond_to_permission_v2', 'mcp__paseo__respond_to_permission_tool',
                 'mcp__paseo__respond_to_permission_async', 'mcp__paseo__respond_to_permissions', 'mcp__paseo__respondtopermission',
                 'mcp__paseo__cancel_agent_turn', 'mcp__paseo__send_agent_prompt_v2', 'mcp__paseo__archive_workspace_now']:
        assert module['classify']({'name': name}).startswith('hold:'), name


def test_more_credential_shapes_are_redacted():
    module = runpy.run_path(str(SCRIPT))
    for name in ['AKIAIOSFODNN7EXAMPLE', 'glpat-abcdefghij0123456789', 'sk_live_abcdefghij0123456789',
                 'AIzaSyA-abcdefghij_0123456789abcdefgh', 'sk_test_abc']:
        assert module['tool_name']({'name': name}, 'claude') == '<redacted>', name
    for name in ['mcp__paseo__list_agents', 'Task-x', 'AIz', 'task_live_x']:
        assert module['tool_name']({'name': name}, 'claude') == name, name


def test_a_handed_off_lead_keeps_its_workers_covered(tmp_path, monkeypatch):
    """`--lead` pins the archived predecessor: the successor's labelled workers and the predecessor's descendants still pass."""
    new, grandchild, worker = ("cccccccc-0000-4000-8000-00000000000c", "dddddddd-0000-4000-8000-00000000000d",
                               "eeeeeeee-0000-4000-8000-00000000000e")
    ledger, home = tmp_path / "self-session", tmp_path / "paseo-home"
    ledger.mkdir()
    (ledger / f"handoff-{LEAD}.json").write_text(json.dumps(
        {"kind": "handoff", "predecessor": LEAD, "successor": new, "home": str(home.resolve()), "status": "archived",
         "ack": {"agent_id": new}}))
    monkeypatch.setenv("ADE_SELF_SESSION_STATE", str(ledger))
    monkeypatch.setenv("PASEO_HOME", str(home))
    result, calls = run_fake(tmp_path, {'requests': [req(grandchild, 'r1'), req(worker, 'r2'), req(OTHER, 'r3'), req(new, 'r4')],
                                        'parents': {grandchild: LEAD, OTHER: None},
                                        'labelled': {f'ade.lead={new}': [worker]}})
    assert result.returncode == 0
    allowed = [c[2] for c in calls if c[:2] == ['permit', 'allow']]
    assert sorted(allowed) == sorted([grandchild, worker])  # the successor itself and a stranger stay excluded
    assert ['ls', '-a', '-g', '--label', f'ade.lead={new}'] in calls and ['ls', '-a', '-g', '--label', f'ade.lead={LEAD}'] in calls
