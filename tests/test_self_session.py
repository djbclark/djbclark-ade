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


class Clock:
    """Injected time: `sleep` advances `now`, nothing sleeps for real; a runaway wait fails loudly."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0 and self.now < 100000, 'runaway wait'
        self.sleeps.append(seconds)
        self.now += seconds


class Native:
    def __init__(self, root):
        self.clock = Clock()
        self.ancestor_rc = 1        # `git merge-base --is-ancestor RECORDED CURRENT`: 0 yes, 1 no, other = git error
        self.git_log = ''           # stdout of `git log RECORDED..CURRENT`
        self.log_rc = 0
        self.status_at = None       # callable(now) -> predecessor `Status`, scripting what `agent inspect` reads
        self.archive_queue = []     # (returncode, stdout, stderr) answers to successive `agent archive` calls
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
        self.probe = None           # BaseException to raise, or (rc, stdout, stderr), for an `agent ls --label ade.handoff=` probe
        self.labels = {}            # 'key=value' -> ids carrying it (every label but ade.handoff, which `labelled` serves)
        self.updates = []           # argv tails of `agent update`
        self.update_result = None   # (returncode, stdout, stderr) replacing the `agent update` answer

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if 'route_agent.py' in argv[1]:
            data = {'stale': False, 'slices': [getattr(self, 'route_choice',
                    {'service': 'go-account-a', 'agent': 'pi', 'model': 'opencode-go-account-a/test-model'})]}
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')
        if argv[0] == 'git' and 'merge-base' in argv:
            assert argv[-3] == '--is-ancestor' and re.fullmatch('[0-9a-f]{40}', argv[-2])
            if isinstance(self.ancestor_rc, BaseException):
                raise self.ancestor_rc
            return subprocess.CompletedProcess(argv, self.ancestor_rc, '', '' if self.ancestor_rc in (0, 1) else 'fatal: bad object')
        if argv[0] == 'git' and 'log' in argv:
            return subprocess.CompletedProcess(argv, self.log_rc, self.git_log, '')
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
            if args[2] == PRED and self.status_at and not data['Archived']:
                data['Status'] = self.status_at(self.clock.now)
        elif args[:2] == ['agent', 'run']:
            if self.run_result is not None:
                return subprocess.CompletedProcess(argv, *self.run_result)
            self.created += 1
            self.rows[SUCC] = {**self.rows[PRED], 'Id': SUCC, 'Status': 'running',
                               'Mode': args[args.index('--mode') + 1] if '--mode' in args else 'default'}
            provider, model = args[args.index('--provider') + 1].split('/', 1)
            self.rows[SUCC].update(Provider=provider, Model=model)
            if provider == 'pi':
                self.rows[SUCC]['AvailableModes'] = []
            self.labelled = [{'id': SUCC}]
            title = next((a.split('=', 1)[1] for a in args if a.startswith('--title=')), None)
            if title is not None:
                self.rows[SUCC]['Name'] = title
            for i, a in enumerate(args):
                if a == '--label' and not args[i + 1].startswith('ade.handoff='):
                    self.labels.setdefault(args[i + 1], set()).add(SUCC)
            if self.create_error:
                raise self.create_error
            data = {'agentId': SUCC, 'status': 'running'}
        elif args[:2] == ['agent', 'ls']:
            if self.probe is not None and any(a.startswith('ade.handoff=') for a in args):
                if isinstance(self.probe, BaseException):
                    raise self.probe
                return subprocess.CompletedProcess(argv, *self.probe)
            # `ls -a` adds includeBackground; a plain `ls -g` (what archive resolves from) hides it
            wanted = [args[i + 1] for i, a in enumerate(args) if a == '--label']
            if wanted and not any(w.startswith('ade.handoff=') for w in wanted):
                data = [{'id': i} for i in sorted(set.intersection(*(self.labels.get(w, set()) for w in wanted)))]
            else:
                data = self.labelled if wanted else [
                    {'id': k} for k in self.rows
                    if k not in self.unlisted and (k not in self.background or '-a' in args)]
        elif args[:2] == ['agent', 'update']:
            self.updates.append(args[2:])
            if self.update_result is not None:
                return subprocess.CompletedProcess(argv, *self.update_result)
            for i, a in enumerate(args):
                if a.startswith('--name='):
                    self.rows[args[2]]['Name'] = a.split('=', 1)[1]
                elif a == '--label':
                    self.labels.setdefault(args[i + 1], set()).add(args[2])
            data = {'agentId': args[2]}
        elif args[:2] == ['agent', 'archive']:
            assert args == ['agent', 'archive', PRED]  # no force or workspace archive
            self.archived += 1
            if self.archive_queue:
                return subprocess.CompletedProcess(argv, *self.archive_queue.pop(0))
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


@pytest.fixture(autouse=True)
def isolated_claims(tmp_path, monkeypatch):
    """finish rebinds ade_claims claims: never read the real registry."""
    monkeypatch.setenv('ADE_STATE_DIR', str(tmp_path / 'ade-state'))


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
                         runner=native, planner=planner, verifier=verifier,
                         clock=native.clock, sleep=native.clock.sleep)
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
    with pytest.raises(ss.SessionError, match='never stayed idle'):  # running for the whole bound
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
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    record = service.handoff(checkpoint, quiesced=True)
    assert record['status'] == 'creation-refused' and native.created == 0 and record['successor'] is None
    assert record['native_error']['op'] == 'agent run'
    assert record['native_error']['code'] == 'INVALID_THINKING_OPTION'
    assert record['native_error']['rc'] == 1
    assert json.loads(Path(record['record']).read_text())['native_error'] == record['native_error']


def test_refused_creation_never_reconciles_and_a_new_handoff_replaces_it(setup):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    refused = service.handoff(checkpoint, quiesced=True)
    assert refused['status'] == 'creation-refused'
    calls = len(native.calls)
    assert service.reconcile(Path(refused['record']))['status'] == 'creation-refused'
    assert len(native.calls) == calls  # no `agent ls`: nothing to reconcile
    native.run_result = None  # the cause is fixed: a new handoff is not blocked by the refusal
    again = service.handoff(checkpoint, quiesced=True)
    assert again['status'] == 'awaiting-ack' and again['successor'] == SUCC
    assert again['refused_before']['code'] == 'INVALID_THINKING_OPTION' and again['token'] != refused['token']


@pytest.mark.parametrize('result', [
    (1, '', 'boom: no envelope here'),                              # no error code
    (1, '', json.dumps({'error': {'message': 'no code'}})),          # envelope without a code
    (1, '', envelope('AGENT_CREATE_FAILED', 'prompt stage failed after the agent existed')),  # outcome unknown (adversary A1)
    (1, '', envelope('DAEMON_CONNECTION_LOST', 'lost')), (1, '', envelope('UNKNOWN_ERROR', 'x')),
    (1, '', envelope('INVALID_CODE', 'unreadable code')),
    (0, 'not json', ''),                                             # unparsable receipt
])
def test_create_failure_without_a_pre_create_code_stays_unknown(setup, result):
    service, native, checkpoint = setup
    native.run_result = result
    record = service.handoff(checkpoint, quiesced=True)
    assert record['status'] == 'creation-unknown'


def test_create_timeout_stays_unknown(setup):
    service, native, checkpoint = setup
    native.create_error = subprocess.TimeoutExpired('paseo', 30)
    assert service.handoff(checkpoint, quiesced=True)['status'] == 'creation-unknown'


def test_cli_reports_creation_refused_with_exit_3(setup, monkeypatch, capsys):
    import importlib.machinery, importlib.util
    path = str(Path(ss.__file__).with_name('ade-self-session'))
    loader = importlib.machinery.SourceFileLoader('ade_self_session_cli', path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    cli = importlib.util.module_from_spec(spec)
    loader.exec_module(cli)
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    monkeypatch.setattr(cli, 'Service', lambda *a, **k: service)
    monkeypatch.setattr(sys, 'argv', ['ade-self-session', '--state-dir', str(service.state), '--paseo-home', str(service.home),
                                      'handoff', '--checkpoint', str(checkpoint), '--quiesced'])
    assert cli.main() == 3
    out = capsys.readouterr()
    assert json.loads(out.out)['status'] == 'creation-refused' and 'creation-refused' in out.err


def test_a_pre_create_code_with_an_agent_carrying_the_token_stays_unknown(setup):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    native.labelled = [{'id': SUCC}]  # Paseo did create one after all
    assert service.handoff(checkpoint, quiesced=True)['status'] == 'creation-unknown'


def test_a_retry_over_a_refused_record_is_blocked_while_its_token_lists_an_agent(setup):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    refused = service.handoff(checkpoint, quiesced=True)
    assert refused['status'] == 'creation-refused'
    native.labelled = [{'id': SUCC}]
    with pytest.raises(ss.SessionError, match='no create replayed'):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0
    assert json.loads(Path(refused['record']).read_text())['status'] == 'creation-refused'


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
    # the identity readback (st-01) also lists, but only ever with --label; archive's own list has none
    listing = [a for a, k in native.calls if a[4:6] == ['agent', 'ls'] and '--label' not in a]
    assert listing and '-a' not in listing[0]  # exactly archive's list


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


@pytest.mark.parametrize('code', ['host_offline', 'commander.excessArguments', 'ns:code-1', 'A' * 64])
def test_native_code_pattern_keeps_lowercase_dotted_and_colon_codes(code):
    assert ss.parse_envelope(envelope(code, 'm')) == (code, 'm')


@pytest.mark.parametrize('code', ['ghp_' + 'a' * 36, 'sk-ant-abc123', 'github_pat_abc123', 'AKIA' + 'A' * 16, 'xoxb-1-abc', 'ns:ghp_abc', 'x.sk-abc'])
def test_native_code_shaped_like_a_bare_token_is_not_recorded(code):
    assert ss.parse_envelope(envelope(code, 'm')) == ('INVALID_CODE', 'm')


@pytest.mark.parametrize('code', [
    'password:hunter2', 'token:abc123XYZ', 'api_key:sk_live_abc123', 'GITHUB_TOKEN:ghx_abc', 'secret=x', 'Password:Hunter2', 'cookie:sid123', 'set-cookie:abc', 'COOKIE:deadbeef',
])
def test_native_code_shaped_like_a_keyword_secret_is_not_recorded(code):
    assert ss.parse_envelope(envelope(code, 'm')) == ('INVALID_CODE', 'm')


@pytest.mark.parametrize('code', [
    'sk_live_' + 'a1b2c3d4' * 3, 'rk_live_51Habcdefghijklmn', 'glpat-' + 'a1b2c3d4e5f6a7b8c9d0', 'npm_' + 'a1b2c3d4' * 4,
    'AIza' + 'Sy' + 'a1b2c3d4' * 4, 'hf_' + 'a1B2c3D4e5' * 3, 'x_ghp_' + 'a1B2c3D4e5' * 3 + 'a1B2c3', 'x-ghp_' + 'a1B2c3D4e5' * 3 + 'a1B2c3',
    '0123456789abcdef0123456789abcdef01234567', 'eyJhbGciOiJIUzI1NiJ9', 'wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY',
])
def test_native_code_with_a_long_alphanumeric_run_holding_a_digit_is_not_recorded(code):
    assert ss.parse_envelope(envelope(code, 'm')) == ('INVALID_CODE', 'm')


@pytest.mark.parametrize('code', ['TASK_SK_1', 'disk-sk-2', 'ghost_town', 'missingMandatoryOptionValue', 'commander.invalidArgument', 'secret_code', 'ns:code-1', 'abcdefghijklmnopqrstuvwxyz'])
def test_native_code_with_token_lookalike_inside_is_kept(code):
    assert ss.parse_envelope(envelope(code, 'm')) == (code, 'm')


@pytest.mark.parametrize('code', ['bad code','a\nb', 'trailing\n', 'tab\tx', 'nul\x00x', 'X' * 65, 'é', 'a/b'])
def test_native_code_pattern_still_rejects_unsafe_codes(code):
    assert ss.parse_envelope(envelope(code, 'm')) == ('INVALID_CODE', 'm')


def test_envelope_stderr_tail_keeps_code_and_message_readable(setup):
    service, native, _ = setup
    native.archive_result = (1, '', envelope('TOKEN_EXPIRED', 'login again'))
    with pytest.raises(ss.NativeError) as caught:
        service.native('agent', 'archive', PRED)
    assert caught.value.info['code'] == 'TOKEN_EXPIRED'
    assert caught.value.info['stderr_tail'] == envelope('TOKEN_EXPIRED', 'login again')


# --- finish waits for a stable idle predecessor (fw-01, 2026-11-14) ---------------------------------

RUNNING = (1, '', envelope('AGENT_RUNNING', 'Agent 1111111 is currently running'))  # Paseo archive.ts wording, PRED's prefix


def archive_calls(native):
    return [a for a, k in native.calls if a[4:6] == ['agent', 'archive']]


def only_reads_and_archive(native):
    """The wait never forces, never archives a workspace, never sends the predecessor anything."""
    for argv, _ in native.calls:
        if argv[0] == 'paseo':
            assert argv[4:6] in (['agent', 'inspect'], ['agent', 'ls'], ['agent', 'archive'],
                                 ['provider', 'ls'], ['workspace', 'ls'], ['agent', 'run']), argv
            assert '--force' not in argv and 'send' not in argv


def test_finish_waits_for_a_stable_idle_window_then_archives(setup):
    service, native, path = finished_up_to_archive(setup)
    native.status_at = lambda now: 'running' if now < 20 else 'idle'
    saw = []
    service.progress = saw.append
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1
    assert native.clock.now >= 20 + 45  # idle only from t=20, then the whole window
    assert native.clock.sleeps and all(x <= ss.FINISH_POLL for x in native.clock.sleeps)
    assert any('not idle' in m for m in saw) and any('stable idle' in m for m in saw)
    only_reads_and_archive(native)


def test_a_busy_sample_restarts_the_window(setup):
    service, native, path = finished_up_to_archive(setup)
    native.status_at = lambda now: 'running' if 30 <= now < 40 else 'idle'  # idle 30 s, busy 10 s, idle again
    assert service.finish(path)['status'] == 'archived'
    assert native.clock.now >= 40 + 45  # the first 30 s of idle did not count
    assert native.archived == 1


def test_pending_permissions_are_not_stable_idle(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['PendingPermissions'] = [{'id': 'p'}]
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=10, timeout=60)
    assert native.archived == 0 and native.clock.now == 60


def test_agent_running_answer_goes_back_to_waiting_then_retries(setup):
    service, native, path = finished_up_to_archive(setup)
    # the 2026-11-14 shape: idle for the whole window, a peer message starts a turn, archive is refused
    native.status_at = lambda now: 'running' if 46 <= now < 70 else 'idle'
    native.archive_queue = [RUNNING]
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 2
    assert native.clock.now >= 70 + 45  # a fresh stable window after the refusal
    done = json.loads(path.read_text())
    assert done['status'] == 'archived' and 'native_error' not in done
    assert done['resolved_native_error']['code'] == 'AGENT_RUNNING'
    only_reads_and_archive(native)


def test_timeout_before_any_archive_keeps_both_sessions(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Status'] = 'running'
    with pytest.raises(ss.SessionError, match=r'never stayed idle.*both sessions preserved'):
        service.finish(path, stable=30, timeout=100, poll=7)  # 7 does not divide 100: the last sleep is clamped
    assert native.archived == 0 and native.clock.now == 100 and native.clock.sleeps[-1] == 2
    saved = json.loads(path.read_text())
    assert saved['status'] == 'acknowledged'  # nothing was attempted
    assert saved['native_error']['code'] == 'PREDECESSOR_NOT_IDLE' and 'never stayed idle' in saved['native_error']['message']
    only_reads_and_archive(native)
    # the predecessor goes idle later: a re-run finishes
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'
    assert 'native_error' not in json.loads(path.read_text())


def test_timeout_after_agent_running_answers_stays_archive_unknown(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING] * 50  # always refused
    with pytest.raises(ss.SessionError, match=r'never stayed idle.*AGENT_RUNNING to \d+ archive'):
        service.finish(path, stable=20, timeout=100, poll=5)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown'
    assert saved['native_error']['code'] == 'PREDECESSOR_NOT_IDLE'
    assert 2 <= native.archived <= 6 and native.clock.now <= 100


def test_other_archive_errors_are_not_retried_even_when_the_message_says_running(setup):
    service, native, path = finished_up_to_archive(setup)
    # classified by the structured code, not by prose
    native.archive_queue = [(1, '', envelope('ARCHIVE_FAILED', 'AGENT_RUNNING elsewhere'))]
    with pytest.raises(ss.NativeError, match='ARCHIVE_FAILED'):
        service.finish(path)
    assert native.archived == 1 and json.loads(path.read_text())['native_error']['code'] == 'ARCHIVE_FAILED'


def test_agent_running_code_is_retried_whatever_the_message(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [(1, '', envelope('AGENT_RUNNING', 'busy'))]
    assert service.finish(path)['status'] == 'archived' and native.archived == 2


def test_already_archived_predecessor_finishes_at_once(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Archived'] = True
    native.rows[PRED]['Status'] = 'running'  # irrelevant once archived
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 0 and native.clock.sleeps == []


def test_no_wait_flags_keep_the_old_single_sample_behaviour(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Status'] = 'running'
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=0, timeout=0)
    assert native.clock.sleeps == [] and native.archived == 0
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path, stable=0, timeout=0)['status'] == 'archived' and native.clock.sleeps == []


@pytest.mark.parametrize('kw', [{'stable': -1}, {'timeout': 10, 'stable': 11}, {'timeout': 10, 'stable': 10}, {'poll': 0},
                                {'poll': 0.1}, {'poll': 3601}, {'timeout': 86401}, {'timeout': 1e308, 'poll': 1e308}, {'timeout': float('nan')}, {'timeout': float('inf')},
                                {'stable': float('inf'), 'timeout': float('inf')}, {'poll': float('inf')}])
def test_nonsense_wait_arguments_are_refused_before_any_native_call(setup, kw):
    service, native, path = finished_up_to_archive(setup)
    before = len(native.calls)
    with pytest.raises(ss.SessionError, match='stable'):
        service.finish(path, **kw)
    assert len(native.calls) == before


def test_checkpoint_changed_during_the_wait_is_caught_before_archive(setup):
    service, native, path = finished_up_to_archive(setup)
    record = json.loads(path.read_text())
    def flip(now):
        if now >= 10:
            Path(record['checkpoint']).write_text('tampered while we waited\n')
        return 'running' if now < 10 else 'idle'
    native.status_at = flip
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    assert native.archived == 0


def test_stable_zero_agent_running_retries_obey_the_bound(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING] * 3
    with pytest.raises(ss.SessionError, match=r'never stayed idle.*last status running \(archive refused\).*AGENT_RUNNING to 1 archive'):
        service.finish(path, stable=0, timeout=0)
    assert len(archive_calls(native)) == 1 and native.clock.sleeps == []
    assert json.loads(path.read_text())['native_error']['code'] == 'PREDECESSOR_NOT_IDLE'


def test_stable_zero_retries_sleep_between_attempts_and_stop_at_the_deadline(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING] * 9
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=0, timeout=10, poll=5)
    assert len(archive_calls(native)) == 3 and native.clock.sleeps == [5, 5] and native.clock.now == 10


def test_agent_running_naming_another_agent_is_not_retried(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [(1, '', envelope('AGENT_RUNNING', 'Agent 3333333 is currently running'))]
    with pytest.raises(ss.SessionError, match='different agent 3333333') as caught:
        service.finish(path)
    assert 'archive_agent' in str(caught.value) and len(archive_calls(native)) == 1
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown' and saved['native_error']['code'] == 'ARCHIVE_RESOLVED_OTHER_AGENT'
    assert guard_says(service) == 'pass'  # sr-43 a: no longer a wait, the send guard stops redirecting at once


def test_failure_after_an_agent_running_refusal_replaces_the_stale_reason(setup):
    service, native, path = finished_up_to_archive(setup)
    record = json.loads(path.read_text())
    native.archive_queue = [RUNNING]
    def tamper(now):
        if now >= 50:
            Path(record['checkpoint']).write_text('changed after the refusal\n')
        return 'idle'
    native.status_at = tamper
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['native_error']['op'] == 'finish' and 'checkpoint or HEAD changed' in saved['native_error']['message']
    assert len(archive_calls(native)) == 1


def test_malformed_permission_count_is_not_idle_and_does_not_crash_the_progress_line(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['PendingPermissions'] = 3
    saw = []
    service.progress = saw.append
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=10, timeout=20)
    assert any('unknown permission wait' in m for m in saw) and native.archived == 0


# --- a moved HEAD: fast-forward tolerated, anything else blocks (fw-01 repair, 2026-11-14) ---------

NEW_HEAD = 'b' * 40


def moved(setup, **kw):
    service, native, path = finished_up_to_archive(setup)
    native.head = NEW_HEAD
    for k, v in kw.items():
        setattr(native, k, v)
    return service, native, path


def test_fast_forwarded_head_is_tolerated_and_recorded(setup):
    service, native, path = moved(setup, ancestor_rc=0, git_log='bbbbbbb second\naaaaaaa first\n')
    done = service.finish(path)
    assert done['status'] == 'archived' and native.archived == 1
    assert done['head_advanced'] == {'from': HEAD, 'to': NEW_HEAD, 'commits': ['bbbbbbb second', 'aaaaaaa first'],
                                     'more': False}
    assert json.loads(path.read_text())['head_advanced'] == done['head_advanced']
    assert done['head'] == HEAD  # the recorded head is never rewritten
    argv = next(a for a, k in native.calls if 'merge-base' in a)
    assert argv[-3:] == ['--is-ancestor', HEAD, NEW_HEAD] and argv[:3] == ['git', '-C', done['cwd']]


def test_long_fast_forward_lists_a_capped_log(setup):
    service, native, path = moved(setup, ancestor_rc=0, git_log=''.join(f'{i:07x} c{i}\n' for i in range(25)))
    drift = service.finish(path)['head_advanced']
    assert len(drift['commits']) == ss.DRIFT_COMMITS and drift['more'] is True


@pytest.mark.parametrize('rc', [1, 128, 2])
def test_head_that_is_not_a_descendant_or_a_git_error_blocks(setup, rc):
    service, native, path = moved(setup, ancestor_rc=rc)
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed.*not a fast-forward'):
        service.finish(path)
    assert native.archived == 0 and 'head_advanced' not in json.loads(path.read_text())


@pytest.mark.parametrize('error', [OSError('no git'), subprocess.TimeoutExpired('git', 10)])
def test_ancestry_check_that_cannot_run_blocks(setup, error):
    service, native, path = moved(setup, ancestor_rc=error)
    with pytest.raises(ss.SessionError, match='not a fast-forward'):
        service.finish(path)
    assert native.archived == 0


def test_checkpoint_change_still_blocks_with_a_fast_forwarded_head(setup):
    service, native, path = moved(setup, ancestor_rc=0)
    Path(json.loads(path.read_text())['checkpoint']).write_text('edited')
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    assert native.archived == 0


def test_repository_that_vanished_or_appeared_blocks(setup):
    service, native, path = moved(setup, ancestor_rc=0, head=None)  # recorded a head, now no repository
    with pytest.raises(ss.SessionError, match='not a fast-forward'):
        service.finish(path)
    assert not any('merge-base' in a for a, k in native.calls)


def test_null_recorded_head_with_a_repository_now_blocks(setup):
    service, native, checkpoint = setup
    native.head = None
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    assert record['head'] is None
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    native.head, native.ancestor_rc = NEW_HEAD, 0
    with pytest.raises(ss.SessionError, match='not a fast-forward'):
        service.finish(path)
    assert native.archived == 0 and not any('merge-base' in a for a, k in native.calls)


def test_head_advancing_during_the_wait_is_recorded_before_the_archive(setup):
    service, native, path = finished_up_to_archive(setup)
    native.ancestor_rc = 0
    def lands(now):
        native.head = NEW_HEAD if now >= 30 else HEAD
        return 'running' if now < 10 else 'idle'
    native.status_at = lands
    done = service.finish(path)
    assert done['status'] == 'archived' and done['head_advanced']['to'] == NEW_HEAD


def test_malformed_recorded_head_blocks_without_reaching_git(setup):
    service, native, path = moved(setup, ancestor_rc=0)
    record = json.loads(path.read_text())
    record['head'] = '--upload-pack=x'
    path.write_text(json.dumps(record))
    with pytest.raises(ss.SessionError, match='not a fast-forward'):
        service.finish(path)
    assert not any('merge-base' in a for a, k in native.calls)


def test_advanced_head_is_saved_even_when_finish_then_fails(setup):
    service, native, path = moved(setup, ancestor_rc=0)
    record = json.loads(path.read_text())
    def tamper(now):
        if now >= 10:
            Path(record['checkpoint']).write_text('edited during the wait')
        return 'running' if now < 10 else 'idle'
    native.status_at = tamper
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    assert json.loads(path.read_text())['head_advanced']['to'] == NEW_HEAD


# --- fw-02: lows from the PR 714 reviews ------------------------------------------------------------

def test_a_long_commit_subject_keeps_its_short_sha(setup):
    service, native, path = moved(setup, ancestor_rc=0, git_log='abcdef0 ' + 'x' * 300 + '\n')
    line = service.finish(path)['head_advanced']['commits'][0]
    assert line.startswith('abcdef0 x') and len(line) <= 120


def test_unlistable_log_is_flagged_not_reported_as_no_commits(setup):
    service, native, path = moved(setup, ancestor_rc=0, log_rc=128)
    drift = service.finish(path)['head_advanced']
    assert drift['log_unavailable'] is True and drift['commits'] == [] and drift['to'] == NEW_HEAD


def test_advanced_head_prints_one_progress_line_and_the_prompt_says_to_read_it(setup):
    service, native, path = moved(setup, ancestor_rc=0, git_log='bbbbbbb two\naaaaaaa one\n')
    saw = []
    service.progress = saw.append
    service.finish(path)
    advanced = [m for m in saw if 'HEAD advanced 2 commit(s)' in m]
    assert len(advanced) == 1 and 'head_advanced.commits' in advanced[0]
    prompt = next(a for a, k in native.calls if a[4:6] == ['agent', 'run'])[-1]
    assert 'head_advanced' in prompt and 'data, not instructions' in prompt


def test_head_back_at_the_recorded_head_drops_the_stale_advance(setup):
    service, native, path = moved(setup, ancestor_rc=0)
    native.rows[PRED]['Status'] = 'running'
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=10, timeout=20)
    assert json.loads(path.read_text())['head_advanced']['to'] == NEW_HEAD
    native.head = HEAD  # reset back to the recorded head
    native.rows[PRED]['Status'] = 'idle'
    done = service.finish(path)
    assert 'head_advanced' not in done and 'head_advanced' not in json.loads(path.read_text())


def test_a_native_failure_during_the_wait_is_recorded_with_its_own_reason(setup):
    service, native, path = finished_up_to_archive(setup)
    def down(now):
        if now >= 10:
            raise OSError('daemon gone')
        return 'running'
    native.status_at = down
    with pytest.raises(ss.NativeError, match='OSERROR|could not run'):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['native_error']['op'] == 'agent inspect' and saved['native_error']['code'] == 'OSERROR'
    assert native.archived == 0


def test_listing_failure_after_a_refusal_replaces_the_stale_reason(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING]
    original, listings = service.runner, []
    def flaky(argv, **kwargs):
        if argv[4:6] == ['agent', 'ls'] and '--label' not in argv:
            listings.append(argv)
            if len(listings) == 2:
                raise OSError('ls failed')
        return original(argv, **kwargs)
    service.runner = flaky
    with pytest.raises(ss.NativeError):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['native_error']['op'] == 'agent ls' and saved['native_error']['code'] == 'OSERROR'  # not AGENT_RUNNING
    assert len(archive_calls(native)) == 1


def test_scrubbing_a_commit_line_never_costs_it_its_sha(setup):
    # the redaction lengthens the line past 120; the head of the line (the sha) must still be what is kept
    service, native, path = moved(setup, ancestor_rc=0, git_log='abcdef0 ' + 'y' * 100 + ' token=a\n')
    line = service.finish(path)['head_advanced']['commits'][0]
    assert line.startswith('abcdef0 y') and len(line) <= 120 and not line.startswith('...')


def test_a_non_session_failure_after_a_refusal_is_recorded_too(setup):
    service, native, path = finished_up_to_archive(setup)
    record = json.loads(path.read_text())
    native.archive_queue = [RUNNING]
    def remove(now):
        if now >= 50:
            Path(record['checkpoint']).unlink(missing_ok=True)
        return 'idle'
    native.status_at = remove
    with pytest.raises(OSError):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['native_error']['op'] == 'finish' and saved['native_error']['code'] is None
    assert 'AGENT_RUNNING' not in json.dumps(saved['native_error'])




# st-01 (2026-11-14): the successor keeps the predecessor's title and chain labels, so `paseo ls` finds a chain's lead.

def run_call(native):
    return next(a for a, _ in native.calls if a[4:6] == ['agent', 'run'])


def run_labels(call):
    return [call[i + 1] for i, a in enumerate(call) if a == '--label']


def settle(service, native, record, path):
    """accept, then finish: the whole successor side of a handoff."""
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    return service.finish(path)


def test_successor_keeps_predecessor_title_and_chain_labels_through_accept_and_finish(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Lead tendcf (cfengine)'
    service.env['PASEO_AGENT_ID'] = PRED
    record = service.handoff(checkpoint, quiesced=True, requested_role='tendcf-lead')
    path = Path(record['record'])
    call = run_call(native)
    assert '--title=Lead tendcf (cfengine)' in call and call.index('--title=Lead tendcf (cfengine)') < call.index('--')
    assert run_labels(call) == ['ade.handoff=' + record['token'], 'ade.chain=' + PRED,
                                'ade.predecessor=' + PRED, 'ade.role=tendcf-lead']
    assert native.rows[SUCC]['Name'] == 'Lead tendcf (cfengine)'
    assert record['identity'] == {
        'title': 'Lead tendcf (cfengine)', 'title_source': 'predecessor-name', 'role_source': 'requested',
        'labels': {'ade.chain': PRED, 'ade.predecessor': PRED, 'ade.role': 'tendcf-lead'},
        'checks': {'create': 'requested'}}
    accepted = accept(service, record, path)
    assert accepted['identity']['checks']['accept'] == 'ok' and native.updates == []
    native.rows[PRED]['Status'] = 'idle'
    finished = service.finish(path)
    assert finished['status'] == 'archived' and finished['identity']['checks']['finish'] == 'ok'
    assert native.updates == [] and native.rows[SUCC]['Name'] == 'Lead tendcf (cfengine)'
    assert json.loads(path.read_text()) == finished


def test_predecessor_without_a_role_label_still_gets_predecessor_and_chain_labels(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Lead plain'
    record = service.handoff(checkpoint, quiesced=True)
    assert run_labels(run_call(native))[1:] == ['ade.chain=' + PRED, 'ade.predecessor=' + PRED]
    assert record['identity']['labels'] == {'ade.chain': PRED, 'ade.predecessor': PRED}
    assert record['identity']['role_source'] is None
    assert settle(service, native, record, Path(record['record']))['identity']['checks'] == {
        'create': 'requested', 'accept': 'ok', 'finish': 'ok'}


def test_chain_record_supplies_title_chain_and_role_when_the_name_is_a_bootstrap_title(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Self-handoff 9f2c: checkpoint ack and accept'
    service.state.mkdir(mode=0o700, parents=True)
    earlier = {'kind': 'handoff', 'home': str(service.home), 'predecessor': OTHER, 'successor': PRED,
               'identity': {'title': 'Lead tendcf', 'labels': {'ade.chain': OTHER, 'ade.predecessor': OTHER,
                                                               'ade.role': 'tendcf-lead'}}}
    (service.state / ('handoff-' + OTHER + '.json')).write_text(json.dumps(earlier))
    record = service.handoff(checkpoint, quiesced=True)
    assert record['identity']['title'] == 'Lead tendcf' and record['identity']['title_source'] == 'chain-record'
    assert record['identity']['labels'] == {'ade.chain': OTHER, 'ade.predecessor': PRED,
                                            'ade.role': 'tendcf-lead'}
    assert record['identity']['role_source'] == 'chain-record'


@pytest.mark.parametrize('name', ['Self-handoff abc: checkpoint ack and accept',
                                  'Self-handoff acknowledgement for session cd5df8af', '-', None])
def test_no_usable_name_and_no_chain_record_gets_a_derived_title(setup, name):
    service, native, checkpoint = setup
    if name is not None:
        native.rows[PRED]['Name'] = name
    record = service.handoff(checkpoint, quiesced=True)
    assert record['identity']['title'] == 'Lead (self-handoff successor)'
    assert record['identity']['title_source'] == 'derived'
    assert '--title=Lead (self-handoff successor)' in run_call(native)
    # paseo#9668: a partial-title archive fallback must never match on an id prefix in a lead's title
    assert PRED[:7] not in record['identity']['title'] and PRED[:8] not in record['identity']['title']


def test_derived_title_names_the_role_when_there_is_one(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, requested_role='tendcf-lead')
    assert record['identity']['title'] == 'Lead tendcf-lead' and record['identity']['title_source'] == 'derived'


def test_an_unprintable_name_falls_through_to_the_next_title_source(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = '\u200b\u200b'
    assert service.handoff(checkpoint, quiesced=True)['identity']['title_source'] == 'derived'


def test_requested_title_wins_and_is_normalised(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Lead other'
    record = service.handoff(checkpoint, quiesced=True, requested_title='  -Lead\ttendcf\n' + 'x' * 300)
    title = record['identity']['title']
    assert title.startswith('-Lead tendcf x') and len(title) == 200 and record['identity']['title_source'] == 'requested'
    assert '--title=' + title in run_call(native)  # `--title=` keeps a leading dash from reading as a flag


@pytest.mark.parametrize('kwargs', [{'requested_role': 'bad role'}, {'requested_role': 'a,b=c'},
                                    {'requested_role': ''}, {'requested_title': '   '}])
def test_invalid_title_or_role_is_refused_before_any_intent(setup, kwargs):
    service, native, checkpoint = setup
    with pytest.raises(ss.SessionError):
        service.handoff(checkpoint, quiesced=True, **kwargs)
    assert native.created == 0 and not list(service.state.glob('handoff-*.json'))


def test_accept_repairs_a_retitled_and_unlabelled_successor(setup):
    service, native, record, path = start(setup)
    native.rows[SUCC]['Name'] = 'Self-handoff x: checkpoint ack and accept'
    native.labels.clear()
    accepted = accept(service, record, path)
    assert accepted['identity']['checks']['accept'] == 'repaired'
    assert len(native.updates) == 1 and native.updates[0][0] == SUCC
    assert '--name=' + record['identity']['title'] in native.updates[0]
    assert [native.updates[0][i + 1] for i, a in enumerate(native.updates[0]) if a == '--label'] == [
        'ade.chain=' + PRED, 'ade.predecessor=' + PRED]
    assert native.rows[SUCC]['Name'] == record['identity']['title']


def test_finish_repairs_a_successor_paseo_retitled_after_accept(setup):
    service, native, record, path = start(setup)
    accept(service, record, path)
    native.rows[SUCC]['Name'] = 'retitled by something'
    native.rows[PRED]['Status'] = 'idle'
    finished = service.finish(path)
    assert finished['identity']['checks'] == {'create': 'requested', 'accept': 'ok', 'finish': 'repaired'}
    assert native.rows[SUCC]['Name'] == record['identity']['title']
    assert [u[1] for u in native.updates] == ['--name=' + record['identity']['title']]  # labels were intact


def test_a_paseo_refusal_to_rename_is_recorded_and_not_fatal_then_resolved(setup):
    service, native, record, path = start(setup)
    native.rows[SUCC]['Name'] = 'retitled'
    native.update_result = (1, '', envelope('AGENT_NOT_FOUND', 'Agent not found'))
    accepted = accept(service, record, path)
    assert accepted['status'] == 'acknowledged' and accepted['ack']['agent_id'] == SUCC
    identity = accepted['identity']
    assert identity['checks']['accept'] == 'failed'
    assert identity['error']['stage'] == 'accept'
    assert identity['error']['native_error']['op'] == 'agent update'
    assert identity['error']['native_error']['code'] == 'AGENT_NOT_FOUND'
    assert json.loads(path.read_text())['identity']['error'] == identity['error']
    native.rows[PRED]['Status'] = 'idle'
    still = service.finish(path)  # still refused: finish archives anyway, the failure stays on the record
    assert still['status'] == 'archived' and still['identity']['checks']['finish'] == 'failed'
    assert native.archived == 1


def test_a_later_successful_check_keeps_the_earlier_refusal_as_history(setup):
    service, native, record, path = start(setup)
    native.rows[SUCC]['Name'] = 'retitled'
    native.update_result = (1, '', envelope('INVALID_NAME', 'nope'))
    accept(service, record, path)
    native.update_result = None
    native.rows[PRED]['Status'] = 'idle'
    finished = service.finish(path)
    identity = finished['identity']
    assert 'error' not in identity and identity['resolved_error']['native_error']['code'] == 'INVALID_NAME'
    assert identity['checks']['finish'] == 'repaired' and native.rows[SUCC]['Name'] == identity['title']


def test_a_record_from_before_st01_has_no_identity_and_is_left_alone(setup):
    service, native, record, path = start(setup)
    old = json.loads(path.read_text())
    del old['identity']
    path.write_text(json.dumps(old))
    native.rows[SUCC]['Name'] = 'whatever it was called'
    finished = settle(service, native, old, path)
    assert finished['status'] == 'archived' and 'identity' not in finished
    assert native.updates == []


@pytest.mark.parametrize('identity', [
    {}, {'title': 5, 'labels': []},
    {'title': 'T', 'labels': 'x'}, {'title': 'T', 'labels': {'ade.role': 'a,ade.kind=code'}},
    {'title': 'T', 'labels': {'ade.kind': 'external-review'}}, {'title': 'T', 'labels': {'ade.chain': 'nope'}},
    {'title': 'T\n', 'labels': {}}])
@pytest.mark.parametrize('stage', ['accept', 'finish'])
def test_a_malformed_or_forged_identity_is_recorded_and_never_fatal_or_sent(setup, identity, stage):
    service, native, record, path = start(setup)
    forged = json.loads(path.read_text())
    forged['identity'] = copy.deepcopy(identity)
    path.write_text(json.dumps(forged))
    if stage == 'finish':
        record = accept(service, forged, path)
        record['identity'] = copy.deepcopy(identity)
        path.write_text(json.dumps(record))
        native.rows[PRED]['Status'] = 'idle'
        done = service.finish(path)
        assert done['status'] == 'archived'
    else:
        done = accept(service, forged, path)
        assert done['status'] == 'acknowledged'
    assert done['identity']['checks'][stage] == 'failed'
    assert done['identity']['error']['stage'] == stage
    assert native.updates == []  # nothing from the record reached `agent update`


def test_a_forged_chain_record_label_is_dropped_before_it_reaches_the_new_record(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Self-handoff x'
    service.state.mkdir(mode=0o700, parents=True)
    earlier = {'kind': 'handoff', 'home': str(service.home), 'predecessor': OTHER, 'successor': PRED,
               'identity': {'title': 'T', 'labels': {'ade.chain': 'not-a-uuid', 'ade.role': 'a,ade.kind=code'}}}
    (service.state / ('handoff-' + OTHER + '.json')).write_text(json.dumps(earlier))
    record = service.handoff(checkpoint, quiesced=True)
    assert record['identity']['labels'] == {'ade.chain': PRED, 'ade.predecessor': PRED}


def test_a_chain_record_from_another_daemon_home_is_ignored(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Self-handoff x'
    service.state.mkdir(mode=0o700, parents=True)
    earlier = {'kind': 'handoff', 'home': '/elsewhere', 'predecessor': OTHER, 'successor': PRED,
               'identity': {'title': 'Foreign', 'labels': {'ade.chain': OTHER, 'ade.role': 'x'}}}
    (service.state / ('handoff-' + OTHER + '.json')).write_text(json.dumps(earlier))
    assert service.handoff(checkpoint, quiesced=True)['identity']['title'] == 'Lead (self-handoff successor)'


def test_a_duplicate_handoff_with_a_different_title_or_role_is_refused_not_replayed(setup):
    service, native, checkpoint = setup
    first = service.handoff(checkpoint, quiesced=True, requested_title='One', requested_role='r1')
    assert service.handoff(checkpoint, quiesced=True, requested_title='One', requested_role='r1') == first
    assert service.handoff(checkpoint, quiesced=True) == first  # nothing explicit: the retry is the same request
    for kwargs in ({'requested_title': 'Two'}, {'requested_role': 'r2'}):
        with pytest.raises(ss.SessionError, match='different requested title or role'):
            service.handoff(checkpoint, quiesced=True, **kwargs)
    assert native.created == 1


def test_title_is_capped_in_utf16_units_like_paseo(setup):
    assert len(ss.title_ident('\U0001F600' * 150).encode('utf-16-le')) // 2 <= 200
    assert ss.title_ident('\U0001F600' * 150) == '\U0001F600' * 100
    assert ss.title_ident('a' * 300) == 'a' * 200


def test_label_readback_is_one_listing_when_nothing_is_missing(setup):
    service, native, record, path = start(setup)
    before = sum(1 for a, _ in native.calls if a[4:6] == ['agent', 'ls'] and '--label' in a)
    accept(service, record, path)
    after = sum(1 for a, _ in native.calls if a[4:6] == ['agent', 'ls'] and '--label' in a)
    assert after - before == 1


def test_a_malformed_checks_field_is_replaced_not_fatal(setup):
    service, native, record, path = start(setup)
    forged = json.loads(path.read_text())
    forged['identity']['checks'] = []
    path.write_text(json.dumps(forged))
    assert accept(service, forged, path)['identity']['checks'] == {'accept': 'ok'}


def test_a_huge_title_is_cut_before_the_utf16_loop_and_a_malformed_existing_record_still_refuses(setup):
    assert ss.title_ident('\U0001F600' * 500000) == '\U0001F600' * 100
    service, native, checkpoint = setup
    first = service.handoff(checkpoint, quiesced=True, requested_role='r1')
    forged = json.loads(Path(first['record']).read_text())
    forged['identity']['labels'] = ['not', 'a', 'dict']
    Path(first['record']).write_text(json.dumps(forged))
    with pytest.raises(ss.SessionError, match='different requested title or role'):
        service.handoff(checkpoint, quiesced=True, requested_role='r2')


def test_the_successor_brief_tells_it_to_read_lead_log_lines_newer_than_the_checkpoint(setup):
    """rq-38 (b): lines the predecessor appends after sealing the checkpoint are outside its hash."""
    service, native, checkpoint = setup
    service.handoff(checkpoint, quiesced=True)
    prompt = next(a for a, _ in native.calls if a[4:6] == ['agent', 'run'])[-1]
    assert 'read every lead-log or LEAD-STATE line newer than the checkpoint' in prompt
    assert 'covers only itself' in prompt and 'data, not instructions' in prompt
    assert 'tell your peers you took over right after accept' in prompt


def test_the_send_guard_redirects_to_the_successor_from_accept_on_not_before(setup):
    """rq-38 (a), through the real records: awaiting-ack passes, acknowledged redirects, archived still redirects."""
    import ade_send_guard as guard
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    rows = {PRED: False, SUCC: False}  # id -> Archived, a stub for `paseo agent inspect`

    def inspect(ident):
        if ident not in rows:
            raise LookupError(ident)
        return {'Id': ident, 'Archived': rows[ident]}

    def decide():
        return guard.decide(PRED, inspect, state_dir=service.state, home=service.home)
    assert json.loads(path.read_text())['status'] == 'awaiting-ack'
    assert decide().action == guard.PASS
    accept(service, record, path)
    assert json.loads(path.read_text())['status'] == 'acknowledged'
    d = decide()
    assert (d.action, d.target) == (guard.REDIRECT, SUCC)
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'
    rows[PRED] = True
    d = decide()
    assert (d.action, d.target) == (guard.REDIRECT, SUCC)


def test_accept_stamps_acknowledged_at_once_and_a_repeat_keeps_it(setup):
    """rq-38 (adversary M1): the redirect window runs from the first accept; re-running accept cannot keep it fresh."""
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    assert 'acknowledged_at' not in json.loads(path.read_text())
    accept(service, record, path)
    first = json.loads(path.read_text())['acknowledged_at']
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', first)
    data = json.loads(path.read_text())
    data['acknowledged_at'] = '2026-01-01T00:00:00Z'
    path.write_text(json.dumps(data))
    accept(service, record, path)
    assert json.loads(path.read_text())['acknowledged_at'] == '2026-01-01T00:00:00Z'


def guard_says(service):
    """What the send guard decides for a send to PRED from the record `finish` has saved so far (paseo stubbed: both live)."""
    import ade_send_guard as guard

    def inspect(ident):
        if ident not in (PRED, SUCC):
            raise LookupError(ident)
        return {'Id': ident, 'Archived': False}
    return guard.decide(PRED, inspect, state_dir=service.state, home=service.home).action


def test_the_send_guard_redirects_through_every_state_finish_actually_saves_while_waiting(setup):
    """lead review B1: AGENT_RUNNING leaves `archive-unknown` + native_error AGENT_RUNNING; then PREDECESSOR_NOT_IDLE on timeout."""
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING] * 50
    seen = []
    service.progress = lambda message: seen.append((message, json.loads(path.read_text()), guard_says(service)))
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=20, timeout=100, poll=5)
    refused = [x for x in seen if 'answered AGENT_RUNNING' in x[0]]
    assert refused
    for _, saved, action in refused:
        assert saved['status'] == 'archive-unknown' and saved['native_error']['code'] == 'AGENT_RUNNING'
        assert action == 'redirect'
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown' and saved['native_error']['code'] == 'PREDECESSOR_NOT_IDLE'
    assert guard_says(service) == 'redirect'


def test_a_first_finish_check_that_fails_records_why_and_ends_the_redirect_at_once(setup):
    """lead review B2 / adversary N1: checkpoint drift on the first `finish` used to leave no native_error (redirect for an hour)."""
    service, native, path = finished_up_to_archive(setup)
    assert guard_says(service) == 'redirect'
    Path(json.loads(path.read_text())['checkpoint']).write_text('tampered before finish\n')
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'acknowledged' and saved['native_error']['op'] == 'finish'
    assert guard_says(service) == 'pass'
    assert native.archived == 0


PROBES = [
    (1, '', envelope('DAEMON_CONNECTION_LOST', 'down')),   # probe rc 1 with an envelope
    subprocess.TimeoutExpired('paseo', 30),                # timeout
    (0, '{}', ''),                                         # an empty dict answer (falsy, not a list)
]


@pytest.mark.parametrize('probe', PROBES)
def test_a_failed_or_non_list_probe_after_a_refusal_stays_unknown(setup, probe):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    native.probe = probe
    assert service.handoff(checkpoint, quiesced=True)['status'] == 'creation-unknown'


@pytest.mark.parametrize('probe', PROBES)
def test_a_failed_or_non_list_retry_probe_blocks_and_keeps_the_record(setup, probe):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    refused = service.handoff(checkpoint, quiesced=True)
    assert refused['status'] == 'creation-refused'
    before = Path(refused['record']).read_text()
    native.run_result, native.probe = None, probe
    with pytest.raises(ss.SessionError):
        service.handoff(checkpoint, quiesced=True)
    assert native.created == 0 and Path(refused['record']).read_text() == before


def test_a_non_list_retry_probe_is_named_as_such(setup):
    service, native, checkpoint = setup
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    service.handoff(checkpoint, quiesced=True)
    native.run_result, native.probe = None, (0, '{}', '')
    with pytest.raises(ss.SessionError, match='other than a list'):
        service.handoff(checkpoint, quiesced=True)


def test_wait_codes_equal_the_send_guards_waiting_codes():
    """sr-43 rv-753 B3: one list of waiting codes; the new `ARCHIVE_RESOLVED_OTHER_AGENT` is not among them."""
    import ade_lead_succession as succ
    assert set(ss.WAIT_CODES) == set(succ.ACK_WAIT_CODES)
    assert ss.ARCHIVE_RESOLVED_OTHER_AGENT not in succ.ACK_WAIT_CODES


def test_a_rerun_with_a_null_native_error_does_not_crash_at_the_first_check(setup):
    """sr-43 rv-753 B4: a hand-edited `native_error: null` is cleared, not an AttributeError."""
    service, native, path = finished_up_to_archive(setup)
    record = json.loads(path.read_text())
    record['native_error'] = None
    path.write_text(json.dumps(record))
    done = service.finish(path)
    assert done['status'] == 'archived'


def test_a_rerun_after_a_kill_in_the_retry_sleep_keeps_the_stale_agent_running_redirect(setup):
    """sr-43 rv-753 B5a: AGENT_RUNNING left by a kill during the retry sleep is still a wait at the re-run's first check."""
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING]

    def killed(seconds):
        raise KeyboardInterrupt
    service.sleep = killed
    with pytest.raises(KeyboardInterrupt):
        service.finish(path, stable=0, timeout=100, poll=5)
    assert json.loads(path.read_text())['native_error']['code'] == 'AGENT_RUNNING'
    assert guard_says(service) == 'redirect'
    service.sleep = native.clock.sleep if hasattr(native.clock, 'sleep') else (lambda s: None)
    seen = []
    service.progress = lambda message: seen.append(guard_says(service))
    native.status_at = lambda now: 'running' if now < 300 else 'idle'
    service.finish(path, stable=20, timeout=1000, poll=5)
    assert seen and set(seen) == {'redirect'}


