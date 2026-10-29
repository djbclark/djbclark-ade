"""Mechanical CI waivers against real temporary Git histories and a fake gh (no network)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin/ci-waiver"


class History:
    def __init__(self, tmp):
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
                    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test"}
        self.git("init", "-b", "master")
        self.commit({"code.py": "original\n", "CHANGELOG.md": "initial\n"})
        self.base = self.git("rev-parse", "HEAD")
        shim = tmp / "shim"
        shim.mkdir()
        self.routes = tmp / "routes.json"
        gh = shim / "gh"
        gh.write_text("#!/usr/bin/env python3\nimport os,sys,json\nr=json.load(open(os.environ['WAIVER_ROUTES'])).get(sys.argv[-1].split('?')[0])\nif r is None: sys.exit(1)\nprint(json.dumps(r))\n")
        gh.chmod(0o755)
        self.env.update(PATH=str(shim) + os.pathsep + self.env["PATH"], WAIVER_ROUTES=str(self.routes))
        self.routes.write_text("{}")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, files):
        for path, body in files.items():
            p = self.repo / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        self.git("add", "--", *files)
        self.git("commit", "-m", "fixture")
        return self.git("rev-parse", "HEAD")

    def merge(self, conflict=False, edit=False, docs_conflict=False):
        self.git("checkout", "-b", "topic")
        self.h0 = self.commit({"feature.py": "feature\n", **({"code.py": "topic\n"} if conflict else {}),
                               **({"CHANGELOG.md": "topic\n"} if docs_conflict else {})})
        self.git("checkout", "master")
        self.target = self.commit({"master.py": "master\n", **({"code.py": "master\n"} if conflict else {}),
                                   **({"CHANGELOG.md": "master\n"} if docs_conflict else {})})
        self.git("checkout", "topic")
        r = subprocess.run(["git", "merge", "--no-ff", "--no-commit", "master"], cwd=self.repo,
                           env=self.env, capture_output=True)
        assert r.returncode == (1 if conflict or docs_conflict else 0), r.stderr
        if conflict:
            (self.repo / "code.py").write_text("hand resolution\n")
            self.git("add", "code.py")
        if docs_conflict:
            (self.repo / "CHANGELOG.md").write_text("human combined notes\n")
            self.git("add", "CHANGELOG.md")
        if edit:
            (self.repo / "code.py").write_text("sneaked in edit\n")
            self.git("add", "code.py")
        self.git("commit", "-m", "merge")
        self.green()

    def green(self, h0="success", master="success"):
        self.routes.write_text(json.dumps({
            f"repos/r/p/commits/{self.h0}/check-runs": {"check_runs": [{"name": "test", "status": "completed", "conclusion": h0}]},
            f"repos/r/p/commits/{self.h0}/status": {"statuses": []},
            "repos/r/p/commits/master": {"sha": self.target},
            "repos/r/p/actions/workflows/test.yml/runs": {"workflow_runs": [{"head_sha": self.target,
                "head_branch": "master", "event": "push", "status": "completed", "conclusion": master,
                "run_number": 1, "run_attempt": 1}]},
        }))

    def classify(self, base=None, head="HEAD", pr=False, script=SCRIPT):
        args = ["--pr", "1"] if pr else ["--base", base or self.base, "--head", head]
        r = subprocess.run([sys.executable, str(script), "classify", *args, "--repo", "r/p", "--json"],
                           cwd=self.repo, env=self.env, check=True, capture_output=True, text=True)
        return json.loads(r.stdout)


@pytest.fixture
def history(tmp_path):
    return History(tmp_path)


@pytest.mark.parametrize("path", ["CHANGELOG.md", "docs/handoffs/nested/handoff.md"])
def test_ci_waiver_docs_only(history, path):
    history.commit({path: "notes\n"})
    assert history.classify()["class"] == "docs-only"


@pytest.mark.parametrize("path", ["code.py", "docs/other.md", "skills/example/SKILL.md", "AGENTS.md"])
def test_ci_waiver_nonallowlist(history, path):
    history.commit({"CHANGELOG.md": "notes\n", path: "code\n"})
    got = history.classify()
    assert got["class"] == "none"
    assert "touches-nonwaivable:" + path in got["reasons"]


def test_ci_waiver_clean_master_merge(history):
    history.merge()
    assert history.classify()["class"] == "master-merge"


@pytest.mark.parametrize("kwargs", [{"conflict": True}, {"edit": True}])
def test_ci_waiver_hand_edited_merge(history, kwargs):
    history.merge(**kwargs)
    got = history.classify()
    assert got["class"] == "none"
    assert "hand-edited:code.py" in got["reasons"]


def test_ci_waiver_only_docs_conflict(history):
    history.merge(docs_conflict=True)
    assert history.classify()["class"] == "master-merge"


@pytest.mark.parametrize("h0,master,reason", [("failure", "success", "h0-not-green"),
                                              ("success", "failure", "master-not-green")])
def test_ci_waiver_red_parent(history, h0, master, reason):
    history.merge()
    history.green(h0=h0, master=master)
    got = history.classify()
    assert got["class"] == "none" and reason in got["reasons"]


@pytest.mark.parametrize("path", [".github/workflows/test.yml", "tests/test_x.py", "bin/pr-wait", "bin/ci-waiver", "config/x.toml"])
def test_ci_waiver_hard_exclusions_even_merge(history, path):
    history.merge()
    history.commit({path: "excluded\n"})
    history.git("reset", "--soft", "HEAD~1")
    history.git("commit", "--amend", "--no-edit")
    got = history.classify()
    assert got["class"] == "none" and "hard-exclusion:" + path in got["reasons"]


def test_ci_waiver_shallow_and_missing_parent(history):
    history.commit({"CHANGELOG.md": "notes\n"})
    (history.repo / ".git/shallow").write_text(history.git("rev-parse", "HEAD") + "\n")
    got = history.classify()
    assert got["class"] == "none" and "shallow-history" in got["reasons"]
    (history.repo / ".git/shallow").unlink()
    assert history.classify(head="f" * 40)["class"] == "none"


def test_ci_waiver_gh_error_and_unreadable_checks(history):
    history.merge()
    history.routes.write_text("{}")
    assert history.classify()["class"] == "none"
    history.green()
    routes = json.loads(history.routes.read_text())
    routes[f"repos/r/p/commits/{history.h0}/check-runs"] = {"check_runs": "bad"}
    history.routes.write_text(json.dumps(routes))
    assert history.classify()["class"] == "none"


def test_ci_waiver_missing_parent_object(history):
    history.merge()
    parent_object = history.repo / ".git/objects" / history.h0[:2] / history.h0[2:]
    parent_object.unlink()
    assert history.classify()["class"] == "none"


def test_ci_waiver_pr_reads_exact_base_and_head(history):
    head = history.commit({"CHANGELOG.md": "notes\n"})
    history.routes.write_text(json.dumps({"repos/r/p/pulls/1": {"base": {"sha": history.base}, "head": {"sha": head}}}))
    got = history.classify(pr=True)
    assert got["class"] == "docs-only" and got["head"] == head


def test_ci_waiver_symlink_finds_sibling_waiter(history):
    history.commit({"CHANGELOG.md": "notes\n"})
    link = history.repo / "ci-waiver-link"
    link.symlink_to(SCRIPT)
    assert history.classify(script=link)["class"] == "docs-only"


def test_ci_waiver_workflow_paths_equal_allowlist():
    import ast
    import yaml
    tree = ast.parse(SCRIPT.read_text())
    allowlist = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WAIVABLE_PATHS" for t in n.targets))
    workflow = yaml.load((ROOT / ".github/workflows/test.yml").read_text(), Loader=yaml.BaseLoader)
    for event in ("push", "pull_request"):
        assert workflow["on"][event]["paths-ignore"] == list(allowlist)
    assert workflow["on"]["push"]["branches"] == ["master"]
