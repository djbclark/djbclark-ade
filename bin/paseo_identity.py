"""Recover only Paseo identity from same-UID Codex app-server ancestors."""

from __future__ import annotations

import ctypes
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

_AGENT = "PASEO_AGENT_ID"
_WORKSPACE = "PASEO_WORKSPACE_ID"
_CWD = "PASEO_AGENT_CWD"
_KEYS = (_AGENT, _WORKSPACE, _CWD)
_ENV_KEYS = {os.fsencode(key): key for key in _KEYS}
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.ASCII | re.IGNORECASE)
_MAX_HOPS = 64
_MAX_PROCARGS = 1024 * 1024


class PaseoIdentityAmbiguousError(RuntimeError):
    """The Codex ancestors disagree on a Paseo identity field."""


def _process_table():
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid=,uid=,comm="], capture_output=True,
            check=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    table = {}
    for line in result.stdout.splitlines():
        try:
            pid_text, parent_text, uid_text, executable = line.split(maxsplit=3)
            pid, parent, uid = map(int, (pid_text, parent_text, uid_text))
        except ValueError:
            continue
        table[pid] = (parent, uid) if os.path.basename(executable) == "codex" else (parent, -1)
    return table


def _is_app_server(argv):
    return (len(argv) >= 2 and os.path.basename(argv[0]) == b"codex"
            and argv[1] == b"app-server")


def _selected_env(entries):
    result = {}
    for entry in entries:
        key, _, value = entry.partition(b"=")
        if key in _ENV_KEYS:
            name = _ENV_KEYS[key]
            decoded = os.fsdecode(value)
            if name in result and result[name] != decoded:
                raise PaseoIdentityAmbiguousError(f"conflicting {name} in Codex app-server environment")
            result[name] = decoded
    return result


def _darwin_procargs(pid):
    # ps eww flattens argv and env with spaces. A cwd can contain spaces or
    # even assignment-shaped text, so use the same kernel data before ps
    # renders it. KERN_PROCARGS2 stores argc, executable, padding, argv, env.
    sysctl = ctypes.CDLL(None).sysctl
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2, pid
    size = ctypes.c_size_t()
    if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        return {}
    if not 4 <= size.value <= _MAX_PROCARGS:
        return {}
    buf = ctypes.create_string_buffer(size.value)
    if sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return {}
    return _parse_darwin_procargs(buf.raw[:size.value])


def _parse_darwin_procargs(raw):
    if len(raw) < 4:
        return {}
    argc = struct.unpack_from("=i", raw)[0]
    executable, separator, rest = raw[4:].partition(b"\0")
    if (argc < 2 or not separator or os.path.basename(executable) != b"codex"):
        return {}
    fields = rest.lstrip(b"\0").split(b"\0", argc)
    if len(fields) != argc + 1 or not _is_app_server(fields[:argc]):
        return {}
    return _selected_env(fields[argc].split(b"\0"))


def _read_pid_env(pid):
    if sys.platform == "darwin":
        return _darwin_procargs(pid)
    if sys.platform.startswith("linux"):
        proc = Path("/proc") / str(pid)
        try:
            if os.readlink(proc / "exe").rsplit("/", 1)[-1] != "codex":
                return {}
            if _is_app_server((proc / "cmdline").read_bytes().split(b"\0")):
                return _selected_env((proc / "environ").read_bytes().split(b"\0"))
        except OSError:
            pass
    return {}


def recover_paseo_env(env=None, *, own_env=None, process_table=None, read_pid_env=None) -> dict[str, str]:
    """Prefer explicit shell identity. Synthetic mappings never probe live PIDs.

    Injected process tables map pid to (ppid, uid, argv), with argv as bytes.
    The reader returns a mapping of env keys for the given PID. Synthetic
    callers must supply both doubles to exercise recovery.
    """
    env = os.environ if env is None else env
    if _AGENT in env:
        return {key: env[key] for key in _KEYS if key in env} if env[_AGENT].strip() else {}
    if own_env is None:
        own_env = env is os.environ
    if not own_env and (process_table is None or read_pid_env is None):
        return {}

    table = _process_table() if process_table is None else process_table
    reader = _read_pid_env if read_pid_env is None else read_pid_env
    pid = os.getpid()
    seen = {pid}
    found = {}
    for _ in range(_MAX_HOPS):
        pid = table.get(pid, (0,))[0]
        if pid <= 1 or pid in seen or pid not in table:
            break
        seen.add(pid)
        _, uid, *argv = table[pid]
        if uid != os.getuid() or (argv and not _is_app_server(argv[0])):
            continue
        values = reader(pid)
        agent = values.get(_AGENT, "")
        if not _UUID.fullmatch(agent):
            continue
        workspace = values.get(_WORKSPACE, "")
        cwd = values.get(_CWD, "")
        candidate = {_AGENT: agent.lower()}
        if re.fullmatch(r"wks_[0-9a-f]{16}", workspace):
            candidate[_WORKSPACE] = workspace
        if os.path.isabs(cwd):
            candidate[_CWD] = cwd
        for key, value in candidate.items():
            if key in found and found[key] != value:
                raise PaseoIdentityAmbiguousError(f"Codex app-server ancestors disagree on {key}")
            found[key] = value
    return found


def resolve_paseo_agent_id(env=None, **kwargs) -> str | None:
    return (recover_paseo_env(env, **kwargs).get(_AGENT) or "").strip() or None
