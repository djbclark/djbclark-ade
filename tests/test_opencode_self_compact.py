"""Native compact must target the scoped session, never the caller's terminal."""

import importlib.machinery
import importlib.util
import json
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
    calls = []

    def api(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({"data": {
            "id": "ses_abc123", "model": {"providerID": "opencode-go"},
        }}) if args[0] == "get" else "", "")

    monkeypatch.setattr(compact, "api", api)
    return calls, tmp_path


def test_own_acp_session_uses_native_api_and_deduplicates(setup, monkeypatch):
    calls, home = setup
    monkeypatch.setenv("ACP_RUN_AGENT", "1")
    monkeypatch.setenv("PASEO_AGENT_ID", "parent-must-not-be-used")
    assert compact.main([]) == 0
    assert calls == [("get", "/api/session/ses_abc123"),
                     ("post", "/api/session/ses_abc123/compact", "--data", "{}")]
    assert compact.main([]) == 7
    assert len(calls) == 2
    state = home / ".local/state/self-slash/opencode_ses_abc123.compact.json"
    assert json.loads(state.read_text())["outcome"] == "accepted"
    assert state.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("scope", ["", "ses_../other", "ses_abc\n", "other"])
def test_invalid_scope_never_calls_api(setup, monkeypatch, scope):
    monkeypatch.setenv("ADE_OPENCODE_SESSION_ID", scope)
    assert compact.main([]) == 2
    assert setup[0] == []


def test_dry_run_makes_no_api_call_or_state_write(setup):
    calls, home = setup
    assert compact.main(["--dry-run"]) == 0
    assert calls == []
    assert not (home / ".local/state/self-slash").exists()


@pytest.mark.parametrize("info", [
    {"id": "ses_other", "model": {"providerID": "opencode-go"}},
    {"id": "ses_abc123", "model": {"providerID": "opencode"}},
    {"id": "ses_abc123"},
])
def test_identity_or_provider_mismatch_never_posts(setup, monkeypatch, info):
    calls = []

    def api(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps({"data": info}), "")

    monkeypatch.setattr(compact, "api", api)
    assert compact.main([]) in (2, 11)
    assert len(calls) == 1 and calls[0][0] == "get"


def test_uncertain_write_is_not_retried(setup, monkeypatch):
    original = compact.api

    def api(*args):
        if args[0] == "post":
            raise subprocess.TimeoutExpired("opencode", 15)
        return original(*args)

    monkeypatch.setattr(compact, "api", api)
    assert compact.main([]) == 11
    assert compact.main([]) == 7


@pytest.mark.parametrize("previous", [{}, [], {"attempted_at": True}, {"attempted_at": float("nan")}])
def test_corrupt_state_does_not_allow_a_duplicate(setup, previous):
    calls, home = setup
    state = home / ".local/state/self-slash/opencode_ses_abc123.compact.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps(previous))
    assert compact.main([]) == 7
    assert calls == []


def test_failed_write_keeps_uncertain_state_and_cooldown(setup, monkeypatch):
    original = compact.api

    def api(*args):
        if args[0] == "post":
            return subprocess.CompletedProcess(args, 1, "", "rejected")
        return original(*args)

    monkeypatch.setattr(compact, "api", api)
    assert compact.main([]) == 11
    assert compact.main([]) == 7


def test_elapsed_cooldown_allows_another_request(setup, monkeypatch):
    monkeypatch.setattr(compact.time, "time", lambda: 1000)
    assert compact.main([]) == 0
    monkeypatch.setattr(compact.time, "time", lambda: 1300)
    assert compact.main([]) == 0
    assert len(setup[0]) == 4


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
