"""Hermetic Node tests of the actual registered Pi virtual-model extension."""

import os
from pathlib import Path
import shutil
import subprocess


def test_pi_dynamic_extension():
    node = shutil.which("node")
    assert node, "Node is required for Pi extension tests"
    fixture = Path(__file__).with_name("pi_dynamic_extension.mjs")
    result = subprocess.run(
        [node, "--test", str(fixture)],
        cwd=fixture.parent.parent,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
