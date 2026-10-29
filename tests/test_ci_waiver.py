"""Mechanical CI waivers against real temporary Git histories and a fake gh (no network)."""
import json
import os
import shutil
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
        self.env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                    "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.test",
                    "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.test"}
        self.git("init", "-b", "master")
        if decider := os.environ.get("WAIVER_CI_DECIDER"):
            subprocess.run([decider, "ci", "decide", str(self.repo), "local",
                            "Isolated local Git history for CI-waiver regression/mutation; not hosted CI"],
                           env=self.env, check=True, capture_output=True, text=True, timeout=15)
        self.commit({"code.py": "original\n", "CHANGELOG.md": "initial\n",
                     ".github/workflows/test.yml": "name: tests\n"})
        self.base = self.git("rev-parse", "HEAD")
        shim = tmp / "shim"
        shim.mkdir()
        self.routes = tmp / "routes.json"
        gh = shim / "gh"
        gh.write_text("#!/usr/bin/env python3\nimport os,sys,json\nroutes=json.load(open(os.environ['WAIVER_ROUTES'])); r=routes.get(sys.argv[-1],routes.get(sys.argv[-1].split('?')[0]))\nif r is None: sys.exit(1)\nif os.environ.get('WAIVER_GH_AUDIT'):\n with open(os.environ['WAIVER_GH_AUDIT'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\nif isinstance(r,dict) and '__pages__' in r:\n for p in r['__pages__']: print(json.dumps(p))\nelse: print(json.dumps(r))\n")
        gh.chmod(0o755)
        self.env.update(PATH=str(shim) + os.pathsep + self.env["PATH"], WAIVER_ROUTES=str(self.routes))
        self.routes.write_text("{}")
        self.real_git = shutil.which("git")
        self.upstream = tmp / "github.git"
        # Replace only the transport destination. Everything after fetch runs in
        # real Git with an independent upstream object store, never the checkout.
        self.transport = shim / "git"
        self.transport.write_text("#!/usr/bin/env python3\nimport os,sys\n"
            "args=sys.argv[1:]\n"
            "if os.environ.get('WAIVER_GIT_AUDIT'):\n"
            " import json\n"
            " with open(os.environ['WAIVER_GIT_AUDIT'],'a') as f: f.write(json.dumps([args,os.getcwd(),{k:v for k,v in os.environ.items() if k.startswith('GIT_')}])+'\\n')\n"
            "if '--verify' in args and os.environ.get('WAIVER_BAD_COMMIT') and args[-1]==os.environ['WAIVER_BAD_COMMIT']+'^{commit}': print('f'*40); sys.exit(0)\n"
            "if 'fetch' in args and 'https://github.com/r/p.git' in args:\n"
            " args=[os.environ['WAIVER_UPSTREAM'] if a=='https://github.com/r/p.git' else a for a in args]\n"
            " args=['-c','protocol.file.allow=always',*args]\n"
            "os.execv(" + repr(self.real_git) + ", [" + repr(self.real_git) + ",*args])\n")
        self.transport.chmod(0o755)
        self.env["WAIVER_UPSTREAM"] = str(self.upstream)

    def publish(self):
        env = {k: v for k, v in self.env.items() if not k.startswith("GIT_")}
        env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        subprocess.run([self.real_git, "-c", "core.commitGraph=false", "clone", "--bare", "--no-local",
                        str(self.repo), str(self.upstream)], env=env, check=True, capture_output=True, timeout=60)

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
            "repos/r/p/branches/master": {"commit": {"sha": self.target}},
            f"repos/r/p/actions/workflows/test.yml/runs?head_sha={self.h0}&per_page=100": {"workflow_runs": [{
                "id": 1, "head_sha": self.h0, "event": "pull_request", "status": "completed",
                "conclusion": h0, "run_number": 1, "run_attempt": 1,
                "head_branch": "topic", "head_repository": {"full_name": "r/p"},
                "path": ".github/workflows/test.yml",
                "pull_requests": [{"number": 1, "base": {"ref": "master", "sha": self.base}}]}]},
            f"repos/r/p/actions/workflows/test.yml/runs?head_sha={self.target}&per_page=100": {"workflow_runs": [{
                "id": 2, "head_sha": self.target, "head_branch": "master", "event": "push", "status": "completed",
                "conclusion": master, "run_number": 2, "run_attempt": 1,
                "path": ".github/workflows/test.yml"}]},
            "repos/r/p/actions/runs/1/attempts/1/jobs": {"jobs": [{"status": "completed", "conclusion": h0}]},
            "repos/r/p/actions/runs/2/attempts/1/jobs": {"jobs": [{"status": "completed", "conclusion": master}]},
        }))

    def classify(self, base=None, head="HEAD", pr=None, script=SCRIPT, cwd=None):
        pr = hasattr(self, "h0") if pr is None else pr
        if pr:
            routes = json.loads(self.routes.read_text())
            routes["repos/r/p/pulls/1"] = {"number": 1, "base": {"ref": getattr(self, "base_ref", "master"),
                "sha": base or self.base}, "head": {"sha": self.git("rev-parse", head),
                    "ref": "topic", "repo": {"full_name": "r/p"}}}
            routes.setdefault("repos/r/p/pulls?head=r%3Atopic&state=all&per_page=100", [routes["repos/r/p/pulls/1"]])
            routes.setdefault("repos/r/p/branches/master", {"commit": {"sha": self.base}})
            routes.setdefault("repos/r/p/issues/1/timeline", [])
            self.routes.write_text(json.dumps(routes))
            if not self.upstream.exists():
                self.publish()
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
    history.publish()
    # Unavailable upstream objects, rather than irrelevant checkout objects.
    shutil.rmtree(history.upstream / "objects")
    (history.upstream / "objects").mkdir()
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
    real_git = str(history.transport.with_name("git-transport"))
    history.transport.rename(real_git)
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