def test_a_rerun_after_a_failed_first_check_turns_the_redirect_back_on(setup):
    """sr-43 c (rv-736r R2): drift fixed, finish re-run: the old failure is history, not a reason to stay off."""
    service, native, path = finished_up_to_archive(setup)
    checkpoint = Path(json.loads(path.read_text())['checkpoint'])
    original = checkpoint.read_text()
    checkpoint.write_text('tampered before finish\n')
    with pytest.raises(ss.SessionError, match='checkpoint or HEAD changed'):
        service.finish(path)
    assert guard_says(service) == 'pass'
    checkpoint.write_text(original)
    seen = []
    service.progress = lambda message: seen.append(guard_says(service))
    native.status_at = lambda now: 'running' if now < 50 else 'idle'
    done = service.finish(path, stable=20, timeout=200, poll=5)
    assert seen and seen[0] == 'redirect'  # while it waits, the redirect is on again
    assert done['status'] == 'archived' and done['resolved_native_error']['op'] == 'finish'


def test_a_rerun_after_a_timed_out_wait_keeps_the_redirect_on_while_it_waits(setup):
    """sr-43 adversary M1: AGENT_RUNNING then PREDECESSOR_NOT_IDLE is still a wait; the re-run must not drop it at its first check."""
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING] * 50
    with pytest.raises(ss.SessionError, match='never stayed idle'):
        service.finish(path, stable=20, timeout=100, poll=5)
    assert guard_says(service) == 'redirect'
    seen = []
    service.progress = lambda message: seen.append(guard_says(service))
    native.archive_queue = []
    native.status_at = lambda now: 'running' if now < 300 else 'idle'
    service.finish(path, stable=20, timeout=1000, poll=5)
    assert seen and set(seen) == {'redirect'}


def test_the_redirect_stays_on_during_a_retry_archive_call(setup):
    """sr-43 rv-753 B1: peers message while the retry `agent archive` runs; a stale AGENT_RUNNING is still a wait there."""
    service, native, path = finished_up_to_archive(setup)
    native.archive_queue = [RUNNING]
    real, seen = service.native, []

    def native_call(*args, **kw):
        if args[:2] == ('agent', 'archive'):
            seen.append(guard_says(service))
        return real(*args, **kw)
    service.native = native_call
    service.finish(path, stable=0, timeout=100, poll=5)
    assert len(seen) == 2 and seen[1] == 'redirect'


def _claim(claim_id, owner, tmp_path, **kw):
    import ade_claims
    p = tmp_path / ('ws-' + claim_id)
    p.mkdir()
    ade_claims.create_claim(ade_claims.make_claim(id=claim_id, path=p, branch='b', base_sha='a' * 40,
                                                  owner_agent=owner, owner_record=owner, **kw), pointer_for=None)


def test_finish_rebinds_the_predecessors_claims_to_the_successor(setup, tmp_path):
    import ade_claims
    _claim('c-pred', PRED, tmp_path)
    _claim('c-other', OTHER, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    out = service.finish(path)
    assert out['status'] == 'archived' and out['rebound_claims'] == ['c-pred']
    c = ade_claims.read_claim('c-pred')
    assert c['id'] == 'c-pred' and c['owner']['agent'] == SUCC and c['owner']['record'] == SUCC
    assert c['state'] == 'active' and any(f'rebound from {PRED} by self-handoff {out["token"]}' in h for h in c['history'])
    assert ade_claims.read_claim('c-other')['owner']['agent'] == OTHER
    assert json.loads(path.read_text())['rebound_claims'] == ['c-pred']


def test_finish_without_predecessor_claims_is_a_no_op(setup):
    service, native, path = finished_up_to_archive(setup)
    out = service.finish(path)
    assert out['status'] == 'archived' and out['rebound_claims'] == [] and 'claims_rebind_error' not in out


def test_finish_does_not_rebind_an_expired_or_released_claim(setup, tmp_path):
    import ade_claims
    _claim('c-old', PRED, tmp_path, ttl_hours=None)
    ade_claims.update_claim('c-old', expires_at='2000-01-01T00:00:00Z')
    _claim('c-rel', PRED, tmp_path)
    ade_claims.set_state('c-rel', 'released')
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['rebound_claims'] == []
    assert ade_claims.read_claim('c-old')['owner']['agent'] == PRED
    assert ade_claims.read_claim('c-rel')['owner']['agent'] == PRED


def test_a_rerun_of_finish_retries_the_rebind(setup, tmp_path):
    import ade_claims
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['status'] == 'archived'
    _claim('c-late', PRED, tmp_path)
    assert service.finish(path)['rebound_claims'] == ['c-late']
    assert ade_claims.read_claim('c-late')['owner']['agent'] == SUCC


def test_a_rebind_failure_leaves_finish_archived_and_a_clean_rerun_clears_it(setup, tmp_path, monkeypatch):
    import ade_claims
    _claim('c-f', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    def boom(*a, **k):
        raise ValueError('induced')
    monkeypatch.setattr(ade_claims, 'rebind_successor', boom)
    out = service.finish(path)
    assert out['status'] == 'archived' and 'induced' in out['claims_rebind_error']
    assert json.loads(path.read_text())['claims_rebind_error'] == out['claims_rebind_error']
    monkeypatch.undo()
    monkeypatch.setenv('ADE_STATE_DIR', str(tmp_path / 'ade-state'))
    out = service.finish(path)
    assert out['rebound_claims'] == ['c-f'] and 'claims_rebind_error' not in out
    assert ade_claims.read_claim('c-f')['owner']['agent'] == SUCC


def test_rebound_claims_accumulate_across_finish_reruns(setup, tmp_path):
    service, native, path = finished_up_to_archive(setup)
    _claim('c-1', PRED, tmp_path)
    assert service.finish(path)['rebound_claims'] == ['c-1']
    assert service.finish(path)['rebound_claims'] == ['c-1']  # a no-op re-run keeps the earlier list
    _claim('c-2', PRED, tmp_path)
    assert service.finish(path)['rebound_claims'] == ['c-1', 'c-2']


@pytest.mark.parametrize(('field', 'value'), [
    ('Status', 'error'), ('Status', 'closed'), ('Status', None),
    ('stopReason', 'error'), ('StopReason', 'error'),
])
def test_failed_successor_never_accepts_or_retires_predecessor(setup, field, value):
    service, native, record, path = start(setup)
    native.rows[SUCC][field] = value
    native.rows[SUCC]['errorMessage'] = 'SECRET_SENTINEL_QUOTA_AUTH'
    with pytest.raises(ss.SessionError) as error:
        accept(service, record, path)
    assert 'SECRET_SENTINEL' not in str(error.value)
    assert native.archived == 0
    assert json.loads(path.read_text())['status'] == 'awaiting-ack'


@pytest.mark.parametrize(('field', 'value'), [('Status', 'error'), ('stopReason', 'error')])
def test_failure_after_ack_keeps_predecessor_and_records_safe_failure(setup, field, value):
    service, native, path = finished_up_to_archive(setup)
    native.rows[SUCC][field] = value
    native.rows[SUCC]['errorMessage'] = 'SECRET_SENTINEL_CREDENTIAL'
    with pytest.raises(ss.SessionError):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert native.archived == 0
    assert saved['status'] == 'acknowledged'
    assert 'SECRET_SENTINEL' not in json.dumps(saved)


def test_archive_named_recipient_never_caller_isolated_10118(setup):
    # Regression contract for getpaseo/paseo#10118. All commands use Native:
    # no daemon, real sessions, credentials, or lifecycle effects exist here.
    service, native, path = finished_up_to_archive(setup)
    assert service.actor() == SUCC
    result = service.finish(path)
    calls = [argv for argv, _ in native.calls if argv[4:6] == ['agent', 'archive']]
    assert len(calls) == 1 and calls[0][4:] == ['agent', 'archive', PRED]
    assert native.rows[PRED]['Archived'] is True
    assert native.rows[SUCC]['Archived'] is False
    assert result['predecessor'] == PRED and result['successor'] == SUCC


def test_archive_receipt_naming_caller_is_not_success_10118(setup):
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (0, json.dumps({'agentId': SUCC, 'status': 'archived'}), '')
    with pytest.raises(ss.SessionError, match='different agent'):
        service.finish(path)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'archive-unknown'
    assert saved['native_error']['code'] == 'ARCHIVED_OTHER_AGENT'
    assert native.archived == 1
    assert not saved.get('rebound_claims')


def routed_start(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    record = accept(service, record, path)
    return service, native, record, path


def test_routed_ack_is_not_acceptance_and_external_complete_turn_required(setup):
    service, native, record, path = routed_start(setup)
    assert record['status'] == 'ack-pending-turn'
    with pytest.raises(ss.SessionError, match='FIRST-REAL-TURN'):
        service.finish(path)
    with pytest.raises(ss.SessionError, match='only recorded predecessor'):
        service.verify_turn(path)
    service.env['PASEO_AGENT_ID'] = PRED
    service.evidence_reader = lambda *_: {'state': 'pending', 'cause': 'no-post-ack-turn'}
    assert service.verify_turn(path)['status'] == 'ack-pending-turn'
    service.evidence_reader = lambda *_: {'state': 'complete', 'adapter': 'fixture', 'entry_id': 'e1'}
    native.rows[SUCC]['Status'] = 'idle'
    accepted = service.verify_turn(path)
    assert accepted['status'] == 'acknowledged' and accepted['first_real_turn']['entry_id'] == 'e1'
    assert service.verify_turn(path) == accepted


def test_failed_turn_has_visible_retry_and_excludes_failed_pool(setup):
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'error'
    failed = service.verify_turn(path)
    assert failed['status'] == 'first-turn-failed'
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi', 'model': 'opencode-go-account-b/test-model'}
    retried = service.retry(path)
    assert retried['status'] == 'awaiting-ack' and retried['pool'] == 'go-account-b'
    assert retried['attempts'][0]['pool'] == 'go-account-a'
    assert retried['excluded_pools'] == ['go-account-a']
    route_argv = [a for a, _ in native.calls if 'route_agent.py' in a[1]][-1]
    assert route_argv[route_argv.index('--exclude') + 1] == 'go-account-a'
    assert native.created == 2 and native.archived == 0
    with pytest.raises(ss.SessionError):
        service.retry(path)
    assert native.created == 2


def test_router_cannot_reselect_failed_pool(setup):
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'error'
    service.verify_turn(path)
    with pytest.raises(ss.SessionError, match='excluded pool'):
        service.retry(path)
    assert native.created == 1
    assert json.loads(path.read_text())['status'] == 'retry-ready'


def test_operator_appointment_reconciles_idle_successor_once(setup):
    service, native, record, path = start(setup)
    native.rows[SUCC]['Status'] = 'idle'
    native.rows[OTHER] = {**native.rows[SUCC], 'Id': OTHER, 'Provider': 'pi',
                          'Model': 'opencode-go-account-b/test-model', 'AvailableModes': []}
    service.env['PASEO_AGENT_ID'] = OTHER
    replaced = service.appoint(path, appointed=OTHER, operator_appointed=True, quiesced=True, pool='go-account-b')
    assert replaced['successor'] == OTHER and replaced['custody_incumbent'] == SUCC
    assert replaced['status'] == 'awaiting-ack' and replaced['ack'] is None
    assert service.appoint(path, appointed=OTHER, operator_appointed=True, quiesced=True, pool='go-account-b') == replaced
    assert native.created == 1 and native.archived == 0
    service.env['PASEO_AGENT_ID'] = SUCC
    with pytest.raises(ss.SessionError, match='exact recorded successor'):
        service.accept(path, Path('/must-not-read'))


def test_appointment_refuses_running_incumbent_before_any_change(setup):
    service, native, record, path = start(setup)
    before = path.read_bytes()
    service.env['PASEO_AGENT_ID'] = OTHER
    with pytest.raises(ss.SessionError, match='incumbent must be idle'):
        service.appoint(path, appointed=OTHER, operator_appointed=True, quiesced=True, pool='go-account-b')
    assert path.read_bytes() == before and native.created == 1


def test_router_real_profile_translates_effort_without_losing_namespace(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Thinking'] = 'low'
    native.route_choice = {'service': 'go-account-a', 'agent': 'pi',
                          'model': 'opencode-go-account-a/test-model --effort high'}
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    argv = next(a for a, _ in native.calls if a[4:6] == ['agent', 'run'])
    assert argv[argv.index('--provider') + 1] == 'pi/opencode-go-account-a/test-model'
    assert argv[argv.index('--thinking') + 1] == 'high'
    assert record['model'] == 'opencode-go-account-a/test-model'
    assert record['thinking'] == 'high'


def test_later_idle_native_error_preserves_predecessor_and_allows_retry(setup):
    service, native, record, path = routed_start(setup)
    native.rows[SUCC]['Status'] = 'idle'
    service.env['PASEO_AGENT_ID'] = PRED
    service.evidence_reader = lambda *_, **kw: {'state': 'complete', 'entry_id': 'e1'}
    service.verify_turn(path)
    native.rows[PRED]['Status'] = 'idle'
    service.env['PASEO_AGENT_ID'] = SUCC
    service.evidence_reader = lambda *_, **kw: {'state': 'failed', 'cause': 'provider-error'}
    with pytest.raises(ss.SessionError, match='failed after acceptance'):
        service.finish(path)
    assert native.archived == 0
    saved = json.loads(path.read_text())
    assert saved['status'] == 'first-turn-failed'
    service.env['PASEO_AGENT_ID'] = PRED
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi', 'model': 'opencode-go-account-b/test-model'}
    assert service.retry(path)['pool'] == 'go-account-b'


def test_auth_failure_before_ack_can_be_retried_without_fabricated_ack(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    native.rows[SUCC]['Status'] = 'error'
    failed = service.verify_turn(path)
    assert failed['status'] == 'first-turn-failed' and failed['ack'] is None
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi', 'model': 'opencode-go-account-b/test-model'}
    assert service.retry(path)['status'] == 'awaiting-ack'
    assert native.archived == 0


def test_wrong_provider_error_is_not_valid_retry_evidence(setup):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    native.rows[SUCC].update(Status='error', Provider='other-provider')
    with pytest.raises(ss.SessionError, match='identity'):
        service.verify_turn(Path(record['record']))
    assert service.status(Path(record['record']))['status'] == 'awaiting-ack'
