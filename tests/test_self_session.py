"""Mocked native self-session transitions; never create/archive live agents."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'bin'))
import ade_self_session as ss

PRED = '11111111-1111-4111-8111-111111111111'
SUCC = '22222222-2222-4222-8222-222222222222'
OTHER = '33333333-3333-4333-8333-333333333333'
WS = 'wks_8bdc13f236e8850f'
HEAD = 'a' * 40
NOT_A_REPO = 'fatal: not a git repository (or any of the parent directories): .git\n'


class Native:
    def __init__(self, root):
        self.calls = []
        self.created = 0
        self.archived = 0
        self.create_error = None
        self.send_error = None
        self.archive_error = None
        self.run_result = None      # (returncode, stdout, stderr) replacing the `agent run` answer
        self.archive_result = None  # same, for `agent archive`
        self.background = set()     # ids in a background workspace: shown by `ls -a` only
        self.unlisted = set()       # ids missing from `agent ls -a -g` (workspace deleted, paseo#9668)
        self.workspaces = [{'workspaceId': WS, 'project': 'p', 'name': 'MAIN p (w)', 'cwd': str(root)}]
        self.head = HEAD
        self.git_result = None  # (returncode, stdout, stderr) overriding the default git answer
        self.rows = {PRED: {'Id': PRED, 'Provider': 'claude', 'Model': 'sonnet',
                           'Status': 'running', 'Archived': False, 'PendingPermissions': [],
                           'Cwd': str(root), 'Mode': 'bypassPermissions', 'ParentAgentId': None,
                           'AvailableModes': [{'id': 'bypassPermissions', 'label': 'Bypass'}]}}
        self.labelled = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if argv[0] == 'git':
            if isinstance(self.git_result, BaseException):
                raise self.git_result
            if self.git_result is not None:
                return subprocess.CompletedProcess(argv, *self.git_result)
            if self.head is None:
                return subprocess.CompletedProcess(argv, 128, '', NOT_A_REPO)
            return subprocess.CompletedProcess(argv, 0, self.head + '\n', '')
        assert argv[:4] == ['paseo', '--home', kwargs['env']['PASEO_HOME'], '--json']
        args = argv[4:]
        if args == ['provider', 'ls']:
            data = [{'provider': self.rows[PRED]['Provider'], 'enabled': 'Enabled', 'status': 'available', 'modes': 'display labels only'}]
        elif args == ['workspace', 'ls']:
            data = self.workspaces
        elif args[:2] == ['agent', 'inspect']:
            data = copy.deepcopy(self.rows[args[2]])
        elif args[:2] == ['agent', 'run']:
            if self.run_result is not None:
                return subprocess.CompletedProcess(argv, *self.run_result)
            self.created += 1
            self.rows[SUCC] = {**self.rows[PRED], 'Id': SUCC, 'Status': 'running',
                               'Mode': args[args.index('--mode') + 1]}
            self.labelled = [{'id': SUCC}]
            if self.create_error:
                raise self.create_error
            data = {'agentId': SUCC, 'status': 'running'}
        elif args[:2] == ['agent', 'ls']:
            # `ls -a` adds includeBackground; a plain `ls -g` (what archive resolves from) hides it
            data = self.labelled if '--label' in args else [
                {'id': k} for k in self.rows
                if k not in self.unlisted and (k not in self.background or '-a' in args)]
        elif args[:2] == ['agent', 'archive']:
            assert args == ['agent', 'archive', PRED]  # no force or workspace archive
            self.archived += 1
            if self.archive_result is not None:
                return subprocess.CompletedProcess(argv, *self.archive_result)
            self.rows[PRED]['Archived'] = True
            if self.archive_error:
                raise self.archive_error
            data = {'agentId': PRED, 'status': 'archived'}
        elif args[:2] == ['agent', 'send']:
            assert args == ['agent', 'send', PRED, '--no-wait', '--behavior', 'steer', '--', '/compact']
            if self.send_error:
                raise self.send_error
            return subprocess.CompletedProcess(argv, 5, json.dumps({'agentId': PRED, 'status': 'queued'}), '')
        else:
            raise AssertionError(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')


@pytest.fixture
def setup(tmp_path):
    cwd = tmp_path / 'work tree'
    cwd.mkdir()
    env = {'PASEO_AGENT_ID': PRED, 'PASEO_AGENT_CWD': str(cwd), 'PASEO_WORKSPACE_ID': WS,
           'PASEO_HOME': str(tmp_path / 'daemon home')}
    native = Native(cwd)
    def planner(provider, catalog, **kwargs):
        assert provider == 'claude'
        assert catalog['modes'] == native.rows[PRED]['AvailableModes']
        assert catalog['enabled'] == 'Enabled'
        return {'status': 'ready', 'provider': 'claude', 'mode_id': 'bypassPermissions', 'provider_options': {}}
    def verifier(plan, row):
        return {'ok': row['Mode'] == plan['mode_id'], 'reason': 'readback'}
    service = ss.Service(tmp_path / 'state', Path(env['PASEO_HOME']), env=env,
                         runner=native, planner=planner, verifier=verifier)
    checkpoint = tmp_path / 'brief.md'
    checkpoint.write_text('Goal, existing authority, completed work, next action, dirty-state and ownership notes.\n')
    return service, native, checkpoint


def start(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True)
    return service, native, record, Path(record['record'])


def accept(service, record, path):
    service.env['PASEO_AGENT_ID'] = SUCC
    ack = {k: record[k] for k in ('token', 'checkpoint_sha256', 'head')}
    ack['next_action'] = 'Verify the recorded worktree claim, then continue the authorized task.'
    target = service.state / 'ack.json'
    target.write_text(json.dumps(ack))
    return service.accept(path, target)


def test_durable_checkpoint_top_level_creation_and_ack_before_archive(setup):
    service, native, record, path = start(setup)
    assert record['status'] == 'awaiting-ack'
    assert Path(record['checkpoint']).read_bytes() == setup[2].read_bytes()
    assert ss.digest(Path(record['checkpoint']).read_bytes()) == record['checkpoint_sha256']
    assert json.loads(path.read_text()) == record
    call, kw = next((a, k) for a, k in native.calls if a[4:6] == ['agent', 'run'])
    assert call[call.index('--workspace') + 1] == WS
    assert call[call.index('--cwd') + 1] == record['cwd']
    assert call[call.index('--mode') + 1] == 'bypassPermissions'
    assert call[call.index('--label') + 1] == 'ade.handoff=' + record['token']
    assert call.index('--json') < call.index('--')
    assert not {'PASEO_AGENT_ID', 'PASEO_AGENT_CWD', 'PASEO_WORKSPACE_ID'} & kw['env'].keys()
    assert native.archived == 0
    service.env['PASEO_AGENT_ID'] = SUCC
    with pytest.raises(ss.SessionError, match='acknowledgement'):
        service.finish(path)
    record = accept(service, record, path)
    assert record['ack']['agent_id'] == SUCC
    with pytest.raises(ss.SessionError, match='idle'):
        service.finish(path)
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1


@pytest.mark.parametrize('workspace', [
    '', PRED, 'wks_', 'wks_8bdc13f236e8850', 'wks_8bdc13f236e8850ff',
    'wks_8bdc13f236e8850g', 'wks_8BDC13F236E8850F',
    'wks_8bdc13f236e8850f\n', 'wks_8bdc13f236e8850f;echo bad',
])
def test_invalid_workspace_rejected_before_creation_intent(setup, workspace):
    service, native, checkpoint = setup
    service.env['PASEO_WORKSPACE_ID'] = workspace
    with pytest.raises(ss.SessionError, match='workspace id'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0
    assert not list(service.state.glob('handoff-*.json'))


def test_workspace_id_is_not_accepted_as_agent_uuid(setup):
    service, native, checkpoint = setup
    service.env['PASEO_AGENT_ID'] = WS
    with pytest.raises(ss.SessionError, match='full UUID'):
        service.handoff(checkpoint, quiesced=True)
    assert native.calls == []


def test_create_intent_persisted_before_effect_and_never_replayed(setup):
    service, native, checkpoint = setup
    original = native.__call__
    def interrupted(argv, **kwargs):
        if argv[4:6] == ['agent', 'run']:
            state = list(service.state.glob('handoff-*.json'))
            assert len(state) == 1
            intent = json.loads(state[0].read_text())
            assert intent['status'] == 'creation-unknown'
            assert Path(intent['checkpoint']).is_file()
        return original(argv, **kwargs)
    service.runner = interrupted
    native.create_error = subprocess.TimeoutExpired('paseo', 30)
    first = service.handoff(checkpoint, quiesced=True)
    assert first['status'] == 'creation-unknown'
    assert service.handoff(checkpoint, quiesced=True) == first
    assert native.created == 1
    fixed = service.reconcile(Path(first['record']))
    assert fixed['status'] == 'awaiting-ack' and fixed['successor'] == SUCC
    assert native.created == 1


@pytest.mark.parametrize('rows', [[], [{'id': SUCC}, {'id': OTHER}]])
def test_ambiguous_creation_requires_unique_native_label(setup, rows):
    service, native, checkpoint = setup
    native.create_error = subprocess.TimeoutExpired('paseo', 30)
    record = service.handoff(checkpoint, quiesced=True)
    native.labelled = rows
    with pytest.raises(ss.SessionError, match='exactly one'):
        service.reconcile(Path(record['record']))
    assert native.created == 1 and native.archived == 0


@pytest.mark.parametrize(('field', 'value'), [('Mode', 'default'), ('Cwd', '/wrong'),
    ('Provider', 'codex'), ('Model', 'different'), ('ParentAgentId', PRED),
    ('PendingPermissions', [{'tool': 'write'}]), ('Archived', True)])
def test_bad_successor_readback_never_accepts_or_archives(setup, field, value):
    service, native, record, path = start(setup)
    native.rows[SUCC][field] = value
    with pytest.raises(ss.SessionError):
        accept(service, record, path)
    assert native.archived == 0


def test_checkpoint_head_and_ack_identity_must_agree(setup):
    service, native, record, path = start(setup)
    service.env['PASEO_AGENT_ID'] = OTHER
    with pytest.raises(ss.SessionError, match='exact recorded successor'):
        service.accept(path, Path('/not/read'))
    native.head = 'b' * 40
    with pytest.raises(ss.SessionError, match='HEAD changed'):
        accept(service, record, path)
    native.head = HEAD
    Path(record['checkpoint']).write_text('changed')
    with pytest.raises(ss.SessionError, match='checkpoint changed'):
        accept(service, record, path)
    assert native.archived == 0


def test_unknown_archive_reconciles_by_readback_without_replay(setup):
    service, native, record, path = start(setup)
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    native.archive_error = subprocess.TimeoutExpired('paseo', 30)
    with pytest.raises(ss.SessionError):
        service.finish(path)
    assert json.loads(path.read_text())['status'] == 'archive-unknown'
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1


def test_compact_receipt_never_means_completed_and_retry_never_resends(setup):
    service, native, checkpoint = setup
    result = service.compact(checkpoint, request_id='compact-1')
    assert result['status'] == 'requested' and result['delivery_status'] == 'queued'
    assert result['completion_confirmed'] is False
    assert service.compact(checkpoint, request_id='compact-1') == result
    assert sum(a[4:6] == ['agent', 'send'] for a, k in native.calls) == 1
    assert native.archived == native.created == 0


def test_compact_timeout_keeps_durable_unknown_no_replay(setup):
    service, native, checkpoint = setup
    native.send_error = subprocess.TimeoutExpired('paseo', 30)
    result = service.compact(checkpoint, request_id='c1')
    assert result['status'] == 'send-unknown'
    assert service.compact(checkpoint, request_id='c1') == result
    assert sum(a[4:6] == ['agent', 'send'] for a, k in native.calls) == 1


def test_unsupported_provider_and_absent_unattended_mode_never_create(setup):
    service, native, checkpoint = setup
    service.planner = lambda *a, **k: {'status': 'unavailable'}
    with pytest.raises(ss.SessionError, match='unattended'):
        service.handoff(checkpoint, quiesced=True)
    native.rows[PRED]['Provider'] = 'hermes'
    with pytest.raises(ss.SessionError, match='unsupported'):
        service.compact(checkpoint, request_id='c1')
    assert native.created == native.archived == 0


def test_quiescence_and_full_self_identity_are_required(setup):
    service, native, checkpoint = setup
    with pytest.raises(ss.SessionError, match='quiesced'):
        service.handoff(checkpoint, quiesced=False)
    service.env['PASEO_AGENT_ID'] = '1111'
    with pytest.raises(ss.SessionError, match='full UUID'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0


def test_transaction_lock_prevents_parallel_intent(setup):
    service, native, checkpoint = setup
    with service.transaction('handoff-' + PRED), pytest.raises(ss.SessionError, match='busy'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0


def test_checkpoint_fifo_refused_before_native_creation(setup, tmp_path):
    service, native, _checkpoint = setup
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(ss.SessionError, match='regular'):
        service.handoff(fifo, quiesced=True)
    assert native.created == 0


def test_persisted_status_does_not_probe_or_write(setup):
    service, native, record, path = start(setup)
    previous = path.read_bytes()
    calls = len(native.calls)
    assert service.status(path) == record
    assert path.read_bytes() == previous and len(native.calls) == calls


def test_successor_cannot_change_ack_or_skip_a_changed_checkpoint_at_retirement(setup):
    service, native, record, path = start(setup)
    accept(service, record, path)
    ack_path = service.state / 'ack.json'
    ack = json.loads(ack_path.read_text())
    ack['next_action'] = 'Conflicting acknowledgement'
    ack_path.write_text(json.dumps(ack))
    with pytest.raises(ss.SessionError, match='conflicting'):
        service.accept(path, ack_path)
    native.rows[PRED]['Status'] = 'idle'
    Path(record['checkpoint']).write_text('later changed')
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    assert native.archived == 0


def test_cli_without_native_runtime_reports_blocked_without_creation(tmp_path):
    # Cold real entrypoint without -B; import must not create repository caches.
    import shutil
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name in ('ade-self-session', 'ade_self_session.py'):
        shutil.copyfile(REPO / 'bin' / name, bindir / name)
    (bindir / 'ade-self-session').chmod(0o755)
    cli = bindir / 'ade-self-session'
    home = tmp_path / 'home'
    home.mkdir()
    result = subprocess.run([str(cli), '--state-dir', str(tmp_path / 'state'),
                             '--paseo-home', str(home), 'compact', '--checkpoint', str(tmp_path / 'not-read'),
                             '--request-id', 'c1'], check=False, capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'PASEO_AGENT_ID': ''})
    assert result.returncode == 1
    assert json.loads(result.stdout)['status'] == 'blocked'
    assert 'full UUID' in result.stdout
    assert not list(bindir.rglob('__pycache__'))
    assert not (tmp_path / 'state').exists()


@pytest.mark.parametrize(('provider', 'mode'), [('claude', 'bypassPermissions'),
    ('codex', 'full-access'), ('antigravity', 'full-access')])
def test_shared_mode_helper_integration(setup, provider, mode):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    native.rows[PRED].update(Provider=provider, Mode='default',
                            AvailableModes=[{'id': mode, 'label': 'Unattended'}])
    record = service.handoff(checkpoint, quiesced=True)
    assert record['mode_plan']['mode_id'] == mode
    assert record['mode_plan']['evidence'] == 'source-and-catalog'
    accept(service, record, Path(record['record']))
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(Path(record['record']))['status'] == 'archived'


def test_explicit_restrictive_successor_mode_is_preserved(setup):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    native.rows[PRED]['AvailableModes'].append({'id': 'plan', 'label': 'Plan'})
    record = service.handoff(checkpoint, quiesced=True, requested_mode='plan')
    assert record['mode_plan']['status'] == 'exempt'
    assert native.rows[SUCC]['Mode'] == 'plan'
    accept(service, record, Path(record['record']))


@pytest.mark.parametrize('provider', ['pi', 'cursor', 'hermes', 'omp', 'opencode'])
def test_unproven_successor_modes_refused_by_actual_shared_helper(setup, provider):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    native.rows[PRED].update(Provider=provider, AvailableModes=[])
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0


def test_missing_requested_restrictive_mode_never_launches(setup):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_mode='read-only')
    assert native.created == 0


@pytest.mark.parametrize('kind', ['handoff', 'compact'])
@pytest.mark.parametrize(('field', 'value'), [('home', '/another/home'), ('kind', 'wrong'), ('predecessor', OTHER)])
def test_duplicate_record_must_match_daemon_kind_and_actor(setup, kind, field, value):
    service, native, checkpoint = setup
    call = (lambda: service.handoff(checkpoint, quiesced=True)) if kind == 'handoff' else (lambda: service.compact(checkpoint, request_id='c1'))
    record = call()
    record[field] = value
    Path(record['record']).write_text(json.dumps(record))
    before = len(native.calls)
    with pytest.raises(ss.SessionError, match='different daemon or identity'):
        call()
    assert len(native.calls) == before


def test_omitted_mode_never_returns_saved_restrictive_transaction(setup):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    native.rows[PRED]['AvailableModes'].append({'id': 'plan', 'label': 'Plan'})
    first = service.handoff(checkpoint, quiesced=True, requested_mode='plan')
    assert first['mode_plan']['status'] == 'exempt'
    calls = len(native.calls)
    with pytest.raises(ss.SessionError, match='different requested mode'):
        service.handoff(checkpoint, quiesced=True)
    with pytest.raises(ss.SessionError, match='different requested mode'):
        service.handoff(checkpoint, quiesced=True, requested_mode='read-only')
    assert service.handoff(checkpoint, quiesced=True, requested_mode='plan') == first
    assert len(native.calls) == calls and native.created == 1


def test_omitted_mode_duplicate_of_ordinary_transaction_still_returns_saved(setup):
    service, native, checkpoint = setup
    first = service.handoff(checkpoint, quiesced=True)
    assert service.handoff(checkpoint, quiesced=True) == first
    assert native.created == 1


def run_args(native):
    return next(a for a, _ in native.calls if a[4:6] == ['agent', 'run'])


def test_explicit_thinking_is_passed_to_native_run_and_recorded(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Thinking'] = 'medium'
    record = service.handoff(checkpoint, quiesced=True, requested_thinking='high')
    call = run_args(native)
    assert call[call.index('--thinking') + 1] == 'high'
    assert call.index('--thinking') < call.index('--')
    assert record['thinking'] == 'high'
    assert json.loads(Path(record['record']).read_text())['thinking'] == 'high'


def test_thinking_defaults_to_the_predecessors_own_level(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Thinking'] = 'high'
    record = service.handoff(checkpoint, quiesced=True)
    call = run_args(native)
    assert call[call.index('--thinking') + 1] == 'high'
    assert record['thinking'] == 'high'


@pytest.mark.parametrize('source', ['absent', None, '', '-', 'auto', 'default', 'bad level;x', 7])
def test_absent_or_unusable_source_thinking_passes_no_flag(setup, source):
    service, native, checkpoint = setup
    if source != 'absent':
        native.rows[PRED]['Thinking'] = source
    record = service.handoff(checkpoint, quiesced=True)
    assert '--thinking' not in run_args(native)
    assert record['thinking'] is None and record['status'] == 'awaiting-ack'


def test_explicit_thinking_beats_the_source_level(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Thinking'] = 'low'
    service.handoff(checkpoint, quiesced=True, requested_thinking='auto')
    call = run_args(native)
    assert call[call.index('--thinking') + 1] == 'auto'


@pytest.mark.parametrize('value', ['', ' high', 'high ', 'high\n', 'hi gh', '-high', 'a;b', '$(x)', 'x' * 33, 5])
def test_invalid_thinking_refused_before_any_native_call(setup, value):
    service, native, checkpoint = setup
    with pytest.raises(ss.SessionError, match='thinking level'):
        service.handoff(checkpoint, quiesced=True, requested_thinking=value)
    assert native.calls == [] and native.created == 0
    assert not list(service.state.glob('handoff-*.json'))


def test_duplicate_handoff_with_different_explicit_thinking_is_refused(setup):
    service, native, checkpoint = setup
    first = service.handoff(checkpoint, quiesced=True, requested_thinking='high')
    calls = len(native.calls)
    with pytest.raises(ss.SessionError, match='different requested thinking'):
        service.handoff(checkpoint, quiesced=True, requested_thinking='low')
    assert service.handoff(checkpoint, quiesced=True, requested_thinking='high') == first
    assert service.handoff(checkpoint, quiesced=True) == first
    assert len(native.calls) == calls and native.created == 1


def test_cli_exposes_thinking_on_handoff_only():
    cli = str(REPO / 'bin' / 'ade-self-session')
    ok = subprocess.run([cli, 'handoff', '--help'], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and '--thinking' in ok.stdout
    bad = subprocess.run([cli, 'compact', '--checkpoint', '/x', '--request-id', 'r', '--thinking', 'high'],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 2


@pytest.mark.parametrize('name', ['{pred}.json', 'handoff-{pred}.lock', 'handoff-{pred}.json.bak',
                                  'compact-{pred}-c1.json'])
def test_load_record_requires_handoff_json_filename(setup, name):
    service, native, record, path = start(setup)
    odd = service.state / name.format(pred=record['predecessor'])
    odd.write_bytes(path.read_bytes())
    calls = len(native.calls)
    for action in (service.reconcile, service.finish):
        with pytest.raises(ss.SessionError, match=r'handoff-<uuid>\.json'):
            action(odd)
    with pytest.raises(ss.SessionError, match=r'handoff-<uuid>\.json'):
        service.accept(odd, service.state / 'ack.json')
    assert len(native.calls) == calls
    assert service.load_record(path) == 'handoff-' + record['predecessor']


def test_non_repository_cwd_records_null_head_and_accepts_and_finishes(setup):
    service, native, checkpoint = setup
    native.head = None
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    assert record['head'] is None and record['status'] == 'awaiting-ack'
    assert json.loads(path.read_text())['head'] is None
    git = [(a, k) for a, k in native.calls if a[0] == 'git']
    assert git and git[0][1]['env']['LC_ALL'] == 'C'
    prompt = next(a for a, _ in native.calls if a[4:6] == ['agent', 'run'])[-1]
    assert 'null' in prompt and 'not a git repository' in prompt
    record = accept(service, record, path)  # ack carries head: null
    assert record['ack']['head'] is None
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1


def test_null_head_ack_must_attest_head_explicitly(setup):
    service, native, checkpoint = setup
    native.head = None
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    service.env['PASEO_AGENT_ID'] = SUCC
    ack = {k: record[k] for k in ('token', 'checkpoint_sha256')}
    ack['next_action'] = 'Continue the authorized task.'
    (service.state / 'ack.json').write_text(json.dumps(ack))  # no head key at all
    with pytest.raises(ss.SessionError, match='ack must attest'):
        service.accept(path, service.state / 'ack.json')
    ack['head'] = HEAD  # a sha is not the recorded null
    (service.state / 'ack.json').write_text(json.dumps(ack))
    with pytest.raises(ss.SessionError, match='ack must attest'):
        service.accept(path, service.state / 'ack.json')


def test_non_repository_that_became_repository_refuses(setup):
    service, native, checkpoint = setup
    native.head = None
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    native.head = HEAD
    with pytest.raises(ss.SessionError, match='HEAD changed'):
        accept(service, record, path)
    native.head = None
    accept(service, record, path)
    native.head = HEAD
    native.rows[PRED]['Status'] = 'idle'
    with pytest.raises(ss.SessionError, match='HEAD changed'):
        service.finish(path)
    assert native.archived == 0


def test_repository_that_stopped_being_repository_refuses(setup):
    service, native, record, path = start(setup)
    native.head = None
    with pytest.raises(ss.SessionError, match='HEAD changed'):
        accept(service, record, path)
    native.head = HEAD
    accept(service, record, path)
    native.head = None
    native.rows[PRED]['Status'] = 'idle'
    with pytest.raises(ss.SessionError, match='HEAD changed'):
        service.finish(path)
    assert native.archived == 0


@pytest.mark.parametrize('result', [
    (128, '', 'fatal: ambiguous argument \'HEAD\': unknown revision or path not in the working tree.\n'),
    (128, '', 'fatal: detected dubious ownership in repository at \'/x\'\n'),
    (128, '', 'fatal: cannot change to \'/gone\': No such file or directory\n'),
    (128, '', ''),
    (128, '', 'fatal: not a git repository: (null)\n'),
    (128, '', 'fatal: not a git repository: /some/gitdir\n'),
    (128, '', 'warning: x\nfatal: not a git repository (or any of the parent directories): .git\n'),
    (128, 'a' * 40 + '\n', NOT_A_REPO),
    (1, '', NOT_A_REPO),
    (0, '', ''),
    (0, 'not-a-sha\n', ''),
    (0, 'A' * 40 + '\n', ''),
    subprocess.TimeoutExpired('git', 10),
    FileNotFoundError('git'),
])
def test_other_git_failures_still_refuse(setup, result):
    service, native, checkpoint = setup
    native.git_result = result
    with pytest.raises(ss.SessionError, match='exact repository HEAD unavailable'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0 and not list(service.state.glob('handoff-*.json'))


def _git(*args, cwd, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True,
                   env={**base, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1', **(env or {})})


def test_real_git_non_repository_unborn_repository_and_env_overrides(tmp_path):
    ceiling = tmp_path / 'plain'
    ceiling.mkdir()
    # An inherited GIT_DIR / GIT_CEILING_DIRECTORIES must not change the answer.
    poison = {'GIT_DIR': str(tmp_path / 'nope'), 'GIT_WORK_TREE': str(tmp_path),
              'GIT_CEILING_DIRECTORIES': str(tmp_path)}
    service = ss.Service(tmp_path / 'state', tmp_path, env={**os.environ, **poison})
    # tmp_path can sit inside a repository on an unusual host; make the check hermetic.
    if subprocess.run(['git', '-C', str(ceiling), 'rev-parse', '--git-dir'], check=False, capture_output=True,
                      env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')}).returncode == 0:
        pytest.skip('temporary directory is inside a git repository')
    assert service.git_head(str(ceiling)) is None
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git('init', '-q', cwd=repo)
    with pytest.raises(ss.SessionError, match='HEAD unavailable'):  # unborn HEAD is not "no repository"
        service.git_head(str(repo))
    _git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty',
         '-m', 'x', cwd=repo)
    head = service.git_head(str(repo))
    assert re.fullmatch(r'[0-9a-f]{40}', head)
    (repo / 'sub').mkdir()
    assert service.git_head(str(repo / 'sub')) == head


def test_non_repository_with_git_entry_above_refuses(setup, tmp_path):
    service, native, checkpoint = setup
    (tmp_path / '.git').write_text('gitdir: /nowhere\n')  # an ancestor of the cwd, git stubbed as "no repository"
    native.head = None
    with pytest.raises(ss.SessionError, match='HEAD unavailable'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0


def real_git_service(tmp_path):
    if subprocess.run(['git', '-C', str(tmp_path), 'rev-parse', '--git-dir'], check=False,
                      capture_output=True,
                      env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')}).returncode == 0:
        pytest.skip('temporary directory is inside a git repository')
    return ss.Service(tmp_path / 'state', tmp_path, env=dict(os.environ))


def test_real_git_broken_gitfile_refuses_whatever_git_prints(tmp_path):
    service = real_git_service(tmp_path)
    broken = tmp_path / 'broken'
    broken.mkdir()
    (broken / '.git').write_text('gitdir: ' + str(tmp_path / 'missing-gitdir') + '\n')
    with pytest.raises(ss.SessionError, match='HEAD unavailable'):
        service.git_head(str(broken))
    (broken / 'sub').mkdir()
    with pytest.raises(ss.SessionError, match='HEAD unavailable'):
        service.git_head(str(broken / 'sub'))


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores file modes')
def test_real_git_unreadable_dot_git_refuses(tmp_path):
    service = real_git_service(tmp_path)
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git('init', '-q', cwd=repo)
    (repo / '.git').chmod(0)
    try:
        with pytest.raises(ss.SessionError, match='HEAD unavailable'):
            service.git_head(str(repo))
    finally:
        (repo / '.git').chmod(0o755)


# --- native failure reasons (2026-11-14: WORKSPACE_NOT_FOUND and a mismatched archive were hidden) ---

def envelope(code, message, details=None):
    error = {'code': code, 'message': message}
    if details:
        error['details'] = details
    return json.dumps({'error': error})


def test_stderr_envelope_is_parsed_with_rc_and_bounded_tail(setup):
    service, native, _ = setup
    native.archive_result = (1, '', envelope('SOME_CODE', 'bad thing') + '\n' + 'x' * 5000)
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    error = caught.value
    assert error.outcome == 'refused'
    assert error.info['code'] == 'SOME_CODE' and error.info['message'] == 'bad thing'
    assert error.info['rc'] == 1 and error.info['op'] == 'agent archive'
    assert len(error.info['stderr_tail']) <= ss.TAIL_LIMIT
    assert 'SOME_CODE' in str(error) and 'bad thing' in str(error) and 'unknown' not in str(error)


def test_envelope_on_stdout_is_also_parsed(setup):
    service, native, _ = setup
    native.archive_result = (2, envelope('ON_STDOUT', 'stdout copy'), '')
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.outcome == 'refused' and caught.value.info['code'] == 'ON_STDOUT'


def test_stderr_tail_scrubs_secret_shaped_values(setup):
    service, native, _ = setup
    native.archive_result = (1, '', envelope('E', 'm') + '\nAuthorization: Bearer abc123 token=hunter2 api_key: "k-9"')
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    tail = caught.value.info['stderr_tail']
    assert 'hunter2' not in tail and 'abc123' not in tail and 'k-9' not in tail and '[redacted]' in tail


@pytest.mark.parametrize('result', [(1, '', ''), (1, 'not json', 'also not json'), (3, '', 'panic: boom')])
def test_unparseable_nonzero_exit_stays_unknown_and_keeps_rc_and_tail(setup, result):
    service, native, _ = setup
    native.archive_result = result
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.outcome == 'unknown' and 'outcome unknown' in str(caught.value)
    assert caught.value.info['rc'] == result[0] and caught.value.info['code'] is None
    assert caught.value.info['stderr_tail'] == result[2]


def test_timeout_and_oserror_are_unknown_outcomes(setup):
    service, native, _ = setup
    for exc, code in ((subprocess.TimeoutExpired('paseo', 30), 'TIMEOUT'), (FileNotFoundError('paseo'), 'OSERROR')):
        native.archive_error = exc
        with pytest.raises(ss.NativeError) as caught:
            service.native('agent', 'archive', PRED)
        assert caught.value.outcome == 'unknown' and caught.value.info['code'] == code
        assert caught.value.info['rc'] is None


def test_agent_send_rc_5_is_still_a_receipt(setup):
    service, _native, checkpoint = setup
    record = service.compact(checkpoint, request_id='r1')
    assert record['status'] == 'requested' and 'native_error' not in record


def test_create_refusal_reason_is_recorded_not_hidden(setup):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('AGENT_CREATE_FAILED', 'provider rejected the mode'))
    record = service.handoff(checkpoint, quiesced=True)
    assert record['status'] == 'creation-unknown' and native.created == 0
    assert record['native_error']['op'] == 'agent run'
    assert record['native_error']['code'] == 'AGENT_CREATE_FAILED'
    assert record['native_error']['rc'] == 1
    assert json.loads(Path(record['record']).read_text())['native_error'] == record['native_error']


def test_malformed_creation_receipt_is_recorded(setup):
    service, native, checkpoint = setup
    native.run_result = (0, json.dumps(['not', 'a', 'dict']), '')
    record = service.handoff(checkpoint, quiesced=True)
    assert record['status'] == 'creation-unknown'
    assert record['native_error']['message'] == 'malformed creation receipt'


def test_compact_send_refusal_is_recorded(setup):
    service, native, checkpoint = setup
    native.send_error = subprocess.TimeoutExpired('paseo', 30)
    record = service.compact(checkpoint, request_id='r2')
    assert record['status'] == 'send-unknown' and record['native_error']['code'] == 'TIMEOUT'


def test_workspace_gone_launches_successor_in_a_new_local_workspace(setup):
    service, native, checkpoint = setup
    native.workspaces = [{'workspaceId': 'wks_0000000000000000'}]
    record = service.handoff(checkpoint, quiesced=True)
    assert record['status'] == 'awaiting-ack' and record['workspace'] == WS
    assert record['workspace_placement'] == 'new-local'
    call = next(a for a, k in native.calls if a[4:6] == ['agent', 'run'])
    assert '--workspace' not in call and call[call.index('--new-workspace') + 1] == 'local'
    assert call[call.index('--cwd') + 1] == record['cwd']
    # verify_successor, accept and finish do not care that the placement differs
    record = accept(service, record, Path(record['record']))
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(Path(record['record']))['status'] == 'archived'


def test_workspace_present_keeps_explicit_workspace(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True)
    assert record['workspace_placement'] == 'existing'
    call = next(a for a, k in native.calls if a[4:6] == ['agent', 'run'])
    assert call[call.index('--workspace') + 1] == WS and '--new-workspace' not in call


def test_workspace_registry_failure_refuses_before_any_intent(setup):
    service, native, checkpoint = setup
    original = native.__call__
    def broken(argv, **kwargs):
        if argv[4:6] == ['workspace', 'ls']:
            return subprocess.CompletedProcess(argv, 1, '', envelope('DAEMON_DOWN', 'no daemon'))
        return original(argv, **kwargs)
    service.runner = broken
    with pytest.raises(ss.NativeError, match='DAEMON_DOWN'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0 and not list(service.state.glob('handoff-*.json'))


def finished_up_to_archive(setup):
    service, native, record, path = start(setup)
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    return service, native, path


def test_archive_refusal_is_recorded_and_not_retried(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (1, '', envelope('ARCHIVE_FAILED', 'agent is busy'))
    with pytest.raises(ss.NativeError, match='ARCHIVE_FAILED'):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown'
    assert saved['native_error']['op'] == 'agent archive' and saved['native_error']['code'] == 'ARCHIVE_FAILED'
    assert native.archived == 1


def test_archive_resolving_to_a_different_agent_gets_the_specific_error(setup):
    service, native, path = finished_up_to_archive(setup)
    # the 2026-11-14 stderr, byte for byte in shape: empty stdout, rc 1
    native.archive_result = (1, '', envelope('AGENT_ALREADY_ARCHIVED', 'Agent c9a97e5 is already archived',
                                             'Archived at: 2026-11-14T10:34:32.539Z'))
    with pytest.raises(ss.SessionError, match='different agent c9a97e5') as caught:
        service.finish(path)
    assert 'archive_agent' in str(caught.value) and PRED in str(caught.value)
    assert 'unknown' not in str(caught.value)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown' and saved['native_error']['code'] == 'AGENT_ALREADY_ARCHIVED'
    assert native.archived == 1  # never retried automatically
    # operator archives by exact id (MCP), then finish completes without another archive call
    native.archive_result = None
    native.rows[PRED]['Archived'] = True
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1
    done = json.loads(path.read_text())
    assert 'native_error' not in done and done['resolved_native_error']['code'] == 'AGENT_ALREADY_ARCHIVED'


def test_archive_error_naming_the_predecessor_prefix_is_not_a_mismatch(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (1, '', envelope('AGENT_ALREADY_ARCHIVED', 'Agent 1111111 is already archived'))
    with pytest.raises(ss.NativeError) as caught:
        service.finish(path)
    assert 'different agent' not in str(caught.value)


def test_predecessor_missing_from_listing_refuses_before_any_archive(setup):
    service, native, path = finished_up_to_archive(setup)
    native.unlisted = {PRED}
    with pytest.raises(ss.SessionError, match=r'absent from `paseo ls -g --json`.*9668.*archive_agent') as caught:
        service.finish(path)
    assert 'nothing archived' in str(caught.value)
    assert native.archived == 0
    assert not any(a[4:6] == ['agent', 'archive'] for a, k in native.calls)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'acknowledged' and saved['native_error']['code'] == 'LISTING_GAP'
    # once the listing shows it again (or the operator archived it by exact id), finish proceeds
    native.unlisted = set()
    assert service.finish(path)['status'] == 'archived' and native.archived == 1


def test_predecessor_in_listing_is_archived_as_before(setup):
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['status'] == 'archived' and native.archived == 1
    listing = [a for a, k in native.calls if a[4:6] == ['agent', 'ls']]
    assert listing and '--label' not in listing[0] and '-a' not in listing[0]  # exactly archive's list


def test_predecessor_only_in_the_background_listing_is_refused(setup):
    service, native, path = finished_up_to_archive(setup)
    native.background = {PRED}  # `agent ls -a -g` would show it; archive's own list would not
    with pytest.raises(ss.SessionError, match=r'absent from `paseo ls -g --json`'):
        service.finish(path)
    assert native.archived == 0
    assert json.loads(path.read_text())['native_error']['code'] == 'LISTING_GAP'


def test_archive_receipt_naming_another_agent_is_reported_and_not_retried(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (0, json.dumps({'agentId': OTHER, 'status': 'archived'}), '')
    with pytest.raises(ss.SessionError, match=OTHER) as caught:
        service.finish(path)
    assert 'archived a different agent' in str(caught.value) and 'archive_agent' in str(caught.value)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown' and saved['native_error']['code'] == 'ARCHIVED_OTHER_AGENT'
    assert OTHER in saved['native_error']['message'] and native.archived == 1


@pytest.mark.parametrize('receipt', [[], {'status': 'archived'}, {'agentId': 7}, {'agentId': ''}])
def test_archive_receipt_without_an_agent_id_is_not_trusted(setup, receipt):
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (0, json.dumps(receipt), '')
    with pytest.raises(ss.SessionError, match='names no agent'):
        service.finish(path)
    assert json.loads(path.read_text())['native_error']['code'] == 'ARCHIVE_RECEIPT_UNREADABLE'
    assert native.archived == 1


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_json_without_error_or_code_is_unknown_not_refused(setup, stream):
    service, native, _ = setup
    receipt = json.dumps({'agentId': SUCC, 'status': 'running'})
    native.archive_result = (1, receipt, '') if stream == 'stdout' else (1, '', receipt)
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.outcome == 'unknown'
    assert ss.parse_envelope(receipt) is None and ss.parse_envelope('{"code": "X"}') == ('X', None)


@pytest.mark.parametrize('secret, text', [
    ('dXNlcjpwYXNz', 'Authorization: Basic dXNlcjpwYXNz'),
    ('def ghi', '{"token": "abc def ghi"}'),
    ('q', '{"password":"p\\"q"}'),
    ('s3cret', 'GET https://user:s3cret@host.example/x failed'),
    ('ghp_abcdefghij0123456789', 'saw ghp_abcdefghij0123456789 in env'),
    ('gho_abcdefghij0123456789', 'gho_abcdefghij0123456789'),
    ('sk-ant-abc123-xyz', 'key sk-ant-abc123-xyz rejected'),
    ('AKIAIOSFODNN7EXAMPLE', 'id AKIAIOSFODNN7EXAMPLE'),
    ('abc999', 'access_key=abc999'),
    ('abc999', 'private-key: abc999'),
    ('sessionvalue', 'Cookie: session=sessionvalue; other=zz'),
    ('sessionvalue', 'set-cookie: session=sessionvalue; Path=/'),
    ('hunter2', "password: 'hunter2'"),
    ('hunter2', 'credentials=hunter2'),
    ('hunter2', 'PASEO_DAEMON_PASSWORD=hunter2'),
    ('abc123', 'GITHUB_TOKEN=abc123'),
    ('zzz', 'MY_API_KEY: zzz'),
    ('abc12345', 'Authorization Bearer abc12345'),
])
def test_scrub_covers_these_secret_shapes(secret, text):
    out = ss.bounded(text, 512)
    assert secret not in out and '[redacted]' in out


def test_scrub_keeps_ordinary_text_and_caps_length():
    assert ss.bounded('Agent not found: ' + PRED, 512) == 'Agent not found: ' + PRED
    assert len(ss.bounded('x' * 10000, 100)) == 100


def test_stderr_is_capped_before_parsing(setup):
    service, native, _ = setup
    native.archive_result = (1, '', 'y' * (4 * ss.STDERR_CAP) + '\n' + envelope('LATE', 'tail kept'))
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.info['code'] == 'LATE'


@pytest.mark.parametrize('message, other', [
    ('Agent decade is busy', None), ('Agent acceded is busy', None), ('Agent c9a97e5 is already archived', 'c9a97e5'),
    ('Agent c9a97e5d-4a92-4646-a016-53032146d0a1 is archived', 'c9a97e5d-4a92-4646-a016-53032146d0a1'),
    ('Agent c9a97e5xyz is archived', None), ('Agent 1111111 is already archived', None),
])
def test_agent_id_regex_is_bounded_as_an_id(message, other):
    error = ss.NativeError('x', {'message': message}, 'refused')
    got = ss.Service.archive_other_agent(error, PRED)
    # 'acceded' is seven hex-looking letters: a false positive that still only refuses, never archives
    assert got == other or (message.startswith('Agent acceded') and got == 'acceded')


@pytest.mark.parametrize('text', [
    'Password required for daemon', 'secretspec run', 'token expired for this session',
    '{"error": {"code": "TOKEN_EXPIRED", "message": "retry"}}', 'task-sk-1 and disk-sk-2', 'my-sk-3',
])
def test_scrub_leaves_prose_codes_and_hyphenated_words_alone(text):
    assert ss.bounded(text, 512) == text


def test_sk_token_still_redacted_at_a_word_start():
    out = ss.bounded('task-sk-1 then sk-ant-abc123 and (sk-live9)', 512)
    assert out == 'task-sk-1 then [redacted] and ([redacted])'


def test_code_is_validated_not_scrubbed():
    assert ss.parse_envelope(envelope('TOKEN_EXPIRED', 'retry')) == ('TOKEN_EXPIRED', 'retry')
    assert ss.parse_envelope(envelope('bad code!', 'm')) == ('INVALID_CODE', 'm')
    assert ss.parse_envelope(envelope('X' * 65, 'm'))[0] == 'INVALID_CODE'
    assert ss.parse_envelope(envelope('', 'm'))[0] is None


def test_envelope_stderr_tail_keeps_code_and_message_readable(setup):
    service, native, _ = setup
    native.archive_result = (1, '', envelope('TOKEN_EXPIRED', 'login again'))
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.info['code'] == 'TOKEN_EXPIRED'
    assert caught.value.info['stderr_tail'] == envelope('TOKEN_EXPIRED', 'login again')