@pytest.mark.parametrize("refbase", ["refs/replace", "refs/alternate-replace"])
def test_ci_waiver_r2_replace_ref_cannot_hide_code(history, refbase):
    fake = history.commit({"CHANGELOG.md": "notes\n"})
    history.git("checkout", "-b", "real", history.base)
    head = history.commit({"code.py": "def f(:\n", "CHANGELOG.md": "notes\n"})
    before = history.classify(head=head)
    assert before["class"] == "none"
    history.git("update-ref", refbase + "/" + head, fake)
    history.env.update(GIT_REPLACE_REF_BASE=refbase, GIT_NO_REPLACE_OBJECTS="0")
    assert history.classify(head=head) == before
    assert history.classify(head=head, pr=True) == before


def test_ci_waiver_r2_grafts_refused(history):
    history.commit({"CHANGELOG.md": "notes\n"})
    (history.repo / ".git/info/grafts").write_text(history.git("rev-parse", "HEAD") + "\n")
    got = history.classify()
    assert got["class"] == "none" and "git-grafts-present" in got["reasons"]


def test_ci_waiver_r2_environment_grafts_ignored(history, tmp_path):
    history.commit({"CHANGELOG.md": "notes\n"})
    grafts = tmp_path / "grafts"
    grafts.write_text(history.git("rev-parse", "HEAD") + "\n")
    history.env["GIT_GRAFT_FILE"] = str(grafts)
    assert history.classify()["class"] == "docs-only"


@pytest.mark.parametrize("case", ["other-base", "missing-base", "unrelated-base-sha", "retargeted",
                                  "wrong-workflow", "missing-workflow", "changed-workflow", "push-history",
                                  "skipped-job", "nonmaster-pr", "control-file", "empty-base-sha"])
