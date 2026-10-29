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
        gh.write_text("#!/usr/bin/env python3\nimport os,sys,json\nroutes=json.load(open(os.environ['WAIVER_ROUTES'])); r=routes.get(sys.argv[-1],routes.get(sys.argv[-1].split('?')[0]))\nif r is None: sys.exit(1)\nprint(json.dumps(r))\n")
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

    def merge(self, conflict=False, edit=False, docs_conflict=False, broken=False):
        self.git("checkout", "-b", "topic")
        self.h0 = self.commit({"feature.py": "feature\n", **({"code.py": "def f(:\n raise SystemExit\n"} if broken else {}), **({"code.py": "topic\n"} if conflict else {}),
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
            "repos/r/p/pulls/1/commits": [{"sha": self.h0}],
            "repos/r/p/issues/1/timeline": [],
            "repos/r/p/commits/master": {"sha": self.target},
            f"repos/r/p/actions/workflows/test.yml/runs?head_sha={self.h0}&per_page=100": {"workflow_runs": [{
                "id": 1, "head_sha": self.h0, "event": "pull_request", "status": "completed",
                "conclusion": h0, "run_number": 1, "run_attempt": 1, "pull_requests": [{"number": 1}]}]},
            f"repos/r/p/actions/workflows/test.yml/runs?head_sha={self.target}&per_page=100": {"workflow_runs": [{
                "id": 2, "head_sha": self.target, "head_branch": "master", "event": "push", "status": "completed",
                "conclusion": master, "run_number": 2, "run_attempt": 1}]},
            "repos/r/p/actions/runs/1/attempts/1/jobs": {"jobs": [{"status": "completed", "conclusion": h0}]},
            "repos/r/p/actions/runs/2/attempts/1/jobs": {"jobs": [{"status": "completed", "conclusion": master}]},
        }))

    def classify(self, base=None, head="HEAD", pr=None, script=SCRIPT, cwd=None):
        pr = hasattr(self, "h0") if pr is None else pr
        if pr:
            routes = json.loads(self.routes.read_text())
            routes["repos/r/p/pulls/1"] = {"base": {"ref": getattr(self, "base_ref", "master"),
                "sha": base or self.base}, "head": {"sha": self.git("rev-parse", head)}}
            self.routes.write_text(json.dumps(routes))
        args = ["--pr", "1"] if pr else ["--base", base or self.base, "--head", head]
        r = subprocess.run([sys.executable, str(script), "classify", "--repo-dir", str(self.repo),
                            *args, "--repo", "r/p", "--json"],
                           cwd=cwd or self.repo, env=self.env, check=True, capture_output=True, text=True)
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
    routes[f"repos/r/p/actions/workflows/test.yml/runs?head_sha={history.h0}&per_page=100"] = {"workflow_runs": "bad"}
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


def edit_routes(history, change):
    routes = json.loads(history.routes.read_text())
    change(routes)
    history.routes.write_text(json.dumps(routes))


def h0_runs(history):
    return f"repos/r/p/actions/workflows/test.yml/runs?head_sha={history.h0}&per_page=100"


