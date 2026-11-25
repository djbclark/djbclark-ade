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
        self.rename_unarchives = False  # an `agent update` of the predecessor flips it back to unarchived
        self.rename_ignored = False     # an `agent update` of the predecessor answers ok but changes nothing
        self.providers = None           # optional full `provider ls` list for cross-provider tests
        self.successor_modes = None     # optional `AvailableModes` list assigned to SUCC on `agent run`
        self.route_plan_fn = None       # optional callable(argv, kwargs) -> CompletedProcess for route_agent.py
        self.launchctl_calls = []       # argv lists passed to launchctl
        self.launchctl_result = None    # optional callable(argv) or (rc, out, err) for launchctl

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if argv and argv[0] == 'launchctl':
            self.launchctl_calls.append(list(argv))
            if callable(self.launchctl_result):
                return self.launchctl_result(argv)
            if self.launchctl_result is not None:
                return subprocess.CompletedProcess(argv, *self.launchctl_result)
            return subprocess.CompletedProcess(argv, 0, '', '')
        if len(argv) > 1 and 'route_agent.py' in argv[1]:
            if self.route_plan_fn is not None:
                return self.route_plan_fn(argv, kwargs)
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
            data = (copy.deepcopy(self.providers) if self.providers is not None else
                    [{'provider': self.rows[PRED]['Provider'], 'enabled': 'Enabled', 'status': 'available', 'modes': 'display labels only'}])
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
            if '--thinking' in args:
                self.rows[SUCC]['Thinking'] = args[args.index('--thinking') + 1]
            if self.successor_modes is not None:
                self.rows[SUCC]['AvailableModes'] = copy.deepcopy(self.successor_modes)
            elif provider == 'pi':
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
            if args[2] == PRED and self.rename_unarchives:
                self.rows[PRED]['Archived'] = False
            for i, a in enumerate(args):
                if a.startswith('--name=') and not (args[2] == PRED and self.rename_ignored):
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


@pytest.fixture(autouse=True)
def isolated_supervisor(tmp_path, monkeypatch):
    """finish repoints the supervisor's lead file: never the live one."""
    monkeypatch.setenv('ADE_SUPERVISOR_STATE_DIR', str(tmp_path / 'supervisor'))


