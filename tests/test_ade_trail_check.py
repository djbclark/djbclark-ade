"""Exercise the Trail diagnostic CLI without an installed Trail package or live hooks."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "ade-trail-check"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def invoke(*args, cwd, env=None):
    return subprocess.run(
        [NODE, str(SCRIPT), *args], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=15,
    )


@pytest.mark.parametrize("relative", [False, True])
def test_matcher_paths_load_and_report_drift(tmp_path, relative):
    matcher = tmp_path / "module with spaces.mjs"
    matcher.write_text("export function agentGuard() { return null; }\n")
    selected = matcher.name if relative else str(matcher)
    result = invoke("--matcher", selected, cwd=tmp_path)
    assert result.returncode == 1, result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "drift"
    assert output["matcher"] == str(matcher)
    # Loading succeeded: a permissive matcher is correctly caught by a denial fixture.
    activation = next(row for row in output["results"] if row["name"] == "activation")
    assert activation["actual"] is None and not activation["ok"]


def test_missing_matcher_is_unavailable(tmp_path):
    result = invoke("--matcher", "missing.mjs", cwd=tmp_path)
    assert result.returncode == 2
    assert json.loads(result.stderr)["status"] == "unavailable"


@pytest.mark.parametrize("args", [("--matcher",), ("--matcher", ""), ("--unknown", "file.mjs")])
def test_invalid_arguments_are_usage_errors(tmp_path, args):
    result = invoke(*args, cwd=tmp_path)
    assert result.returncode == 2
    assert "usage:" in json.loads(result.stderr)["error"]


def test_roster_contains_diagnostic_description():
    result = subprocess.run(
        [str(REPO / "bin" / "ade-roster")], cwd=REPO,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    expected = "| [`ade-trail-check`](bin/ade-trail-check) | Detect drift in the installed Trail skill-consent matcher. |"
    assert expected in result.stdout