@pytest.mark.parametrize("exploit", ["e1", "e1b", "e1c", "pending", "pending-stale-success", "skipped", "neutral", "no-pr", "not-former-head"])
def test_ci_waiver_h0_evidence(history, exploit):
    history.merge(broken=True)
    def change(routes):
        run = routes[h0_runs(history)]["workflow_runs"][0]
        if exploit == "e1":
            run["event"] = "workflow_dispatch"
        elif exploit in ("e1b", "e1c"):
            routes[h0_runs(history)]["workflow_runs"] = []
            routes[f"repos/r/p/commits/{history.h0}/status"] = {"statuses": [{"state": "success"}]}
            routes[f"repos/r/p/commits/{history.h0}/check-runs"] = {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        elif exploit in ("pending", "pending-stale-success"):
            routes["repos/r/p/actions/runs/1/attempts/1/jobs"]["jobs"].append({"status": "in_progress", "conclusion": "success" if exploit == "pending-stale-success" else None})
        elif exploit in ("skipped", "neutral"):
            routes["repos/r/p/actions/runs/1/attempts/1/jobs"]["jobs"].append({"status": "completed", "conclusion": exploit})
        elif exploit == "no-pr":
            routes["repos/r/p/pulls/1/commits"] = []
        elif exploit == "not-former-head":
            run["pull_requests"] = [{"number": 99}]
    edit_routes(history, change)
    assert history.classify()["class"] == "none"


@pytest.mark.parametrize("parent", ["h0", "target"])
def test_ci_waiver_latest_failed_rerun(history, parent):
    history.merge()
    commit = getattr(history, parent)
    def change(routes):
        runs = routes[f"repos/r/p/actions/workflows/test.yml/runs?head_sha={commit}&per_page=100"]["workflow_runs"]
        runs.append({**runs[0], "run_attempt": 2, "conclusion": "failure"})
    edit_routes(history, change)
    assert history.classify()["class"] == "none"


def test_ci_waiver_conflict_marker_blob(history):
    history.merge(conflict=True)
    r = subprocess.run(["git", "-c", "merge.conflictStyle=merge", "merge-tree", "--write-tree", history.h0, history.target],
                       cwd=history.repo, env=history.env, capture_output=True, text=True)
    assert r.returncode == 1
    tree = r.stdout.splitlines()[0]
    blob = history.git("show", tree + ":code.py") + "\n"
    (history.repo / "code.py").write_text(blob)
    history.git("add", "code.py")
    history.git("commit", "--amend", "--no-edit")
    got = history.classify()
    assert got["class"] == "none" and "hand-edited:code.py" in got["reasons"]


@pytest.mark.parametrize("origin", ["committed", "worktree", "info", "global"])
def test_ci_waiver_e4_attributes_neutralized(history, origin):
    attr = "code.py merge=union\n"
    if origin == "committed":
        history.base = history.commit({".gitattributes": attr})
    history.git("checkout", "-b", "topic")
    history.h0 = history.commit({"code.py": "def f(:\n return 2\n"})
    history.git("checkout", "master")
    history.target = history.commit({"code.py": "def f():\n return 3\n"})
    history.git("checkout", "topic")
    if origin == "worktree":
        (history.repo / ".gitattributes").write_text(attr)
    elif origin == "info":
        (history.repo / ".git/info/attributes").write_text(attr)
    elif origin == "global":
        p = history.repo.parent / "global-attributes"
        p.write_text(attr)
        n = int(history.env.get("GIT_CONFIG_COUNT", "0"))
        history.env.update({"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "core.attributesFile", f"GIT_CONFIG_VALUE_{n}": str(p)})
    history.git("merge", "--no-ff", "master", "-m", "union")
    history.green()
    got = history.classify()
    assert got["class"] == "none" and "hand-edited:code.py" in got["reasons"]


@pytest.mark.parametrize("path", ["Tests/conftest.py", "Bin/PR-WAIT", "bin/CI-WAIVER", "nested/TESTS/x.py",
    "nested/Conftest.py", "nested/Test_x.py", "claude/hooks/handoff-tools/tests/test_context_size_nudge.py",
    ".gitattributes", "nested/.gitattributes", ".gitmodules", ".gitignore", "nested/.gitcontrol"])
def test_ci_waiver_expanded_exclusions(history, path):
    history.commit({path: "excluded\n"})
    got = history.classify()
    assert got["class"] == "none" and "hard-exclusion:" + path in got["reasons"]


@pytest.mark.parametrize("kind", ["symlink", "executable", "gitlink"])
def test_ci_waiver_doc_modes(history, kind):
    path = "docs/handoffs/link"
    if kind == "symlink":
        p = history.repo / path
        p.parent.mkdir(parents=True)
        p.symlink_to("../../code.py")
        history.git("add", path)
    elif kind == "executable":
        path = "CHANGELOG.md"
        history.git("update-index", "--chmod=+x", path)
    else:
        history.git("update-index", "--add", "--cacheinfo", "160000," + history.base + "," + path)
    history.git("commit", "-m", "mode")
    got = history.classify()
    assert got["class"] == "none" and "unsafe-doc-mode:" + path in got["reasons"]


def test_ci_waiver_repo_dir_pinned(history, tmp_path):
    history.commit({"CHANGELOG.md": "notes\n"})
    assert history.classify(cwd=tmp_path)["class"] == "docs-only"


def test_ci_waiver_base_must_master(history):
    history.commit({"CHANGELOG.md": "notes\n"})
    history.base_ref = "other"
    got = history.classify(pr=True)
    assert got["class"] == "none" and "base-not-master" in got["reasons"]


def test_ci_waiver_normalizes_paths():
    import runpy
    mod = runpy.run_path(str(SCRIPT))
    for path in ("../CHANGELOG.md", "docs/handoffs/../../../code.py", "/CHANGELOG.md"):
        with pytest.raises(ValueError, match="unsafe-path"):
            mod["normalized"](path)
    assert mod["excluded"]("BIN//PR-WAIT")


def test_ci_waiver_unsupported_attr_source_refuses(history):
    import shutil
    history.merge()
    real_git = shutil.which("git")
    shim = Path(history.env["PATH"].split(os.pathsep)[0]) / "git"
    shim.write_text("#!/usr/bin/env python3\nimport os,sys\nif any(a.startswith('--attr-source=') for a in sys.argv[1:]): sys.exit(129)\nos.execv(" + repr(real_git) + ",[" + repr(real_git) + ",*sys.argv[1:]])\n")
    shim.chmod(0o755)
    got = history.classify()
    assert got["class"] == "none" and got["reasons"][0].startswith("git-error:--attr-source=")


def test_ci_waiver_git_dir_environment_ignored(history, tmp_path):
    history.commit({"CHANGELOG.md": "notes\n"})
    other = tmp_path / "other"
    other.mkdir()
    foreign = History(other)
    history.env["GIT_DIR"] = str(foreign.repo / ".git")
    assert history.classify(pr=False)["class"] == "docs-only"