@pytest.fixture(autouse=True)
def isolated_net_resume_plist(tmp_path, monkeypatch):
    """finish repoints the legacy net-resume plist: never the live one."""
    monkeypatch.setenv('ADE_NET_RESUME_PLIST', str(tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'))


@pytest.fixture(autouse=True)
def isolated_quota(tmp_path, monkeypatch):
    """handoff checks quota headroom: never read live aiuse/paseo in offline tests."""
    monkeypatch.setenv('ROUTE_AGENT_AIUSE', 'off')
    monkeypatch.setenv('ROUTE_AGENT_PASEO', 'off')
    monkeypatch.setenv('AIUSE_SNAPSHOT', str(tmp_path / 'no-aiuse-snapshot.json'))
    monkeypatch.delenv('ROUTE_AGENT_AIUSE_JSON', raising=False)
    monkeypatch.delenv('ROUTE_AGENT_PASEO_USAGE_JSON', raising=False)


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


# --- an errored predecessor is retired without the idle wait (operator ruling 2026-11-21) ---------------

def test_errored_predecessor_is_archived_without_the_idle_wait(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Status'] = 'error'  # out of quota: it runs no turn and never becomes idle
    saw = []
    service.progress = saw.append
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1
    assert native.clock.now < ss.FINISH_STABLE and not native.clock.sleeps  # no stable window was waited out
    assert any('status error' in m for m in saw)
    only_reads_and_archive(native)


def test_errored_predecessor_with_a_permission_wait_is_still_archived(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Status'] = 'error'
    native.rows[PRED]['PendingPermissions'] = [{'id': 'p'}]  # left over from the turn that failed
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 1


def test_errored_predecessor_still_needs_the_successor_ack(setup):
    service, native, path = finished_up_to_archive(setup)
    native.rows[PRED]['Status'] = 'error'
    record = json.loads(path.read_text())
    record['ack'] = None
    path.write_text(json.dumps(record))
    with pytest.raises(ss.SessionError, match='acknowledgement required'):
        service.finish(path)
    assert native.archived == 0


def test_errored_predecessor_woken_before_archive_goes_back_to_the_idle_wait(setup):
    service, native, path = finished_up_to_archive(setup)
    # error at first, a peer message wakes it (archive refused AGENT_RUNNING), then it settles idle
    native.status_at = lambda now: 'error' if now < 1 else ('running' if now < 30 else 'idle')
    native.archive_queue = [RUNNING]
    assert service.finish(path)['status'] == 'archived'
    assert native.archived == 2
    assert native.clock.now >= 30 + 45  # the second attempt waited for a full stable idle window


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
    retired = f'RETIRED Lead tendcf (cfengine) (-> {SUCC})'
    assert native.updates == [[PRED, '--name=' + retired]] and native.rows[SUCC]['Name'] == 'Lead tendcf (cfengine)'
    assert native.rows[PRED]['Name'] == retired and native.rows[PRED]['Archived'] is True
    assert finished['identity']['checks']['retire_rename'] == 'ok'
    assert finished['identity']['retire_rename'] == {'reason': 'renamed', 'name': retired}
    assert json.loads(path.read_text()) == finished


def test_predecessor_without_a_role_label_still_gets_predecessor_and_chain_labels(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Lead plain'
    record = service.handoff(checkpoint, quiesced=True)
    assert run_labels(run_call(native))[1:] == ['ade.chain=' + PRED, 'ade.predecessor=' + PRED]
    assert record['identity']['labels'] == {'ade.chain': PRED, 'ade.predecessor': PRED}
    assert record['identity']['role_source'] is None
    assert settle(service, native, record, Path(record['record']))['identity']['checks'] == {
        'create': 'requested', 'accept': 'ok', 'finish': 'ok', 'retire_rename': 'ok'}


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
    assert finished['identity']['checks'] == {'create': 'requested', 'accept': 'ok', 'finish': 'repaired',
                                              'retire_rename': 'skipped'}  # the predecessor had no name to clash with
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
    if stage == 'finish':
        assert done['identity']['checks']['retire_rename'] == 'skipped'
        assert done['identity']['retire_rename'] == {'reason': 'malformed-identity'}
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


def _plugin_rebinds_on_archive(service, claim_id, to_agent):
    """Stand in for the ade-claim plugin: the moment Paseo archives the predecessor, an agent created in the workspace
    takes the predecessor's claim (agent.create.after -> rebind-owner)."""
    import ade_claims
    real = service.native

    def native_call(*args, **kw):
        out = real(*args, **kw)
        if args[:2] == ('agent', 'archive'):
            ade_claims.rebind_owner(claim_id, from_agent=PRED, to_agent=to_agent, owner_state='archived')
        return out
    service.native = native_call


def test_m2_a_claim_the_plugin_rebound_to_someone_else_is_reported_not_lost_or_taken(setup, tmp_path):
    """M2: between the archive and `rebind_claims` the plugin handed c-race to another new agent. finish neither takes it back
    (it is live) nor drops it silently: it records it, with the owner, in claims_not_rebound."""
    import ade_claims
    _claim('c-race', PRED, tmp_path)
    _claim('c-calm', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    messages = []
    service.progress = messages.append
    _plugin_rebinds_on_archive(service, 'c-race', 'agent-x')
    out = service.finish(path)
    assert out['status'] == 'archived' and out['rebound_claims'] == ['c-calm']
    assert out['predecessor_claims'] == ['c-calm', 'c-race']
    assert out['claims_not_rebound'] == [{'id': 'c-race', 'fate': 'other', 'owner': 'agent-x'}]
    assert ade_claims.read_claim('c-race')['owner']['agent'] == 'agent-x'      # not stolen back
    assert ade_claims.read_claim('c-calm')['owner']['agent'] == SUCC
    assert any('c-race' in m and 'agent-x' in m for m in messages)
    assert json.loads(path.read_text())['claims_not_rebound'] == out['claims_not_rebound']


def test_m2_a_claim_already_the_successors_is_not_reported_or_rebound_twice(setup, tmp_path):
    """The plugin (or an earlier finish run) already gave the claim to the successor: it is accounted for, not an error."""
    import ade_claims
    _claim('c-mine', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    _plugin_rebinds_on_archive(service, 'c-mine', SUCC)
    out = service.finish(path)
    assert out['rebound_claims'] == [] and 'claims_not_rebound' not in out
    c = ade_claims.read_claim('c-mine')
    assert c['owner']['agent'] == SUCC and sum('rebound from' in h for h in c['history']) == 1


def test_m2_a_claim_released_before_the_archive_is_a_normal_ending(setup, tmp_path):
    _claim('c-rel2', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    import ade_claims
    real = service.native

    def native_call(*args, **kw):
        if args[:2] == ('agent', 'archive'):
            ade_claims.set_state('c-rel2', 'released')
        return real(*args, **kw)
    service.native = native_call
    out = service.finish(path)
    assert out['rebound_claims'] == [] and 'claims_not_rebound' not in out


def test_m2_a_rerun_keeps_the_report(setup, tmp_path):
    _claim('c-race', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    _plugin_rebinds_on_archive(service, 'c-race', 'agent-x')
    first = service.finish(path)['claims_not_rebound']
    assert service.finish(path)['claims_not_rebound'] == first   # archived re-run: same snapshot, same report


def test_m2_a_rerun_after_archive_unknown_still_reports_the_claim_the_plugin_gave_away(setup, tmp_path):
    """Adversary M-1: the first finish archives but fails to read the receipt; the plugin hands c-race to agent-x; the re-run's
    fresh snapshot no longer lists it, yet it is reported (snapshots merge, and the claim's history names the rebind)."""
    import ade_claims
    _claim('c-race', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    real = service.native
    state = {'n': 0}

    def native_call(*args, **kw):
        out = real(*args, **kw)
        if args[:2] == ('agent', 'archive'):
            ade_claims.rebind_owner('c-race', from_agent=PRED, to_agent='agent-x', owner_state='archived')
            state['n'] += 1
            if state['n'] == 1:
                raise ss.SessionError('archive outcome unknown')
        return out
    service.native = native_call
    with pytest.raises(ss.SessionError, match='outcome unknown'):
        service.finish(path, stable=0, timeout=100, poll=5)
    out = service.finish(path, stable=0, timeout=100, poll=5)
    assert out['status'] == 'archived'
    assert out['claims_not_rebound'] == [{'id': 'c-race', 'fate': 'other', 'owner': 'agent-x'}]


def test_m2_an_archive_done_before_finish_is_covered_by_the_claim_history(setup, tmp_path):
    """No snapshot exists (the predecessor was archived by someone else first); the claim's history still names the rebind."""
    import ade_claims
    _claim('c-race', PRED, tmp_path)
    service, native, path = finished_up_to_archive(setup)
    ade_claims.rebind_owner('c-race', from_agent=PRED, to_agent='agent-x', owner_state='archived')
    native.rows[PRED]['Archived'] = True
    out = service.finish(path, stable=0, timeout=100, poll=5)
    assert out['claims_not_rebound'] == [{'id': 'c-race', 'fate': 'other', 'owner': 'agent-x'}]


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
    service.evidence_reader = lambda *_, **kw: {'state': 'complete', 'adapter': 'fixture', 'entry_id': 'e1'}
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


def test_completed_custody_continues_chain_and_rebinds_claim_once(setup, tmp_path):
    import ade_claims
    service, native, original_path = finished_up_to_archive(setup)
    original = service.finish(original_path)
    _claim('c-incumbent', SUCC, tmp_path)
    native.rows[SUCC]['Status'] = 'idle'
    native.rows[OTHER] = {**native.rows[SUCC], 'Id': OTHER, 'Provider': 'pi',
                          'Model': 'opencode-go-account-b/test-model', 'AvailableModes': []}
    service.env['PASEO_AGENT_ID'] = OTHER
    appointed = service.appoint(original_path, appointed=OTHER, operator_appointed=True,
                                 quiesced=True, pool='go-account-b')
    path = Path(appointed['record'])
    assert path != original_path and appointed['predecessor'] == SUCC
    assert appointed['identity']['labels']['ade.predecessor'] == SUCC
    assert json.loads(original_path.read_text())['successor'] == SUCC
    assert ade_claims.read_claim('c-incumbent')['owner']['agent'] == SUCC
    # Recover a kill after continuation save but before parent appointment marker.
    old = json.loads(original_path.read_text()); old.pop('appointment')
    original_path.write_text(json.dumps(old))
    assert service.appoint(original_path, appointed=OTHER, operator_appointed=True,
                           quiesced=True, pool='go-account-b')['token'] == appointed['token']
    ack = {k: appointed[k] for k in ('token', 'checkpoint_sha256', 'head')}
    ack['next_action'] = 'read checkpoint, then run assigned work'
    ack_path = service.state / 'appointed-ack.json'; ack_path.write_text(json.dumps(ack))
    assert service.accept(path, ack_path)['status'] == 'ack-pending-turn'
    service.evidence_reader = lambda *_, **kw: {'state': 'complete', 'entry_id': 'e1'}
    service.env['PASEO_AGENT_ID'] = SUCC
    assert service.verify_turn(path)['status'] == 'acknowledged'
    assert ade_claims.read_claim('c-incumbent')['owner']['agent'] == SUCC
    service.env['PASEO_AGENT_ID'] = OTHER
    archive_calls = []
    def runner(argv, **kwargs):
        if argv[4:6] == ['agent', 'archive']:
            assert argv[6:] == [SUCC]
            archive_calls.append(SUCC)
            native.rows[SUCC]['Archived'] = True
            return subprocess.CompletedProcess(argv, 0, json.dumps({'agentId': SUCC}), '')
        return native(argv, **kwargs)
    service.runner = runner
    finished = service.finish(path)
    assert finished['rebound_claims'] == ['c-incumbent']
    moved = ade_claims.read_claim('c-incumbent')
    assert moved['owner']['agent'] == OTHER
    service.finish(path)
    assert ade_claims.read_claim('c-incumbent')['history'] == moved['history']
    assert archive_calls == [SUCC]
    assert native.rows[OTHER]['Archived'] is False


def test_predecessor_can_classify_failure_after_accept_without_successor_action(setup):
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'idle'
    service.evidence_reader = lambda *_, **kw: {'state': 'complete', 'entry_id': 'e1'}
    assert service.verify_turn(path)['status'] == 'acknowledged'
    native.rows[SUCC]['Status'] = 'error'
    assert service.verify_turn(path)['status'] == 'first-turn-failed'
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi', 'model': 'opencode-go-account-b/test-model'}
    assert service.retry(path)['pool'] == 'go-account-b'
    assert native.archived == 0


@pytest.mark.parametrize('enrolled', [PRED, SUCC, OTHER])
def test_legacy_appointment_cannot_bypass_enrolled_retirement_gate(setup, monkeypatch, enrolled):
    from types import SimpleNamespace
    service, native, record, path = start(setup)
    service.env['PASEO_AGENT_ID'] = OTHER
    before, calls = path.read_bytes(), len(native.calls)
    monkeypatch.setattr(ss, '_coord', lambda: SimpleNamespace(role_for=lambda agent: 'pilot' if agent == enrolled else None))
    with pytest.raises(ss.SessionError, match='enrolled appointment blocked'):
        service.appoint(path, appointed=OTHER, operator_appointed=True, quiesced=True, pool='go-account-b')
    assert path.read_bytes() == before
    assert len(native.calls) == calls
    assert native.created == 1 and native.archived == 0


def write_routed_transcript(service, record, stop_reason):
    """Native Pi evidence, including persistence identity; no injected reader."""
    transcript = (service.state / 'native-turn.jsonl').resolve()
    header = {'type': 'session', 'version': 3, 'id': 'native-session', 'cwd': record['cwd']}
    terminal = {'type': 'message', 'id': 'e1', 'parentId': None,
                'timestamp': '2026-11-19T12:00:01Z',
                'message': {'role': 'assistant', 'stopReason': stop_reason,
                            'usage': {'output': 12},
                            'content': [{'type': 'text', 'text': 'checkpoint read'}]}}
    transcript.write_text('\n'.join(json.dumps(x) for x in (header, terminal)) + '\n')
    key = record['cwd'].strip('/').replace('/', '-') or 'root'
    stored = service.home / 'agents' / key / (record['successor'] + '.json')
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(json.dumps({'id': record['successor'], 'cwd': record['cwd'],
        'provider': 'pi', 'config': {'model': record['model']},
        'persistence': {'provider': 'pi', 'sessionId': 'native-session',
                        'nativeHandle': str(transcript)}}))
    return transcript


@pytest.mark.parametrize('stop_reason', ['error', 'aborted'])
def test_pre_ack_idle_transcript_failure_allows_retry(setup, stop_reason):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    native.rows[SUCC]['Status'] = 'idle'
    write_routed_transcript(service, record, stop_reason)
    failed = service.verify_turn(path)
    assert failed['status'] == 'first-turn-failed' and failed['ack'] is None
    assert failed['first_turn_failure'] == {'state': 'failed', 'cause': 'provider-' + stop_reason}
    assert json.loads(path.read_text()) == failed
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi',
                           'model': 'opencode-go-account-b/test-model'}
    retried = service.retry(path)
    assert retried['pool'] == 'go-account-b' and retried['status'] == 'awaiting-ack'
    assert retried['attempts'][0]['first_turn_failure'] == failed['first_turn_failure']
    assert retried['excluded_pools'] == ['go-account-a']
    assert native.created == 2 and native.archived == 0


def test_pre_ack_successful_transcript_still_requires_real_ack(setup):
    import datetime
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    native.rows[SUCC]['Status'] = 'idle'
    transcript = write_routed_transcript(service, record, 'stop')
    pending = service.verify_turn(path)
    assert pending['status'] == 'awaiting-ack' and pending['ack'] is None
    assert 'first_real_turn' not in pending
    with pytest.raises(ss.SessionError):
        service.retry(path)
    with pytest.raises(ss.SessionError):
        service.finish(path)
    acknowledged = accept(service, pending, path)
    assert acknowledged['status'] == 'ack-pending-turn'
    # Append a real terminal after the actual ack timestamp.
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    later = copy.deepcopy(rows[-1])
    later.update(id='e2', parentId='e1',
                 timestamp=(datetime.datetime.fromisoformat(acknowledged['ack_observed_at'])
                            + datetime.timedelta(seconds=1)).isoformat())
    transcript.write_text('\n'.join(json.dumps(x) for x in [*rows, later]) + '\n')
    service.env['PASEO_AGENT_ID'] = PRED
    assert service.verify_turn(path)['status'] == 'acknowledged'
    assert native.created == 1 and native.archived == 0


@pytest.mark.parametrize('evidence', [
    {'state': 'complete'}, {'state': 'pending', 'cause': 'unknown'}, {'state': 'unknown'},
])
def test_pre_ack_non_failure_evidence_never_acknowledges(setup, evidence):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    native.rows[SUCC]['Status'] = 'idle'
    service.evidence_reader = lambda *_, **kw: evidence
    if evidence['state'] == 'unknown':
        with pytest.raises(ss.SessionError, match='invalid first-turn'):
            service.verify_turn(path)
    else:
        assert service.verify_turn(path)['status'] == 'awaiting-ack'
    saved = json.loads(path.read_text())
    assert saved['ack'] is None and 'first_real_turn' not in saved
    assert native.archived == 0


def test_retry_creation_refusal_preserves_history_on_next_handoff(setup):
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'error'
    service.verify_turn(path)
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi',
                           'model': 'opencode-go-account-b/test-model'}
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    native.labelled = []
    refused = service.retry(path)
    assert refused['status'] == 'creation-refused'
    assert refused['attempts'][0]['pool'] == 'go-account-a'
    assert refused['excluded_pools'] == ['go-account-a']
    native.labelled = [{'id': SUCC}]
    before = path.read_bytes()
    with pytest.raises(ss.SessionError, match='no create replayed'):
        service.handoff(Path(refused['checkpoint']), quiesced=True)
    assert path.read_bytes() == before
    native.labelled = []
    native.run_result = None
    # No route kind supplied: recovery must preserve the original kind itself.
    retried = service.handoff(Path(refused['checkpoint']), quiesced=True)
    assert retried['status'] == 'awaiting-ack' and retried['pool'] == 'go-account-b'
    for key in ('attempts', 'excluded_pools', 'route_kind'):
        assert retried[key] == refused[key]
    assert retried['refused_before'] == refused['native_error']
    route_argv = [a for a, _ in native.calls if 'route_agent.py' in a[1]][-1]
    assert route_argv[route_argv.index('--exclude') + 1] == 'go-account-a'
    assert route_argv[route_argv.index('--kinds') + 1] == 'judgment'
    assert native.created == 2 and native.archived == 0


@pytest.mark.parametrize('tail_kind', ['recovered', 'parent', 'timestamp', 'message', 'entry', 'missing-type', 'unknown-type'])
def test_pre_ack_historical_error_does_not_authorize_retry(setup, tail_kind):
    service, native, checkpoint = setup
    record = service.handoff(checkpoint, quiesced=True, route_kind='judgment')
    path = Path(record['record'])
    native.rows[SUCC]['Status'] = 'idle'
    transcript = write_routed_transcript(service, record, 'error')
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    tail = copy.deepcopy(rows[-1])
    tail.update(id='e2', parentId='e1', timestamp='2026-11-19T12:00:02Z')
    tail['message']['stopReason'] = 'stop'
    expected = 'acknowledgement-required'
    if tail_kind == 'parent':
        tail['parentId'] = 'unrelated'
        expected = 'branched or malformed native transcript unsupported'
    elif tail_kind == 'timestamp':
        tail['timestamp'] = 'not-a-time'
        expected = 'invalid native timestamp'
    elif tail_kind == 'message':
        tail['message'] = []
        expected = 'malformed native message'
    elif tail_kind in ('missing-type', 'unknown-type'):
        if tail_kind == 'missing-type':
            tail.pop('type')
        else:
            tail['type'] = 'unknown-schema'
        expected = 'unsupported native entry type'
    elif tail_kind == 'entry':
        tail = []
        expected = 'malformed native entry'
    transcript.write_text('\n'.join(json.dumps(x) for x in [*rows, tail]) + '\n')
    pending = service.verify_turn(path)
    assert pending['status'] == 'awaiting-ack' and pending['ack'] is None
    assert pending['first_turn_pending'] == expected
    assert 'first_turn_failure' not in pending and 'first_real_turn' not in pending
    before = path.read_bytes()
    calls_before = len(native.calls)
    with pytest.raises(ss.SessionError, match='only a routed failed first turn'):
        service.retry(path)
    assert path.read_bytes() == before
    assert len(native.calls) == calls_before
    assert pending['excluded_pools'] == [] and pending['attempts'] == []
    assert native.created == 1 and native.archived == 0


def test_post_ack_timestamp_cutoff_cannot_resurrect_historical_failure(setup):
    import datetime
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'idle'
    transcript = write_routed_transcript(service, record, 'error')
    rows = [json.loads(line) for line in transcript.read_text().splitlines()]
    ack_time = datetime.datetime.fromisoformat(record['ack_observed_at'])
    rows[-1]['timestamp'] = (ack_time + datetime.timedelta(seconds=1)).isoformat()
    recovered = copy.deepcopy(rows[-1])
    recovered.update(id='e2', parentId='e1',
                     timestamp=(ack_time - datetime.timedelta(seconds=1)).isoformat())
    recovered['message']['stopReason'] = 'stop'
    transcript.write_text('\n'.join(json.dumps(x) for x in [*rows, recovered]) + '\n')
    pending = service.verify_turn(path)
    assert pending['status'] == 'ack-pending-turn'
    assert pending['first_turn_pending'] == 'non-monotonic native timestamps'
    assert 'first_turn_failure' not in pending and 'first_real_turn' not in pending
    before = path.read_bytes()
    calls_before = len(native.calls)
    with pytest.raises(ss.SessionError, match='only a routed failed first turn'):
        service.retry(path)
    assert path.read_bytes() == before and len(native.calls) == calls_before
    assert pending['attempts'] == [] and pending['excluded_pools'] == []
    assert native.created == 1 and native.archived == 0


def _lead_file(tmp_path, text):
    d = tmp_path / 'supervisor'
    d.mkdir(exist_ok=True)
    f = d / 'lead'
    if text is not None:
        f.write_text(text)
        f.chmod(0o644)
    return f


def test_finish_repoints_the_supervisor_lead_file_to_the_successor(setup, tmp_path):
    lead = _lead_file(tmp_path, PRED + '\n')
    service, native, path = finished_up_to_archive(setup)
    out = service.finish(path)
    assert out['status'] == 'archived' and out['supervisor_lead'] == 'repointed' and 'supervisor_lead_error' not in out
    assert lead.read_text() == SUCC + '\n' and (lead.stat().st_mode & 0o777) == 0o644
    assert [p.name for p in lead.parent.iterdir()] == ['lead']  # no temp file left behind
    assert json.loads(path.read_text())['supervisor_lead'] == 'repointed'
    again = service.finish(path)  # a re-run keeps the outcome and the file
    assert again['supervisor_lead'] == 'repointed' and lead.read_text() == SUCC + '\n'


def test_finish_leaves_another_chains_lead_alone(setup, tmp_path):
    lead = _lead_file(tmp_path, OTHER + '\n')
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['supervisor_lead'] == 'unchanged-not-predecessor'
    assert lead.read_text() == OTHER + '\n'


def test_finish_without_a_supervisor_lead_file_creates_none(setup, tmp_path):
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['supervisor_lead'] == 'absent'
    assert not (tmp_path / 'supervisor' / 'lead').exists()


def test_finish_does_not_follow_a_symlinked_lead_file(setup, tmp_path):
    real = tmp_path / 'elsewhere'
    real.write_text(PRED + '\n')
    (tmp_path / 'supervisor').mkdir()
    (tmp_path / 'supervisor' / 'lead').symlink_to(real)
    service, native, path = finished_up_to_archive(setup)
    assert service.finish(path)['supervisor_lead'] == 'unchanged-not-regular'
    assert real.read_text() == PRED + '\n' and (tmp_path / 'supervisor' / 'lead').is_symlink()


def test_a_failed_archive_never_touches_the_supervisor_lead_file(setup, tmp_path):
    lead = _lead_file(tmp_path, PRED + '\n')
    service, native, path = finished_up_to_archive(setup)
    native.archive_result = (1, '', envelope('ARCHIVE_FAILED', 'agent is busy'))
    with pytest.raises(ss.NativeError):
        service.finish(path)
    assert lead.read_text() == PRED + '\n' and 'supervisor_lead' not in json.loads(path.read_text())


def test_a_write_failure_is_recorded_and_a_rerun_retries_it(setup, tmp_path, monkeypatch):
    lead = _lead_file(tmp_path, PRED + '\n')
    service, native, path = finished_up_to_archive(setup)
    real = ss.write_atomic

    def failing(file, data, mode=None):  # the record saves go through write_atomic too: fail only the lead file
        if Path(file).name == 'lead':
            raise OSError('disk full')
        return real(file, data, mode)
    monkeypatch.setattr(ss, 'write_atomic', failing)
    out = service.finish(path)
    assert out['status'] == 'archived' and out['supervisor_lead'] == 'error' and 'disk full' in out['supervisor_lead_error']
    assert lead.read_text() == PRED + '\n'
    monkeypatch.setattr(ss, 'write_atomic', real)
    out = service.finish(path)
    assert out['supervisor_lead'] == 'repointed' and 'supervisor_lead_error' not in out and lead.read_text() == SUCC + '\n'


# --- 2026-11-22: the retired predecessor is told apart from the live lead --------------------------------------------

def named_chain(setup, name='fork-release-alerts'):
    """handoff from a predecessor called `name`: the successor inherits it (title_source predecessor-name)."""
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = name
    record = service.handoff(checkpoint, quiesced=True)
    assert record['identity']['title'] == name and record['identity']['title_source'] == 'predecessor-name'
    return service, native, record, Path(record['record'])


def test_finish_renames_the_archived_predecessor_so_the_live_lead_is_the_only_one_with_the_name(setup):
    service, native, record, path = named_chain(setup)
    finished = settle(service, native, record, path)
    retired = f'RETIRED fork-release-alerts (-> {SUCC})'
    assert native.rows[PRED]['Name'] == retired and native.rows[SUCC]['Name'] == 'fork-release-alerts'
    assert native.rows[PRED]['Archived'] is True  # the rename must never revive it
    verbs = [tuple(a[4:6]) + ((a[6],) if len(a) > 6 else ()) for a, _ in native.calls if a[:1] == ['paseo']]
    assert verbs.index(('agent', 'archive', PRED)) < verbs.index(('agent', 'update', PRED))  # after the archive, never before
    assert finished['identity']['checks']['retire_rename'] == 'ok'
    assert finished['identity']['retire_rename'] == {'reason': 'renamed', 'name': retired}
    assert json.loads(path.read_text()) == finished
    again = service.finish(path)  # a re-run does not rename twice
    assert again['identity']['checks']['retire_rename'] == 'ok' and len(native.updates) == 1


def test_a_long_name_is_cut_never_the_successor_suffix(setup):
    service, native, record, path = named_chain(setup, name='\U0001F600' * 97 + ' tail')
    settle(service, native, record, path)
    new = native.rows[PRED]['Name']
    assert new.endswith(f' (-> {SUCC})') and new.startswith('RETIRED ')
    assert ss.utf16_len(new) <= 200
    assert new == ss.retired_title(record['identity']['title'], SUCC)
    assert ss.retired_title('a' * 300, SUCC) == 'RETIRED ' + 'a' * (200 - 8 - len(f' (-> {SUCC})')) + f' (-> {SUCC})'


def test_a_predecessor_already_told_apart_is_not_renamed(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'Lead other'
    record = service.handoff(checkpoint, quiesced=True, requested_title='Lead tendcf')
    finished = settle(service, native, record, Path(record['record']))
    assert finished['identity']['checks']['retire_rename'] == 'skipped'
    assert finished['identity']['retire_rename'] == {'reason': 'names-differ'}
    assert native.updates == [] and native.rows[PRED]['Name'] == 'Lead other'


def test_an_already_retired_predecessor_name_is_kept(setup):
    service, native, record, path = named_chain(setup)
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    native.rows[PRED]['Name'] = 'RETIRED by hand'  # an earlier run, or the operator, already marked it
    finished = service.finish(path)
    assert finished['identity']['checks']['retire_rename'] == 'ok'
    assert finished['identity']['retire_rename']['reason'] == 'already-retired'
    assert native.updates == [] and native.rows[PRED]['Name'] == 'RETIRED by hand'


def test_a_refused_rename_is_recorded_not_fatal_and_a_rerun_retries_it(setup):
    service, native, record, path = named_chain(setup)
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    native.update_result = (1, '', envelope('AGENT_NOT_FOUND', 'Agent not found'))
    finished = service.finish(path)
    assert finished['status'] == 'archived' and native.archived == 1
    assert finished['identity']['checks']['retire_rename'] == 'failed'
    detail = finished['identity']['retire_rename']
    assert detail['reason'] == 'native-error' and detail['native_error']['code'] == 'AGENT_NOT_FOUND'
    assert detail['native_error']['op'] == 'agent update'
    assert native.rows[PRED]['Name'] == 'fork-release-alerts'
    native.update_result = None
    again = service.finish(path)  # the archived record: only the retryable steps run
    assert native.archived == 1
    assert again['identity']['checks']['retire_rename'] == 'ok'
    assert native.rows[PRED]['Name'] == f'RETIRED fork-release-alerts (-> {SUCC})'


def test_a_rename_that_would_unarchive_the_predecessor_is_reported_as_failed(setup):
    service, native, record, path = named_chain(setup)
    native.rename_unarchives = True
    finished = settle(service, native, record, path)
    assert finished['status'] == 'archived'
    assert finished['identity']['checks']['retire_rename'] == 'failed'
    assert finished['identity']['retire_rename']['reason'] == 'rename-unarchived-predecessor'
    assert native.rows[PRED]['Archived'] is False  # observed and recorded; finish never forces a second archive
    assert native.archived == 1


def test_a_rename_that_does_not_take_effect_is_reported_as_failed(setup):
    service, native, record, path = named_chain(setup)
    native.rename_ignored = True
    finished = settle(service, native, record, path)
    assert finished['identity']['checks']['retire_rename'] == 'failed'
    assert finished['identity']['retire_rename']['reason'] == 'name-readback-mismatch'


def test_a_predecessor_that_is_not_archived_is_skipped_and_stays_retryable(setup):
    service, native, record, path = named_chain(setup)
    done = settle(service, native, record, path)
    done['identity']['checks'].pop('retire_rename')
    native.rows[PRED]['Archived'] = False
    service.retire_predecessor_name(done, path)
    assert done['identity']['checks']['retire_rename'] == 'skipped'
    assert done['identity']['retire_rename'] == {'reason': 'predecessor-not-archived'}
    native.rows[PRED]['Archived'] = True
    service.retire_predecessor_name(done, path)  # the skip was not final
    assert done['identity']['checks']['retire_rename'] == 'ok'


def test_a_revived_retired_name_is_never_inherited_as_the_next_title(setup):
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = f'RETIRED fork-release-alerts (-> {SUCC})'
    record = service.handoff(checkpoint, quiesced=True)
    assert record['identity']['title'] == 'Lead (self-handoff successor)' and record['identity']['title_source'] == 'derived'


WORKER_RUN = str(Path(ss.__file__).with_name('ade-worker-run').resolve())


@pytest.mark.parametrize('window, state', [('MAIN p (w)', 'rename-advised'), ('p chat', 'rename-advised'),
                                           ('LEAD p (w)', 'ok'), ('LEAD fork-release-alerts (CVE watch)', 'ok'),
                                           ('LEAD p (w) stray', 'rename-advised'), ('xLEAD p (w)', 'rename-advised')])
def test_finish_advises_the_exact_rename_lead_command_when_the_window_is_not_a_lead_window(setup, window, state):
    service, native, record, path = named_chain(setup)
    native.workspaces[0]['name'] = window
    finished = settle(service, native, record, path)
    info = finished['lead_window']
    assert info['state'] == state and info['name'] == window
    if state == 'ok':
        assert 'command' not in info
    else:
        assert info['command'] == f'{WORKER_RUN} rename-lead --lead {SUCC} --window-middle fork-release-alerts'
    assert json.loads(path.read_text())['lead_window'] == info
    assert not [a for a, _ in native.calls if a[4:6] == ['workspace', 'rename']]  # observe and advise only


def test_the_window_advice_is_unknown_when_the_window_is_not_listed(setup):
    service, native, record, path = named_chain(setup)
    native.workspaces[:] = []
    assert settle(service, native, record, path)['lead_window'] == {'state': 'unknown', 'reason': 'window-not-listed'}


def test_a_failing_workspace_listing_never_fails_finish(setup):
    service, native, record, path = named_chain(setup)
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'

    def runner(argv, **kwargs):
        if argv[4:6] == ['workspace', 'ls']:
            raise subprocess.TimeoutExpired(argv, 30)
        return native(argv, **kwargs)
    service.runner = runner
    finished = service.finish(path)
    assert finished['status'] == 'archived' and finished['lead_window']['state'] == 'unknown'
    assert 'timed out' in finished['lead_window']['reason']


WS2 = 'wks_0123456789abcdef'


def new_local_chain(setup, state_name=None, window='MAIN q (z)'):
    """A handoff whose predecessor workspace had vanished: the successor sits in WS2, named only in its daemon state file."""
    service, native, checkpoint = setup
    native.rows[PRED]['Name'] = 'fork-release-alerts'
    native.workspaces[:] = []  # WS (the predecessor's) is gone: placement new-local
    record = service.handoff(checkpoint, quiesced=True)
    assert record['workspace_placement'] == 'new-local' and record['workspace'] == WS
    native.workspaces.append({'workspaceId': WS2, 'project': 'p', 'name': window, 'cwd': '/x'})
    if state_name is not None:
        agents = service.home / 'agents' / 'proj'
        agents.mkdir(parents=True)
        (agents / (SUCC + '.json')).write_text(json.dumps({'workspaceId': WS2}))
    return service, native, record, Path(record['record'])


@pytest.mark.parametrize('window, state', [('MAIN q (z)', 'rename-advised'), ('LEAD q (z)', 'ok')])
def test_the_window_advice_follows_a_new_local_successor_to_its_own_workspace(setup, window, state):
    service, native, record, path = new_local_chain(setup, state_name='proj', window=window)
    info = settle(service, native, record, path)['lead_window']
    assert info['state'] == state and info['name'] == window  # WS2 (the successor's), not WS (the predecessor's, gone)
    if state == 'rename-advised':
        assert info['command'] == f'{WORKER_RUN} rename-lead --lead {SUCC} --window-middle fork-release-alerts'
        assert 'reason' not in info


@pytest.mark.parametrize('content', [None, 'not json', '[]', '{"workspaceId": "nope"}', '[' * 200000])
def test_an_unreadable_new_local_window_still_gets_the_rename_advice(setup, content):
    service, native, record, path = new_local_chain(setup)
    if content is not None:
        agents = service.home / 'agents' / 'proj'
        agents.mkdir(parents=True)
        (agents / (SUCC + '.json')).write_text(content)
    info = settle(service, native, record, path)['lead_window']
    assert info == {'state': 'rename-advised', 'reason': 'successor-window-unresolved',
                    'command': f'{WORKER_RUN} rename-lead --lead {SUCC} --window-middle fork-release-alerts'}


DECOY = 'ffffffff-ffff-4fff-8fff-ffffffffffff'


@pytest.mark.parametrize('with_own', [False, True])
def test_the_successor_window_is_read_from_its_own_state_file_only(setup, with_own):
    """A decoy agent's state file (another agent's workspace) is never read for the successor."""
    service, native, record, path = new_local_chain(setup, state_name='proj' if with_own else None, window='MAIN q (z)')
    agents = service.home / 'agents' / 'proj'
    agents.mkdir(parents=True, exist_ok=True)
    native.workspaces.append({'workspaceId': 'wks_fedcba9876543210', 'project': 'p', 'name': 'LEAD decoy (d)', 'cwd': '/x'})
    (agents / (DECOY + '.json')).write_text(json.dumps({'workspaceId': 'wks_fedcba9876543210'}))
    info = settle(service, native, record, path)['lead_window']
    if with_own:
        assert info['state'] == 'rename-advised' and info['name'] == 'MAIN q (z)'
    else:
        assert info['state'] == 'rename-advised' and info['reason'] == 'successor-window-unresolved'


# --- 2026-11-23: rename-lead advice uses absolute path + safe --repo + --window-middle -------------------------------

@pytest.mark.parametrize('frontmatter_repo, expected_repo', [
    ('djbclark/stayturgid', 'stayturgid'),
    ('stayturgid', 'stayturgid'),
    ('"djbclark/stayturgid"', 'stayturgid'),
    ("'stayturgid'", 'stayturgid'),
    ('djbclark/stayturgid  # primary repo', 'stayturgid'),
    ('frdminc/paseo.dev_1-test', 'paseo.dev_1-test'),
])
def test_lead_window_advice_extracts_single_frontmatter_repo(setup, frontmatter_repo, expected_repo):
    import shlex
    service, native, checkpoint = setup
    messages = []
    service.progress = messages.append
    checkpoint.write_text(f'---\nrepo: {frontmatter_repo}\nbranch: master\n---\n# Handoff\n')
    native.rows[PRED]['Name'] = 'stayturgid fleet hardening (341 fix in flight)'
    record = service.handoff(checkpoint, quiesced=True)
    finished = settle(service, native, record, Path(record['record']))
    cmd = finished['lead_window']['command']
    assert shlex.split(cmd) == [
        WORKER_RUN, 'rename-lead', '--lead', SUCC,
        '--repo', expected_repo,
        '--window-middle', 'stayturgid fleet hardening (341 fix in flight)',
    ]
    assert "'stayturgid fleet hardening (341 fix in flight)'" in cmd
    advice_lines = [m for m in messages if 'run as the successor:' in m]
    assert len(advice_lines) == 1
    assert WORKER_RUN in advice_lines[0]
    assert '[--window-middle "WORK"]' not in advice_lines[0]
    assert '[--repo REPO]' not in advice_lines[0]


@pytest.mark.parametrize('frontmatter', [
    '---\nrepo: djbclark/djbclark-ade (lead), djbclark/site-djbclark (ops)\n---\nbody\n',
    '---\nrepo: djbclark/a, djbclark/b\n---\nbody\n',
    '---\nrepo: stayturgid; rm -rf /\n---\nbody\n',
    '---\nrepo: $(whoami)/stayturgid\n---\nbody\n',
    '---\nrepo: stayturgid#evil\n---\nbody\n',
    '---\nrepo: -bad-leading-hyphen\n---\nbody\n',
    '---\nrepo: /Users/djbclark/src/stayturgid\n---\nbody\n',
    '---\nrepo: null\n---\nbody\n',
    '---\nrepo: ""\n---\nbody\n',
    '---\nrepo: "a" "b"\n---\nbody\n',
    '---\nrepo: a\nrepo: b\n---\nbody\n',
    '---\nrepo: ' + 'r' * 95 + '\n---\nbody\n',
    '---\nrepo: stayturgid\n  and other-repo\n---\nbody\n',
    '---\nbranch: master\n---\nrepo: stayturgid\n',
    'repo: stayturgid\nno frontmatter\n',
    '---\nrepo: stayturgid\nunclosed frontmatter\n',
])
def test_lead_window_advice_omits_repo_on_multi_or_malformed_frontmatter(setup, frontmatter):
    import shlex
    service, native, checkpoint = setup
    messages = []
    service.progress = messages.append
    checkpoint.write_text(frontmatter)
    native.rows[PRED]['Name'] = 'stayturgid fleet hardening'
    record = service.handoff(checkpoint, quiesced=True)
    finished = settle(service, native, record, Path(record['record']))
    cmd = finished['lead_window']['command']
    argv = shlex.split(cmd)
    assert argv == [WORKER_RUN, 'rename-lead', '--lead', SUCC, '--window-middle', 'stayturgid fleet hardening']
    advice_lines = [m for m in messages if 'run as the successor:' in m]
    assert len(advice_lines) == 1
    assert '[--repo REPO]' in advice_lines[0]
    assert '[--window-middle "WORK"]' not in advice_lines[0]


def test_lead_window_advice_survives_missing_or_symlinked_checkpoint(setup, tmp_path):
    import shlex
    service, native, checkpoint = setup
    checkpoint.write_text('---\nrepo: stayturgid\n---\nbody\n')
    native.rows[PRED]['Name'] = 'fleet work'
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    finished = settle(service, native, record, path)
    assert '--repo' in shlex.split(finished['lead_window']['command'])

    # Missing preserved checkpoint still advises safely without failing finish.
    preserved = Path(record['checkpoint'])
    preserved.unlink()
    service.advise_lead_window(finished, path)
    assert shlex.split(finished['lead_window']['command']) == [
        WORKER_RUN, 'rename-lead', '--lead', SUCC, '--window-middle', 'fleet work',
    ]

    # Symlinked preserved checkpoint is never followed.
    target = tmp_path / 'elsewhere.md'
    target.write_text('---\nrepo: stayturgid\n---\n')
    preserved.symlink_to(target)
    service.advise_lead_window(finished, path)
    assert '--repo' not in shlex.split(finished['lead_window']['command'])

    # Embedded NUL in checkpoint path never fails finish/advice.
    finished['checkpoint'] = '/tmp/bad\x00path.md'
    service.advise_lead_window(finished, path)
    assert '--repo' not in shlex.split(finished['lead_window']['command'])


@pytest.mark.parametrize('title, title_source, frontmatter_repo, role', [
    ('', 'predecessor-name', 'stayturgid', None),
    ('-', 'predecessor-name', 'stayturgid', None),
    ('Self-handoff abc-123', 'predecessor-name', 'stayturgid', None),
    ('RETIRED old-lead (-> ' + PRED + ')', 'predecessor-name', 'stayturgid', None),
    ('Lead (self-handoff successor)', 'derived', 'stayturgid', None),
    ('Lead (self-handoff successor)', 'predecessor-name', 'stayturgid', None),
    ('Lead stayturgid', 'derived', 'stayturgid', 'stayturgid'),
    ('Lead stayturgid', 'predecessor-name', 'stayturgid', None),
    ('LEAD stayturgid', 'predecessor-name', 'stayturgid', None),
    ('LEAD ops', 'predecessor-name', None, None),
    ('stayturgid', 'predecessor-name', 'stayturgid', None),
    ('LEAD stayturgid (existing work)', 'predecessor-name', 'stayturgid', None),
    ('Lead ops-chain', 'predecessor-name', None, 'ops-chain'),
])
def test_lead_window_advice_skips_placeholder_bootstrap_retired_and_generic_titles(
        setup, title, title_source, frontmatter_repo, role):
    import shlex
    service, native, checkpoint = setup
    messages = []
    service.progress = messages.append
    if frontmatter_repo:
        checkpoint.write_text(f'---\nrepo: {frontmatter_repo}\n---\nbody\n')
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    labels = {'ade.chain': PRED, 'ade.predecessor': PRED}
    if role:
        labels['ade.role'] = role
    record['identity'] = {'title': title, 'title_source': title_source, 'role_source': 'requested' if role else None,
                          'labels': labels, 'checks': {'create': 'requested'}}
    service.advise_lead_window(record, path)
    cmd = record['lead_window']['command']
    argv = shlex.split(cmd)
    expected = [WORKER_RUN, 'rename-lead', '--lead', SUCC]
    if frontmatter_repo:
        expected += ['--repo', frontmatter_repo]
    assert argv == expected
    advice_lines = [m for m in messages if 'run as the successor:' in m]
    assert len(advice_lines) == 1
    assert '[--window-middle "WORK"]' in advice_lines[0]
    if frontmatter_repo:
        assert '[--repo REPO]' not in advice_lines[0]
    else:
        assert '[--repo REPO]' in advice_lines[0]


@pytest.mark.parametrize('raw_title, frontmatter_repo', [
    ('stayturgid fleet hardening (341 fix in flight)', 'djbclark/stayturgid'),
    ('  line1\n\tline2\x07  (parens & $var `tick`)  ', 'djbclark/stayturgid'),
    ('-leading-hyphen work', 'stayturgid'),
    ('x' * 180, 'djbclark/stayturgid'),
    ('y' * 180, None),
])
def test_lead_window_advice_command_parses_and_passes_ade_worker_run_rename_lead(
        setup, tmp_path, raw_title, frontmatter_repo):
    """The emitted command argv is accepted end-to-end by `bin/ade-worker-run rename-lead` without rejection."""
    import shlex
    import ade_ws_names as wsn

    service, native, checkpoint = setup
    if frontmatter_repo:
        checkpoint.write_text(f'---\nrepo: {frontmatter_repo}\n---\nbody\n')
    record = service.handoff(checkpoint, quiesced=True)
    path = Path(record['record'])
    record['identity'] = {'title': raw_title, 'title_source': 'predecessor-name', 'role_source': None,
                          'labels': {'ade.chain': PRED, 'ade.predecessor': PRED}, 'checks': {'create': 'requested'}}
    service.advise_lead_window(record, path)
    cmd = record['lead_window']['command']
    argv = shlex.split(cmd)
    assert argv[0] == WORKER_RUN and argv[1:4] == ['rename-lead', '--lead', SUCC]

    # Run the real `bin/ade-worker-run` with a fake `paseo` stub and verify it renames cleanly (rc == 0).
    paseo_home = tmp_path / 'paseo-home'
    state_dir = tmp_path / 'worker-run-state'
    fake_bin = tmp_path / 'fake-bin'
    fake_bin.mkdir()
    agent_dir = paseo_home / 'agents' / 'proj'
    agent_dir.mkdir(parents=True)
    (agent_dir / f'{SUCC}.json').write_text(json.dumps({'workspaceId': WS}))
    repo_dir = tmp_path / 'ops'
    repo_dir.mkdir()
    fake_paseo = fake_bin / 'paseo'
    fake_paseo.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'args = sys.argv[1:]\n'
        f'if args == ["workspace", "ls", "--json"]:\n'
        f'    print(json.dumps([{{"workspaceId": {WS!r}, "name": "MAIN ops (stale)", "cwd": {str(repo_dir)!r}}}]))\n'
        'elif args[:2] == ["workspace", "rename"]:\n'
        '    print("{}")\n'
        'else:\n'
        '    sys.stderr.write("unexpected: " + repr(args) + "\\n")\n'
        '    sys.exit(1)\n'
    )
    fake_paseo.chmod(0o755)
    env = {**os.environ, 'PATH': f'{fake_bin}:{os.environ.get("PATH", "")}',
           'PASEO_HOME': str(paseo_home), 'PASEO_AGENT_ID': SUCC,
           'ADE_WORKER_RUN_STATE': str(state_dir)}
    res = subprocess.run(argv, capture_output=True, text=True, env=env, check=False)
    assert res.returncode == 0, f'ade-worker-run rejected advised command: {cmd}\nstderr={res.stderr}'
    out = json.loads(res.stdout)
    assert out['renamed'] is True
    parsed = wsn.parse(out['windowName'])
    assert parsed is not None and parsed.kind == 'LEAD'
    assert len(out['windowName']) <= wsn.NAME_LIMIT
    if frontmatter_repo:
        assert parsed.repo == 'stayturgid'
    else:
        assert parsed.repo == 'ops'


# --- 2026-11-23: cross-provider operator-authorized handoffs (--provider PROVIDER/MODEL) -----------------------------

LIVE_PROVIDERS = [
    {'provider': 'claude', 'enabled': 'Enabled', 'status': 'available',
     'modes': 'Plan Mode, Always Ask, Accept File Edits, Auto mode, Bypass'},
    {'provider': 'codex', 'enabled': 'Enabled', 'status': 'available',
     'modes': 'Default Permissions, Auto-review, Full Access'},
    {'provider': 'antigravity', 'enabled': 'Enabled', 'status': 'available',
     'modes': 'Default, Accept edits, Auto, Plan, Full access'},
    {'provider': 'pi', 'enabled': 'Enabled', 'status': 'available', 'modes': ''},
    {'provider': 'cursor', 'enabled': 'Enabled', 'status': 'available', 'modes': 'Agent, Plan, Ask'},
    {'provider': 'hermes', 'enabled': 'Enabled', 'status': 'available',
     'modes': "Default, Accept Edits, Don't Ask"},
    {'provider': 'opencode', 'enabled': 'Disabled', 'status': 'unavailable', 'modes': ''},
]


def _cross_setup(setup, *, pred_provider='claude', pred_model='claude-opus-5-5', pred_mode='bypassPermissions',
                 pred_modes=None, providers=None, succ_modes=None):
    service, native, checkpoint = setup
    service.planner = service.verifier = None
    native.rows[PRED].update(
        Provider=pred_provider, Model=pred_model, Mode=pred_mode, Name='Lead djbclark-ade',
        AvailableModes=pred_modes if pred_modes is not None else [{'id': pred_mode, 'label': pred_mode}],
    )
    native.providers = copy.deepcopy(LIVE_PROVIDERS if providers is None else providers)
    native.successor_modes = succ_modes
    return service, native, checkpoint


@pytest.mark.parametrize('catalog_kind', ['display-labels', 'structured'])
def test_cross_provider_claude_to_antigravity_full_lifecycle(setup, tmp_path, catalog_kind):
    """claude -> antigravity/gemini-4-neon --thinking high: handoff, send-guard, accept, finish, claims, supervisor, RETIRED."""
    import ade_claims
    import ade_send_guard as send_guard

    providers = copy.deepcopy(LIVE_PROVIDERS)
    if catalog_kind == 'structured':
        for row in providers:
            if row['provider'] == 'antigravity':
                row['modes'] = [{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}]
    service, native, checkpoint = _cross_setup(
        setup, providers=providers,
        succ_modes=[{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}],
    )
    _claim('c-cross', PRED, tmp_path)
    lead_file = _lead_file(tmp_path, PRED + '\n')

    record = service.handoff(
        checkpoint, quiesced=True,
        requested_provider='antigravity/gemini-4-neon', requested_thinking='high',
    )
    path = Path(record['record'])
    call = run_args(native)
    assert call[call.index('--provider') + 1] == 'antigravity/gemini-4-neon'
    assert call[call.index('--mode') + 1] == 'full-access'
    assert call[call.index('--thinking') + 1] == 'high'
    assert record['schema_version'] == 1
    assert record['status'] == 'awaiting-ack'
    assert record['provider'] == 'antigravity' and record['model'] == 'gemini-4-neon'
    assert record['thinking'] == 'high'
    assert record['mode_plan']['provider'] == 'antigravity' and record['mode_plan']['mode_id'] == 'full-access'
    assert record['predecessor_provider'] == 'claude'
    assert record['predecessor_model'] == 'claude-opus-5-5'
    assert record['cross_provider'] is True

    # Before accept, send-guard passes to predecessor; from acknowledged onward, it redirects to successor.
    def inspect_fn(aid):
        if aid not in native.rows:
            raise LookupError(aid)
        return copy.deepcopy(native.rows[aid])

    assert send_guard.decide(PRED, inspect_fn, state_dir=service.state, home=service.home).action == send_guard.PASS
    acked = accept(service, record, path)
    assert acked['status'] == 'acknowledged'
    redirected = send_guard.decide(PRED, inspect_fn, state_dir=service.state, home=service.home)
    assert (redirected.action, redirected.target) == (send_guard.REDIRECT, SUCC)

    native.rows[PRED]['Status'] = 'idle'
    finished = service.finish(path)
    assert finished['status'] == 'archived'
    assert native.rows[PRED]['Archived'] is True
    assert finished['rebound_claims'] == ['c-cross']
    assert ade_claims.read_claim('c-cross')['owner']['agent'] == SUCC
    assert finished['supervisor_lead'] == 'repointed'
    assert lead_file.read_text() == SUCC + '\n'
    assert finished['identity']['checks']['retire_rename'] == 'ok'
    assert native.rows[PRED]['Name'] == f'RETIRED Lead djbclark-ade (-> {SUCC})'
    after = send_guard.decide(PRED, inspect_fn, state_dir=service.state, home=service.home)
    assert (after.action, after.target) == (send_guard.REDIRECT, SUCC)


@pytest.mark.parametrize(('pred_provider', 'pred_model', 'pred_mode', 'target', 'expected_mode', 'succ_modes'), [
    ('claude', 'claude-opus-5-5', 'bypassPermissions', 'codex/gpt-6-astra', 'full-access',
     [{'id': 'default'}, {'id': 'full-access'}]),
    ('antigravity', 'gemini-4-neon', 'full-access', 'claude/claude-opus-5-5', 'bypassPermissions',
     [{'id': 'auto'}, {'id': 'plan'}, {'id': 'bypassPermissions'}]),
])
def test_cross_provider_codex_and_antigravity_to_claude(setup, pred_provider, pred_model, pred_mode, target, expected_mode, succ_modes):
    service, native, checkpoint = _cross_setup(
        setup, pred_provider=pred_provider, pred_model=pred_model, pred_mode=pred_mode, succ_modes=succ_modes,
    )
    record = service.handoff(checkpoint, quiesced=True, requested_provider=target)
    target_provider, target_model = target.split('/', 1)
    call = run_args(native)
    assert call[call.index('--provider') + 1] == target
    assert call[call.index('--mode') + 1] == expected_mode
    assert record['provider'] == target_provider and record['model'] == target_model
    assert record['mode_plan']['provider'] == target_provider and record['mode_plan']['mode_id'] == expected_mode
    assert record['predecessor_provider'] == pred_provider and record['predecessor_model'] == pred_model
    assert record['cross_provider'] is True
    path = Path(record['record'])
    accept(service, record, path)
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'


def test_same_provider_model_override_uses_predecessor_modes_and_records_predecessor_model(setup):
    service, native, checkpoint = _cross_setup(setup)
    record = service.handoff(checkpoint, quiesced=True, requested_provider='claude/claude-sonnet-5-5')
    assert record['provider'] == 'claude' and record['model'] == 'claude-sonnet-5-5'
    assert record['mode_plan']['mode_id'] == 'bypassPermissions'
    assert record['mode_plan']['evidence'] == 'source-and-catalog'
    assert record['predecessor_provider'] == 'claude' and record['predecessor_model'] == 'claude-opus-5-5'
    assert 'cross_provider' not in record


def test_cross_provider_accept_verifies_target_mode_provider_model_and_thinking(setup):
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'full-access'}],
    )
    record = service.handoff(
        checkpoint, quiesced=True,
        requested_provider='antigravity/gemini-4-neon', requested_thinking='high',
    )
    path = Path(record['record'])
    # Mode drifted to default -> refused.
    native.rows[SUCC]['Mode'] = 'default'
    with pytest.raises(ss.SessionError, match='unattended mode not verified'):
        accept(service, record, path)
    native.rows[SUCC]['Mode'] = 'full-access'
    # AvailableModes missing planned mode -> refused.
    native.rows[SUCC]['AvailableModes'] = [{'id': 'default'}]
    with pytest.raises(ss.SessionError, match='unattended mode not verified'):
        accept(service, record, path)
    native.rows[SUCC]['AvailableModes'] = [{'id': 'default'}, {'id': 'full-access'}]
    # Thinking level mismatch -> refused.
    native.rows[SUCC]['Thinking'] = 'low'
    with pytest.raises(ss.SessionError, match='thinking level readback mismatch'):
        accept(service, record, path)
    native.rows[SUCC]['Thinking'] = 'high'
    # Provider or model mismatch -> refused.
    native.rows[SUCC]['Provider'] = 'claude'
    with pytest.raises(ss.SessionError, match='readback mismatch'):
        accept(service, record, path)
    native.rows[SUCC]['Provider'] = 'antigravity'
    assert accept(service, record, path)['status'] == 'acknowledged'


@pytest.mark.parametrize('bad', [
    '', 'antigravity', 'antigravity/', '/gemini-4-neon', 'antigravity/a/b',
    'antigravity/default', 'antigravity/DEFAULT', 'antigravity/-',
    ' antigravity/gemini-4-neon', 'antigravity/gemini-4-neon ',
    'antigravity/gemini 4', 'antigravity/gemini\n4', 'antigravity/gemini\x004',
    'antigravity/gemini-*', 'antigravity/gemini-?', 'antigravity/gemini-[4]',
    '-claude/opus', 'claude/-opus', 'claude/opus;rm',
    'Antigravity/gemini-4-neon', 'Claude/claude-opus-5-5', 'CODEX/gpt-6-astra', 42,
])
def test_invalid_provider_flag_refused_before_any_native_call(setup, bad):
    service, native, checkpoint = _cross_setup(setup)
    with pytest.raises(ss.SessionError, match='PROVIDER/MODEL'):
        service.handoff(checkpoint, quiesced=True, requested_provider=bad)
    assert native.calls == [] and native.created == 0
    assert not list(service.state.glob('handoff-*.json'))


def test_provider_and_route_kind_are_mutually_exclusive(setup):
    service, native, checkpoint = _cross_setup(setup)
    with pytest.raises(ss.SessionError, match='mutually exclusive'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', route_kind='judgment')
    assert native.calls == [] and native.created == 0


@pytest.mark.parametrize('retired', [
    'opencode/x', 'omp/x', 'crush/x', 'agy/x', 'grok/x',
    'OpenCode/x', 'OPENCODE/x', 'AGY/gemini-4-neon', 'OMP/x', 'Grok/x', 'Crush/x',
])
@pytest.mark.parametrize('mode', [None, 'plan'])
def test_retired_provider_refused_before_any_native_call(setup, retired, mode):
    service, native, checkpoint = _cross_setup(setup)
    with pytest.raises(ss.SessionError, match='retired provider'):
        service.handoff(checkpoint, quiesced=True, requested_provider=retired, requested_mode=mode)
    assert native.calls == [] and native.created == 0


@pytest.mark.parametrize('placeholder', ['-', ' - ', ',', ' , ', '-,-'])
@pytest.mark.parametrize('mode', [None, 'plan'])
def test_placeholder_label_modes_refused_for_cross_provider_handoff(setup, placeholder, mode):
    providers = copy.deepcopy(LIVE_PROVIDERS)
    for row in providers:
        if row['provider'] == 'antigravity':
            row['modes'] = placeholder
    service, native, checkpoint = _cross_setup(setup, providers=providers)
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode=mode)
    assert native.created == 0


@pytest.mark.parametrize('bad_modes', [
    [{'id': 'plan'}, {'id': 'plan'}],
    [{'id': 'plan'}, 'bad'],
    [{'id': 'plan'}, {'id': ''}],
])
def test_malformed_or_duplicate_target_structured_modes_refused_even_for_restrictive_mode(setup, bad_modes):
    providers = [
        {'provider': 'claude', 'enabled': 'Enabled', 'status': 'available', 'modes': [{'id': 'bypassPermissions'}]},
        {'provider': 'antigravity', 'enabled': 'Enabled', 'status': 'available', 'modes': bad_modes},
    ]
    service, native, checkpoint = _cross_setup(setup, providers=providers)
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode='plan')
    assert native.created == 0


@pytest.mark.parametrize('catalog_kind', ['display-labels', 'structured'])
@pytest.mark.parametrize('bad_mode', ['', 'auto', 'foo', 'full-access'])
def test_non_restrictive_requested_mode_refused_uniformly_on_cross_provider_handoff(setup, catalog_kind, bad_mode):
    providers = copy.deepcopy(LIVE_PROVIDERS)
    if catalog_kind == 'structured':
        for row in providers:
            if row['provider'] == 'antigravity':
                row['modes'] = [{'id': 'default'}, {'id': 'auto'}, {'id': 'plan'}, {'id': 'full-access'}]
    service, native, checkpoint = _cross_setup(setup, providers=providers)
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode=bad_mode)
    assert native.created == 0


@pytest.mark.parametrize('target', ['pi/test-model', 'cursor/composer-2.5', 'hermes/hermes-4'])
def test_modeless_and_unsupported_target_providers_refused(setup, target):
    service, native, checkpoint = _cross_setup(setup)
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_provider=target)
    assert native.created == 0


def test_cross_provider_thinking_inheritance_follows_existing_rules(setup):
    service, native, checkpoint = _cross_setup(setup, succ_modes=[{'id': 'full-access'}])
    native.rows[PRED]['Thinking'] = 'high'
    record = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon')
    call = run_args(native)
    assert call[call.index('--thinking') + 1] == 'high'
    assert record['thinking'] == 'high'
    accept(service, record, Path(record['record']))


def test_cross_provider_cannot_combine_with_routed_retry(setup):
    service, native, record, path = routed_start(setup)
    service.env['PASEO_AGENT_ID'] = PRED
    native.rows[SUCC]['Status'] = 'error'
    service.verify_turn(path)
    # First: retry fails planning so status stays retry-ready -> --provider refused.
    with pytest.raises(ss.SessionError, match='excluded pool'):
        service.retry(path)
    assert service.status(path)['status'] == 'retry-ready'
    with pytest.raises(ss.SessionError, match='routed handoff retry'):
        service.handoff(Path(record['checkpoint']), quiesced=True, requested_provider='antigravity/gemini-4-neon')
    # Next: router picks go-account-b, creation refuses -> routed creation-refused also rejects --provider.
    native.route_choice = {'service': 'go-account-b', 'agent': 'pi', 'model': 'opencode-go-account-b/test-model'}
    native.run_result = (1, '', envelope('INVALID_THINKING_OPTION', 'bad level'))
    native.labelled = []
    refused = service.handoff(Path(record['checkpoint']), quiesced=True)
    assert refused['status'] == 'creation-refused' and refused['route_kind'] == 'judgment'
    with pytest.raises(ss.SessionError, match='routed handoff retry'):
        service.handoff(Path(refused['checkpoint']), quiesced=True, requested_provider='antigravity/gemini-4-neon')


def test_modeless_pi_refused_even_with_restrictive_mode_and_list_catalog(setup):
    providers = copy.deepcopy(LIVE_PROVIDERS)
    for row in providers:
        if row['provider'] == 'pi':
            row['modes'] = []
    service, native, checkpoint = _cross_setup(setup, providers=providers)
    for mode in (None, 'plan'):
        with pytest.raises(ss.SessionError, match='supported unattended'):
            service.handoff(checkpoint, quiesced=True, requested_provider='pi/test-model', requested_mode=mode)
    assert native.created == 0


@pytest.mark.parametrize(('target', 'providers_patch'), [
    ('go/some-model', None),
    ('unknown/model-1', None),
    ('antigravity/gemini-4-neon', [{'provider': 'antigravity', 'enabled': 'Disabled', 'status': 'unavailable', 'modes': ''}]),
    ('antigravity/gemini-4-neon', [{'provider': 'antigravity', 'enabled': 'Enabled', 'status': 'error', 'modes': 'Full access'}]),
    ('antigravity/gemini-4-neon', []),
])
def test_unknown_or_unavailable_target_provider_refused(setup, target, providers_patch):
    service, native, checkpoint = _cross_setup(setup, providers=LIVE_PROVIDERS if providers_patch is None else providers_patch)
    with pytest.raises(ss.SessionError, match='provider unavailable'):
        service.handoff(checkpoint, quiesced=True, requested_provider=target)
    assert native.created == 0


def test_duplicate_handoff_with_different_provider_refused(setup):
    service, native, checkpoint = _cross_setup(setup, succ_modes=[{'id': 'full-access'}])
    first = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon')
    calls = len(native.calls)
    with pytest.raises(ss.SessionError, match='different requested provider/model'):
        service.handoff(checkpoint, quiesced=True, requested_provider='codex/gpt-6-astra')
    with pytest.raises(ss.SessionError, match='different requested provider/model'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-carbon')
    assert service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon') == first
    assert service.handoff(checkpoint, quiesced=True) == first
    assert len(native.calls) == calls and native.created == 1


def test_explicit_restrictive_mode_validated_against_target_catalog(setup):
    providers = [
        {'provider': 'claude', 'enabled': 'Enabled', 'status': 'available',
         'modes': [{'id': 'bypassPermissions'}, {'id': 'plan'}, {'id': 'read-only'}]},
        {'provider': 'antigravity', 'enabled': 'Enabled', 'status': 'available',
         'modes': [{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}]},
    ]
    service, native, checkpoint = _cross_setup(
        setup,
        pred_modes=[{'id': 'bypassPermissions'}, {'id': 'plan'}, {'id': 'read-only'}],
        providers=providers,
        succ_modes=[{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}],
    )
    # Predecessor supports read-only, target does NOT -> refused before launch!
    with pytest.raises(ss.SessionError, match='supported unattended'):
        service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode='read-only')
    assert native.created == 0
    # Target supports plan -> accepted and verified end-to-end!
    record = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode='plan')
    assert record['mode_plan']['status'] == 'exempt' and record['mode_plan']['mode_id'] == 'plan'
    assert run_args(native)[run_args(native).index('--mode') + 1] == 'plan'
    accept(service, record, Path(record['record']))


def test_label_only_restrictive_mode_still_verified_at_accept(setup):
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}],
    )
    record = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_mode='read-only')
    assert record['mode_plan']['status'] == 'exempt' and record['mode_plan']['mode_id'] == 'read-only'
    # Live successor lacks read-only in AvailableModes -> accept fails closed!
    with pytest.raises(ss.SessionError, match='unattended mode not verified'):
        accept(service, record, Path(record['record']))


