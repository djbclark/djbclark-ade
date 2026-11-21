"""bin/herdr-skill-refresh and the tracked skills/herdr/SKILL.md."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "herdr-skill-refresh"

UPSTREAM = "---\nname: herdr\ndescription: upstream text\n---\n# Herdr\n\nbody line\n"


def _tree(tmp_path: Path) -> Path:
    """A throwaway checkout: the script resolves skills/herdr/SKILL.md next to itself."""
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "bin" / "herdr-skill-refresh")
    return root


def _fake_herdr(tmp_path: Path, stdout: str, rc: int = 0) -> Path:
    d = tmp_path / "fakebin"
    d.mkdir()
    f = d / "herdr"
    f.write_text(f"#!/bin/sh\ncat <<'EOF_'\n{stdout}EOF_\nexit {rc}\n")
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return d


def _run(root: Path, path: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": path, "HOME": str(root)}
    return subprocess.run(
        [sys.executable, str(root / "bin" / "herdr-skill-refresh"), *args],
        capture_output=True, text=True, env=env,
    )


def test_refresh_keeps_loosened_frontmatter_and_upstream_body(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    fake = _fake_herdr(tmp_path, UPSTREAM)
    r = _run(root, f"{fake}:/usr/bin:/bin")
    assert r.returncode == 0, r.stderr
    text = (root / "skills" / "herdr" / "SKILL.md").read_text()
    assert text.startswith("---\nname: herdr\ndescription: >-\n")
    assert "upstream text" not in text
    assert text.endswith("# Herdr\n\nbody line\n")
    assert _run(root, f"{fake}:/usr/bin:/bin", "--check").returncode == 0
    # no temp files left behind
    assert [p.name for p in (root / "skills" / "herdr").iterdir()] == ["SKILL.md"]


def test_check_reports_drift(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    fake = _fake_herdr(tmp_path, UPSTREAM)
    assert _run(root, f"{fake}:/usr/bin:/bin").returncode == 0
    skill = root / "skills" / "herdr" / "SKILL.md"
    skill.write_text(skill.read_text() + "hand edit\n")
    r = _run(root, f"{fake}:/usr/bin:/bin", "--check")
    assert r.returncode == 1 and "DIFFERS" in r.stdout


def test_missing_herdr_is_a_clean_error(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    r = _run(root, "/usr/bin:/bin")
    assert r.returncode == 1
    assert "not installed" in r.stderr and "Traceback" not in r.stderr


def test_unterminated_frontmatter_is_a_clean_error(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    fake = _fake_herdr(tmp_path, "---\nname: herdr\nno close\n")
    r = _run(root, f"{fake}:/usr/bin:/bin")
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert not (root / "skills" / "herdr" / "SKILL.md").exists()


def test_failing_herdr_writes_nothing(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    fake = _fake_herdr(tmp_path, UPSTREAM, rc=3)
    r = _run(root, f"{fake}:/usr/bin:/bin")
    assert r.returncode == 1
    assert not (root / "skills" / "herdr").exists()


def test_tracked_skill_is_discoverable_by_skill_everywhere() -> None:
    """skill-everywhere --all finds `*/SKILL.md` under skills/: name must match the directory."""
    text = (REPO / "skills" / "herdr" / "SKILL.md").read_text()
    assert text.startswith("---\nname: herdr\n")
    assert os.access(SCRIPT, os.X_OK)
