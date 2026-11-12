"""Cached key worklists must never become current verification or collection."""
from __future__ import annotations

import copy
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'bin'))
import ade_install as ai


@pytest.fixture
def catalog(tmp_path):
    return ai.Catalog(data={
        'component': [
            {'id': 'hard', 'class': 'hard', 'summary': 'Required tool'},
            {'id': 'yes', 'class': 'optional', 'chosen': True},
            {'id': 'no', 'class': 'offered', 'chosen': False},
            {'id': 'never', 'class': 'never'},
        ],
        'key': [
            {'name': name, 'components': links, 'create_url': 'https://example.test/keys',
             'verify_argv': ['must-not-run']}
            for name, links in [
                ('HARD', ['hard']), ('YES', ['yes']), ('NO', ['no']),
                ('NEVER', ['never']), ('SHARED', ['hard', 'no']),
                ('UNLINKED', []), ('UNKNOWN', ['not-recorded']),
                ('PARTIAL', ['hard', 'not-recorded']),
            ]
        ] + [{'name': 'NO_RECIPE', 'components': ['hard'], 'create_url': 'UNKNOWN'}],
    }, path=tmp_path / 'catalog', root=tmp_path)


def cache(status='invalid'):
    return {'schema_version': 1, 'updated_at': '2026-11-10T17:18:19Z',
            'keys': {'HARD': {'status': status, 'detail': 'MUST_NOT_APPEAR'},
                     'NO': {'status': 'invalid'}}}


def test_selection_coverage_and_purity(catalog, monkeypatch):
    before = copy.deepcopy(catalog.data)
    forbidden = Mock(side_effect=AssertionError('unexpected effect'))
    for method in ('keys_observe', 'observe_key_verify', 'observe_secretspec_check',
                   'save_keys_state', '_atomic_write_json', 'load_keys_plan_cache'):
        monkeypatch.setattr(ai, method, forbidden)
    monkeypatch.setattr(ai.subprocess, 'run', forbidden)
    monkeypatch.setattr(ai.shutil, 'which', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    plan = ai.keys_plan(catalog, cache=cache(), cache_status='loaded')
    rows = {r['name']: r for r in plan['keys']}
    assert rows['HARD']['action'] == 'review-credential'
    assert rows['HARD']['purposes'] == ['Required tool']
    assert rows['YES']['selected_components'] == ['yes']
    assert rows['SHARED']['selected_components'] == ['hard']
    for name in ('NO', 'NEVER'):
        assert rows[name]['action'] == 'skip-unchosen'
    assert rows['UNLINKED']['coverage_gaps'] == ['unlinked-key']
    assert rows['UNKNOWN']['action'] == 'resolve-coverage'
    assert rows['UNKNOWN']['unknown_components'] == ['not-recorded']
    assert rows['PARTIAL']['selected_components'] == ['hard']
    assert rows['PARTIAL']['coverage_gaps'] == ['unknown-component']
    assert rows['NO_RECIPE']['create_url'] is None
    assert rows['NO_RECIPE']['coverage_gaps'] == ['no-verify-command', 'creation-url-unknown']
    assert plan['freshness'] == 'unverified'
    assert plan['current_verification'] == 'unknown'
    assert plan['setup_complete'] is False
    assert plan['cached_at'] == '2026-11-10T17:18:19Z'
    assert 'MUST_NOT_APPEAR' not in json.dumps(plan)
    for row in rows.values():
        assert row['execution_authorized'] is False
        assert 'argv' not in row
    assert catalog.data == before
    forbidden.assert_not_called()


@pytest.mark.parametrize(('status', 'action'), [
    ('missing', 'review-credential'), ('invalid', 'review-credential'),
    ('no-quota', 'review-credential'), ('expiring', 'review-credential'),
    ('unreachable', 'retry-verification'), ('error', 'retry-verification'),
    ('ok', 'none-cached-ok'), ('unknown', 'resolve-coverage'),
    ('INJECTED_OUTCOME', 'resolve-coverage'), ([], 'resolve-coverage'),
])
def test_status_semantics(catalog, status, action):
    plan = ai.keys_plan(catalog, cache=cache(status), cache_status='loaded')
    assert plan['keys'][0]['action'] == action
    assert plan['current_verification'] == 'unknown' and plan['setup_complete'] is False
    assert 'INJECTED_OUTCOME' not in json.dumps(plan)


def test_all_cached_ok_is_never_current_verification(catalog):
    state = {'keys': {r['name']: {'status': 'ok'} for r in catalog.keys}}
    plan = ai.keys_plan(catalog, cache=state, cache_status='loaded')
    assert plan['freshness'] == 'unverified'
    assert plan['current_verification'] == 'unknown'
    assert plan['setup_complete'] is False


@pytest.mark.parametrize('timestamp', [
    'payload-not-a-date', '2026-02-30T00:00:00Z', '2026-11-10T99:00:00Z',
    '2026-11-10T00:00:00+00:00', '2026-11-10T00:00:00Z\n', [], None,
])
def test_timestamps_are_strict_and_not_copied(catalog, timestamp):
    state = cache()
    state['updated_at'] = timestamp
    plan = ai.keys_plan(catalog, cache=state, cache_status='loaded')
    assert plan['cached_at'] is None
    assert 'payload-not-a-date' not in json.dumps(plan)


@pytest.mark.parametrize('raw', [
    b'not-json-DISCARD', b'[]', b'{"schema_version":99,"keys":{}}',
    b'{"schema_version":true,"keys":{}}', b'{"schema_version":1,"keys":[]}',
    b'\xff', b' ' * (1024 * 1024 + 1), b'[' * 1100,
])
def test_invalid_cache_is_bounded_unknown(tmp_path, catalog, raw):
    path = tmp_path / 'state.json'
    path.write_bytes(raw)
    state, status = ai.load_keys_plan_cache(path)
    assert state == {} and status == 'invalid'
    plan = ai.keys_plan(catalog, cache=state, cache_status=status)
    assert all(row['cached_status'] == 'unknown' for row in plan['keys'])
    assert 'DISCARD' not in json.dumps(plan)


def test_cache_missing_and_extra_payload(tmp_path, catalog):
    path = tmp_path / 'state.json'
    assert ai.load_keys_plan_cache(path) == ({}, 'missing')
    state = cache()
    state['keys']['HARD']['value'] = 'DISCARD_EXTRA'
    state['other'] = 'DISCARD_EXTRA'
    path.write_text(json.dumps(state))
    loaded, status = ai.load_keys_plan_cache(path)
    plan = ai.keys_plan(catalog, cache=loaded, cache_status=status)
    assert status == 'loaded'
    assert 'DISCARD_EXTRA' not in json.dumps(plan)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob('*')}


