"""Tests for bin/ade-scan-state: a temp bigteam dir and temp git repos, nothing real is read."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-scan-state"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def load() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("ade_scan_state", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_scan_state", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout


def make_bigteam(root: Path) -> None:
    done = root / "done-task"
    (done / "jobs").mkdir(parents=True)
    (done / "CLAIM").write_text("session: x\nstart: y\nDONE Tue Oct 20 2026 abc123\n")
    (done / "x-report.md").write_text("# a unique finding\n")
    (done / "x-report.md.done").write_text("")
    (done / "jobs" / "open.json").write_text(json.dumps({"label": "a"}))
    (done / "jobs" / "shut.json").write_text(json.dumps({"label": "b", "closed": 1}))
    (done / "x.jsonl").write_text("{}\n" * 10)
    scratch = root / "scratch-task"
    scratch.mkdir()
    (scratch / "build.log").write_text("log\n" * 100)
    open_claim = root / "open-task"
    open_claim.mkdir()
    (open_claim / "CLAIM").write_text("session: z\nstart: y\n")
    cited = root / "cited-task"
    cited.mkdir()
    (cited / "report.md").write_text("# kept elsewhere\n")
    big = root / "big-task"
    big.mkdir()
    (big / "q-report.md").write_text("# mixed\n")
    (big / "cache.bin").write_bytes(b"\0" * 200_000)
    (root / "loose.txt").write_text("not a task\n")


def test_bigteam_verdicts_claims_and_open_jobs(tmp_path):
    mod = load()
    root = tmp_path / "bigteam"
    root.mkdir()
    make_bigteam(root)
    refs = tmp_path / "docs"
    refs.mkdir()
    (refs / "notes.md").write_text("the report of cited-task lives here\n")
    res = mod.scan_bigteam(root, [refs], [], unique_max=100_000, top=2)
    by = {t["task"]: t for t in res["tasks"]}
    assert by["done-task"]["verdict"] == "unique"
    assert by["done-task"]["claim"] == "DONE"
    assert by["done-task"]["open_job_records"] == ["open.json"]
    assert by["done-task"]["reports"] == [
        {"path": "x-report.md", "bytes": 19, "done": True}]
    assert by["done-task"]["unique_bytes"] == 19
    assert by["scratch-task"]["verdict"] == "scratch"
    assert by["scratch-task"]["claim"] == "no CLAIM"
    assert by["open-task"]["claim"] == "open"
    assert by["cited-task"]["verdict"] == "scratch"
    assert by["cited-task"]["referenced_in"]
    assert by["big-task"]["verdict"] == "mixed"
    assert res["loose_files"] == ["loose.txt"]
    biggest = max(res["tasks"], key=lambda t: t["bytes"])
    assert biggest["task"] == "big-task"
    assert biggest["fills"][0]["name"] == "cache.bin"


def test_exclude_glob_drops_the_scan_doc_self_reference(tmp_path):
    mod = load()
    root = tmp_path / "bigteam"
    (root / "t").mkdir(parents=True)
    (root / "t" / "r-report.md").write_text("x\n")
    refs = tmp_path / "docs"
    refs.mkdir()
    (refs / "ade-everywhere-phase0-scan-1.md").write_text("t\n")
    res = mod.scan_bigteam(root, [refs], ["ade-everywhere-phase0-scan-*.md"], 10_000, 1)
    assert res["tasks"][0]["verdict"] == "unique"


def test_checkout_with_unpushed_commit_and_untracked_file(tmp_path):
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    work = tmp_path / "pastures" / "grp" / "work"
    work.parent.mkdir(parents=True)
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "first")
    git(work, "push", "-u", "origin", "main")
    (work / "b.txt").write_text("b\n")
    git(work, "add", "b.txt")
    git(work, "commit", "-m", "second, unpushed")
    (work / "untracked.txt").write_text("u\n")
    (work / "a.txt").write_text("changed\n")
    before = git(work, "status", "--porcelain")
    res = mod.scan_git([tmp_path / "pastures"], remote=True)
    assert len(res) == 1
    c = res[0]
    assert c["branch"] == "main"
    assert c["unpushed"] == 1
    assert c["untracked"] == 1 and c["untracked_sample"] == ["untracked.txt"]
    assert c["modified"] == 1
    assert c["on_origin"] is True
    assert c["verdict"] == "unpushed commits" and "dirty" in c["flags"]
    assert git(work, "status", "--porcelain") == before  # read-only


def test_orphan_branch_clean_checkout_and_no_upstream(tmp_path):
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(origin), str(seed))
    git(seed, "checkout", "-b", "main")
    (seed / "a.txt").write_text("a\n")
    git(seed, "add", "a.txt")
    git(seed, "commit", "-m", "first")
    git(seed, "push", "-u", "origin", "main")
    roots = tmp_path / "roots"
    roots.mkdir()
    clean = roots / "clean"
    git(tmp_path, "clone", str(origin), str(clean))
    orphan = roots / "orphan"
    git(tmp_path, "clone", str(origin), str(orphan))
    git(orphan, "checkout", "-b", "feature-x")
    (orphan / "f.txt").write_text("f\n")
    git(orphan, "add", "f.txt")
    git(orphan, "commit", "-m", "only here")
    res = {Path(c["path"]).name: c for c in mod.scan_git([roots], remote=False)}
    assert res["clean"]["verdict"] == "clean and pushed"
    assert res["clean"]["unpushed"] == 0
    assert res["orphan"]["verdict"] == "orphan branch"
    assert res["orphan"]["unpushed"] == "no upstream"
    assert res["orphan"]["on_origin"] is False
    assert res["orphan"]["ahead_of_origin"] == 1


def test_cli_json_exit_code_and_usage_error(tmp_path):
    root = tmp_path / "bigteam"
    (root / "t").mkdir(parents=True)
    (root / "t" / "r-report.md").write_text("x\n")
    p = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--json"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["summary"]["bigteam"]["verdicts"] == {"unique": 1}
    assert out["summary"]["bigteam"]["unique_bytes"] == 2
    bad = subprocess.run([str(SCRIPT)], capture_output=True, text=True)
    assert bad.returncode == 2


def test_repo_without_origin_is_an_orphan_branch(tmp_path):
    mod = load()
    roots = tmp_path / "roots"
    repo = roots / "local-only"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "master")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", "only copy")
    c = mod.scan_git([roots], remote=True)[0]
    assert c["has_origin"] is False and c["on_origin"] is False
    assert c["ahead_of_origin"] == 1
    assert c["verdict"] == "orphan branch" and "no origin remote" in c["flags"]


def test_stale_remote_refs_do_not_make_a_pushed_branch_an_orphan(tmp_path):
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    roots = tmp_path / "roots"
    work = roots / "work"
    roots.mkdir()
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "pushed behind the local refs' back")
    git(work, "push", "origin", "main")
    git(work, "update-ref", "-d", "refs/remotes/origin/main")  # as if never fetched
    c = mod.scan_git([roots], remote=True)[0]
    assert c["on_origin"] is True and c["ahead_of_origin"] == 0
    assert c["verdict"] == "clean and pushed"


def test_branch_on_origin_without_upstream_but_ahead_is_unpushed(tmp_path):
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    roots = tmp_path / "roots"
    work = roots / "work"
    roots.mkdir()
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "pushed")
    git(work, "push", "origin", "main")
    (work / "b.txt").write_text("b\n")
    git(work, "add", "b.txt")
    git(work, "commit", "-m", "local only")
    git(work, "update-ref", "-d", "refs/remotes/origin/main")
    c = mod.scan_git([roots], remote=True)[0]
    assert c["on_origin"] is True and c["unpushed"] == "no upstream"
    assert c["ahead_of_origin"] == 1 and c["verdict"] == "unpushed commits"
