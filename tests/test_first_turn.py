"""Isolated Pi durable evidence fixtures. No live session or credentials."""
import datetime
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from ade_first_turn import pi_first_turn, EvidenceError

@pytest.fixture
def evidence(tmp_path):
    cwd = '/fixture/project'
    transcript = tmp_path / 'session.jsonl'
    record = {'provider': 'pi', 'successor': 'fixture-id', 'cwd': cwd, 'model': 'pool/model',
              'acknowledged_at': '2026-11-18T12:00:00.500000+00:00'}
    home = tmp_path / 'home'
    p = home / 'agents/fixture-project/fixture-id.json'
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'id': 'fixture-id', 'cwd': cwd, 'provider': 'pi', 'config': {'model': 'pool/model'},
        'persistence': {'provider': 'pi', 'sessionId': 'session-id', 'nativeHandle': str(transcript)}}))
    header = {'type': 'session', 'version': 3, 'id': 'session-id', 'cwd': cwd}
    terminal = {'type': 'message', 'id': 'e1', 'parentId': None, 'timestamp': '2026-11-18T12:00:01Z',
        'message': {'role': 'assistant', 'stopReason': 'stop', 'usage': {'output': 12},
                    'content': [{'type': 'text', 'text': 'read checkpoint, next action is test'}]}}
    def write(*entries):
        transcript.write_text('\n'.join(json.dumps(x) for x in [header, *(entries or [terminal])]) + '\n')
    write()
    return home, record, transcript, terminal, write

def test_completed_native_terminal_after_ack(evidence):
    home, record, _, terminal, _ = evidence
    result = pi_first_turn(home, record, {'Status': 'idle'})
    assert result['state'] == 'complete' and result['entry_id'] == terminal['id']
    assert 'read checkpoint' not in json.dumps(result)

@pytest.mark.parametrize('reason', ['error', 'aborted'])
def test_native_failure_is_secret_safe(evidence, reason):
    home, record, _, terminal, write = evidence
    terminal['message'].update(stopReason=reason, errorMessage='SECRET_SENTINEL')
    write(terminal)
    result = pi_first_turn(home, record, {'Status': 'idle'})
    assert result['state'] == 'failed' and 'SECRET' not in json.dumps(result)

@pytest.mark.parametrize('change', ['stale', 'tool', 'empty', 'zero', 'user'])
def test_non_real_or_pre_ack_terminal_does_not_accept(evidence, change):
    home, record, _, terminal, write = evidence
    if change == 'stale': terminal['timestamp'] = '2026-11-18T12:00:00.400000Z'
    if change == 'tool': terminal['message']['stopReason'] = 'toolUse'
    if change == 'empty': terminal['message']['content'] = []
    if change == 'zero': terminal['message']['usage']['output'] = 0
    if change == 'user': terminal['message']['role'] = 'user'
    write(terminal)
    assert pi_first_turn(home, record, {'Status': 'idle'})['state'] == 'pending'

def test_branched_transcript_cannot_reuse_success(evidence):
    home, record, _, terminal, write = evidence
    sibling = {**terminal, 'id': 'sibling', 'parentId': None}
    write(terminal, sibling)
    with pytest.raises(EvidenceError, match='branched'):
        pi_first_turn(home, record, {'Status': 'idle'})

def test_header_identity_and_symlink_fail_closed(evidence, tmp_path):
    home, record, transcript, _, _ = evidence
    original = transcript.read_text()
    transcript.write_text(original.replace('session-id', 'wrong-session'))
    with pytest.raises(EvidenceError, match='header mismatch'):
        pi_first_turn(home, record, {'Status': 'idle'})
    transcript.unlink()
    target = tmp_path / 'target.jsonl'; target.write_text(original); transcript.symlink_to(target)
    with pytest.raises(EvidenceError):
        pi_first_turn(home, record, {'Status': 'idle'})