def test_ci_waiver_r2_master_workflow_evidence(history, case):
    # All jobs are green; only their provenance makes this invalid evidence.
    history.merge(broken=True)
    def change(routes):
        run = routes[h0_runs(history)]["workflow_runs"][0]
        if case == "other-base":
            run["pull_requests"][0]["base"]["ref"] = "evil"
        elif case == "missing-base":
            del run["pull_requests"][0]["base"]
        elif case == "unrelated-base-sha":
            run["pull_requests"][0]["base"]["sha"] = history.h0
        elif case == "retargeted":
            routes["repos/r/p/issues/1/timeline"] = [{"event": "base_ref_changed"}]
        elif case == "wrong-workflow":
            run["path"] = ".github/workflows/always-green.yml"
        elif case == "missing-workflow":
            del run["path"]
        elif case == "changed-workflow":
            # A later master changed the workflow after the green H0 run.
            history.git("checkout", "master")
            tip = history.commit({".github/workflows/test.yml": "name: stronger tests\n"})
            history.git("checkout", "topic")
            routes["repos/r/p/branches/master"] = {"commit": {"sha": tip}}
        elif case == "push-history":
            run["event"] = "push"
            # Unproven timeline shapes must never rescue an unassociated run.
            routes["repos/r/p/issues/1/timeline"] = [{"event": "synchronize", "after": history.h0}]
        elif case == "skipped-job":
            routes["repos/r/p/actions/runs/1/attempts/1/jobs"]["jobs"].append(
                {"status": "completed", "conclusion": "skipped"})
        elif case == "nonmaster-pr":
            history.base_ref = "evil"
        elif case == "control-file":
            history.commit({"nested/.gitcontrol": "control\n"})
            history.git("reset", "--soft", "HEAD~1")
            history.git("commit", "--amend", "--no-edit")
        elif case == "empty-base-sha":
            run["pull_requests"][0]["base"]["sha"] = ""
    edit_routes(history, change)
    got = history.classify()
    assert got["class"] == "none"
    if case == "control-file":
        assert "hard-exclusion:nested/.gitcontrol" in got["reasons"]


def test_ci_waiver_r3_base_sha_required(history):
    history.merge()
    edit_routes(history, lambda routes: routes[h0_runs(history)]["workflow_runs"][0]["pull_requests"][0]["base"].pop("sha"))
    assert history.classify()["class"] == "none"


def test_ci_waiver_r2_target_removed_from_master(history):
    history.merge()
    # T retains its successful master push run, but a rewrite removed it.
    edit_routes(history, lambda routes: routes.update({
        "repos/r/p/branches/master": {"commit": {"sha": history.base}}}))
    got = history.classify()
    assert got["class"] == "none" and "target-not-on-master" in got["reasons"]


def test_ci_waiver_r2_isolated_git_environment_and_attr_refusal(history):
    import shutil
    history.merge()
    real_git = str(history.transport.with_name("git-transport"))
    history.transport.rename(real_git)
    shim = Path(history.env["PATH"].split(os.pathsep)[0]) / "git"
    audit = history.repo.parent / "git-audit.jsonl"
    shim.write_text("#!/usr/bin/env python3\nimport os,sys,json\n"
        "with open(" + repr(str(audit)) + ", 'a') as f: f.write(json.dumps([sys.argv[1:], "
        "{k:os.environ.get(k) for k in ['GIT_NO_REPLACE_OBJECTS','GIT_GRAFT_FILE','GIT_REPLACE_REF_BASE','GIT_DIR']}])+ '\\n')\n"
        "if any(a.startswith('--attr-source=') for a in sys.argv[1:]): sys.exit(129)\n"
        "os.execv(" + repr(real_git) + ",[" + repr(real_git) + ",*sys.argv[1:]])\n")
    shim.chmod(0o755)
    history.env.update(GIT_NO_REPLACE_OBJECTS="0", GIT_REPLACE_REF_BASE="refs/poison")
    got = history.classify()
    assert got["class"] == "none" and got["reasons"][0].startswith("git-error:--attr-source=")
    calls = [json.loads(line) for line in audit.read_text().splitlines()]
    assert any("merge-tree" in args or "check-attr" in args for args, env in calls)
    for args, env in calls:
        if args == ["rev-parse", "HEAD"]:  # fixture's API head resolution, before the classifier
            continue
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert env["GIT_GRAFT_FILE"] == os.devnull
        assert env["GIT_REPLACE_REF_BASE"] is None


@pytest.mark.parametrize("parent,reason", [(1, "h0-not-green"), (2, "master-not-green")])
def test_ci_waiver_r3_empty_jobs_fail_closed(history, parent, reason):
    history.merge()
    edit_routes(history, lambda routes: routes.update({
        f"repos/r/p/actions/runs/{parent}/attempts/1/jobs": {"jobs": []}}))
    got = history.classify()
    assert got["class"] == "none" and reason in got["reasons"]


@pytest.mark.parametrize("path", ["changelog.md", "CHANGELOG.MD", "Docs/Handoffs/run.py",
                                   "docſ/handoffs/run.py", "docs//handoffs/run.py"])
