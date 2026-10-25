"""Run the RTK OpenCode plugin's permission test in CI: no OpenCode, no model, a fake rtk binary."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_rtk_plugin_permission_scan():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the plugin test")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False).stdout.strip()
    if int(version.lstrip("v").split(".")[0]) < 22:
        pytest.skip(f"{version} cannot import rtk.ts (needs TypeScript type stripping, Node 22.6+)")
    result = subprocess.run([node, "--experimental-strip-types", "--test", str(root / "opencode-plugins/rtk.test.js")],
                            capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