def test_creation_refused_replay_after_fixing_provider_works_cleanly(setup):
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'full-access'}],
    )
    native.run_result = (1, '', envelope('INVALID_MODEL', 'Unknown model bad-model'))
    native.labelled = []
    refused = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/bad-model')
    assert refused['status'] == 'creation-refused'
    assert refused['native_error']['code'] == 'INVALID_MODEL'
    assert refused['provider'] == 'antigravity' and refused['model'] == 'bad-model'

    # Fix --provider and replay cleanly (label probe confirms no agent was created).
    native.run_result = None
    retried = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon', requested_thinking='high')
    assert retried['status'] == 'awaiting-ack'
    assert retried['provider'] == 'antigravity' and retried['model'] == 'gemini-4-neon'
    assert retried['refused_before'] == refused['native_error']
    path = Path(retried['record'])
    accept(service, retried, path)
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'


def test_cli_exposes_provider_on_handoff_only():
    cli = str(REPO / 'bin' / 'ade-self-session')
    ok = subprocess.run([cli, 'handoff', '--help'], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and '--provider' in ok.stdout
    bad = subprocess.run([cli, 'compact', '--checkpoint', '/x', '--request-id', 'r', '--provider', 'antigravity/gemini-4-neon'],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 2


# --- 2026-11-23: quota-floor guard on handoff ------------------------------------------------------------------------

def _canned_aiuse(tmp_path, available):
    path = tmp_path / 'canned-aiuse.json'
    path.write_text(json.dumps({
        'collected_at': '2026-11-23T15:00:00Z',
        'fresh': True,
        'available': available,
    }))
    return path


def test_quota_guard_auto_reroutes_scarce_predecessor_via_route_agent(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 9.0, 'binding_window': 'weekly',
         'windows': [{'id': 'weekly', 'remaining_percent': 9.0, 'used_percent': 91.0}]},
        {'provider': 'antigravity', 'pool_family': 'gemini', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 82.0, 'binding_window': '5h',
         'windows': [{'id': '5h', 'remaining_percent': 82.0, 'used_percent': 18.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    messages = []
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'plan'}, {'id': 'full-access'}],
    )
    service.progress = messages.append
    native.route_choice = {
        'service': 'antigravity-neon', 'agent': 'antigravity',
        'model': 'gemini-4-neon --effort high', 'remaining': 82.0,
    }

    record = service.handoff(checkpoint, quiesced=True)
    call = run_args(native)
    assert call[call.index('--provider') + 1] == 'antigravity/gemini-4-neon'
    assert call[call.index('--mode') + 1] == 'full-access'
    assert call[call.index('--thinking') + 1] == 'high'
    assert record['provider'] == 'antigravity' and record['model'] == 'gemini-4-neon'
    assert record['predecessor_provider'] == 'claude' and record['predecessor_model'] == 'claude-opus-5-5'
    assert record['cross_provider'] is True
    assert record['quota_reroute'] == {
        'source_pool': 'claude',
        'source_remaining_pct': 9.0,
        'floor_pct': 15.0,
        'routed_to': 'antigravity/gemini-4-neon',
        'target_service': 'antigravity-neon',
        'route_kind': 'judgment',
        'target_remaining_pct': 82.0,
    }
    route_argv = next(a for a, _ in native.calls if len(a) > 1 and 'route_agent.py' in a[1])
    assert route_argv[route_argv.index('--exclude') + 1] == 'claude'
    assert any('quota-floor guard' in m and 'antigravity/gemini-4-neon' in m for m in messages)

    path = Path(record['record'])
    assert accept(service, record, path)['status'] == 'acknowledged'
    native.rows[PRED]['Status'] = 'idle'
    assert service.finish(path)['status'] == 'archived'


def test_quota_guard_skips_non_unattended_routed_candidate_and_picks_next(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 8.0, 'binding_window': 'weekly',
         'windows': [{'id': 'weekly', 'remaining_percent': 8.0, 'used_percent': 92.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'full-access'}],
    )
    seen_excludes = []

    def plan_fn(argv, kwargs):
        ex = [argv[i + 1] for i, a in enumerate(argv) if a == '--exclude']
        seen_excludes.append(ex)
        if 'cursor-auto' not in ex:
            choice = {'service': 'cursor-auto', 'agent': 'cursor', 'model': 'default', 'remaining': 70.0}
        elif 'zai' not in ex:
            choice = {'service': 'zai', 'agent': 'pi', 'model': 'zai/glm-5.3-flash --effort high', 'remaining': 90.0}
        else:
            choice = {'service': 'antigravity-neon', 'agent': 'antigravity', 'model': 'gemini-4-neon --effort high', 'remaining': 75.0}
        return subprocess.CompletedProcess(argv, 0, json.dumps({'stale': False, 'slices': [choice]}), '')

    native.route_plan_fn = plan_fn
    record = service.handoff(checkpoint, quiesced=True)
    assert record['provider'] == 'antigravity' and record['model'] == 'gemini-4-neon'
    assert record['quota_reroute']['routed_to'] == 'antigravity/gemini-4-neon'
    assert any('cursor-auto' in ex and 'zai' in ex and 'claude' in ex for ex in seen_excludes)


def test_quota_guard_refuses_cleanly_when_no_alternative_available(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 9.0, 'binding_window': 'weekly',
         'windows': [{'id': 'weekly', 'remaining_percent': 9.0, 'used_percent': 91.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    service, native, checkpoint = _cross_setup(setup)
    native.route_choice = {'service': None, 'agent': None, 'model': None, 'remaining': None}

    with pytest.raises(ss.SessionError) as exc:
        service.handoff(checkpoint, quiesced=True)
    msg = str(exc.value)
    assert 'claude' in msg and '9%' in msg and '15%' in msg
    assert '--provider PROVIDER/MODEL' in msg and '--allow-scarce-pool' in msg
    assert native.created == 0
    assert not list(service.state.glob('handoff-*.json'))


def test_quota_guard_allow_scarce_pool_overrides_and_clones_source(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 9.0, 'binding_window': 'weekly',
         'windows': [{'id': 'weekly', 'remaining_percent': 9.0, 'used_percent': 91.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    messages = []
    service, native, checkpoint = _cross_setup(setup)
    service.progress = messages.append

    record = service.handoff(checkpoint, quiesced=True, allow_scarce_pool=True)
    assert record['provider'] == 'claude' and record['model'] == 'claude-opus-5-5'
    assert record['allow_scarce_pool'] is True
    assert 'quota_reroute' not in record
    assert not any(len(a) > 1 and 'route_agent.py' in a[1] for a, _ in native.calls)
    assert any('--allow-scarce-pool' in m for m in messages)


def test_quota_guard_healthy_predecessor_clones_without_reroute(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 45.0, 'binding_window': 'weekly',
         'windows': [{'id': 'weekly', 'remaining_percent': 45.0, 'used_percent': 55.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    service, native, checkpoint = _cross_setup(setup)
    record = service.handoff(checkpoint, quiesced=True)
    assert record['provider'] == 'claude' and record['model'] == 'claude-opus-5-5'
    assert 'quota_reroute' not in record
    assert not any(len(a) > 1 and 'route_agent.py' in a[1] for a, _ in native.calls)


def test_quota_guard_explicit_provider_warns_if_scarce_but_never_blocks(setup, tmp_path, monkeypatch):
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'antigravity', 'pool_family': 'gemini', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 5.0, 'binding_window': '5h',
         'windows': [{'id': '5h', 'remaining_percent': 5.0, 'used_percent': 95.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    messages = []
    service, native, checkpoint = _cross_setup(
        setup, succ_modes=[{'id': 'default'}, {'id': 'full-access'}],
    )
    service.progress = messages.append
    record = service.handoff(checkpoint, quiesced=True, requested_provider='antigravity/gemini-4-neon')
    assert record['provider'] == 'antigravity' and record['model'] == 'gemini-4-neon'
    assert 'quota_reroute' not in record
    assert any('honoring explicit --provider' in m and '5%' in m for m in messages)


def test_quota_guard_fails_safe_on_corrupt_aiuse(setup, tmp_path, monkeypatch):
    bad = tmp_path / 'corrupt-aiuse.json'
    bad.write_text('{not valid json')
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(bad))
    service, native, checkpoint = _cross_setup(setup)
    record = service.handoff(checkpoint, quiesced=True)
    assert record['provider'] == 'claude' and record['model'] == 'claude-opus-5-5'
    assert 'quota_reroute' not in record


def test_quota_guard_fable_sublimit_and_codex_floor(setup, tmp_path, monkeypatch):
    # Claude Fable model: weekly is 50%, but Fable sublimit is 8% (< 15% frontier1_min_left).
    canned = _canned_aiuse(tmp_path, [
        {'provider': 'claude', 'pool_family': 'default', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 50.0, 'binding_window': 'weekly',
         'windows': [
             {'id': 'weekly', 'remaining_percent': 50.0, 'used_percent': 50.0},
             {'id': 'fable', 'pool_family': 'fable', 'quota_scope': 'model_sublimit',
              'remaining_percent': 8.0, 'used_percent': 92.0},
         ]},
        {'provider': 'codex', 'pool_family': 'openai_api', 'age_seconds': 30,
         'usable_now': True, 'headroom_percent': 18.0, 'binding_window': 'credits',
         'windows': [{'id': 'credits', 'remaining_percent': 18.0, 'used_percent': 82.0}]},
    ])
    monkeypatch.setenv('ROUTE_AGENT_AIUSE_JSON', str(canned))
    service, native, checkpoint = _cross_setup(
        setup, pred_model='claude-fable-5-2', succ_modes=[{'id': 'full-access'}],
    )
    native.route_choice = {
        'service': 'antigravity-neon', 'agent': 'antigravity',
        'model': 'gemini-4-neon --effort high', 'remaining': 80.0,
    }
    record = service.handoff(checkpoint, quiesced=True)
    assert record['quota_reroute']['window'] == 'fable'
    assert record['quota_reroute']['source_remaining_pct'] == 8.0

    # Codex gpt-6.2-sol at 18% (< 25% codex:judgment estimate floor) also reads scarce.
    codex_status = service.check_pool_headroom('codex', 'gpt-6.2-sol', str(tmp_path))
    assert codex_status['pool'] == 'codex' and codex_status['scarce'] is True and codex_status['floor'] == 25.0


def test_cli_exposes_allow_scarce_pool_on_handoff_only():
    cli = str(REPO / 'bin' / 'ade-self-session')
    ok = subprocess.run([cli, 'handoff', '--help'], capture_output=True, text=True, check=False)
    assert ok.returncode == 0 and '--allow-scarce-pool' in ok.stdout
    bad = subprocess.run([cli, 'compact', '--checkpoint', '/x', '--request-id', 'r', '--allow-scarce-pool'],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 2


# --- 2026-11-23: automatic legacy com.djbclark.ade-net-resume.plist repoint in finish() ------------------------------

def _write_net_resume_plist(path: Path, argv, *, label='com.djbclark.ade-net-resume', mode=0o644):
    import plistlib
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        'Label': label,
        'ProgramArguments': list(argv),
        'StartInterval': 60,
        'RunAtLoad': False,
        'EnvironmentVariables': {'PATH': '/usr/local/bin:/usr/bin:/bin'},
    }
    path.write_bytes(plistlib.dumps(doc, fmt=plistlib.FMT_XML, sort_keys=False))
    path.chmod(mode)
    return path


def test_finish_repoints_legacy_net_resume_plist_atomically_and_reloads(setup, tmp_path):
    import plistlib
    plist_path = tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'
    orig_argv = ['/opt/ade/bin/ade-job-run', '--lock-dir', '/tmp/adm', 'com.djbclark.ade-net-resume', '--',
                 '/opt/ade/bin/ade-net-resume', '--lead', PRED, '--quota', '--apply']
    _write_net_resume_plist(plist_path, orig_argv, mode=0o644)
    reloaded = []
    service, native, path = finished_up_to_archive(setup)
    service.net_resume_plist = plist_path
    service.net_resume_reloader = lambda p, lbl: reloaded.append((p, lbl))

    out = service.finish(path)
    assert out['status'] == 'archived' and out['net_resume_plist'] == 'repointed' and 'net_resume_plist_error' not in out
    doc = plistlib.loads(plist_path.read_bytes())
    assert doc['ProgramArguments'] == [
        '/opt/ade/bin/ade-job-run', '--lock-dir', '/tmp/adm', 'com.djbclark.ade-net-resume', '--',
        '/opt/ade/bin/ade-net-resume', '--lead', SUCC, '--quota', '--apply',
    ]
    assert '--transition-below' not in doc['ProgramArguments']
    assert doc['StartInterval'] == 60 and doc['EnvironmentVariables'] == {'PATH': '/usr/local/bin:/usr/bin:/bin'}
    assert (plist_path.stat().st_mode & 0o777) == 0o644
    assert [p.name for p in plist_path.parent.iterdir()] == ['com.djbclark.ade-net-resume.plist']
    assert reloaded == [(plist_path, 'com.djbclark.ade-net-resume')]

    # Idempotent re-run: keeps outcome, does not reload again.
    again = service.finish(path)
    assert again['net_resume_plist'] == 'repointed' and len(reloaded) == 1


def test_finish_net_resume_plist_darwin_runner_calls_bootout_and_bootstrap(setup, tmp_path, monkeypatch):
    plist_path = tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead', PRED, '--quota', '--apply'])
    monkeypatch.setattr(ss.sys, 'platform', 'darwin')
    service, native, path = finished_up_to_archive(setup)
    service.net_resume_plist = plist_path

    out = service.finish(path)
    assert out['net_resume_plist'] == 'repointed'
    uid = os.getuid()
    assert native.launchctl_calls == [
        ['launchctl', 'bootout', f'gui/{uid}/com.djbclark.ade-net-resume'],
        ['launchctl', 'bootstrap', f'gui/{uid}', str(plist_path)],
    ]


def test_finish_net_resume_plist_leaves_lead_file_and_other_chains_and_symlinks_alone(setup, tmp_path):
    plist_path = tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'
    reloaded = []
    service, native, path = finished_up_to_archive(setup)
    service.net_resume_plist = plist_path
    service.net_resume_reloader = lambda p, lbl: reloaded.append((p, lbl))

    # Absent plist -> absent, nothing created.
    out = service.finish(path)
    assert out['net_resume_plist'] == 'absent' and not plist_path.exists() and not reloaded

    # --lead-file plist -> uses-lead-file, untouched.
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead-file', '/tmp/lead', '--apply'])
    before = plist_path.read_bytes()
    assert service.finish(path)['net_resume_plist'] == 'uses-lead-file'
    assert plist_path.read_bytes() == before and not reloaded

    # Another chain's lead -> unchanged-not-predecessor.
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead', OTHER, '--apply'])
    before = plist_path.read_bytes()
    assert service.finish(path)['net_resume_plist'] == 'unchanged-not-predecessor'
    assert plist_path.read_bytes() == before and not reloaded

    # Already naming successor -> already-successor, no reload.
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead', SUCC, '--apply'])
    assert service.finish(path)['net_resume_plist'] == 'already-successor' and not reloaded

    # Symlink -> unchanged-not-regular, never followed.
    target = tmp_path / 'real.plist'
    _write_net_resume_plist(target, ['/opt/ade/bin/ade-net-resume', '--lead', PRED, '--apply'])
    plist_path.unlink()
    plist_path.symlink_to(target)
    before = target.read_bytes()
    assert service.finish(path)['net_resume_plist'] == 'unchanged-not-regular'
    assert plist_path.is_symlink() and target.read_bytes() == before and not reloaded


def test_finish_net_resume_plist_reload_failure_and_malformed_xml_are_non_fatal(setup, tmp_path):
    plist_path = tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead', PRED, '--apply'])
    service, native, path = finished_up_to_archive(setup)
    service.net_resume_plist = plist_path

    def boom(p, lbl):
        raise RuntimeError('launchctl bootstrap exited 5')

    service.net_resume_reloader = boom
    out = service.finish(path)
    assert out['status'] == 'archived' and out['net_resume_plist'] == 'error'
    assert 'launchctl bootstrap exited 5' in out['net_resume_plist_error']

    # Re-run retries reload cleanly once launchctl recovers.
    retried = []
    service.net_resume_reloader = lambda p, lbl: retried.append((p, lbl))
    again = service.finish(path)
    assert again['net_resume_plist'] == 'repointed' and 'net_resume_plist_error' not in again
    assert retried == [(plist_path, 'com.djbclark.ade-net-resume')]

    # Malformed XML plist is recorded as error without failing finish.
    plist_path.write_text('not xml at all')
    bad = service.finish(path)
    assert bad['status'] == 'archived' and bad['net_resume_plist'] == 'error'


def test_failed_archive_never_touches_net_resume_plist(setup, tmp_path):
    plist_path = tmp_path / 'LaunchAgents' / 'com.djbclark.ade-net-resume.plist'
    _write_net_resume_plist(plist_path, ['/opt/ade/bin/ade-net-resume', '--lead', PRED, '--apply'])
    before = plist_path.read_bytes()
    service, native, path = finished_up_to_archive(setup)
    service.net_resume_plist = plist_path
    native.archive_result = (1, '', envelope('ARCHIVE_FAILED', 'busy'))
    with pytest.raises(ss.NativeError):
        service.finish(path)
    assert plist_path.read_bytes() == before
    assert 'net_resume_plist' not in json.loads(path.read_text())


# --- 2026-11-23: PR #955 carried review LOWs (1-4) -------------------------------------------------------------------

@pytest.mark.parametrize('val', ['N/A', 'n/a', 'na', 'NA', 'TBD', 'tbd', 'unknown', 'Unknown'])
def test_pr955_low1_frontmatter_null_tokens_return_none(tmp_path, val):
    cp = tmp_path / 'cp.md'
    cp.write_text(f'---\nrepo: {val}\n---\nbody\n')
    assert ss.checkpoint_frontmatter_repo(str(cp)) is None


def test_pr955_low2_resolve_sibling_resolves_symlinked_module_first(tmp_path, monkeypatch):
    real_dir = tmp_path / 'real_bin'
    link_dir = tmp_path / 'link_bin'
    real_dir.mkdir()
    link_dir.mkdir()
    real_mod = real_dir / 'ade_self_session.py'
    real_mod.write_text('# stub\n')
    real_worker = real_dir / 'ade-worker-run'
    real_worker.write_text('#!/bin/sh\n')
    link_mod = link_dir / 'ade_self_session.py'
    link_mod.symlink_to(real_mod)
    monkeypatch.setattr(ss, '__file__', str(link_mod))
    cmd, _, _ = ss.build_rename_lead_command({'successor': SUCC})
    assert cmd.startswith(str(real_worker.resolve()) + ' ')


def test_pr955_low3_frontmatter_multiline_blank_line_continuation(tmp_path):
    cp_cont = tmp_path / 'cont.md'
    cp_cont.write_text('---\nrepo: stayturgid\n\n  other-repo\n---\n')
    assert ss.checkpoint_frontmatter_repo(str(cp_cont)) is None

    cp_ok = tmp_path / 'ok.md'
    cp_ok.write_text('---\nrepo: stayturgid\n\nother: value\n---\n')
    assert ss.checkpoint_frontmatter_repo(str(cp_ok)) == 'stayturgid'


def test_pr955_low4_advise_lead_window_guards_resolve_and_unexpected_errors(setup, monkeypatch):
    # _resolve_sibling falls back to os.path.abspath when Path.resolve raises OSError/RuntimeError.
    orig_resolve = Path.resolve

    def fail_resolve(self, *args, **kwargs):
        if self.name in ('ade_self_session.py', 'ade-worker-run'):
            raise RuntimeError('symlink loop')
        return orig_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', fail_resolve)
    cmd, _, _ = ss.build_rename_lead_command({'successor': SUCC})
    assert 'ade-worker-run rename-lead --lead ' + SUCC in cmd
    monkeypatch.setattr(Path, 'resolve', orig_resolve)

    # Unexpected non-SessionError inside advise_lead_window is caught and recorded without failing finish.
    service, native, path = finished_up_to_archive(setup)
    monkeypatch.setattr(ss, 'build_rename_lead_command', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    out = service.finish(path)
    assert out['status'] == 'archived'
    assert out['lead_window']['state'] == 'unknown'
    assert 'RuntimeError: boom' in out['lead_window']['reason']


@pytest.mark.parametrize('missing', [None, '', '   '])
def test_q122_missing_paseo_agent_id_gives_non_paseo_local_handoff_hint(setup, missing):
    """Carried #122 (2026-11-25): unset/blank PASEO_AGENT_ID keeps 'a full UUID is required'
    and points non-Paseo / Herdr Claude Code sessions to local Steps 0-7 + manual /new + /baton."""
    service, native, checkpoint = setup
    if missing is None:
        service.env.pop('PASEO_AGENT_ID', None)
    else:
        service.env['PASEO_AGENT_ID'] = missing
    with pytest.raises(ss.SessionError) as exc:
        service.handoff(checkpoint, quiesced=True)
    msg = str(exc.value)
    assert 'PASEO_AGENT_ID is unset' in msg
    assert 'a full UUID is required' in msg
    assert 'Paseo-only' in msg
    assert 'Steps 0-7' in msg and 'skip Step 9' in msg and '/new then /baton <exact Tier 1 pointer>' in msg
    assert native.calls == []
    assert not list(service.state.glob('handoff-*.json'))

    with pytest.raises(ss.SessionError) as exc_compact:
        service.compact(checkpoint, request_id='c-nonpaseo')
    assert 'PASEO_AGENT_ID is unset' in str(exc_compact.value)
    assert '/new then /baton <exact Tier 1 pointer>' in str(exc_compact.value)


def test_q122_malformed_paseo_agent_id_keeps_strict_ident_error(setup):
    """Non-empty malformed PASEO_AGENT_ID still raises ident()'s strict 'a full UUID is required'."""
    service, native, checkpoint = setup
    service.env['PASEO_AGENT_ID'] = 'not-a-uuid'
    with pytest.raises(ss.SessionError) as exc:
        service.handoff(checkpoint, quiesced=True)
    assert str(exc.value) == 'a full UUID is required'
    assert native.calls == []
