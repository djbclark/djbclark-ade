"""Both transitional wrapper spellings remain accepted by the Bash test gate."""
import json
from pathlib import Path
import subprocess
import sys

GATE = Path(__file__).resolve().parents[1] / "claude/hooks/bg_test_gate.py"


def test_wrapper_aliases_and_bare_test():
    for command in ("~/ops/site-private/bin/bg pytest tests/t.py",
                    "~/ops/site-private/bin/bgrun pytest tests/t.py",
                    "~/ops/site-private-djbclark/bin/bgrun pytest tests/t.py",
                    "pytest tests/t.py"):
        result = subprocess.run([sys.executable, str(GATE)], input=json.dumps({
            "tool_name": "Bash", "tool_input": {"command": command}}),
            capture_output=True, text=True, check=True)
        if command.startswith("pytest"):
            assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
            assert "bin/bgrun" in result.stdout
        else:
            assert not result.stdout
