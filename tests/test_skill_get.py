"""Unit tests for bin/skill-get: catalogue, keyword search, paging, --ref confinement."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "skill-get"


def make(tmp: Path):
    root = tmp / "skills"
    a = root / "alpha"
    (a / "references").mkdir(parents=True, exist_ok=True)
    (a / "SKILL.md").write_text("---\nname: alpha\ndescription: >-\n  Does alpha things\n  across lines.\n---\n# Alpha\n" + "x" * 1500)
    (a / "references" / "r.md").write_text("ref body")
    (root / "beta").mkdir(exist_ok=True)
    (root / "beta" / "SKILL.md").write_text("---\nname: beta\ndescription: Beta fetches web pages\n---\nbeta body")
    (root / ".trash").mkdir(exist_ok=True)
    (root / ".trash" / "SKILL.md").write_text("hidden")
    (tmp / "secret.txt").write_text("nope")
    return root


def run(tmp, *args):
    env = dict(os.environ, SKILL_GET_ROOTS=str(make(tmp)))
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_list_names_only(tmp_path):
    p = run(tmp_path, "--list")
    assert p.returncode == 0 and "alpha, beta" in p.stdout and "hidden" not in p.stdout


def test_list_keyword_shows_folded_description(tmp_path):
    p = run(tmp_path, "--list", "alpha")
    assert "alpha: Does alpha things across lines." in p.stdout and "beta" not in p.stdout


def test_list_no_match(tmp_path):
    assert run(tmp_path, "--list", "zzz").returncode == 1


def test_get_strips_frontmatter_and_lists_refs(tmp_path):
    p = run(tmp_path, "alpha", "--max-chars", "1000")
    assert "# Alpha" in p.stdout and "description:" not in p.stdout
    assert "TRUNCATED" in p.stdout and "--offset" in p.stdout
    assert "references/r.md" in p.stdout


def test_get_second_page(tmp_path):
    p = run(tmp_path, "alpha", "--offset", "1000", "--max-chars", "1000")
    assert "TRUNCATED" not in p.stdout and "# Alpha" not in p.stdout


def test_ref_file_and_escape(tmp_path):
    assert "ref body" in run(tmp_path, "alpha", "--ref", "references/r.md").stdout
    p = run(tmp_path, "alpha", "--ref", "../../secret.txt")
    assert p.returncode == 1 and "nope" not in p.stdout


def test_unknown_suggests_close(tmp_path):
    p = run(tmp_path, "alpa")
    assert p.returncode == 1 and "alpha" in p.stdout
