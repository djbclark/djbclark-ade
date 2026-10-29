"""paseo-new-seat: every seat runs yolo (home rule 16). `auto_accept` is a separate feature flag and does not
change a claude seat's permission mode, so the create must carry `modeId` itself (2026-10-26: a claude seat
opened without one started in `default` and prompted)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parent.parent / "bin"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is needed to run the dry-run half")


def dry_run(tmp_path: Path, *extra: str) -> dict:
    """Run bin/paseo-new-seat --dry-run with plain node standing in for Paseo's Electron helper."""
    helper = tmp_path / "helper"
    helper.write_text(f'#!/bin/sh\nexec "{NODE}" "$@"\n')
    helper.chmod(0o755)
    env = dict(os.environ, PASEO_NEW_SEAT_HELPER=str(helper), PASEO_NEW_SEAT_CLI_DIST=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, str(BIN / "paseo-new-seat"), "--title", "t", "--cwd", str(tmp_path),
         "--workspace", "wks_x", "--dry-run", *extra],
        env=env, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_claude_seat_defaults_to_bypass_permissions(tmp_path):
    assert dry_run(tmp_path, "--provider", "claude", "--model", "claude-sonnet-5-5")["modeId"] == "bypassPermissions"


def test_explicit_mode_wins(tmp_path):
    assert dry_run(tmp_path, "--provider", "claude", "--mode", "plan")["modeId"] == "plan"


def test_other_provider_keeps_its_own_default(tmp_path):
    assert dry_run(tmp_path, "--provider", "omp", "--model", "x")["modeId"] is None


def test_no_auto_accept_keeps_a_claude_seat_prompting(tmp_path):
    assert dry_run(tmp_path, "--provider", "claude", "--model", "claude-sonnet-5-5", "--no-auto-accept")["modeId"] is None


def test_a_mode_that_looks_like_a_flag_is_refused(tmp_path):
    helper = tmp_path / "helper"
    helper.write_text(f'#!/bin/sh\nexec "{NODE}" "$@"\n')
    helper.chmod(0o755)
    env = dict(os.environ, PASEO_NEW_SEAT_HELPER=str(helper), PASEO_NEW_SEAT_CLI_DIST=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, str(BIN / "paseo-new-seat"), "--title", "t", "--cwd", str(tmp_path),
         "--provider", "claude", "--mode=--allow-new-workspace", "--dry-run"],
        env=env, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 2 and "not a mode id" in proc.stderr


def test_a_deliberate_non_yolo_claude_seat_is_labelled_perm_ask(tmp_path):
    labels = lambda *x: dry_run(tmp_path, "--provider", "claude", *x)["labels"]  # noqa: E731
    assert labels("--mode", "plan") == {"perm": "ask"}
    assert labels("--no-auto-accept") == {"perm": "ask"}
    assert labels() == {}


def test_other_providers_get_no_perm_label(tmp_path):
    assert dry_run(tmp_path, "--provider", "omp", "--model", "x")["labels"] == {}


def create_with_stub_daemon(tmp_path: Path, provider: str, features: list, *extra: str) -> subprocess.CompletedProcess:
    """Run the real create path against a stub daemon whose agent state file is already written."""
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "client.js").write_text(
        "export const connectToDaemon = async () => ({"
        " createAgent: async () => ({ id: 'abcdef12-0000' }), close: async () => {} });\n")
    (tmp_path / "utils" / "daemon-target.js").write_text("export const selectDaemonTarget = () => ({});\n")
    home = tmp_path / "home"
    state = home / ".paseo" / "agents" / "proj"
    state.mkdir(parents=True)
    (state / "abcdef12-0000.json").write_text(json.dumps({"features": features, "lastModeId": "bypassPermissions"}))
    helper = tmp_path / "helper"
    helper.write_text(f'#!/bin/sh\nexec "{NODE}" "$@"\n')
    helper.chmod(0o755)
    env = dict(os.environ, HOME=str(home), PASEO_NEW_SEAT_HELPER=str(helper), PASEO_NEW_SEAT_CLI_DIST=str(tmp_path))
    return subprocess.run(
        [sys.executable, str(BIN / "paseo-new-seat"), "--title", "t", "--cwd", str(tmp_path),
         "--workspace", "wks_x", "--provider", provider, *extra],
        env=env, capture_output=True, text=True, timeout=60, check=False)


def test_a_claude_seat_with_no_auto_accept_feature_verifies_by_its_mode(tmp_path):
    proc = create_with_stub_daemon(tmp_path, "claude", [], "--mode", "bypassPermissions")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "NOT verified" not in proc.stdout and "grey" not in proc.stdout
    assert "mode: bypassPermissions (verified)" in proc.stdout


def test_a_provider_that_may_not_have_loaded_its_features_is_still_unverified(tmp_path):
    proc = create_with_stub_daemon(tmp_path, "cline", [])
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "NOT verified" in proc.stdout
