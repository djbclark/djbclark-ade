"""Unit tests for plugins/ade-claim (no live Paseo daemon)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_ade_claim_plugin_argv_builder() -> None:
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node, "Node is required to validate the ade-claim Paseo plugin"
    test_file = root / "plugins" / "ade-claim" / "server" / "claim-lib.test.mjs"
    result = subprocess.run([node, "--test", str(test_file)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