def test_ci_waiver_r3_exact_allowlist(history, path):
    # Probe matching directly too: case-insensitive Mac filesystems can otherwise
    # preserve an existing CHANGELOG filename while changing its content.
    import runpy
    assert not runpy.run_path(str(SCRIPT))["waivable"](path)
    if path.casefold() != "changelog.md" and "//" not in path:
        history.commit({path: "new path"})
        assert history.classify()["class"] == "none"


def test_ci_waiver_r3_allowlist_no_unicode_normalization():
    import runpy
    import unicodedata
    mod = runpy.run_path(str(SCRIPT))
    # Neither current literal allowlist entry has a composed Unicode character;
    # use a decomposed Git path and a composed policy entry to detect NFC widening.
    mod["waivable"].__globals__["WAIVABLE_PATHS"] = ("docs/handoffs/café.md",)
    assert not mod["waivable"](unicodedata.normalize("NFD", "docs/handoffs/café.md"))


@pytest.mark.parametrize("case", ["nonmaster-base", "stale-base", "retargeted"])
def test_ci_waiver_r3_docs_base_provenance(history, case):
    history.git("checkout", "-b", "unmerged")
    unmerged = history.commit({"code.py": "unmerged code"})
    if case == "nonmaster-base":
        history.base = unmerged
    elif case == "stale-base":
        # API says master, but its stale base SHA still contains unmerged code.
        history.base = unmerged
    history.commit({"CHANGELOG.md": "docs"})
    history.routes.write_text(json.dumps({
        "repos/r/p/branches/master": {"commit": {"sha": history.git("rev-parse", "master")}},
        "repos/r/p/issues/1/timeline": [{"event": "base_ref_changed"}] if case == "retargeted" else []}))
    got = history.classify(pr=True)
    assert got["class"] == "none"
    assert ("pr-base-retargeted" if case == "retargeted" else "base-not-on-master") in got["reasons"]


@pytest.mark.parametrize("path", ["pyproject.toml", "nested/pytest.ini", "setup.cfg", "tox.ini",
                                   "uv.lock", "docs/handoffs/conftest.py", "docs/handoffs/requirements-dev.txt"])
def test_ci_waiver_r3_test_config_excluded(history, path):
    history.commit({path: "test configuration"})
    got = history.classify()
    assert got["class"] == "none" and "hard-exclusion:" + path in got["reasons"]


@pytest.mark.parametrize("poison", ["commit-graph", "alternates", "replace", "core-config", "missing-gitdir"])
def test_ci_waiver_r3_checkout_store_never_read(history, poison):
    fake = history.commit({"CHANGELOG.md": "notes"})
    fake_tree = history.git("rev-parse", fake + "^{tree}")
    history.git("checkout", "-b", "real", history.base)
    head = history.commit({"code.py": "def f(:", "CHANGELOG.md": "notes"})
    real_tree = history.git("rev-parse", head + "^{tree}")
    history.publish()  # freeze GitHub evidence before corrupting the checkout
    before = history.classify(pr=True, head=head)
    assert before["class"] == "none" and "touches-nonwaivable:code.py" in before["reasons"]
    if poison == "commit-graph":
        history.git("commit-graph", "write", "--reachable")
        graph = history.repo / ".git/objects/info/commit-graph"
        data = graph.read_bytes()
        assert data.count(bytes.fromhex(real_tree)) == 1
        tmp = graph.with_suffix(".tmp")
        tmp.write_bytes(data.replace(bytes.fromhex(real_tree), bytes.fromhex(fake_tree)))
        os.replace(tmp, graph)
        assert history.git("-c", "core.commitGraph=true", "diff", "--name-only", history.base, head) == "CHANGELOG.md"
    elif poison == "alternates":
        # Real head SHA, counterfeit loose object in an alternate store. The
        # checkout itself can resolve it after its genuine loose object is removed.
        import zlib
        evil = history.repo.parent / "evil-objects"
        dest = evil / head[:2] / head[2:]
        dest.parent.mkdir(parents=True)
        body = history.git("cat-file", "commit", head).replace(real_tree, fake_tree).encode()
        dest.write_bytes(zlib.compress(b"commit " + str(len(body)).encode() + b"\0" + body))
        (history.repo / ".git/objects" / head[:2] / head[2:]).unlink()
        (history.repo / ".git/objects/info/alternates").write_text(str(evil) + "\n")
    elif poison == "replace":
        history.git("update-ref", "refs/replace/" + head, fake)
    elif poison == "core-config":
        history.git("config", "core.repositoryformatversion", "999")
    else:
        (history.repo / ".git").rename(history.repo / "checkout-gitdir-hidden")
    # Bypass fixture head resolution, which intentionally cannot read a broken
    # checkout. The CLI gets all SHA inputs from its API, not from the checkout.
    r = subprocess.run([sys.executable, str(SCRIPT), "classify", "--repo-dir", str(history.repo),
                        "--pr", "1", "--repo", "r/p", "--json"], cwd=history.repo,
                       env=history.env, capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == before


def test_ci_waiver_r3_fetch_failure_not_waived(history):
    history.commit({"CHANGELOG.md": "docs"})
    history.publish()
    shutil.rmtree(history.upstream)
    # A valid local docs diff must not be used as fallback for failed GitHub fetch.
    history.upstream.mkdir()
    got = history.classify(pr=True)
    assert got["class"] == "none" and got["reasons"] == ["git-error:fetch"]


def test_ci_waiver_r3_private_fetch_and_merge_audit(history):
    history.merge()
    history.env["WAIVER_GIT_AUDIT"] = str(history.repo.parent / "git-calls.jsonl")
    got = history.classify()
    assert got["class"] == "master-merge"
    calls = [json.loads(line) for line in Path(history.env["WAIVER_GIT_AUDIT"]).read_text().splitlines()]
    calls = [(args, cwd, env) for args, cwd, env in calls if args != ["rev-parse", "HEAD"]]
    directories = {cwd for args, cwd, env in calls}
    assert len(directories) == 1 and str(history.repo) not in directories
    assert any("merge-tree" in args for args, cwd, env in calls)
    fetches = [args for args, cwd, env in calls if "fetch" in args]
    assert {args[-1] for args in fetches} >= {history.base, history.h0, history.target, got["head"]}
    for args in fetches:
        assert args[-2] == "https://github.com/r/p.git"
    for args, cwd, env in calls:
        assert "core.commitGraph=false" in args
        assert "gc.writeCommitGraph=false" in args and "fetch.writeCommitGraph=false" in args
        assert "protocol.allow=never" in args and "protocol.https.allow=always" in args
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1" and env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert "GIT_ALTERNATE_OBJECT_DIRECTORIES" not in env and "GIT_OBJECT_DIRECTORY" not in env
    assert not Path(next(iter(directories))).exists()  # private store removed


def test_ci_waiver_r3_each_fetched_sha_verified(history):
    head = history.commit({"CHANGELOG.md": "docs"})
    history.env["WAIVER_BAD_COMMIT"] = head
    got = history.classify(pr=True)
    assert got["class"] == "none" and got["reasons"] == ["fetched-commit-mismatch"]


def test_ci_waiver_r3_pr_cannot_select_offline_mode(history):
    r = subprocess.run([sys.executable, str(SCRIPT), "classify", "--repo-dir", str(history.repo),
                        "--pr", "1", "--base", history.base, "--head", history.base],
                       env=history.env, capture_output=True, text=True)
    assert r.returncode == 2 and "use --pr N OR" in r.stderr


@pytest.mark.parametrize("case,reason", [
    ("second-run-pr", "h0-not-pr-head"),
    ("other-number", "h0-not-pr-head"),
    ("closed-earlier-pr", "h0-ambiguous-pr-history"),
    ("closed-master-pr", "h0-ambiguous-pr-history"),
    ("fork-run", "h0-head-provenance"),
    ("other-branch", "h0-head-provenance"),
    ("missing-branch", "h0-head-provenance"),
    ("missing-repository", "h0-head-provenance"),
    ("no-history", "h0-ambiguous-pr-history"),
    ("other-history-number", "h0-ambiguous-pr-history"),
    ("history-base-evil", "h0-ambiguous-pr-history"),
    ("history-head-moved", "h0-ambiguous-pr-history"),
])
def test_ci_waiver_r4_h0_provenance(history, case, reason):
    history.merge(broken=True)
    # Establish all other guards pass; the negative case changes one fact only.
    assert history.classify()["class"] == "master-merge"
    def change(routes):
        run = routes[h0_runs(history)]["workflow_runs"][0]
        endpoint = "repos/r/p/pulls?head=r%3Atopic&state=all&per_page=100"
        own = routes[endpoint][0]
        if case == "second-run-pr":
            run["pull_requests"].append({"number": 99, "base": {"ref": "evil", "sha": history.base}})
        elif case == "other-number":
            # N14: keep a fully valid master base, changing ONLY PR number.
            run["pull_requests"][0]["number"] = 99
        elif case in ("closed-earlier-pr", "closed-master-pr"):
            other = {**own, "number": 99, "state": "closed",
                     "base": {"ref": "evil" if case == "closed-earlier-pr" else "master", "sha": history.base}}
            # A closed PR on page TWO is not visible in run.pull_requests.
            routes[endpoint] = {"__pages__": [[own], [other]]}
        elif case == "fork-run":
            run["head_repository"]["full_name"] = "attacker/p"
        elif case == "other-branch":
            run["head_branch"] = "different"
        elif case == "missing-branch":
            del run["head_branch"]
        elif case == "missing-repository":
            del run["head_repository"]
        elif case == "no-history":
            routes[endpoint] = []
        elif case == "other-history-number":
            own["number"] = 99
        elif case == "history-base-evil":
            own["base"]["ref"] = "evil"
        elif case == "history-head-moved":
            own["head"]["sha"] = history.h0
    edit_routes(history, change)
    got = history.classify()
    assert got["class"] == "none" and got["reasons"] == [reason]


def test_ci_waiver_r4_history_query_all_states_paginated(history):
    history.merge()
    audit = history.repo.parent / "gh-calls.jsonl"
    history.env["WAIVER_GH_AUDIT"] = str(audit)
    assert history.classify()["class"] == "master-merge"
    calls = [json.loads(line) for line in audit.read_text().splitlines()]
    calls = [args for args in calls if "pulls?" in args[-1]]
    assert len(calls) == 1
    assert "--paginate" in calls[0]
    assert calls[0][-1] == "repos/r/p/pulls?head=r%3Atopic&state=all&per_page=100"


def test_ci_waiver_r4_private_store_strips_inherited_git_environment(history):
    history.commit({"CHANGELOG.md": "docs\n"})
    assert history.classify(pr=True)["class"] == "docs-only"  # publish independent upstream
    history.git("config", "core.repositoryformatversion", "999")
    audit = history.repo.parent / "poison-env-audit.jsonl"
    env = {**history.env, "WAIVER_GIT_AUDIT": str(audit),
           "GIT_DIR": str(history.repo / ".git"),
           "GIT_OBJECT_DIRECTORY": str(history.repo / ".git/objects"),
           "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(history.repo / ".git/objects"),
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.repositoryformatversion",
           "GIT_CONFIG_VALUE_0": "999"}
    # Invoke the actual CLI; fixture Git commands must not consume the poison.
    r = subprocess.run([sys.executable, str(SCRIPT), "classify", "--repo-dir", str(history.repo),
                        "--pr", "1", "--repo", "r/p", "--json"],
                       env=env, check=True, capture_output=True, text=True)
    assert json.loads(r.stdout)["class"] == "docs-only"
    calls = [json.loads(line) for line in audit.read_text().splitlines()]
    assert calls
    for args, cwd, child_env in calls:
        assert cwd != str(history.repo)
        assert not {"GIT_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                    "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"} & child_env.keys()


@pytest.mark.parametrize("path", [
    ".pytest.ini", "pytest.toml", ".pytest.toml", "uv.toml",
    "docs/handoffs/.pytest.ini", "docs/handoffs/pytest.toml",
    "docs/handoffs/.pytest.toml", "docs/handoffs/uv.toml",
    "pytest.py", "pytest/__main__.py", "_pytest/config/__init__.py",
])
def test_ci_waiver_r4_test_execution_exclusions(history, path):
    history.commit({path: "configuration or shadow package\n"})
    got = history.classify()
    assert got["class"] == "none" and "hard-exclusion:" + path in got["reasons"]


def test_ci_waiver_r4_nonexcluded_hand_edit_still_denied(history):
    history.merge()
    # A name missing from an open-ended denylist is still not allowlisted.
    history.commit({"unlisted-test-control.cfg": "pass without testing\n"})
    history.git("reset", "--soft", "HEAD~1")
    history.git("commit", "--amend", "--no-edit")
    got = history.classify()
    assert got["class"] == "none"
    assert got["reasons"] == ["hand-edited:unlisted-test-control.cfg"]
