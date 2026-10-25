"""Native compact must target the scoped session, never the caller's terminal."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("native_compact", str(ROOT / "bin/opencode-self-compact"))
spec = importlib.util.spec_from_loader(loader.name, loader)
compact = importlib.util.module_from_spec(spec)
loader.exec_module(compact)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ADE_OPENCODE_SESSION_ID", "ses_abc123")
    monkeypatch.setenv("ADE_OPENCODE_DIRECTORY", "/repo with spaces")
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"output": {"accepted": True}}), "")
    monkeypatch.setattr(compact, "invoke", run)
    return calls, tmp_path


def test_own_acp_session_uses_single_plugin_guard_not_a_direct_compact(setup, monkeypatch):
    monkeypatch.setenv("ACP_RUN_AGENT", "1")
    monkeypatch.setenv("PASEO_AGENT_ID", "parent-must-not-be-used")
    assert compact.main([]) == 0
    call = setup[0][0]
    assert call[:3] == ["opencode", "api", "post"]
    assert call[3] == "/api/rpc/ade.go-context/compact?location%5Bdirectory%5D=%2Frepo+with+spaces"
    assert json.loads(call[5]) == {"input": {"sessionID": "ses_abc123"}}
    assert len(setup[0]) == 1


@pytest.mark.parametrize("scope", ["", "ses_../other", "ses_abc\n", "other"])
def test_invalid_scope_never_calls_api(setup, monkeypatch, scope):
    monkeypatch.setenv("ADE_OPENCODE_SESSION_ID", scope)
    assert compact.main([]) == 2
    assert setup[0] == []


@pytest.mark.parametrize("directory", ["", "relative/path"])
def test_directory_must_also_be_tool_scoped(setup, monkeypatch, directory):
    monkeypatch.setenv("ADE_OPENCODE_DIRECTORY", directory)
    assert compact.main([]) == 2
    assert setup[0] == []


def test_dry_run_makes_no_api_call_or_state_write(setup):
    assert compact.main(["--dry-run"]) == 0
    assert setup[0] == []
    assert not (setup[1] / ".local/state/self-slash").exists()


@pytest.mark.parametrize("body", [{"output": {"accepted": False}}, {}, {"output": {}}, {"output": {"accepted": 1}}])
def test_only_guard_acceptance_counts_as_success(setup, monkeypatch, body):
    monkeypatch.setattr(compact, "invoke", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps(body), ""))
    assert compact.main([]) == 7


def test_unavailable_or_uncertain_guard_is_not_retried_in_the_helper(setup, monkeypatch):
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("opencode", 20)
    monkeypatch.setattr(compact, "invoke", run)
    assert compact.main([]) == 11
    assert len(calls) == 1


def test_self_slash_routes_before_parent_host_or_acp_guard(setup):
    result = subprocess.run([str(ROOT / "bin/self-slash"), "--dry-run", "/compact"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "no API call made" in result.stdout


@pytest.mark.parametrize("command", ["/new", "/clear", "/reset", "/quit", "/compact focus"])
def test_self_slash_refuses_unverified_native_lifecycle(setup, command):
    result = subprocess.run([str(ROOT / "bin/self-slash"), "--dry-run", command],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "native" in result.stderr


def test_native_self_slash_preserves_the_callers_cli_path(setup, tmp_path):
    binary = tmp_path / "bin" / "opencode"
    binary.parent.mkdir()
    marker = tmp_path / "native-call.json"
    binary.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n" +
                      "Path(" + repr(str(marker)) + ").write_text(json.dumps(sys.argv[1:]))\n" +
                      "print(json.dumps({'output': {'accepted': False}}))\n")
    binary.chmod(0o755)
    env = {**os.environ, "PATH": str(binary.parent) + os.pathsep + os.environ["PATH"],
           "BASH_ENV": "/dev/null"}
    env.pop("ENV", None)
    result = subprocess.run([str(ROOT / "bin/self-slash"), "/compact"], env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 7, result.stderr
    args = json.loads(marker.read_text())
    assert args[:2] == ["api", "post"]
    assert args[2].startswith("/api/rpc/ade.go-context/compact?")
    assert json.loads(args[4]) == {"input": {"sessionID": "ses_abc123"}}
