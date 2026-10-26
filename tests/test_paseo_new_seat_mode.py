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


def dry_run(tmp_path: Path, *extra: str, key: str = "config") -> dict:
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
    return json.loads(proc.stdout)[key]


def test_claude_seat_defaults_to_bypass_permissions(tmp_path):
    assert dry_run(tmp_path, "--provider", "claude", "--model", "claude-sonnet-5-5")["modeId"] == "bypassPermissions"


def test_explicit_mode_wins(tmp_path):
    assert dry_run(tmp_path, "--provider", "claude", "--mode", "plan")["modeId"] == "plan"


def test_other_provider_keeps_its_own_default(tmp_path):
    assert "modeId" not in dry_run(tmp_path, "--provider", "omp", "--model", "x")


def test_no_auto_accept_keeps_a_claude_seat_prompting(tmp_path):
    assert "modeId" not in dry_run(tmp_path, "--provider", "claude", "--model", "claude-sonnet-5-5", "--no-auto-accept")


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
    labels = lambda *x: dry_run(tmp_path, "--provider", "claude", *x, key="labels")  # noqa: E731
    assert labels("--mode", "plan") == {"perm": "ask"}
    assert labels("--no-auto-accept") == {"perm": "ask"}
    assert labels() == {}


def test_other_providers_get_no_perm_label(tmp_path):
    assert dry_run(tmp_path, "--provider", "omp", "--model", "x", key="labels") == {}
