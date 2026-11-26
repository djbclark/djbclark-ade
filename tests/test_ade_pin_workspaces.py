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
                {"id": "bad-name", "name": 123},
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
        "would-pin bad-name  ",
        "already-pinned pinned  OTHER ade",
        "3/4 window(s) to pin",
    ]
    assert pin.main(["pin"]) == 0
    assert client.calls == ["lead", "custom", "bad-name"]
    assert capsys.readouterr().out.endswith("pinned 3/3 window(s)\n")


def test_pin_failure_keeps_sweeping(pin, client, capsys):
    client.failures.add("lead")
    assert pin.main(["pin"]) == 1
    assert client.calls == ["lead", "custom", "bad-name"]
    out, err = capsys.readouterr()
    assert out.endswith("pinned 2/3 window(s)\n")
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


def test_human_renamed_windows_use_structured_registry_metadata(pin, monkeypatch, tmp_path, capsys):
    lead_id = "8cd86203-d33b-49db-abde-9baba52bcf61"
    state_dir = tmp_path / "wr-state"
    state_dir.mkdir()
    pin.wsn.write_window_registry(
        state_dir / f"{lead_id}.windows.json",
        {"wks_w1", "wks_o1"},
        {
            "wks_w1": {"windowId": "wks_w1", "box": "WORKER", "repo": "djbclark-ade", "lead": lead_id},
            "wks_o1": {"windowId": "wks_o1", "box": "OTHER", "repo": "djbclark-ade", "lead": lead_id},
        },
    )
    monkeypatch.setenv("ADE_WORKER_RUN_STATE", str(state_dir))

    class Client:
        calls = []

        def list_workspaces(self, *, include_pin_state):
            return [
                {"id": "wks_w1", "title": "Daniel debugging Venice"},
                {"id": "wks_o1", "title": "WORKER notes for Daniel"},
                {"id": "wks_l1", "title": "My custom lead window"},
            ]

        def set_workspace_pinned(self, workspace_id):
            self.calls.append(workspace_id)

    inst = Client()
    monkeypatch.setattr(pin.pc, "PaseoClient", lambda: inst)
    assert pin.main(["pin"]) == 0
    # wks_w1 is structurally WORKER so skipped despite custom human title; wks_o1 is structurally OTHER so pinned despite `WORKER ` title.
    assert inst.calls == ["wks_o1", "wks_l1"]


def test_node_and_python_registry_validation_aligned(pin, tmp_path):
    """P2 Round 2: bin/ade-pin-workspaces.mjs matches bin/ade_ws_names.py on UUID filenames,
    windows-membership checks, invalid box/null entries rejection, symlinks, and FIFOs."""
    import json
    import os
    import shutil

    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    state_dir = tmp_path / "wr-state"
    state_dir.mkdir()
    lead_ok = "8cd86203-d33b-49db-abde-9baba52bcf61"
    lead_bad_box = "11111111-2222-3333-4444-555555555555"
    lead_orphan = "22222222-2222-3333-4444-555555555555"
    lead_null = "33333333-2222-3333-4444-555555555555"
    lead_sym = "44444444-2222-3333-4444-555555555555"
    lead_fifo = "55555555-2222-3333-4444-555555555555"

    # Valid UUID registry
    pin.wsn.write_window_registry(
        state_dir / f"{lead_ok}.windows.json",
        {"wks_w1", "wks_o1"},
        {
            "wks_w1": {"windowId": "wks_w1", "box": "WORKER"},
            "wks_o1": {"windowId": "wks_o1", "box": "OTHER"},
        },
    )
    # Non-UUID filename must be skipped by both Python and Node
    (state_dir / "not-a-uuid.windows.json").write_text(
        json.dumps({"windows": ["wks_nonuuid"], "entries": {"wks_nonuuid": {"windowId": "wks_nonuuid", "box": "WORKER"}}}),
        encoding="utf-8",
    )
    # Invalid explicit box must reject the file
    (state_dir / f"{lead_bad_box}.windows.json").write_text(
        json.dumps({"windows": ["wks_badbox"], "entries": {"wks_badbox": {"windowId": "wks_badbox", "box": "GARBAGE"}}}),
        encoding="utf-8",
    )
    # Orphan entry absent from windows list must reject the file
    (state_dir / f"{lead_orphan}.windows.json").write_text(
        json.dumps({"windows": ["wks_present"], "entries": {"wks_orphan": {"windowId": "wks_orphan", "box": "WORKER"}}}),
        encoding="utf-8",
    )
    # Explicit null entries must reject the file
    (state_dir / f"{lead_null}.windows.json").write_text(
        json.dumps({"windows": ["wks_null"], "entries": None}),
        encoding="utf-8",
    )
    # Symlink registry must be rejected (not followed)
    target = tmp_path / "outside.json"
    target.write_text(
        json.dumps({"windows": ["wks_sym"], "entries": {"wks_sym": {"windowId": "wks_sym", "box": "WORKER"}}}),
        encoding="utf-8",
    )
    (state_dir / f"{lead_sym}.windows.json").symlink_to(target)
    # FIFO must not hang and must be skipped
    os.mkfifo(state_dir / f"{lead_fifo}.windows.json")

    # Python side
    py_reg = pin.wsn.all_registered_windows(state_dir)
    assert set(py_reg) == {"wks_w1", "wks_o1"}

    # Node side via mock CLI dist (no daemon, no PATH mutation)
    dist = tmp_path / "dist"
    (dist / "utils").mkdir(parents=True)
    pinned_log = tmp_path / "pinned.json"
    (dist / "utils" / "daemon-target.js").write_text("export function selectDaemonTarget() { return {}; }\n", encoding="utf-8")
    (dist / "utils" / "client.js").write_text(
        "import { writeFileSync } from 'node:fs';\n"
        f"const pinned = [];\n"
        "export async function connectToDaemon() {\n"
        "  return {\n"
        "    async fetchWorkspaces() {\n"
        "      return { entries: [\n"
        "        { id: 'wks_w1', title: 'Daniel debugging Venice' },\n"
        "        { id: 'wks_o1', title: 'WORKER notes' },\n"
        "        { id: 'wks_nonuuid', title: 'Custom non-uuid' },\n"
        "        { id: 'wks_orphan', title: 'Custom orphan' },\n"
        "        { id: 'wks_sym', title: 'Custom sym' },\n"
        "      ] };\n"
        "    },\n"
        "    async setWorkspacePinned(id) { pinned.push(id); },\n"
        f"    async close() {{ writeFileSync({str(pinned_log)!r}, JSON.stringify(pinned)); }},\n"
        "  };\n"
        "}\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "PASEO_SET_MODEL_CLI_DIST": str(dist),
        "ADE_WORKER_RUN_STATE": str(state_dir),
    }
    res = subprocess.run([node, str(BIN / "ade-pin-workspaces.mjs"), "pin"], capture_output=True, text=True, env=env, timeout=15)
    assert res.returncode == 0, res.stderr
    assert json.loads(pinned_log.read_text(encoding="utf-8")) == ["wks_o1", "wks_nonuuid", "wks_orphan", "wks_sym"]
