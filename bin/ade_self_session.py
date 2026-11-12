"""Explicit same-host self-session requests; no unattended crash restart.

Native CLI contract inspected at getpaseo/paseo 4df5307 (2026-11-12).
A durable intent precedes every irreversible request. Ambiguous sends/creates
are not replayed; a queued receipt is never completion or acknowledgement.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import stat
import datetime
import uuid
from typing import Callable


class SessionError(RuntimeError):
    pass


def ident(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise SessionError('a full UUID is required') from None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SessionError('input must be a regular file')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SessionError('input exceeds byte limit')
    return data


def write_atomic(path: Path, data: bytes) -> None:
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Service:
    def __init__(self, state: Path, home: Path, *, env=None, runner=None,
                 planner=None, verifier=None):
        self.state = state.resolve()
        self.home = home.resolve()
        self.env = dict(os.environ if env is None else env)
        self.runner = runner or subprocess.run
        self.planner = planner
        self.verifier = verifier

    def native(self, *args, detached=False):
        env = dict(self.env)
        if detached:
            for key in ('PASEO_AGENT_ID', 'PASEO_AGENT_CWD', 'PASEO_WORKSPACE_ID'):
                env.pop(key, None)
        try:
            result = self.runner(['paseo', '--home', str(self.home), '--json', *args],
                                 env=env, capture_output=True, text=True, timeout=30)
            if len(result.stdout or '') > 16 * 1024 * 1024:
                raise SessionError('native response too large; inspect before retry')
            data = json.loads(result.stdout)
            if result.returncode != 0 and not (args[:2] == ('agent', 'send') and result.returncode == 5):
                raise SessionError('native command refused or failed; inspect before retry')
            return data
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise SessionError('native outcome unknown; inspect before retry') from None

    def actor(self):
        return ident(self.env.get('PASEO_AGENT_ID', ''))

    def inspect(self, agent):
        row = self.native('agent', 'inspect', ident(agent))
        if not isinstance(row, dict) or row.get('Id') != agent:
            raise SessionError('native identity readback unavailable')
        return row

    @contextlib.contextmanager
    def transaction(self, key):
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.state / (key + '.json')
        with (self.state / (key + '.lock')).open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SessionError('session transaction busy; no request sent') from None
            try:
                record = json.loads(read_regular(path, 262144)) if path.exists() else None
                yield path, record
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def save(self, path, record):
        write_atomic(path, (json.dumps(record, sort_keys=True, indent=2) + '\n').encode())

    def git_head(self, cwd):
        try:
            p = self.runner(['git', '-C', cwd, 'rev-parse', 'HEAD'], capture_output=True,
                            text=True, timeout=10)
            value = p.stdout.strip()
            if p.returncode == 0 and re.fullmatch(r'[0-9a-f]{40}', value):
                return value
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise SessionError('exact repository HEAD unavailable')

    def checkpoint(self, path, *, token):
        # User/agent-authored nonsecret briefing, not harvested credentials/logs.
        data = read_regular(path, 1024 * 1024)
        if not data.strip() or len(data) > 1024 * 1024:
            raise SessionError('checkpoint must be nonempty and at most 1 MiB')
        data.decode('utf-8')
        target = self.state / (token + '.checkpoint.md')
        write_atomic(target, data)
        return str(target), digest(data)

    def mode_plan(self, source, requested=None):
        # Same-provider/model succession only: source modes are live native IDs,
        # not reconstructed from provider-ls's comma-joined display labels.
        planner = self.planner
        if planner is None:
            from paseo_yolo import plan_unattended_config
            planner = plan_unattended_config
        providers = self.native('provider', 'ls')
        if not isinstance(providers, list):
            raise SessionError('native provider registry unavailable')
        row = next((r for r in providers if isinstance(r, dict) and r.get('provider') == source['Provider']), None)
        if not row or row.get('status') not in ('available', 'ready') or row.get('enabled') not in (True, 'Enabled'):
            raise SessionError('provider unavailable')
        catalog = {**row, 'modes': source.get('AvailableModes')}
        plan = planner(source['Provider'], catalog, requested=requested)
        if (plan.get('status') not in ('ready', 'exempt') or not plan.get('mode_id')
                or plan.get('provider_options') or not isinstance(catalog['modes'], list)
                or not any(isinstance(m, dict) and m.get('id') == plan['mode_id'] for m in catalog['modes'])):
            raise SessionError('supported unattended successor mode unavailable')
        return plan

    def verify_successor(self, record):
        verifier = self.verifier
        if verifier is None:
            from paseo_yolo import verify_unattended_snapshot
            verifier = verify_unattended_snapshot
        row = self.inspect(record['successor'])
        if (row.get('Archived') is not False or row.get('Cwd') != record['cwd']
                or row.get('Provider') != record['provider'] or row.get('Model') != record['model']
                or row.get('ParentAgentId') is not None or row.get('PendingPermissions') != []):
            raise SessionError('successor identity, placement, parent or permission readback mismatch')
        checked = verifier(record['mode_plan'], row)
        if not checked.get('ok'):
            raise SessionError('successor unattended mode not verified')
        return row

    def handoff(self, checkpoint: Path, *, quiesced: bool, requested_mode=None):
        predecessor = self.actor()
        with self.transaction('handoff-' + predecessor) as (path, existing):
            if existing:
                if (not isinstance(existing, dict) or existing.get('home') != str(self.home)
                        or existing.get('kind') != 'handoff' or existing.get('predecessor') != predecessor):
                    raise SessionError('existing transaction belongs to a different daemon or identity')
                if requested_mode and existing.get('mode_plan', {}).get('mode_id') != requested_mode:
                    raise SessionError('existing transaction has a different requested mode; no create replayed')
                return existing  # duplicate/ambiguous creation is never replayed
            if not quiesced:
                raise SessionError('finish other writes/jobs and attest --quiesced first')
            source = self.inspect(predecessor)
            if (source.get('Archived') is not False or source.get('PendingPermissions') != []
                    or source.get('Status') not in ('idle', 'running')):
                raise SessionError('predecessor archived or permission state unresolved')
            cwd = source.get('Cwd')
            if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                raise SessionError('absolute predecessor cwd unavailable')
            if (not isinstance(source.get('Provider'), str) or not source['Provider']
                    or not isinstance(source.get('Model'), str) or source['Model'] in ('', '-', 'default')):
                raise SessionError('concrete predecessor provider/model unavailable')
            workspace = ident(self.env.get('PASEO_WORKSPACE_ID', ''))
            plan = self.mode_plan(source, requested_mode)
            token = str(uuid.uuid4())
            preserved, sha = self.checkpoint(checkpoint, token=token)
            record = {'schema_version': 1, 'kind': 'handoff', 'token': token,
                      'predecessor': predecessor, 'successor': None, 'home': str(self.home),
                      'cwd': cwd, 'workspace': workspace, 'provider': source['Provider'],
                      'model': source['Model'], 'mode_plan': plan, 'head': self.git_head(cwd),
                      'checkpoint': preserved, 'checkpoint_sha256': sha,
                      'status': 'creation-unknown', 'ack': None, 'record': str(path)}
            self.save(path, record)  # survives crash before/after unknown native effect
            tool = shlex.quote(str(Path(__file__).with_name('ade-self-session').resolve()))
            common = f"{tool} --state-dir {shlex.quote(str(self.state))} --paseo-home {shlex.quote(str(self.home))}"
            record_arg = '--record ' + shlex.quote(str(path))
            ack_arg = '--ack-file ' + shlex.quote(str(self.state / (token + '.ack.json')))
            mode_instruction = ('Preserve the explicit operator-requested restrictive mode. '
                                if plan['status'] == 'exempt' else 'Ordinary trusted successor; retain unattended mode. ')
            prompt = (
                f'Self-handoff {token}. {mode_instruction}'
                f'Read checkpoint {preserved}. Transaction {path}. Do not write project files yet. '
                f'Write your own nonsecret JSON acknowledgement at {self.state / (token + ".ack.json")} '
                'containing token, checkpoint_sha256, head and next_action. Read and confirm the '
                f'checkpoint and scope yourself, then run {common} accept {record_arg} {ack_arg}. '
                'If creation receipt is not yet saved, wait and retry accept only. '
                f'After acknowledgement, let predecessor finish; run {common} finish {record_arg}. '
                'Never force/archive a workspace. Continue project work only after finish confirms archived '
                'and you have reconciled exclusive workspace ownership under the repository rules. '
                'If any check fails, preserve both sessions and report it.'
            )
            try:
                result = self.native('agent', 'run', '--workspace', workspace, '--cwd', cwd,
                                     '--provider', source['Provider'] + '/' + source['Model'],
                                     '--mode', plan['mode_id'], '--no-wait', '--label',
                                     'ade.handoff=' + token, '--', prompt, detached=True)
                if not isinstance(result, dict):
                    raise SessionError('malformed creation receipt')
                record['successor'] = ident(result.get('agentId', ''))
                record['status'] = 'awaiting-ack'
            except SessionError:
                self.save(path, record)
                return record
            self.save(path, record)
            return record

    def load_record(self, path):
        if path.parent.resolve() != self.state:
            raise SessionError('record must be in this state directory')
        return 'handoff-' + ident(path.stem.removeprefix('handoff-'))

    def reconcile(self, path):
        with self.transaction(self.load_record(path)) as (target, record):
            if not record or record.get('home') != str(self.home):
                raise SessionError('transaction unavailable on this daemon home')
            if self.actor() != record['predecessor']:
                raise SessionError('only predecessor reconciles an ambiguous creation')
            if record['status'] != 'creation-unknown':
                return record
            rows = self.native('agent', 'ls', '-a', '-g', '--label', 'ade.handoff=' + record['token'])
            if not isinstance(rows, list) or len(rows) != 1:
                raise SessionError('need exactly one token-labelled successor; no create replayed')
            record['successor'] = ident(rows[0].get('id', ''))
            self.verify_successor(record)
            record['status'] = 'awaiting-ack'
            self.save(target, record)
            return record

    def accept(self, path, ack_file):
        with self.transaction(self.load_record(path)) as (target, record):
            if not record or record.get('home') != str(self.home):
                raise SessionError('transaction unavailable on this daemon home')
            if self.actor() != record.get('successor'):
                raise SessionError('only exact recorded successor can acknowledge')
            self.verify_successor(record)
            if digest(read_regular(Path(record['checkpoint']), 1024 * 1024)) != record['checkpoint_sha256']:
                raise SessionError('preserved checkpoint changed')
            if self.git_head(record['cwd']) != record['head']:
                raise SessionError('repository HEAD changed; reconcile before acknowledgement')
            ack = json.loads(read_regular(ack_file, 65536))
            if (not isinstance(ack, dict) or any(ack.get(k) != record[k]
                    for k in ('token', 'checkpoint_sha256', 'head'))
                    or not isinstance(ack.get('next_action'), str) or not ack['next_action'].strip() or len(ack['next_action']) > 4096):
                raise SessionError('ack must attest token, checkpoint digest, HEAD and next action')
            safe_ack = {k: ack[k] for k in ('token', 'checkpoint_sha256', 'head', 'next_action')}
            safe_ack['agent_id'] = record['successor']
            if record.get('ack') and record['ack'] != safe_ack:
                raise SessionError('conflicting acknowledgement; preserve existing receipt')
            if record['status'] not in ('awaiting-ack', 'acknowledged'):
                raise SessionError('transaction is not awaiting acknowledgement')
            record['ack'] = safe_ack
            record['status'] = 'acknowledged'
            self.save(target, record)
            return record

    def finish(self, path):
        with self.transaction(self.load_record(path)) as (target, record):
            if not record or record.get('home') != str(self.home):
                raise SessionError('transaction unavailable on this daemon home')
            if self.actor() != record.get('successor') or not record.get('ack'):
                raise SessionError('recorded successor acknowledgement required before retirement')
            if record['status'] == 'archived':
                return record
            self.verify_successor(record)
            if (digest(read_regular(Path(record['checkpoint']), 1024 * 1024)) != record['checkpoint_sha256']
                    or self.git_head(record['cwd']) != record['head']):
                raise SessionError('checkpoint or HEAD changed; preserve predecessor')
            predecessor = self.inspect(record['predecessor'])
            if predecessor.get('Archived') is not True:
                if predecessor.get('Status') != 'idle' or predecessor.get('PendingPermissions') != []:
                    raise SessionError('predecessor must be idle without permission waits; never force archive')
                record['status'] = 'archive-unknown'
                self.save(target, record)
                self.native('agent', 'archive', record['predecessor'])  # never --force/workspace archive
                predecessor = self.inspect(record['predecessor'])
                if predecessor.get('Archived') is not True:
                    raise SessionError('archive unconfirmed; preserve transaction and inspect before retry')
            record['status'] = 'archived'
            self.save(target, record)
            return record

    def compact(self, checkpoint, *, request_id):
        predecessor = self.actor()
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', request_id):
            raise SessionError('request id must be 1–64 letters, digits, underscores or hyphens')
        with self.transaction('compact-' + predecessor + '-' + request_id) as (path, existing):
            if existing:
                if (not isinstance(existing, dict) or existing.get('home') != str(self.home)
                        or existing.get('kind') != 'compact' or existing.get('predecessor') != predecessor):
                    raise SessionError('existing transaction belongs to a different daemon or identity')
                return existing  # no ambiguous replay, even after a timeout
            source = self.inspect(predecessor)
            if (source.get('Archived') is not False or source.get('PendingPermissions') != []
                    or source.get('Provider') not in ('claude', 'codex', 'pi')):
                raise SessionError('native compact unsupported or permission state unresolved')
            token = str(uuid.uuid4())
            preserved, sha = self.checkpoint(checkpoint, token=token)
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            record = {'schema_version': 1, 'kind': 'compact', 'token': token,
                      'predecessor': predecessor, 'home': str(self.home), 'record': str(path),
                      'checkpoint': preserved, 'checkpoint_sha256': sha,
                      'status': 'send-unknown', 'requested_at': timestamp,
                      'completion_confirmed': False,
                      'completion_limit': 'CLI exposes no request-correlated compaction completion; inspect provider timeline, never infer success from receipt'}
            self.save(path, record)
            try:
                result = self.native('agent', 'send', predecessor, '--no-wait', '--behavior', 'steer', '--', '/compact')
                if (not isinstance(result, dict) or result.get('agentId') != predecessor
                        or result.get('status') not in ('queued', 'sent', 'completed')):
                    raise SessionError('invalid send receipt')
                record['status'] = 'requested'
                record['delivery_status'] = result['status']
            except SessionError:
                pass
            self.save(path, record)
            return record

    def status(self, path):
        if path.parent.resolve() != self.state or not re.fullmatch(
                r'(?:handoff-[0-9a-f-]{36}|compact-[0-9a-f-]{36}-[a-zA-Z0-9_-]{1,64})\.json', path.name):
            raise SessionError('record must be a session transaction in this state directory')
        record = json.loads(read_regular(path, 262144))
        if not isinstance(record, dict) or record.get('home') != str(self.home):
            raise SessionError('transaction unavailable on this daemon home')
        return record  # persisted observation only, no native probes/retries
