"""Run the ade-yolo plugin's offline node tests under pytest (no daemon, no install)."""
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "plugins" / "ade-yolo"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node is not installed")
def test_ade_yolo_node_suite():
    result = subprocess.run(
        [NODE, "--test", "server/yolo-lib.test.mjs"], cwd=PLUGIN,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
