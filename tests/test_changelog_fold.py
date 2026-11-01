"""bin/changelog-fold folds changelog.d/*.md fragments into CHANGELOG.md's Unreleased (2026-10-31).

Every test builds a throwaway repo directory in tmp_path (no git needed) and runs the real script on it
with --repo, so the checkout's own CHANGELOG.md and changelog.d/ are never touched.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "changelog-fold"
REPO = SCRIPT.parent.parent

EXISTING = """# Changelog

Intro text.

## Unreleased

### Added

- old added one (#1)
  wrapped continuation of the old entry
- old added two (#2)

### Fixed

- old fix (#3)

## 1.0.0 - 2026-01-01

### Added

- shipped thing (#0)
"""


def make_repo(tmp_path, changelog=EXISTING, fragments=None):
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    d = tmp_path / "changelog.d"
    d.mkdir()
    (d / "README.md").write_text("fragments live here\n")
    for name, body in (fragments or {}).items():
        (d / name).write_text(body)
    return tmp_path


def run(repo, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args], capture_output=True, text=True)


def frags(repo):
    return sorted(p.name for p in (repo / "changelog.d").iterdir() if p.name != "README.md")


def test_fold_into_existing_sections_newest_first_and_creates_missing_in_order(tmp_path):
    repo = make_repo(tmp_path, fragments={
        "feat-x.md": "### Added\n\n- new thing (#10)\n\n### Security\n\n- closed a hole (#10).\n",
        "fix-y.md": "### Changed\n\n- changed a flag (#11)\n",
    })
    r = run(repo)
    assert r.returncode == 0, r.stderr
    assert (repo / "CHANGELOG.md").read_text() == """# Changelog

Intro text.

## Unreleased

### Added

- new thing (#10)
- old added one (#1)
  wrapped continuation of the old entry
- old added two (#2)

### Changed

- changed a flag (#11)

### Fixed

- old fix (#3)

### Security

- closed a hole (#10).

## 1.0.0 - 2026-01-01

### Added

- shipped thing (#0)
"""
    assert frags(repo) == []


def test_fold_into_empty_unreleased_at_end_of_file(tmp_path):
    repo = make_repo(tmp_path, changelog="# Changelog\n\n## Unreleased\n",
                     fragments={"a.md": "### Added\n\n- first (#5)\n"})
    assert run(repo).returncode == 0
    assert (repo / "CHANGELOG.md").read_text() == "# Changelog\n\n## Unreleased\n\n### Added\n\n- first (#5)\n"


def test_missing_unreleased_section_is_created_above_the_first_release(tmp_path):
    repo = make_repo(tmp_path, changelog="# Changelog\n\n## 1.0.0 - 2026-01-01\n\n### Added\n\n- old (#0)\n",
                     fragments={"a.md": "### Fixed\n\n- fixed (#5)\n"})
    assert run(repo).returncode == 0
    assert (repo / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## Unreleased\n\n### Fixed\n\n- fixed (#5)\n\n## 1.0.0 - 2026-01-01\n\n### Added\n\n- old (#0)\n")


def test_two_fragments_to_one_section_go_in_file_name_order(tmp_path):
    repo = make_repo(tmp_path, fragments={
        "b-branch.md": "### Added\n\n- from b (#21)\n",
        "a-branch.md": "### Added\n\n- from a first line (#20)\n  and its second line (#20)\n",
    })
    assert run(repo).returncode == 0
    text = (repo / "CHANGELOG.md").read_text()
    added = text.split("### Added\n\n")[1].split("\n\n")[0]
    assert added.splitlines() == [
        "- from a first line (#20)", "  and its second line (#20)", "- from b (#21)",
        "- old added one (#1)", "  wrapped continuation of the old entry", "- old added two (#2)"]


def test_bad_fragment_is_refused_by_check_and_by_fold_and_nothing_is_written(tmp_path):
    repo = make_repo(tmp_path, fragments={
        "good.md": "### Added\n\n- fine (#30)\n",
        "bad-heading.md": "### Improved\n\n- nope (#31)\n",
        "no-number.md": "### Fixed\n\n- forgot the number\n",
        "stray.md": "just prose\n",
    })
    before = (repo / "CHANGELOG.md").read_text()
    for args in (("--check",), ()):
        r = run(repo, *args)
        assert r.returncode == 1
        assert "bad-heading.md" in r.stderr and "no-number.md" in r.stderr and "stray.md" in r.stderr
        assert "good.md" not in r.stderr
        assert (repo / "CHANGELOG.md").read_text() == before
        assert frags(repo) == ["bad-heading.md", "good.md", "no-number.md", "stray.md"]


def test_check_accepts_valid_fragments_without_writing_or_deleting(tmp_path):
    repo = make_repo(tmp_path, fragments={"a.md": "### Added\n\n- ok (#40)\n  wrapped (#40)\n"})
    before = (repo / "CHANGELOG.md").read_text()
    r = run(repo, "--check")
    assert r.returncode == 0, r.stderr
    assert (repo / "CHANGELOG.md").read_text() == before and frags(repo) == ["a.md"]


def test_entry_must_end_with_number_on_its_last_wrapped_line(tmp_path):
    repo = make_repo(tmp_path, fragments={"a.md": "### Added\n\n- starts (#40) but\n  ends without it\n"})
    assert run(repo, "--check").returncode == 1


def test_empty_fragment_and_stray_file_are_refused(tmp_path):
    repo = make_repo(tmp_path, fragments={"empty.md": "\n", "notes.txt": "x"})
    r = run(repo, "--check")
    assert r.returncode == 1 and "empty.md" in r.stderr and "notes.txt" in r.stderr


def test_a_wrong_repo_or_a_missing_changelog_is_exit_2_even_for_check(tmp_path):  # adversary PR190 r1 A4
    assert run(tmp_path / "typo").returncode == 2
    assert run(tmp_path / "typo", "--check").returncode == 2
    (tmp_path / "r").mkdir()
    repo = make_repo(tmp_path / "r", fragments={"a.md": "### Added\n\n- x (#1)\n"})
    (repo / "CHANGELOG.md").unlink()
    assert run(repo, "--check").returncode == 2
    (repo / "changelog.d" / "a.md").unlink()
    assert run(repo, "--check").returncode == 2  # no fragments is not an excuse either


def test_second_run_is_a_noop(tmp_path):
    repo = make_repo(tmp_path, fragments={"a.md": "### Added\n\n- once (#50)\n"})
    assert run(repo).returncode == 0
    after_first = (repo / "CHANGELOG.md").read_text()
    r = run(repo)
    assert r.returncode == 0 and (repo / "CHANGELOG.md").read_text() == after_first


def test_rerun_after_a_crash_before_the_deletions_does_not_duplicate(tmp_path):
    repo = make_repo(tmp_path, fragments={"a.md": "### Added\n\n- once (#50)\n"})
    assert run(repo).returncode == 0
    folded = (repo / "CHANGELOG.md").read_text()
    (repo / "changelog.d" / "a.md").write_text("### Added\n\n- once (#50)\n")  # the deletion that never happened
    r = run(repo)
    assert r.returncode == 0 and "skipped" in r.stdout
    assert (repo / "CHANGELOG.md").read_text() == folded and frags(repo) == []


def test_rerun_after_a_release_moved_the_entry_under_a_dated_heading_does_not_duplicate(tmp_path):  # adversary PR190 r1 A3
    moved = "# Changelog\n\n## Unreleased\n\n## 1.1.0 - 2026-02-01\n\n### Added\n\n- once (#50)\n"
    repo = make_repo(tmp_path, changelog=moved, fragments={"a.md": "### Added\n\n- once (#50)\n"})
    r = run(repo)
    assert r.returncode == 0 and "skipped" in r.stdout
    assert (repo / "CHANGELOG.md").read_text().count("- once (#50)") == 1 and frags(repo) == []


def test_a_bom_in_a_fragment_is_accepted(tmp_path):
    repo = make_repo(tmp_path, fragments={})
    (repo / "changelog.d" / "bom.md").write_bytes(b"\xef\xbb\xbf### Added\n\n- with a bom (#60)\n")
    assert run(repo, "--check").returncode == 0


def test_missing_changelog_is_a_usage_error_and_keeps_the_fragments(tmp_path):
    repo = make_repo(tmp_path, fragments={"a.md": "### Added\n\n- x (#1)\n"})
    (repo / "CHANGELOG.md").unlink()
    assert run(repo).returncode == 2
    assert frags(repo) == ["a.md"]


def test_committed_fragments_in_this_repo_are_valid():
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(REPO), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
