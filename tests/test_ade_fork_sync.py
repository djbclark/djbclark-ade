"""Synthetic Git integration tests. Run in Linux CI, never against live forks."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
from ade_fork_sync import Held, Sync, SyncSpec


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, text=True,
                          capture_output=True).stdout.strip()


class Permit:
    def permits(self, spec, operation):
        return True


class Network:
    """Map trusted-looking URLs to local fixture repos; fake only GitHub."""
    def __init__(self, mapping):
        self.mapping = mapping
        self.prs = []
        self.created = 0
        self.release = {'draft': False, 'prerelease': False, 'tag_name': 'v1'}
        self.pushed = 0

    def __call__(self, argv, cwd=None):
        if argv[0] == 'gh':
            if argv[1:3] == ['api', 'repos/up/repo/releases/latest']:
                out = json.dumps(self.release)
            elif argv[1:3] == ['pr', 'list']:
                out = json.dumps(self.prs)
            elif argv[1:3] == ['pr', 'create']:
                self.created += 1
                branch = argv[argv.index('--head') + 1]
                head = git(self.mapping['https://github.com/fork/repo'], 'rev-parse', branch)
                self.prs = [{'url': 'https://github.com/fork/repo/pull/1',
                             'headRefName': branch, 'headRefOid': head, 'baseRefName': 'main'}]
                out = self.prs[0]['url']
            else:
                raise AssertionError(argv)
            return subprocess.CompletedProcess(argv, 0, out, '')
        if 'push' in argv:
            self.pushed += 1
        args = [self.mapping.get(x, x) for x in argv]
        return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=30)


@pytest.fixture
def setup(tmp_path):
    up, fork, work = [tmp_path / n for n in ('up', 'fork', 'work')]
    up.mkdir()
    git(up, 'init', '-b', 'main')
    git(up, 'config', 'user.name', 'Fixture')
    git(up, 'config', 'user.email', 'fixture@example.invalid')
    (up / 'shared').write_text('base\n')
    git(up, 'add', '.')
    git(up, 'commit', '-m', 'base')
    git(tmp_path, 'clone', '--bare', str(up), str(fork))
    git(tmp_path, 'clone', str(fork), str(work))
    git(work, 'config', 'user.name', 'Fixture')
    git(work, 'config', 'user.email', 'fixture@example.invalid')
    (work / 'patch').write_text('local patch')
    git(work, 'add', '.')
    git(work, 'commit', '-m', 'patch')
    git(work, 'push', 'origin', 'main')
    (up / 'new').write_text('upstream')
    git(up, 'add', '.')
    git(up, 'commit', '-m', 'upstream')
    git(up, 'tag', 'v1')
    network = Network({'https://github.com/up/repo': str(up), 'https://github.com/fork/repo': str(fork)})
    sync = Sync(network, Permit())
    spec = SyncSpec('test', 'https://github.com/fork/repo', 'https://github.com/up/repo')
    return sync, spec, up, fork, work, network


def test_merge_and_retry(setup):
    sync, spec, up, fork, work, net = setup
    plan = sync.discover(spec)
    result = sync.apply(plan, work, spec.fork)
    assert result['status'] == 'pr_pending'
    assert (work / 'patch').read_text() == 'local patch'
    assert (work / 'new').read_text() == 'upstream'
    assert git(fork, 'rev-parse', 'main') == plan.base
    assert git(work, 'show', '-s', '--format=%P', result['head']).split() == [plan.base, plan.upstream_commit]
    assert sync.apply(plan, work, spec.fork) == result
    assert net.created == net.pushed == 1


def test_conflict_retains_diagnostics(setup):
    sync, spec, up, fork, work, net = setup
    (work / 'shared').write_text('fork\n')
    git(work, 'commit', '-am', 'fork conflict'); git(work, 'push', 'origin', 'main')
    (up / 'shared').write_text('upstream\n')
    git(up, 'commit', '-am', 'upstream conflict'); git(up, 'tag', '-f', 'v1')
    plan = sync.discover(spec)
    with pytest.raises(Held, match='conflict'):
        sync.apply(plan, work, spec.fork)
    assert git(fork, 'rev-parse', 'main') == plan.base
    assert git(work, 'ls-files', '--unmerged')
    assert (work.parent / 'work.fork-sync-conflict.txt').exists()
    assert net.pushed == 0


def test_dirty_refuses(setup):
    sync, spec, _, _, work, net = setup
    plan = sync.discover(spec)
    (work / 'untracked').write_text('WIP')
    with pytest.raises(Held, match='dirty'):
        sync.apply(plan, work, spec.fork)
    assert net.pushed == 0


@pytest.mark.parametrize('advance', ['tag', 'base'])
def test_moving_refs(setup, advance):
    sync, spec, up, _, work, net = setup
    plan = sync.discover(spec)
    if advance == 'tag':
        git(up, 'tag', '-f', 'v1', 'HEAD~1')
    else:
        (work / 'extra').write_text('advance')
        git(work, 'add', '.'); git(work, 'commit', '-m', 'advance'); git(work, 'push', 'origin', 'main')
    with pytest.raises(Held, match='changed'):
        sync.apply(plan, work, spec.fork)
    assert net.pushed == 0


@pytest.mark.parametrize('remote', ['https://github.com/up/repo', 'https://github.com/other/repo'])
def test_wrong_remote(setup, remote):
    sync, spec, _, _, work, net = setup
    with pytest.raises(Held, match='publication_remote'):
        sync.apply(sync.discover(spec), work, remote)
    assert net.pushed == 0


def test_authority_and_patch_queue(setup):
    sync, spec, _, _, work, net = setup
    plan = sync.discover(spec)
    with pytest.raises(Held, match='policy_authority'):
        Sync(net).apply(plan, work, spec.fork)
    from dataclasses import replace
    with pytest.raises(Held, match='adapter_required'):
        sync.discover(replace(spec, strategy='patch-queue'))


def test_stable_no_release_and_bad_runner(setup):
    sync, spec, *_, net = setup
    net.release = {'message': 'Not Found'}
    with pytest.raises(Held, match='stable_release'):
        sync.discover(spec)
    with pytest.raises(Held, match='malformed_runner'):
        Sync(lambda *_: {}).discover(spec)


def test_unrelated_pr_and_malformed_api(setup):
    sync, spec, _, _, work, net = setup
    plan = sync.discover(spec)
    net.prs = [{'url': 'https://github.com/fork/repo/pull/2', 'headRefName': 'contribution',
                'headRefOid': plan.base, 'baseRefName': 'main'}]
    with pytest.raises(Held, match='unrelated_active_pr'):
        sync.apply(plan, work, spec.fork)
    net.prs = [None]
    with pytest.raises(Held, match='malformed_pr'):
        sync.apply(plan, work, spec.fork)
    assert net.pushed == 0


def test_publish_disables_inherited_extra_writes(setup):
    sync, spec, _, fork, work, net = setup
    dep = work.parent / 'dependency-source'
    dep.mkdir()
    git(dep, 'init', '-b', 'main')
    git(dep, 'config', 'user.name', 'Fixture')
    git(dep, 'config', 'user.email', 'fixture@example.invalid')
    (dep / 'file').write_text('baseline')
    git(dep, 'add', '.'); git(dep, 'commit', '-m', 'baseline')
    remote = work.parent / 'dependency-remote'
    git(work.parent, 'clone', '--bare', str(dep), str(remote))
    git(work, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(remote), 'dependency')
    sub = work / 'dependency'
    git(sub, 'config', 'user.name', 'Fixture')
    git(sub, 'config', 'user.email', 'fixture@example.invalid')
    (sub / 'file').write_text('unpublished dependency change')
    git(sub, 'commit', '-am', 'unpublished dependency')
    git(work, 'add', '.'); git(work, 'commit', '-m', 'dependency pointer')
    git(work, 'push', 'origin', 'main')
    git(work, 'tag', '-a', 'private-reachable-tag', '-m', 'must stay local')
    git(work, 'config', 'push.followTags', 'true')
    git(work, 'config', 'push.recurseSubmodules', 'on-demand')
    fork_before = set(git(fork, 'show-ref').splitlines())
    dep_before = git(remote, 'show-ref')
    plan = sync.discover(spec)
    result = sync.apply(plan, work, spec.fork)
    assert set(git(fork, 'show-ref').splitlines()) - fork_before == {
        result['head'] + ' refs/heads/' + plan.branch}
    assert git(remote, 'show-ref') == dep_before
    assert not git(fork, 'tag', '--list')
    assert net.pushed == 1


def test_process_death_releases_persistent_lock(setup):
    sync, spec, _, _, work, _ = setup
    plan = sync.discover(spec)
    code = '''
import os, signal, sys
from types import SimpleNamespace
from ade_fork_sync import Sync, SyncSpec
class Permit:
    def permits(self, *args): return True
class Crash(Sync):
    def _apply(self, *args, **kwargs):
        os.kill(os.getpid(), signal.SIGKILL)
spec = SyncSpec('test', 'https://github.com/fork/repo', 'https://github.com/up/repo')
Crash(authority=Permit()).apply(SimpleNamespace(spec=spec), sys.argv[1], spec.fork)
'''
    import os
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'bin'))
    child = subprocess.run([sys.executable, '-c', code, str(work)], env=env,
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == -9, child.stderr
    lock = work.parent / 'work.fork-sync.lock'
    inode = lock.stat().st_ino
    assert sync.apply(plan, work, spec.fork)['status'] == 'pr_pending'
    assert lock.stat().st_ino == inode
    assert sync.apply(plan, work, spec.fork)['status'] == 'pr_pending'
    assert lock.stat().st_ino == inode


@pytest.mark.parametrize('revoke_at', ['merge', 'push'])
@pytest.mark.parametrize('revoked_value', [False, 1, 'true', None])
def test_unattended_authority_rechecked_at_each_write(setup, revoke_at, revoked_value):
    sync, spec, _, _, work, net = setup
    class Revocable:
        app = True
        def permits(self, spec, operation):
            return self.app if operation == 'app-token-ci' else True
    authority = Revocable()
    def runner(argv, cwd=None):
        result = net(argv, cwd)
        if revoke_at in argv:
            authority.app = revoked_value
        return result
    sync = Sync(runner, authority)
    plan = sync.discover(spec)
    with pytest.raises(Held, match='github_app_token_required'):
        sync.apply(plan, work, spec.fork, unattended=True)
    assert net.created == 0
    assert net.pushed == (1 if revoke_at == 'push' else 0)
