"""Test the pin sweep entry point without starting a daemon or replacing PATH."""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import subprocess
import sys

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
SCRIPT = BIN / "ade-pin-workspaces"


@pytest.fixture
def pin(monkeypatch):
    monkeypatch.delenv("ADE_PASEO_TRANSPORT", raising=False)
    monkeypatch.delenv("ADE_PASEO_URL", raising=False)
    monkeypatch.delenv("PASEO_HOST", raising=False)
    monkeypatch.delenv("PASEO_HOME", raising=False)
    monkeypatch.syspath_prepend(str(BIN))
    loader = SourceFileLoader("_ade_pin_workspaces_test", str(SCRIPT))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


@pytest.fixture
def client(pin, monkeypatch):
    class Client:
        calls = []
        failures = set()

        def list_workspaces(self, *, include_pin_state):
            assert include_pin_state is True
            return [
                {"id": "lead", "title": "LEAD ade", "name": "WORKER overridden"},
                {"id": "custom", "title": None, "name": "custom window"},
                {"id": "pinned", "title": "OTHER ade", "pinnedAt": "stamp"},
                {"id": "worker", "title": "WORKER ade"},
                {"id": "workers", "name": "WORKERS ade"},
                {"id": "retired", "title": "RETIRED ade"},
                {"id": "archiving", "archivingAt": "stamp"},
                {"id": "archived", "archivedAt": "stamp"},
                {"id": "background", "background": True},
            ]

        def set_workspace_pinned(self, workspace_id):
            self.calls.append(workspace_id)
            if workspace_id in self.failures:
                raise pin.pc.DaemonError("denied")

    instance = Client()
    monkeypatch.setattr(pin.pc, "PaseoClient", lambda: instance)
    monkeypatch.setattr(pin, "pin_legacy", lambda _: pytest.fail("unexpected legacy process"))
    return instance


def test_check_and_apply(pin, client, capsys):
    assert pin.main(["pin", "--check"]) == 0
    assert client.calls == []
    assert capsys.readouterr().out.splitlines() == [
        "would-pin lead  LEAD ade",
        "would-pin custom  custom window",
        "already-pinned pinned  OTHER ade",
        "2/3 window(s) to pin",
    ]
    assert pin.main(["pin"]) == 0
    assert client.calls == ["lead", "custom"]
    assert capsys.readouterr().out.endswith("pinned 2/2 window(s)\n")


def test_pin_failure_keeps_sweeping(pin, client, capsys):
    client.failures.add("lead")
    assert pin.main(["pin"]) == 1
    assert client.calls == ["lead", "custom"]
    out, err = capsys.readouterr()
    assert out.endswith("pinned 1/2 window(s)\n")
    assert err == "pin failed lead: denied\n"


def test_daemon_failure_never_falls_back(pin, client, monkeypatch, capsys):
    def unavailable(**kwargs):
        raise pin.pc.DaemonError("unavailable")

    monkeypatch.setattr(client, "list_workspaces", unavailable)
    assert pin.main(["pin"]) == 1
    assert client.calls == []
    assert "unavailable" in capsys.readouterr().err


def test_explicit_cli_preserves_helper_argv_and_exit(pin, monkeypatch, tmp_path):
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o700)
    monkeypatch.setenv("ADE_PASEO_TRANSPORT", "cli")
    monkeypatch.setenv("PASEO_SET_MODEL_HELPER", str(helper))
    monkeypatch.setenv("PASEO_SET_MODEL_CLI_DIST", str(tmp_path))

    def run(argv, *, env, check):
        assert argv == [str(helper), "--disable-warning=DEP0040",
                        str(BIN / "ade-pin-workspaces.mjs"), "pin", "--check"]
        assert env["ELECTRON_RUN_AS_NODE"] == "1"
        assert env["PASEO_SET_MODEL_CLI_DIST"] == str(tmp_path)
        assert check is False
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(pin.subprocess, "run", run)
    assert pin.main(["pin", "--check"]) == 1
    helper.unlink()
    assert pin.main(["pin"]) == 69


def test_explicit_url_takes_precedence_over_cli(pin, client, monkeypatch):
    monkeypatch.setenv("ADE_PASEO_TRANSPORT", "cli")
    monkeypatch.setenv("ADE_PASEO_URL", "ws://127.0.0.1:7263/ws")
    assert pin.main(["pin", "--check"]) == 0
    assert client.calls == []


def test_isolated_entry_point_through_symlink(tmp_path):
    script = tmp_path / "ade-pin-workspaces"
    script.symlink_to(SCRIPT)
    result = subprocess.run([sys.executable, "-I", str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "ade-pin-workspaces pin [--check]" in result.stdout
    result = subprocess.run([sys.executable, "-I", str(script), "pin", "--bad"], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr


@pytest.mark.parametrize("host, url", [
    ("localhost:8888", "http://localhost:8888"),
    ("ws://127.0.0.1:8888/ws", "ws://127.0.0.1:8888/ws"),
    ("/tmp/paseo.sock", "unix:///tmp/paseo.sock"),
])
def test_explicit_local_host(pin, client, monkeypatch, host, url):
    monkeypatch.setenv("PASEO_HOST", host)

    def connect(*, url: str):
        assert url == expected_url
        return client

    expected_url = url
    monkeypatch.setattr(pin.pc, "PaseoClient", connect)
    assert pin.main(["pin", "--check"]) == 0
    assert client.calls == []


@pytest.mark.parametrize("host, home, error", [
    ("example.com:8888", "", "must specify a local endpoint"),
    ("127.0.0.1:8888", "/tmp/paseo-home", "PASEO_HOME and PASEO_HOST are both set"),
    ("http://[invalid", "", "must specify a local endpoint"),
])
def test_unsupported_host_never_pins_default(pin, client, monkeypatch, capsys, host, home, error):
    monkeypatch.setenv("PASEO_HOST", host)
    if home:
        monkeypatch.setenv("PASEO_HOME", home)
    monkeypatch.setattr(pin.pc, "PaseoClient", lambda **kwargs: pytest.fail("unexpected daemon lookup"))
    assert pin.main(["pin"]) == 1
    assert error in capsys.readouterr().err
