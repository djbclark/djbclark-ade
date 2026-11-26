import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import paseo_identity as identity  # noqa: E402

AGENT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
WORKSPACE = "wks_8bdc13f236e8850f"
CODEX = [b"/opt/bin/codex", b"app-server"]


def forbidden(*args):
    pytest.fail("unexpected live process lookup")


def recover(*rows):
    table = {os.getpid(): (100_000, os.getuid(), [])}
    values = {}
    for index, (argv, env) in enumerate(rows, 100_000):
        parent = index + 1 if index < 100_000 + len(rows) - 1 else 1
        table[index] = (parent, os.getuid(), argv)
        values[index] = env
    return identity.recover_paseo_env({}, process_table=table, read_pid_env=values.__getitem__)


@pytest.mark.parametrize("raw", [AGENT, "", " \t"])
def test_shell_identity_and_explicit_opt_out(monkeypatch, raw):
    monkeypatch.setattr(identity, "_process_table", forbidden)
    result = identity.recover_paseo_env(
        {"PASEO_AGENT_ID": raw, "PASEO_WORKSPACE_ID": WORKSPACE}, own_env=True,
        read_pid_env=forbidden,
    )
    assert result == ({"PASEO_AGENT_ID": raw, "PASEO_WORKSPACE_ID": WORKSPACE} if raw.strip() else {})


def test_synthetic_environment_never_reads_live_pids(monkeypatch):
    monkeypatch.setattr(identity, "_process_table", forbidden)
    assert identity.recover_paseo_env({}, own_env=False) == {}
    assert identity.recover_paseo_env({}, read_pid_env=forbidden) == {}



def darwin_procargs(argv):
    executable = b"/opt/bin/codex\0"
    return struct.pack("=i", len(argv)) + executable + b"\0" * (-len(executable) % 8) + b"\0".join(argv) + b"\0"


@pytest.mark.parametrize("cwd", ["/work/tree", "/work tree/OTHER_VAR=literal"])
def test_recovers_allowlisted_environment_with_exact_value_boundaries(cwd):
    expected = {"PASEO_AGENT_ID": AGENT, "PASEO_WORKSPACE_ID": WORKSPACE, "PASEO_AGENT_CWD": cwd}
    raw = darwin_procargs(CODEX)
    entries = {**expected, "OPENAI_API_KEY": "secret PASEO_AGENT_ID=fake", "GITHUB_TOKEN": "secret"}
    raw += b"\0".join(f"{key}={value}".encode() for key, value in entries.items()) + b"\0"
    assert identity._parse_darwin_procargs(raw) == expected
    assert recover((CODEX, entries)) == expected


@pytest.mark.parametrize("argv", [[b"zsh", b"-c", b"codex app-server"],
                                  [b"python", b"codex", b"app-server"],
                                  [b"codex", b"app-server-proxy"],
                                  [b"codex", b"exec", b"app-server"]])
def test_unrelated_ancestor_ignored(argv):
    assert recover((argv, {"PASEO_AGENT_ID": AGENT})) == {}


def test_conflicting_identity_and_optional_fields_fail_closed():
    first = {"PASEO_AGENT_ID": AGENT, "PASEO_WORKSPACE_ID": WORKSPACE}
    for changed in ({"PASEO_AGENT_ID": OTHER}, {"PASEO_WORKSPACE_ID": "wks_" + "1" * 16},
                    {"PASEO_AGENT_CWD": "/another path"}):
        with pytest.raises(identity.PaseoIdentityAmbiguousError, match="disagree") as err:
            recover((CODEX, {**first, "PASEO_AGENT_CWD": "/first", "GITHUB_TOKEN": "secret"}),
                    (CODEX, {**first, **changed}))
        assert "secret" not in str(err.value)
    assert recover((CODEX, first), (CODEX, {"PASEO_AGENT_ID": AGENT})) == first


