"""Stage 0 dual-read wrapper paths and lookalike rejections for claude/hooks/bg_test_gate.py."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

GATE = Path(__file__).resolve().parents[1] / "claude/hooks/bg_test_gate.py"


def _run_gate(command: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )


@pytest.mark.parametrize(
    "command",
    [
        "~/ops/site-private/bin/bg pytest tests/t.py",
        "~/ops/site-private/bin/bgrun pytest tests/t.py",
        "~/ops/site-private-djbclark/bin/bgrun pytest tests/t.py",
        "~/ops/site-public-djbclark/bin/bgrun pytest tests/t.py",
        "~/.local/bin/bgrun pytest tests/t.py",
        "~/.local/bin/bg pytest tests/t.py",
        "$HOME/.local/bin/bgrun pytest tests/t.py",
        '"$HOME/.local/bin/bgrun" pytest tests/t.py',
        "${HOME}/.local/bin/bgrun pytest tests/t.py",
        "/Users/me/.local/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-public-djbclark/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-private-djbclark/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-public-djbclark-lab/bin/bg pytest tests/t.py",
        "/Users/me/tendcf-ops/tendcf-public-djbclark/bin/bgrun pytest tests/t.py",
        "timeout 600 ~/.local/bin/bgrun pytest tests/t.py",
        "echo 'pytest tests/t.py'",
    ],
)
def test_wrapper_aliases_allowed(command: str) -> None:
    result = _run_gate(command)
    assert not result.stdout, (command, result.stdout)


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/t.py",
        "bg pytest tests/t.py",
        "bgrun pytest tests/t.py",
        "/tmp/bgrun pytest tests/t.py",
        "~/ops/site-private/bin/bgrunner pytest tests/t.py",
        "~/tendcf-ops/tendcf-public-foo-wt/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-private-foo-wt/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-private/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/tendcf-public-Foo/bin/bgrun pytest tests/t.py",
        "~/tendcf-ops/site-private/bin/bgrun pytest tests/t.py",
        "~/.local/bin/bgrun pytest a.py; pytest b.py",
    ],
)
def test_bare_and_lookalike_wrappers_denied(command: str) -> None:
    result = _run_gate(command)
    assert result.stdout, f"expected deny for {command!r}"
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "bin/bgrun" in result.stdout
