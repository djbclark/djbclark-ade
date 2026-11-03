"""Execute the canonical TS extension and schema with real, provider-free child processes."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "pi/extensions/subagent"


def test_pi_subagent_invocation(tmp_path):
    node = shutil.which("node")
    installed = (EXTENSION / "node_modules/@earendil-works/pi-coding-agent").exists()
    if not node or not installed:
        if os.environ.get("CI") and os.environ.get("RUNNER_OS") == "Linux":
            pytest.fail("Linux CI must install the subagent Node dependencies")
        pytest.skip("Requires Node 24+ and npm install in pi/extensions/subagent (Linux CI)")
    home = tmp_path / "home"
    home.mkdir()
    # Deliberately do not pass the operator's environment, credential locations, or Pi stores.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PI_CODING_AGENT_DIR": str(home / ".pi/agent"),
        "PI_OFFLINE": "1",
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "SUBAGENT_TEST_ROOT": str(tmp_path),
        "SUBAGENT_TEST_LOG": str(tmp_path / "children.jsonl"),
    }
    result = subprocess.run(
        [node, str(EXTENSION / "test-invocation.mjs")],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout
