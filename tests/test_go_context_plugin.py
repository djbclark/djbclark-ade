"""Run native V2 plugin tests in CI without starting OpenCode or calling a model."""
from pathlib import Path
import shutil
import subprocess


def test_native_go_context_plugin():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node, "Node is required to validate the native OpenCode plugin"
    result = subprocess.run([node, "--test", str(root / "opencode-plugins/go-context/guard.test.js")],
                            capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
