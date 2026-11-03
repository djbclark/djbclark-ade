"""Bounded private JSON artifacts, no-follow dirfds and stable-inode locks.

One Unix-user trust boundary, not protection against a malicious same-uid process.
A local flock never constitutes a distributed ownership lock.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import stat
from pathlib import Path

from .planning import canonical

MAX_BYTES = 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")


def _regular(fd, private=True):
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid():
        raise ValueError("unsafe-artifact-inode")
    if private and stat.S_IMODE(s.st_mode) != 0o600:
        raise ValueError("unsafe-artifact-permissions")
    if s.st_size > MAX_BYTES:
        raise ValueError("artifact-too-large")


def _decode(fd):
    with os.fdopen(os.dup(fd), "rb") as f:
        body = f.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("artifact-too-large")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate-json-key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("nonfinite-json")
    try:
        return json.loads(body, object_pairs_hook=unique, parse_constant=invalid)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as e:
        raise ValueError("invalid-artifact-json") from e


def read_input(path):
    """Import regular metadata, not arbitrary FIFOs, devices, symlinks or transcripts."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        _regular(fd, private=False)
        return _decode(fd)
    finally:
        os.close(fd)


class Store:
    def __init__(self, root, *, create=False):
        root = Path(root)
        if not root.is_absolute() or ".." in root.parts or root == Path("/"):
            raise ValueError("state-root-must-be-absolute")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in root.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = nxt
            s = os.fstat(fd)
            if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
                raise ValueError("state-root-not-private")
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, *args):
        os.close(self.fd)

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError("invalid-artifact-name")
        return name

    def read(self, name):
        fd = os.open(self._name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            _regular(fd)
            return _decode(fd)
        finally:
            os.close(fd)

    def _check_target(self, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
        except FileNotFoundError:
            return
        try:
            _regular(fd)
        finally:
            os.close(fd)

    def write(self, name, value):
        """Call under lock for read/modify/write. Fsync file then directory."""
        name = self._name(name)
        data = canonical(value) + b"\n"
        if len(data) > MAX_BYTES:
            raise ValueError("artifact-too-large")
        self._check_target(name)
        tmp = ".write-" + secrets.token_hex(16)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp, dir_fd=self.fd)

    @contextlib.contextmanager
    def lock(self):
        fd = os.open("coordinator.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            _regular(fd)
            # A second invocation refuses immediately, never waits indefinitely.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)
