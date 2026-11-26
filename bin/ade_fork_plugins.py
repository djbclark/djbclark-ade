"""Trusted, offline master-source snapshot recipe. No activation or authority."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import selectors
import time
import subprocess
import tempfile

from ade_fork_release import ContractError, canonical, parse, validate

MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 20000
GIT_TIMEOUT = 30.0
PLUGINS = ('ade-yolo', 'ade-window-name', 'ade-claim')
# Protected recipe, NEVER taken from candidate metadata.
LINKS = {'CLAUDE.md': 'AGENTS.md', 'libexec/agent-bin/git': 'bin/ade-git-guard'}
HELPERS = {
    'ade-yolo': (),
    'ade-window-name': ('bin/ade_ws_autoname.py', 'bin/ade_ws_names.py'),
    'ade-claim': ('bin/ade_claims.py', 'bin/paseo_identity.py', 'bin/ade-git-guard',
                  'libexec/agent-bin/git', 'libexec/git-hooks/pre-push',
                  'libexec/git-hooks/reference-transaction'),
}
TOOLS = ('python', 'git', 'node', 'paseo_compiler')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(value: str) -> str:
    if (not isinstance(value, str) or not value or '\\' in value or
            any(ord(c) < 32 or ord(c) > 126 for c in value) or
            value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ContractError('unsafe snapshot path')
    return value


def git(repo: Path, *args: str) -> bytes:
    # Stream with a deadline AND byte cap. Never block in buffered read before wait.
    env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    with subprocess.Popen(['git', '--no-replace-objects', '-C', str(repo), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as proc:
        deadline = time.monotonic() + GIT_TIMEOUT
        data = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ContractError('git object read timed out')
                    chunk = os.read(proc.stdout.fileno(), min(65536, MAX_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ContractError('git object exceeds bound')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ContractError('git object read timed out')
            try:
                status = proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                raise ContractError('git object read timed out') from error
            if status:
                raise ContractError('git object read failed')
            return bytes(data)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()


def produce(repo: Path, master_commit: str) -> bytes:
    """Exact object input. Caller must independently authenticate current qualified master."""
    if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', master_commit):
        raise ContractError('full commit required')
    tree = git(repo, 'rev-parse', master_commit + '^{tree}').decode().strip()
    entries = {}
    for line in git(repo, 'ls-tree', '-rz', '--full-tree', tree).split(b'\0'):
        if not line:
            continue
        meta, raw = line.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        path = safe_path(raw.decode('utf-8'))
        if path in entries or kind != 'blob' or mode not in ('100644', '100755', '120000'):
            raise ContractError('unsupported or duplicate source entry')
        entries[path] = (mode, oid)
    if len(entries) > MAX_FILES:
        raise ContractError('too many source files')
    files = []
    total = 0
    for path, (mode, oid) in sorted(entries.items()):
        resolved = path
        if mode == '120000':
            target = git(repo, 'cat-file', 'blob', oid).decode()
            resolved = LINKS.get(path)
            if resolved is None or os.path.normpath(str(PurePosixPath(path).parent / target)) != resolved:
                raise ContractError('unreviewed source symlink')
            if resolved not in entries or entries[resolved][0] == '120000':
                raise ContractError('missing or linked target')
        target_mode, target_oid = entries[resolved]
        content = git(repo, 'cat-file', 'blob', target_oid)
        total += len(content)
        if total > MAX_BYTES:
            raise ContractError('source exceeds bound')
        files.append(dict(path=path, source_mode=mode, object=oid, target=resolved,
                          target_object=target_oid, mode=0o555 if target_mode == '100755' else 0o444,
                          sha256=sha(content), content=base64.b64encode(content).decode()))
    payload = canonical(dict(version=1, commit=master_commit, tree=tree, files=files))
    if len(payload) > MAX_BYTES:
        raise ContractError('payload exceeds bound')
    inspect(payload)
    return payload


def inspect(payload: bytes) -> dict:
    """Validate EVERY entry before any filesystem mutation; JSON avoids tar/zip link semantics."""
    if len(payload) > MAX_BYTES:
        raise ContractError('payload exceeds bound')
    data = parse(payload.decode('utf-8'))
    if set(data) != {'version', 'commit', 'tree', 'files'} or data['version'] != 1:
        raise ContractError('invalid snapshot schema')
    for key in ('commit', 'tree'):
        if not isinstance(data[key], str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', data[key]):
            raise ContractError('invalid object identity')
    files = data['files']
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise ContractError('invalid file count')
    seen = set()
    for row in files:
        if set(row) != {'path', 'source_mode', 'object', 'target', 'target_object', 'mode', 'sha256', 'content'}:
            raise ContractError('invalid file schema')
        path = safe_path(row['path']); safe_path(row['target'])
        if path in seen or any('/'.join(path.split('/')[:i]) in seen for i in range(1, len(path.split('/')))):
            raise ContractError('duplicate or overlapping path')
        seen.add(path)
        if row['source_mode'] not in ('100644', '100755', '120000') or row['mode'] not in (0o444, 0o555):
            raise ContractError('invalid mode')
        if row['source_mode'] == '120000':
            if LINKS.get(path) != row['target']:
                raise ContractError('unreviewed link')
        elif row['target'] != path or row['target_object'] != row['object']:
            raise ContractError('invalid source mapping')
        for key in ('object', 'target_object'):
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', row[key]):
                raise ContractError('invalid blob identity')
        try:
            content = base64.b64decode(row['content'], validate=True)
        except (ValueError, TypeError) as error:
            raise ContractError('invalid content encoding') from error
        algo = hashlib.sha1 if len(row['target_object']) == 40 else hashlib.sha256
        blob = algo(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if sha(content) != row['sha256'] or blob != row['target_object']:
            raise ContractError('content identity mismatch')
    if [r['path'] for r in files] != sorted(seen):
        raise ContractError('noncanonical path order')
    bypath = {r['path']: r for r in files}
    for row in files:
        if row['target'] not in bypath or bypath[row['target']]['sha256'] != row['sha256']:
            raise ContractError('missing materialized target')
    return data


def payload_tree_hash(payload: bytes) -> str:
    rows = inspect(payload)['files']
    graph = {}
    for row in rows:
        node = graph
        parts = row['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (row,)
    h = hashlib.sha256()
    def visit(node, prefix=''):
        for name in sorted(node):
            value = node[name]; path = prefix + name
            if isinstance(value, tuple):
                value = value[0]
                content = base64.b64decode(value['content'])
                h.update(canonical(['file', path, value['mode'], len(content)]) + b'\n')
                h.update(content); h.update(b'\n')
            else:
                h.update(canonical(['directory', path]) + b'\n')
                visit(value, path + '/')
    visit(graph)
    return h.hexdigest()


def tree_hash(root: Path) -> str:
    """Paseo hashPluginSnapshot JSONL v1, ASCII paths, sealed file modes."""
    h = hashlib.sha256()
    def visit(directory):
        for p in sorted(directory.iterdir()):
            s = p.lstat(); rel = p.relative_to(root).as_posix()
            if stat.S_ISDIR(s.st_mode):
                h.update(canonical(['directory', rel]) + b'\n'); visit(p)
            elif stat.S_ISREG(s.st_mode) and s.st_nlink == 1:
                h.update(canonical(['file', rel, s.st_mode & 0o777, s.st_size]) + b'\n')
                h.update(p.read_bytes()); h.update(b'\n')
            else:
                raise ContractError('unsafe retained tree entry')
    if root.is_symlink() or not root.is_dir():
        raise ContractError('unsafe snapshot root')
    visit(root)
    return h.hexdigest()


def sync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def stage(payload: bytes, store: Path, expected_tree: str) -> Path:
    """Private administrator-owned store. Never activate, rewrite config or overwrite."""
    data = inspect(payload)
    if payload_tree_hash(payload) != expected_tree:
        raise ContractError('payload/tree substitution')
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = store.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ContractError('store must be private and owned')
    destination = store / sha(payload)
    if destination.exists() or destination.is_symlink():
        if tree_hash(destination) != expected_tree:
            raise ContractError('corrupt retained snapshot')
        return destination
    temp = Path(tempfile.mkdtemp(prefix='.stage-', dir=store))
    # On failure retain inspectable private staging; never remove prior artifacts.
    for row in data['files']:
        p = temp / row['path']; p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('xb') as f:
            f.write(base64.b64decode(row['content'])); f.flush()
            os.fchmod(f.fileno(), row['mode'])
            getattr(os, 'fdatasync', os.fsync)(f.fileno()); os.fsync(f.fileno())
    directories = [p for p in temp.rglob('*') if p.is_dir()] + [temp]
    for p in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        p.chmod(0o555); sync_dir(p)
    if tree_hash(temp) != expected_tree:
        raise ContractError('actual sealed tree hash mismatch')
    libc = ctypes.CDLL(None, use_errno=True)
    if hasattr(libc, 'renameat2'):
        rc = libc.renameat2(-100, os.fsencode(temp), -100, os.fsencode(destination), 1)
    elif hasattr(libc, 'renamex_np'):
        rc = libc.renamex_np(os.fsencode(temp), os.fsencode(destination), 4)
    else:
        raise ContractError('atomic no-replace directory publication unavailable')
    if rc != 0:
        raise ContractError('snapshot publication refused')
    sync_dir(store)
    return destination


def qualify(payload, plugin, receipt, expected, policy, authenticated, evidence, trusted_evidence):
    """Consistency + separately authenticated CI; no authority and no live probes."""
    data = inspect(payload)
    if plugin not in PLUGINS or expected['fork_commit'] != data['commit']:
        raise ContractError('plugin/source mismatch')
    paths = {r['path'] for r in data['files']}
    required = (*HELPERS[plugin], f'plugins/{plugin}/index.server.ts', f'plugins/{plugin}/paseo-plugin.json')
    if any(p not in paths for p in required):
        return 'HOLD'
    # Protected evaluator must prove complete transitive helper bindings and cold compilation.
    keys = {*TOOLS, 'helper_bindings', 'cold_compatibility', 'native_tree_sha256', 'server_bundle_sha256', 'master_commit'}
    if (not isinstance(trusted_evidence, dict) or set(trusted_evidence) != keys or
            evidence != trusted_evidence or trusted_evidence['master_commit'] != data['commit'] or
            any(not trusted_evidence[k] for k in keys)):
        return 'HOLD'
    if (expected['toolchain'] != canonical({'plugin_snapshot_evidence': sha(canonical(trusted_evidence))}).decode('utf-8') or
            trusted_evidence['native_tree_sha256'] != payload_tree_hash(payload)):
        return 'HOLD'
    validate(receipt, expected, policy, artifact=payload)
    if authenticated.authenticates(receipt) is not True:
        return 'HOLD'
    return 'QUALIFIED'
