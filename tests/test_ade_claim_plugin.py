"""Unit tests for plugins/ade-claim (no live Paseo daemon)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADE_CLAIMS = ROOT / "bin" / "ade_claims.py"


def test_ade_claim_plugin_argv_builder() -> None:
    node = shutil.which("node")
    assert node, "Node is required to validate the ade-claim Paseo plugin"
    test_file = ROOT / "plugins" / "ade-claim" / "server" / "claim-lib.test.mjs"
    result = subprocess.run(
        [node, "--test", str(test_file)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_bind_owner_merges_owner_on_active_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """W3 CLI: ade_claims.py bind-owner stamps owner.agent / owner.record."""
    state = tmp_path / "ade-state"
    state.mkdir()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    # Isolate from a real git worktree: --no-pointer.
    repo = tmp_path / "ws"
    repo.mkdir()
    new = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "new",
            "--id",
            "wt-w3-test",
            "--path",
            str(repo),
            "--branch",
            "cursor/w3",
            "--base-sha",
            "deadbeef",
            "--no-pointer",
            "--ttl",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert new.returncode == 0, new.stdout + new.stderr

    bind = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "bind-owner",
            "--id",
            "wt-w3-test",
            "--owner-agent",
            "agent-abc",
            "--owner-record",
            "agent-abc",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert bind.returncode == 0, bind.stdout + bind.stderr
    assert bind.stdout.strip() == "wt-w3-test"

    listed = subprocess.run(
        [sys.executable, str(ADE_CLAIMS), "list", "--json", "--state", "active"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert listed.returncode == 0, listed.stdout + listed.stderr
    rows = json.loads(listed.stdout)
    hit = next(r for r in rows if r["id"] == "wt-w3-test")
    assert hit["owner"]["agent"] == "agent-abc"
    assert hit["owner"]["record"] == "agent-abc"


def test_bind_owner_refuses_missing_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "ade-state"
    state.mkdir()
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    missing = subprocess.run(
        [
            sys.executable,
            str(ADE_CLAIMS),
            "bind-owner",
            "--id",
            "no-such",
            "--owner-agent",
            "agent-x",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ADE_STATE_DIR": str(state)},
    )
    assert missing.returncode == 2
    assert "no claim" in missing.stderr