@pytest.mark.parametrize('option', ['--root', '--roo', '--roo='])
@pytest.mark.parametrize('json_output', [False, True])
def test_cold_actual_cli_has_no_writes_or_probes(tmp_path, option, json_output):
    root = tmp_path / 'repo'
    bindir = root / 'bin'
    bindir.mkdir(parents=True)
    for name in ('ade-install', 'ade_install.py', 'ade_install_catalog.py', 'ade_config.py', 'model_tiers.py'):
        shutil.copyfile(REPO / 'bin' / name, bindir / name)
    cli = bindir / 'ade-install'
    cli.chmod(0o755)
    config = root / 'config'
    config.mkdir()
    shutil.copyfile(REPO / 'config/install.schema.json', config / 'install.schema.json')
    (config / 'install.toml').write_text('''schema_version = 1
[[component]]
id = "tool"
class = "hard"
probe_argv = ["sudo-secretspec"]
[[key]]
name = "TEST_KEY"
components = ["tool"]
create_url = "https://example.test/keys"
verify_argv = ["sudo-secretspec"]
''')
    tripwire = bindir / 'sudo-secretspec'
    tripwire.write_text('#!/bin/sh\ntouch "' + str(tmp_path / 'unexpected-call') + '"\nexit 99\n')
    tripwire.chmod(0o755)
    # Inherited sitecustomize/PYTHONPATH are ignored by the real -I shebang;
    # test the cold executable itself without -B or imported ADE modules.
    home = tmp_path / 'home'
    home.mkdir()
    state = tmp_path / 'outcomes.json'
    state.write_text(json.dumps({'schema_version': 1, 'updated_at': '2026-11-10T00:00:00Z',
                                'keys': {'TEST_KEY': {'status': 'invalid', 'detail': 'DISCARD'}}}))
    before = snapshot(tmp_path)
    root_args = [option + str(root)] if option.endswith('=') else [option, str(root)]
    result = subprocess.run([str(cli), *root_args, 'keys-plan', '--state', str(state),
                             *(['--json'] if json_output else [])],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'HOME': str(home), 'PATH': str(bindir) + os.pathsep + os.environ['PATH']})
    assert result.returncode == 0, result.stderr
    assert 'DISCARD' not in result.stdout + result.stderr
    if json_output:
        payload = json.loads(result.stdout)
        assert payload['keys'][0]['action'] == 'review-credential'
        assert payload['setup_complete'] is False
    else:
        assert 'freshness=unverified' in result.stdout
        assert 'review-credential: TEST_KEY' in result.stdout
    assert snapshot(tmp_path) == before


