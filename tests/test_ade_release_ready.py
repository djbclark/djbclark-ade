"""bin/ade-release-ready: dry-run first-release readiness gate (Carried #15, 2026-11-10).

Every test but the live-checkout smoke builds a throwaway repo in tmp_path and runs the real
script with --repo, so this checkout's CHANGELOG.md / tags / roster are never touched. The tool
must never create a tag: tests assert no `git tag` side effect and no CHANGELOG write.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-release-ready"
REPO = SCRIPT.parent.parent
BIN = REPO / "bin"


def run(repo: Path, *args: str, env: dict | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def git(repo: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def seed_git(repo: Path) -> None:
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "seed")


def make_ready_repo(tmp_path: Path, *, with_git: bool = True, fragments: dict | None = None) -> Path:
    """Minimal tree that passes every local readiness check (roster copied from this checkout)."""
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n\n- something ready to ship (#1)\n",
        encoding="utf-8",
    )
    frag = tmp_path / "changelog.d"
    frag.mkdir()
    (frag / "README.md").write_text("fragments live here\n", encoding="utf-8")
    for name, body in (fragments or {}).items():
        (frag / name).write_text(body, encoding="utf-8")

    b = tmp_path / "bin"
    b.mkdir()
    # Real helpers: the gate shells out to them with --check / --repo|--root.
    for name in ("changelog-fold", "ade-roster", "ade-update"):
        src = BIN / name
        dest = b / name
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o755)

    # ade-roster --check needs skills/ + README roster markers matching tracked files.
    # Use a tiny synthetic roster the copied ade-roster will regenerate against.
    skills = tmp_path / "skills" / "alpha"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Alpha skill for the fixture.\n---\n\n# Alpha\n",
        encoding="utf-8",
    )
    # bin rows: only the three tools above (ade-roster lists every file in bin/)
    # Write README with a placeholder, then let ade-roster --write fill it.
    (tmp_path / "README.md").write_text(
        "# Fixture\n\n<!-- roster:start -->\nold\n<!-- roster:end -->\n",
        encoding="utf-8",
    )
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "test.yml").write_text("name: Tests\non: push\njobs: {}\n", encoding="utf-8")
    (wf / "adversary-marker.yml").write_text("name: adversary-marker\non: pull_request\njobs: {}\n", encoding="utf-8")

    if with_git:
        seed_git(tmp_path)
        # Roster check uses git ls-files; rewrite after the seed commit tracks the files.
        subprocess.run(
            [sys.executable, str(b / "ade-roster"), "--write", "--root", str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        git(tmp_path, "add", "README.md")
        git(tmp_path, "commit", "-m", "roster")
    else:
        subprocess.run(
            [sys.executable, str(b / "ade-roster"), "--write", "--root", str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    return tmp_path


def test_ready_repo_exits_0_and_creates_no_tag(tmp_path):
    repo = make_ready_repo(tmp_path)
    before_tags = git(repo, "tag", "-l").stdout
    before_cl = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    before_frags = sorted(p.name for p in (repo / "changelog.d").iterdir())
    r = run(repo, "--version", "0.1.0", "--date", "2026-11-10")
    assert r.returncode == 0, r.stderr + r.stdout
    assert "READY" in r.stdout
    assert "NOT DONE" in r.stdout
    assert "v0.1.0" in r.stdout
    assert "## 0.1.0 - 2026-11-10" in r.stdout
    assert git(repo, "tag", "-l").stdout == before_tags
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == before_cl
    assert sorted(p.name for p in (repo / "changelog.d").iterdir()) == before_frags


def test_json_ready_plan_lists_empty_performed(tmp_path):
    repo = make_ready_repo(tmp_path, fragments={
        "feat.md": "### Added\n\n- a fragment entry (#2)\n",
    })
    # fragment added after last commit: re-check still ok (fold --check does not need git)
    r = run(repo, "--json", "--version", "0.1.0", "--date", "2026-11-10")
    assert r.returncode == 0, r.stderr + r.stdout
    rep = json.loads(r.stdout)
    assert rep["ready"] is True
    assert rep["plan"]["performed"] == []
    assert rep["plan"]["would_push_tag"] is False
    assert rep["plan"]["tag"] == "v0.1.0"
    assert "feat.md" in rep["plan"]["would_fold_fragments"]


def test_empty_unreleased_and_no_fragments_is_not_ready(tmp_path):
    repo = make_ready_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n", encoding="utf-8")
    r = run(repo, "--json")
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert rep["ready"] is False
    assert any("nothing to release" in p for p in rep["problems"])


def test_bad_fragment_fails_rule10(tmp_path):
    repo = make_ready_repo(tmp_path, fragments={"bad.md": "### Added\n\n- no pr number\n"})
    r = run(repo, "--json")
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any("changelog-fold --check failed" in p for p in rep["problems"])


def test_existing_version_tag_blocks(tmp_path):
    repo = make_ready_repo(tmp_path)
    git(repo, "tag", "v0.1.0")
    r = run(repo, "--json", "--version", "0.1.0")
    assert r.returncode == 1
    rep = json.loads(r.stdout)
    assert any("tag already exists" in p for p in rep["problems"])
    # other versions still ready
    r2 = run(repo, "--json", "--version", "0.2.0", "--date", "2026-11-10")
    assert r2.returncode == 0, r2.stderr + r2.stdout


def test_existing_changelog_section_blocks(tmp_path):
    repo = make_ready_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n### Added\n\n- next (#3)\n\n"
        "## 0.1.0 - 2026-01-01\n\n### Added\n\n- shipped (#0)\n",
        encoding="utf-8",
    )
    r = run(repo, "--json", "--version", "0.1.0")
    assert r.returncode == 1
    assert any("already has" in p for p in json.loads(r.stdout)["problems"])


def test_missing_ci_workflow_blocks(tmp_path):
    repo = make_ready_repo(tmp_path)
    (repo / ".github" / "workflows" / "test.yml").unlink()
    r = run(repo, "--json")
    assert r.returncode == 1
    assert any("test.yml missing" in p for p in json.loads(r.stdout)["problems"])


def test_missing_ade_update_check_flag_blocks(tmp_path):
    repo = make_ready_repo(tmp_path)
    (repo / "bin" / "ade-update").write_text(
        "#!/usr/bin/env python3\n\"\"\"ade-update without the check flag.\"\"\"\n",
        encoding="utf-8",
    )
    r = run(repo, "--json")
    assert r.returncode == 1
    assert any("does not advertise --check" in p for p in json.loads(r.stdout)["problems"])


def test_bad_version_or_date_is_usage(tmp_path):
    repo = make_ready_repo(tmp_path)
    assert run(repo, "--version", "v0.1.0").returncode == 2
    assert run(repo, "--date", "10 Nov 2026").returncode == 2
    assert run(tmp_path / "nowhere").returncode == 2


def test_slim_tags_are_ignored(tmp_path):
    repo = make_ready_repo(tmp_path)
    git(repo, "tag", "slim-2026-11-07")
    git(repo, "tag", "pre-slim-2026-11-06")
    r = run(repo, "--json", "--version", "0.1.0", "--date", "2026-11-10")
    assert r.returncode == 0, r.stderr + r.stdout
    tags = json.loads(r.stdout)["checks"]["local_release_tags"]
    assert tags == []


def test_this_checkout_smoke_does_not_tag():
    """Live smoke: run against this checkout; never create a tag; exit 0 or 1 is fine."""
    before = subprocess.run(
        ["git", "-C", str(REPO), "tag", "-l"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    r = run(REPO, "--json", "--version", "0.1.0", "--date", "2099-01-01")
    assert r.returncode in (0, 1), r.stderr + r.stdout
    after = subprocess.run(
        ["git", "-C", str(REPO), "tag", "-l"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    assert after == before
    rep = json.loads(r.stdout)
    assert rep["plan"]["performed"] == []
    assert "v0.1.0" == rep["plan"]["tag"]
