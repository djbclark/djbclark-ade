"""bin/ade-retro: read-only retrospective facts, against a fake `gh` on PATH and a throwaway git repo."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "bin" / "ade-retro"

# Records its argv, then prints scenario.json's "out" (or fails with "rc"/"err").
FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
s = json.load(open(os.path.join(d, "scenario.json")))
if sys.argv[1:2] != ["api"] or "search/issues" not in sys.argv:  # only REST search is answered (GraphQL is 403)
    sys.stderr.write("HTTP 403: GraphQL not allowed")
    sys.exit(1)
sys.stdout.write(s.get("out", ""))
sys.stderr.write(s.get("err", ""))
sys.exit(s.get("rc", 0))
"""

CHANGELOG = """# Changelog

## Unreleased

### Added

- Added `old thing` that shipped in the window. (#11)
- Unrelated entry from long ago. (#3)
"""


def git(root: Path, *args: str, date: str = "2026-11-02T12:00:00") -> None:
    env = dict(os.environ, GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def commit_file(root: Path, rel: str, text: str, date: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git(root, "add", rel, date=date)
    git(root, "commit", "-m", "add " + rel, date=date)


@pytest.fixture()
def world(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", "https://github.com/acme/widgets.git")
    commit_file(root, "CHANGELOG.md", CHANGELOG, "2026-10-01T12:00:00")
    commit_file(root, "changelog.d/in-window.md", "### Fixed\n\n- Fixed the in-window bug. (#12)\n", "2026-11-02T12:00:00")
    commit_file(root, "changelog.d/edge-start.md", "### Changed\n\n- Changed at the start edge. (#13)\n", "2026-11-01T00:30:00")
    commit_file(root, "changelog.d/edge-end.md", "### Changed\n\n- Changed at the end edge. (#14)\n", "2026-11-07T23:30:00")
    commit_file(root, "changelog.d/before.md", "### Added\n\n- Added before the window. (#8)\n", "2026-10-31T23:30:00")
    commit_file(root, "changelog.d/after.md", "### Added\n\n- Added after the window. (#9)\n", "2026-11-08T00:30:00")
    commit_file(root, "docs/handoffs/HANDOFF_x_a_2026-11-03_ab12.md", "# Handoff in window\n\nbody\n", "2026-11-03T12:00:00")
    commit_file(root, "docs/handoffs/HANDOFF_x_b_2026-10-30_cd34.md", "# Handoff before\n", "2026-10-30T12:00:00")
    gh_dir = tmp_path / "gh"
    gh_dir.mkdir()
    gh = gh_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)

    class W:
        def scenario(self, **kw) -> None:
            (gh_dir / "scenario.json").write_text(json.dumps(kw))

        def calls(self):
            p = gh_dir / "calls.log"
            return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

        def run(self, *args: str):
            env = dict(os.environ, PATH=str(gh_dir) + os.pathsep + os.environ["PATH"], FAKE_GH_DIR=str(gh_dir))
            return subprocess.run([sys.executable, str(TOOL), "--root", str(root), *args],
                                  capture_output=True, text=True, env=env, timeout=60)

    w = W()
    w.root = root
    return w


def item(n, title, merged, branch=""):
    return {"number": n, "title": title, "html_url": "https://github.com/acme/widgets/pull/%d" % n,
            "user": {"login": "dj"}, "pull_request": {"merged_at": merged}}


PRS = [item(11, "Ship old thing", "2026-11-01T09:00:00Z"), item(12, "Fix bug", "2026-11-02T09:00:00Z"),
       item(15, "Doc only", "2026-11-03T09:00:00Z")]


def search(items, total=None, pages=1):
    """gh api --paginate output: one JSON object per page, concatenated."""
    per = max(1, -(-len(items) // pages))
    return "".join(json.dumps({"total_count": len(items) if total is None else total,
                               "items": items[i:i + per]}) for i in range(0, max(len(items), 1), per))


def test_gh_success_json(world) -> None:
    world.scenario(out=search(PRS))
    r = world.run("--since", "2026-11-01", "--until", "2026-11-07", "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["tool"] == "ade-retro" and rep["repo"] == "acme/widgets"
    assert [p["number"] for p in rep["prs"]] == [11, 12, 15]
    assert {(e["pr"], e["source"]) for e in rep["changelog"]} == {(11, "CHANGELOG.md"), (12, "changelog.d/in-window.md")}
    assert [h["date"] for h in rep["handoffs"]] == ["2026-11-03"]
    assert rep["handoffs"][0]["title"] == "Handoff in window"
    assert rep["prs"][1] == {"number": 12, "title": "Fix bug", "url": "https://github.com/acme/widgets/pull/12",
                             "author": {"login": "dj"}, "mergedAt": "2026-11-02T09:00:00Z"}
    argv = world.calls()[0]
    assert argv[:4] == ["api", "-X", "GET", "search/issues"] and "--paginate" in argv
    assert "q=repo:acme/widgets is:pr is:merged merged:2026-11-01..2026-11-07" in argv
    assert "per_page=100" in argv and "pr" not in argv[:1]


def test_search_pages_are_concatenated_and_cap_is_noted(world) -> None:
    world.scenario(out=search(PRS, total=1500, pages=3))
    rep = json.loads(world.run("--since", "2026-11-01", "--until", "2026-11-07", "--json").stdout)
    assert [p["number"] for p in rep["prs"]] == [11, 12, 15]
    assert any("search capped" in n and "1500" in n for n in rep["notes"])


def test_search_without_items_is_a_source_failure(world) -> None:
    world.scenario(out='{"message": "x"}')
    assert world.run("--since", "2026-11-01", "--until", "2026-11-07").returncode == 3


def test_markdown_headings_and_gap(world) -> None:
    world.scenario(out=search(PRS))
    r = world.run("--since", "2026-11-01", "--until", "2026-11-07")
    assert r.returncode == 0
    for h in ("## A. Merged PRs", "## B. Changelog", "## C. Handoffs", "## D. Gaps"):
        assert h in r.stdout
    assert "PR #15 has no changelog entry" in r.stdout
    assert "[#12](https://github.com/acme/widgets/pull/12)" in r.stdout


def test_gh_failure_falls_back_to_git_fragments_window_edges(world) -> None:
    world.scenario(rc=1, err="gh: not logged in")
    r = world.run("--since", "2026-11-01", "--until", "2026-11-07", "--json")
    assert r.returncode == 3
    rep = json.loads(r.stdout)
    assert rep["prs"] == []
    assert sorted(e["pr"] for e in rep["changelog"]) == [12, 13, 14]  # not 8 (before) or 9 (after)
    assert all(e["source"].startswith("git:changelog.d/") for e in rep["changelog"])
    assert any("gh api search/issues failed" in n for n in rep["notes"])


def test_gh_failure_markdown_still_prints_report(world) -> None:
    world.scenario(rc=4, err="boom")
    r = world.run("--since", "2026-11-01", "--until", "2026-11-07")
    assert r.returncode == 3
    assert "## D. Gaps" in r.stdout and "gh api search/issues failed" in r.stdout


def test_gh_unreadable_json_is_a_source_failure(world) -> None:
    world.scenario(out="not json")
    assert world.run("--since", "2026-11-01", "--until", "2026-11-07").returncode == 3


def test_missing_gh_binary_is_exit_3(world, tmp_path) -> None:
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")
    # make sure no real gh is found: use a PATH holding only git and python
    bindir = tmp_path / "only"
    bindir.mkdir()
    for tool in ("git",):
        found = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
        (bindir / tool).symlink_to(found)
    env["PATH"] = str(bindir)
    r = subprocess.run([sys.executable, str(TOOL), "--root", str(world.root), "--since", "2026-11-01",
                        "--until", "2026-11-07", "--json"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 3
    assert json.loads(r.stdout)["changelog"]


def test_usage_errors(world) -> None:
    assert world.run().returncode == 2
    assert world.run("--since", "11/01/2026").returncode == 2
    assert world.run("--since", "2026-11-05", "--until", "2026-11-01").returncode == 2
    assert world.run("--since", "2026-11-01", "--repo", "nope").returncode == 2
    assert world.run("--since", "2026-11-01", "--root", "/nonexistent-dir-x").returncode == 2
    assert world.calls() == []


def test_until_defaults_to_today_and_repo_flag_wins(world) -> None:
    world.scenario(out=search([]))
    r = world.run("--since", "2026-11-01", "--repo", "other/thing", "--json")
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert rep["repo"] == "other/thing" and rep["until"] >= "2026-11-04"
    assert "q=repo:other/thing is:pr is:merged merged:2026-11-01..%s" % rep["until"] in world.calls()[0]


def test_read_only(world) -> None:
    world.scenario(out=search(PRS))
    before = subprocess.run(["git", "-C", str(world.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    mtimes = {p: p.stat().st_mtime_ns for p in world.root.rglob("*") if ".git" not in p.parts and p.is_file()}
    world.run("--since", "2026-11-01", "--until", "2026-11-07")
    after = subprocess.run(["git", "-C", str(world.root), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert before == after == ""
    assert mtimes == {p: p.stat().st_mtime_ns for p in world.root.rglob("*") if ".git" not in p.parts and p.is_file()}


def test_changelog_fold_has_main_guard_and_parser() -> None:
    src = (TOOL.parent / "changelog-fold").read_text()
    assert 'if __name__ == "__main__":' in src and "def parse_fragment_text(" in src