def test_cli_refuses_effects_and_uses_default_cache(tmp_path, monkeypatch, capsys):
    import runpy
    root = tmp_path / 'repo'
    config = root / 'config'
    config.mkdir(parents=True)
    shutil.copyfile(REPO / 'config/install.schema.json', config / 'install.schema.json')
    shutil.copyfile(REPO / 'tests/fixtures/install_catalog/minimal.toml', config / 'install.toml')
    state = tmp_path / 'existing-cache.json'
    state.write_text(json.dumps({'schema_version': 1, 'keys': {}}))
    monkeypatch.setenv('HOME', str(tmp_path))  # never overlay the host's local.toml
    monkeypatch.setenv('ADE_KEYS_STATE_PATH', str(state))
    forbidden = Mock(side_effect=AssertionError('report attempted an effect'))
    monkeypatch.setattr(ai.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(ai.shutil, 'which', forbidden)
    monkeypatch.setattr(ai, '_atomic_write_json', forbidden)
    original_open = Path.open
    def read_only_open(path, mode='r', *args, **kwargs):
        assert not any(flag in mode for flag in 'wax+'), 'report opened a file for writing'
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', read_only_open)
    cli = runpy.run_path(str(REPO / 'bin/ade-install'))
    assert cli['main'](['keys-plan', '--root', str(root), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['cache_status'] == 'loaded'
    state.unlink()
    assert cli['main'](['keys-plan', '--root', str(root), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['cache_status'] == 'missing'
    assert not state.exists()
    forbidden.assert_not_called()


def test_cli_invalid_catalog_has_fixed_error(tmp_path):
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'install.toml').write_text('MUST_NOT_ECHO = [broken')
    result = subprocess.run([sys.executable, '-I', '-B', str(REPO / 'bin/ade-install'),
                             'keys-plan', '--root', str(tmp_path), '--json'],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'mode': 'cached-plan-only', 'error': 'invalid-catalog'}
    assert 'MUST_NOT_ECHO' not in result.stdout + result.stderr


@pytest.mark.skipif(shutil.which('just') is None, reason='Just development dependency unavailable')
def test_just_recipe_forwards_arguments_to_cli(tmp_path):
    root = tmp_path / 'repo'
    (root / 'bin').mkdir(parents=True)
    text = (REPO / 'justfile').read_text()
    assert '\n[positional-arguments]\nkeys-plan *args:\n' in text
    recipe = text.split('\nkeys-plan *args:\n', 1)[1].split('\n\n', 1)[0]
    (root / 'justfile').write_text(
        'root := justfile_directory()\n[positional-arguments]\nkeys-plan *args:\n' + recipe + '\n')
    cli = root / 'bin/ade-install'
    cli.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
    cli.chmod(0o755)
    awkward = str(tmp_path / 'dir with space' / '$(touch pwned);*.json')
    result = subprocess.run([shutil.which('just'), '--justfile', str(root / 'justfile'),
                             'keys-plan', '--json', '--state', awkward],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['keys-plan', '--root', str(root), '--json', '--state', awkward]
    assert not (root / 'pwned').exists() and not Path('pwned').exists()


def _minimal_root(tmp_path):
    root = tmp_path / 'repo'
    (root / 'config').mkdir(parents=True)
    shutil.copyfile(REPO / 'config/install.schema.json', root / 'config/install.schema.json')
    shutil.copyfile(REPO / 'tests/fixtures/install_catalog/minimal.toml', root / 'config/install.toml')
    return root


def test_explicit_empty_state_is_invalid_not_default(tmp_path, monkeypatch, capsys):
    import runpy
    root = _minimal_root(tmp_path)
    live = tmp_path / 'live.json'
    live.write_text(json.dumps({'schema_version': 1, 'keys': {}}))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('ADE_KEYS_STATE_PATH', str(live))
    cli = runpy.run_path(str(REPO / 'bin/ade-install'))
    assert cli['main'](['keys-plan', '--root', str(root), '--json', '--state', '']) == 0
    assert json.loads(capsys.readouterr().out)['cache_status'] == 'invalid'


def test_explicit_empty_root_is_invalid_catalog(tmp_path, monkeypatch, capsys):
    import runpy
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.chdir(REPO)  # an accidental fallback to cwd would find a valid catalog
    cli = runpy.run_path(str(REPO / 'bin/ade-install'))
    assert cli['main'](['keys-plan', '--root', '', '--json']) == 1
    assert json.loads(capsys.readouterr().out) == {'mode': 'cached-plan-only', 'error': 'invalid-catalog'}


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'device'])
def test_nonregular_cache_refused_without_blocking(tmp_path, kind):
    path = tmp_path / 'nonregular'
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'directory':
        path.mkdir()
    else:
        path = Path('/dev/null')
    # Isolate in a subprocess: the regression's blocking open cannot stall pytest.
    code = '''
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import ade_install as ai
print(json.dumps(ai.load_keys_plan_cache(Path(sys.argv[2]))))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(REPO / 'bin'), str(path)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{}, 'invalid']


def test_cache_descriptor_is_readonly_nonblocking(tmp_path, monkeypatch):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps(cache()))
    real_open = ai.os.open
    flags_seen = []
    def checked_open(path, flags, *args, **kwargs):
        assert flags & os.O_NONBLOCK
        assert flags & os.O_CLOEXEC
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        flags_seen.append(flags)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(ai.os, 'open', checked_open)
    assert ai.load_keys_plan_cache(path)[1] == 'loaded'
    assert len(flags_seen) == 1