def test_malformed_values_are_ignored():
    assert recover((CODEX, {"PASEO_AGENT_ID": "invalid", "PASEO_WORKSPACE_ID": WORKSPACE})) == {}
    assert recover((CODEX, {"PASEO_AGENT_ID": AGENT, "PASEO_WORKSPACE_ID": "invalid",
                            "PASEO_AGENT_CWD": "relative"})) == {"PASEO_AGENT_ID": AGENT}


def test_ancestor_walk_skips_other_uids_and_stops_on_cycle():
    pid = os.getpid()
    table = {
        pid: (100_000, os.getuid(), []),
        100_000: (100_001, os.getuid() + 1, CODEX),
        100_001: (100_000, os.getuid(), CODEX),
    }
    reads = []

    def read(ancestor):
        reads.append(ancestor)
        return {"PASEO_AGENT_ID": AGENT}

    assert identity.recover_paseo_env({}, process_table=table, read_pid_env=read) == {"PASEO_AGENT_ID": AGENT}
    assert reads == [100_001]

def test_non_assignment_does_not_conflict_with_valid_identity():
    entries = [f"PASEO_AGENT_ID={AGENT}".encode(), b"PASEO_AGENT_ID"]
    assert identity._selected_env(entries) == {"PASEO_AGENT_ID": AGENT}


def test_darwin_parser_does_not_shift_empty_argv_zero():
    raw = darwin_procargs([b"", *CODEX]) + b"IGNORED=first\0" + f"PASEO_AGENT_ID={AGENT}".encode() + b"\0"
    assert identity._parse_darwin_procargs(raw) == {}


@pytest.mark.parametrize("error", [OSError, AttributeError])
def test_unavailable_darwin_sysctl_degrades_cleanly(monkeypatch, error):
    def unavailable(_):
        raise error("sysctl unavailable")

    monkeypatch.setattr(identity.ctypes, "CDLL", unavailable)
    assert identity._darwin_procargs(100_000) == {}


def test_sysctl_uses_platform_argument_types(monkeypatch):
    raw = darwin_procargs(CODEX) + f"PASEO_AGENT_ID={AGENT}".encode() + b"\0"

    def sysctl(mib, count, output, size_pointer, new, newlen):
        assert list(mib) == [1, 49, 100_000]
        assert count == 3 and new is None and newlen == 0
        assert sysctl.restype is identity.ctypes.c_int
        assert sysctl.argtypes[-1] is identity.ctypes.c_size_t
        size_pointer._obj.value = len(raw)
        if output is not None:
            output.raw = raw
        return 0

    from types import SimpleNamespace

    monkeypatch.setattr(identity.ctypes, "CDLL", lambda _: SimpleNamespace(sysctl=sysctl))
    assert identity._darwin_procargs(100_000) == {"PASEO_AGENT_ID": AGENT}


def test_process_table_uses_portable_ps_and_trims_comm(monkeypatch):
    from types import SimpleNamespace

    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "/bin/ps":
            raise FileNotFoundError
        return SimpleNamespace(stdout="123 45 501 /app/bin/codex  \n")

    monkeypatch.setattr(identity.subprocess, "run", run)
    assert identity._process_table() == {123: (45, 501)}
    assert calls == [[exe, "-A", "-o", "pid=,ppid=,uid=,comm="] for exe in ("/bin/ps", "ps")]


def test_linux_accepts_running_replaced_codex_binary(monkeypatch):
    monkeypatch.setattr(identity.sys, "platform", "linux")
    monkeypatch.setattr(identity.os, "readlink", lambda _: "/opt/bin/codex (deleted)")
    payloads = {"cmdline": b"\0".join(CODEX) + b"\0", "environ": f"PASEO_AGENT_ID={AGENT}".encode() + b"\0"}
    monkeypatch.setattr(Path, "read_bytes", lambda path: payloads[path.name])
    assert identity._read_pid_env(100_000) == {"PASEO_AGENT_ID": AGENT}
