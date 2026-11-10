"""tests for .github/scripts/pytest-suite-needed.sh (docs/changelog CI short-circuit)."""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "pytest-suite-needed.sh"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
    )
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=master", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=check,
        timeout=30,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    (tmp_path / "keep.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a\n", encoding="utf-8")
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "CHANGELOG.md").write_text("# c\n", encoding="utf-8")
    script_dir = tmp_path / ".github" / "scripts"
    script_dir.mkdir(parents=True)
    script_dir.joinpath("pytest-suite-needed.sh").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    os.chmod(script_dir / "pytest-suite-needed.sh", 0o755)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _run(repo: Path, base: str, head: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / ".github/scripts/pytest-suite-needed.sh"), "--base", base, "--head", head],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_docs_only_skips(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "docs" / "b.md").write_text("b\n", encoding="utf-8")
    (repo / "changelog.d" / "x.md").write_text("- note (#0)\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# c\nmore\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "docs")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, base, head)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "suite=skip" in r.stdout


def test_root_instruction_markdown_only_skips(repo: Path) -> None:
    """AGENTS/README/LICENSE alone should not burn ~11 min of pytest-linux (2026-11-10)."""
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    (repo / "README.md").write_text("# readme\n", encoding="utf-8")
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "root md")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, base, head)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "suite=skip" in r.stdout


def test_code_change_needs_suite(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "keep.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "docs" / "b.md").write_text("b\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "code")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "suite=needed" in r.stdout
    assert "keep.py" in r.stdout


def test_workflow_change_needs_suite(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True)
    wf.joinpath("test.yml").write_text("name: t\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "wf")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "suite=needed" in r.stdout
