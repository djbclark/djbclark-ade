"""Exercise the script's ref selection with real Git commit ancestry."""
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/github-ci-run"


@pytest.mark.parametrize("local,remote,expected,warns", [
    ("old", "new", "refs/remotes/fork/ci/base", True),
    ("new", "old", "refs/remotes/fork/ci/base", False),
    ("new", "new", "refs/remotes/fork/ci/base", False),
    (None, "new", "refs/remotes/fork/ci/base", False),
    ("new", None, "refs/heads/ci/base", False),
    (None, None, None, False),
])
def test_base_ref_selection(tmp_path, local, remote, expected, warns):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "old")
    commits = {"old": git("rev-parse", "HEAD")}
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "new")
    commits["new"] = git("rev-parse", "HEAD")
    if local:
        git("update-ref", "refs/heads/ci/base", commits[local])
    if remote:
        git("update-ref", "refs/remotes/fork/ci/base", commits[remote])
    # Run the exact selection block, stopping before any overlay or network work.
    selection = SCRIPT.read_text().split("base_ref=\n", 1)[1].split("\ntarget_sha=", 1)[0]
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail\nremote=fork\nbase_ref=\n' + selection
         + '\nprintf "%s\n" "$base_ref"'],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    if expected is None:
        assert result.returncode == 2
        assert result.stderr.strip() == "github-ci-run: ci/base not found locally or on fork"
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected
    assert ("local ci/base is behind fork/ci/base" in result.stderr) == warns
