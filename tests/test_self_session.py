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
        elif args[:2] == ['agent', 'inspect']:
            data = copy.deepcopy(self.rows[args[2]])
        elif args[:2] == ['agent', 'run']:
            self.created += 1
            self.rows[SUCC] = {**self.rows[PRED], 'Id': SUCC, 'Status': 'running',
                               'Mode': args[args.index('--mode') + 1]}
            self.labelled = [{'id': SUCC}]
            if self.create_error:
                raise self.create_error
            data = {'agentId': SUCC, 'status': 'running'}
        elif args[:2] == ['agent', 'ls']:
            data = self.labelled
        elif args[:2] == ['agent', 'archive']:
            assert args == ['agent', 'archive', PRED]  # no force or workspace archive
            self.archived += 1
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
