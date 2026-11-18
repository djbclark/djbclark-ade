"""Authenticate and unpack fixed, completed native BUILD inputs; execute nothing.

This is deliberately separate from the qualified ADE evaluator. A successful
build/inventory archive is a measurement input, never a runtime qualification.
Expectations are reviewed bytes beside this script, not downloaded metadata.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'bin'))
from ade_fork_ci import GitHubEvaluation, validate_metadata  # noqa: E402
from ade_fork_release import ContractError, parse  # noqa: E402

MAX_ZIP = 128 * 1024 * 1024
MAX_TAR = 512 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
MAX_MEMBERS = 10000
HEX = re.compile(r'[a-f0-9]{64}')
BUILTINS = (
    'antigravity-provider', 'claude-usage-source', 'codex-usage-source',
    'copilot-usage-source', 'cursor-usage-source', 'fx-provider',
    'grok-usage-source', 'hoplite-provider', 'kimi-usage-source',
    'minimax-usage-source', 'muse-provider', 'opencode-go-usage-source',
    'worktree-include', 'zai-usage-source',
)


def require(condition, message):
    if not condition:
        raise ContractError(message)


@dataclass(frozen=True)
class BuildInput:
    repository: str
    repository_id: int
    workflow_id: int
    workflow_path: str
    evaluator_commit: str  # Existing metadata checker names the producing commit this way.
    run_id: int
    run_attempt: int
    actor_id: int
    event: str
    jobs: tuple[str, ...]
    artifact_id: int
    artifact_name: str
    archive_sha256: str
    tar_sha256: str
    manifest_sha256: str
    evidence_sha256: str
    workflow_ref: str | None = None

    def __post_init__(self):
        require(self.repository == 'djbclark/paseo' and self.repository_id == 1432178170,
                'unexpected native repository')
        require(self.workflow_id == 422873369 and
                self.workflow_path == '.github/workflows/fork-qualified-host.yml',
                'unexpected native producer workflow')
        require(self.actor_id == 131936 and self.event == 'push' and
                self.jobs == ('sealed-linux-host',), 'unexpected build authority/job')
        require(re.fullmatch(r'[a-f0-9]{40}', self.evaluator_commit or '') is not None,
                'invalid source commit')
        for value in (self.run_id, self.run_attempt, self.artifact_id):
            require(type(value) is int and value > 0, 'invalid build/run identity')
        for value in (self.archive_sha256, self.tar_sha256, self.manifest_sha256, self.evidence_sha256):
            require(type(value) is str and HEX.fullmatch(value), 'invalid protected digest')
        require(self.artifact_name ==
                f'qualified-daemon-build-{self.evaluator_commit}-{self.run_id}-{self.run_attempt}',
                'artifact name does not bind source/run/attempt')
        require(self.workflow_ref is None, 'unexpected build workflow ref override')


def load_expected():
    value = parse(Path(__file__).with_name('native-build-input.json').read_text())
    require(type(value) is dict and value.pop('qualification', None) is False,
            'build input must be explicitly non-qualification')
    require(type(value.get('jobs')) is list, 'expected job list missing')
    value['jobs'] = tuple(value['jobs'])
    try:
        return BuildInput(**value)
    except TypeError as error:
        raise ContractError('invalid fixed build expectations') from error


def file_digest(file):
    with open(file, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(artifact_path, output, *, timeout=90):
    """Enforce both stream budgets before retaining bytes, then reap our child."""
    arguments = ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                 artifact_path + '/zip']
    proc = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, [0, MAX_ZIP, True])
            selector.register(proc.stderr, selectors.EVENT_READ, [0, 16384, False])
            while selector.get_map():
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'native build download timed out')
                events = selector.select(remaining)
                require(events, 'native build download timed out')
                for key, _ in events:
                    budget = key.data
                    chunk = os.read(key.fileobj.fileno(), min(65536, budget[1] + 1 - budget[0]))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    budget[0] += len(chunk)
                    require(budget[0] <= budget[1], 'native build download stream exceeded bound')
                    if budget[2]:
                        output.write(chunk)
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'native build download timed out')
        try:
            code = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise ContractError('native build download timed out') from error
        require(code == 0, 'native build download failed')
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()  # Actual child settlement, never a dropped timeout handle.
        proc.stdout.close()
        proc.stderr.close()


def copy_bounded(source, destination, limit):
    total, digest = 0, hashlib.sha256()
    while chunk := source.read(min(65536, limit + 1 - total)):
        total += len(chunk)
        require(total <= limit, 'archive byte bound exceeded')
        digest.update(chunk)
        destination.write(chunk)
    return total, digest.hexdigest()


def safe_name(name):
    require(type(name) is str and name and not name.startswith('/') and
            '\\' not in name and '\x00' not in name and
            all(part not in ('', '.', '..') for part in name.split('/')),
            'unsafe archive member path')
    require(str(PurePosixPath(name)) == name, 'noncanonical archive path')
    return name


def inspect_archive(archive, temporary, expected):
    """Hash every regular member without extractall, imports, or executable calls."""
    require(archive.stat().st_size <= MAX_ZIP and file_digest(archive) == expected.archive_sha256,
            'build ZIP digest/size mismatch')
    tar_path = temporary / 'build.tar'
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        require(len(entries) == 2 and {x.filename for x in entries} ==
                {'SHA256SUMS', 'qualified-daemon-build.tar'}, 'unexpected outer archive members')
        for item in entries:
            require(not item.flag_bits & 1 and not item.is_dir() and
                    not stat.S_ISLNK(item.external_attr >> 16), 'special/encrypted ZIP member')
        sums = zipped.getinfo('SHA256SUMS')
        require(sums.file_size <= 256, 'checksum record too large')
        require(zipped.read(sums) ==
                f'{expected.tar_sha256}  qualified-daemon-build.tar\n'.encode(),
                'tar checksum declaration mismatch')
        item = zipped.getinfo('qualified-daemon-build.tar')
        require(0 < item.file_size <= MAX_TAR, 'expanded tar size outside bound')
        with zipped.open(item) as source, tar_path.open('xb') as output:
            size, digest = copy_bounded(source, output, MAX_TAR)
        require(size == item.file_size and digest == expected.tar_sha256,
                'inner tar digest/size mismatch')
    regular, directories, metadata = {}, set(), {}
    total = 0
    with tarfile.open(tar_path, 'r:') as tar:
        for index, item in enumerate(tar):
            require(index < MAX_MEMBERS, 'too many tar members')
            name = safe_name(item.name)
            require(name not in regular and name not in directories, 'duplicate tar member')
            require(not item.mode & 0o7000, 'special permission bits forbidden')
            require(name == 'qualified-daemon' or name.startswith('qualified-daemon/') or
                    name in ('qualified-daemon.manifest.json', 'qualified-daemon.build-evidence.json'),
                    'unexpected archive root')
            if item.isdir():
                require(name == 'qualified-daemon' or name.startswith('qualified-daemon/'),
                        'metadata cannot be a directory')
                require(item.mode == 0o555, 'retained directory mode mismatch')
                directories.add(name)
                continue
            require(item.isfile() and 0 <= item.size <= MAX_TAR,
                    'links/special archive members forbidden')
            total += item.size
            require(total <= MAX_TAR, 'expanded member sum exceeded')
            source = tar.extractfile(item)
            digest = hashlib.sha256()
            saved = bytearray() if name in (
                'qualified-daemon.manifest.json', 'qualified-daemon.build-evidence.json') else None
            count = 0
            while chunk := source.read(65536):
                digest.update(chunk)
                count += len(chunk)
                if saved is not None:
                    require(len(saved) + len(chunk) <= MAX_JSON, 'metadata too large')
                    saved.extend(chunk)
            require(count == item.size, 'truncated tar member')
            regular[name] = {'mode': item.mode, 'size': count, 'sha256': digest.hexdigest()}
            if saved is not None:
                metadata[name] = bytes(saved)
    require('qualified-daemon' in directories, 'retained tree missing')
    for name in regular.keys() | directories:
        for parent in PurePosixPath(name).parents:
            if str(parent) != '.':
                require(str(parent) in directories, 'missing/non-directory archive ancestor')
    raw_manifest = metadata.get('qualified-daemon.manifest.json', b'')
    raw_evidence = metadata.get('qualified-daemon.build-evidence.json', b'')
    require(hashlib.sha256(raw_manifest).hexdigest() == expected.manifest_sha256 and
            hashlib.sha256(raw_evidence).hexdigest() == expected.evidence_sha256,
            'protected manifest/build evidence mismatch')
    manifest, evidence = parse(raw_manifest.decode()), parse(raw_evidence.decode())
    require(type(manifest) is dict and type(evidence) is dict, 'metadata objects required')
    require(manifest.get('schemaVersion') == 2 and manifest.get('profile') == 'enclosing-daemon-v2',
            'unexpected retained profile')
    require(manifest.get('builtinPlugins') == list(BUILTINS), 'complete builtin inventory missing')
    require(evidence.get('schemaVersion') == 1 and evidence.get('qualification') is False and
            evidence.get('kind') == 'paseo-daemon-build-input-evidence', 'runtime qualification forbidden')
    require(type(evidence.get('source')) is dict and type(evidence.get('build')) is dict,
            'source/build metadata objects required')
    require(evidence.get('source', {}).get('commit') == expected.evaluator_commit and
            evidence.get('build', {}).get('repository') == expected.repository and
            evidence.get('build', {}).get('runId') == str(expected.run_id) and
            evidence.get('build', {}).get('attempt') == str(expected.run_attempt) and
            evidence.get('manifestSha256') == expected.manifest_sha256 and
            evidence.get('distributionBuildId') == manifest.get('distributionBuildId'),
            'build evidence source/run/distribution mismatch')
    files = manifest.get('files')
    require(type(files) is list and files, 'retained inventory absent')
    expected_files = {}
    for row in files:
        require(type(row) is dict and set(row) == {'path', 'mode', 'size', 'sha256'},
                'invalid retained file row')
        require(type(row['mode']) is int and row['mode'] in (0o444, 0o555) and
                type(row['size']) is int and 0 <= row['size'] <= MAX_TAR and
                type(row['sha256']) is str and HEX.fullmatch(row['sha256']),
                'invalid retained file mode/size/digest')
        name = 'qualified-daemon/' + safe_name(row['path'])
        require(name not in expected_files, 'duplicate retained file row')
        expected_files[name] = {key: row[key] for key in ('mode', 'size', 'sha256')}
    tree = {name: row for name, row in regular.items() if name.startswith('qualified-daemon/')}
    require(tree == expected_files, 'archive bytes/modes differ from complete manifest')
    return tar_path, manifest, evidence


def materialize(tar_path, destination):
    """Called only after whole-archive validation; never installs into a live path."""
    destination.mkdir(mode=0o700)  # Never overwrite/reuse another attempt's tree.
    try:
        directories = []
        with tarfile.open(tar_path, 'r:') as tar:
            for item in tar:
                file = destination / item.name
                if item.isdir():
                    file.mkdir(mode=0o700)
                    directories.append(file)
                else:
                    with file.open('xb') as out, tar.extractfile(item) as source:
                        shutil.copyfileobj(source, out, 65536)
                    file.chmod(item.mode)
        for file in reversed(directories):
            file.chmod(0o555)
    except BaseException:
        for file in destination.rglob('*'):
            if file.is_dir():
                file.chmod(0o700)
        shutil.rmtree(destination)
        raise


def acquire(destination):
    expected = load_expected()
    require(not destination.exists() and not destination.is_symlink(), 'new output path required')
    api = GitHubEvaluation().api
    base = f'repos/{expected.repository}/actions'
    run_path = f'{base}/runs/{expected.run_id}'
    artifact_path = f'{base}/artifacts/{expected.artifact_id}'
    run, artifact = api(run_path), api(artifact_path)
    pages = api(f'{run_path}/attempts/{expected.run_attempt}/jobs?per_page=100', paginate=True)
    require(type(pages) is list and all(type(p) is dict and type(p.get('jobs')) is list
                                      for p in pages), 'malformed job pages')
    jobs = [job for page in pages for job in page['jobs']]
    validate_metadata(expected, run, jobs, artifact)
    with tempfile.TemporaryDirectory(prefix='fork-build-input-') as name:
        temporary = Path(name)
        archive = temporary / 'build.zip'
        with archive.open('xb') as output:
            download(artifact_path, output)
        tar_path, manifest, evidence = inspect_archive(archive, temporary, expected)
        validate_metadata(expected, api(run_path), jobs, api(artifact_path))
        materialize(tar_path, destination)
    return {'status': 'build-input-acquired', 'qualification': False,
            'source': expected.evaluator_commit, 'run_id': expected.run_id,
            'attempt': expected.run_attempt, 'archive_sha256': expected.archive_sha256,
            'manifest_sha256': expected.manifest_sha256, 'files': len(manifest['files'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    options = parser.parse_args()
    try:
        print(json.dumps(acquire(options.output.resolve()), sort_keys=True))
    except (ContractError, OSError, ValueError, zipfile.BadZipFile, tarfile.TarError,
            subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'hold', 'reason': type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
