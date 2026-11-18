"""Offline CI fixtures only; never run plugin installs or a daemon."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import ade_fork_plugins as p


def command(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


@pytest.fixture
def source(tmp_path):
    command(tmp_path, 'init', '-q')
    command(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    command(tmp_path, 'config', 'user.name', 'Fixture')
    (tmp_path / 'helper').write_text('exact bytes\n')
    command(tmp_path, 'add', 'helper')
    command(tmp_path, 'commit', '-qm', 'fixture')
    return tmp_path, command(tmp_path, 'rev-parse', 'HEAD')


def test_exact_and_dirty_ignored(source):
    root, commit = source
    first = p.produce(root, commit)
    (root / 'helper').write_text('dirty')
    (root / 'untracked').write_text('ignored')
    assert p.produce(root, commit) == first
    assert base64.b64decode(p.inspect(first)['files'][0]['content']) == b'exact bytes\n'


def test_stage_retention_and_native_hash(source, tmp_path):
    payload = p.produce(*source); digest = p.payload_tree_hash(payload)
    root = p.stage(payload, tmp_path / 'store', digest)
    assert p.tree_hash(root) == digest
    assert p.stage(payload, tmp_path / 'store', digest) == root
    (root / 'helper').chmod(0o644)
    (root / 'helper').write_text('corruption')
    with pytest.raises(p.ContractError):
        p.stage(payload, tmp_path / 'store', digest)


@pytest.mark.parametrize('kind', ['escape', 'duplicate', 'content', 'mode', 'overlap'])
def test_reject_before_writing(source, tmp_path, kind):
    payload = json.loads(p.produce(*source)); row = payload['files'][0]
    if kind == 'escape': row['path'] = '../escape'
    if kind == 'duplicate': payload['files'].append(dict(row))
    if kind == 'content': row['content'] = base64.b64encode(b'substitution').decode()
    if kind == 'mode': row['mode'] = 0o777
    if kind == 'overlap':
        other = dict(row); other['path'] = 'helper/child'; payload['files'].append(other)
    with pytest.raises(p.ContractError):
        p.stage(p.canonical(payload), tmp_path / 'never', '0' * 64)
    assert not (tmp_path / 'never').exists()


def test_unsafe_link(source):
    root, _ = source
    (root / 'escape').symlink_to('/etc/passwd')
    command(root, 'add', 'escape'); command(root, 'commit', '-qm', 'link')
    with pytest.raises(p.ContractError):
        p.produce(root, command(root, 'rev-parse', 'HEAD'))


def test_substituted_tree(source, tmp_path):
    with pytest.raises(p.ContractError):
        p.stage(p.produce(*source), tmp_path / 'never', '0' * 64)
    assert not (tmp_path / 'never').exists()


def test_missing_helpers_hold(source):
    payload = p.produce(*source)
    assert p.qualify(payload, 'ade-claim', None, {'fork_commit': source[1]}, {}, None, {}, {}) == 'HOLD'


def test_cold_plugin_behavior_from_sealed_source(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    payload = p.produce(repo, command(repo, 'rev-parse', 'HEAD'))
    root = p.stage(payload, tmp_path / 'store', p.payload_tree_hash(payload))
    for plugin in p.PLUGINS:
        subprocess.run(['node', '--test', *map(str, (root / 'plugins' / plugin / 'server').glob('*.test.mjs'))], check=True)
    # Python helper binding survives normal plugins/ID/../../bin layout.
    assert (root / 'plugins/ade-window-name/../../bin/ade_ws_names.py').is_file()
    assert (root / 'libexec/agent-bin/git').is_file()
    assert not (root / 'libexec/agent-bin/git').is_symlink()
