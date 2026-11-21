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

UPSTREAM = "---\nname: herdr\ndescription: UPSTREAMDESC\n---\n# Herdr\n\nbody line\n"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


def _tree(tmp_path: Path, linked: bool = True) -> Path:
    """A throwaway checkout (a linked worktree by default): the script resolves skills/herdr/SKILL.md next to itself."""
    main = tmp_path / "main"
    (main / "bin").mkdir(parents=True)
    _git("init", "-q", cwd=main)
    shutil.copy(SCRIPT, main / "bin" / "herdr-skill-refresh")
    _git("add", "-A", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    if not linked:
        return main
    wt = tmp_path / "wt"
    _git("worktree", "add", "-q", "-b", "work", str(wt), cwd=main)
    return wt


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
    assert "UPSTREAMDESC" not in text
    assert text.endswith("# Herdr\n\nbody line\n")
    # the ADE overlay sits between the frontmatter and the untouched upstream body
    assert text.index("## ADE rules (override the upstream text below)") < text.index("# Herdr\n\nbody line")
    assert _run(root, f"{fake}:/usr/bin:/bin", "--check").returncode == 0
    # no temp files left behind
    assert [p.name for p in (root / "skills" / "herdr").iterdir()] == ["SKILL.md"]


def test_refresh_refuses_to_write_in_the_shared_checkout(tmp_path: Path) -> None:
    root = _tree(tmp_path, linked=False)
    fake = _fake_herdr(tmp_path, UPSTREAM)
    r = _run(root, f"{fake}:/usr/bin:/bin")
    assert r.returncode == 2 and "linked worktree" in r.stderr
    assert not (root / "skills" / "herdr" / "SKILL.md").exists()
    assert _run(root, f"{fake}:/usr/bin:/bin", "--check").returncode == 1  # --check still runs (file absent = drift)


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


def test_tracked_skill_carries_the_ade_overlay_and_upstream_guard() -> None:
    """PR 855 adversary findings 1, 2, 3 and 6: the rules are in the file every TUI loads."""
    text = (REPO / "skills" / "herdr" / "SKILL.md").read_text()
    head = " ".join(text[:text.index("\n---\n", 4)].split())  # the description is folded over lines
    assert "Do not use merely because a task could benefit from a background terminal" in head
    assert "message another agent" not in head  # messaging is not what the description invites
    overlay = text[text.index("## ADE rules"):text.index("\n# Herdr")]
    for needle in ("herdr agent prompt", "send-keys", "paseo send --json", "SendMessage", "atomic reply file",
                   "Only the receiver writes an ack file", "route_agent.py plan", "bgrun", "PASEO_AGENT_ID"):
        assert needle in overlay, needle
    assert text.index("## ADE rules") < text.index("\n# Herdr")
