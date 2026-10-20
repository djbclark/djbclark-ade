"""Tests for bin/ade-scan-state: a temp bigteam dir and temp git repos, nothing real is read."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import time
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


def make_repo(path: Path, name: str = "a.txt") -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    (path / name).write_text("a\n")
    git(path, "add", name)
    git(path, "commit", "-m", "first")
    return path


def test_config_that_runs_commands_is_skipped_and_never_run(tmp_path):
    mod = load()
    roots = tmp_path / "roots"
    fsm = make_repo(roots / "fsm")
    upl = make_repo(roots / "upl")
    ok = make_repo(roots / "ok")
    m_fsm, m_upl = tmp_path / "PWNED-fsmonitor", tmp_path / "PWNED-uploadpack"
    git(fsm, "config", "core.fsmonitor", f"touch {m_fsm}; false")
    git(upl, "remote", "add", "origin", str(ok))
    git(upl, "config", "remote.origin.uploadpack", f"touch {m_upl}; git-upload-pack")
    res = {Path(c["path"]).name: c for c in mod.scan_git([roots], remote=True)}
    assert not m_fsm.exists() and not m_upl.exists()
    for name, key in (("fsm", "core.fsmonitor"), ("upl", "remote.origin.uploadpack")):
        assert res[name]["verdict"] == "skipped: repo config runs commands"
        assert res[name]["config_keys"] == [key]
        assert res[name]["untracked"] is None
    assert res["ok"]["verdict"] != res["fsm"]["verdict"]
    # second layer: even a call that bypasses the config check does not run fsmonitor
    (fsm / "new.txt").write_text("x\n")
    mod.git(fsm, "status", "--porcelain")
    assert not m_fsm.exists()
    summary = mod.summarize({"checkouts": list(res.values())})
    assert summary["checkouts"]["skipped"] == 2
    assert "| - |" in mod.markdown({"checkouts": [res["fsm"]]})


def test_runs_commands_keys(tmp_path):
    mod = load()
    for key, value in (("core.fsmonitor", "/x/hook"), ("core.sshCommand", "ssh -i k"),
                       ("remote.origin.uploadpack", "x"), ("remote.o.receivepack", "x"),
                       ("filter.lfs.clean", "x"), ("credential.helper", "!x"),
                       ("core.hooksPath", "/h"), ("include.path", "../x"),
                       ("includeIf.gitdir:/a/.path", "x"), ("remote.o.vcs", "x")):
        assert mod.runs_commands(key, value), key
    for key, value in (("core.fsmonitor", "false"), ("core.fsmonitor", "true"),
                       ("remote.origin.url", "x"), ("user.name", "x"), ("core.bare", "false")):
        assert not mod.runs_commands(key, value), key
    repo = make_repo(tmp_path / "r")
    git(repo, "config", "core.fsmonitor", "false")
    git(repo, "config", "filter.x.clean", "cat")
    assert mod.unsafe_config(repo) == ["filter.x.clean"]
    git(repo, "config", "--unset", "filter.x.clean")
    assert mod.unsafe_config(repo) == []


def test_config_included_from_a_file_is_caught(tmp_path):
    mod = load()
    repo = make_repo(tmp_path / "roots" / "inc")
    extra = tmp_path / "extra.cfg"
    extra.write_text("[core]\n\tsshCommand = touch /nonexistent/x\n")
    git(repo, "config", "include.path", str(extra))
    c = mod.scan_git([tmp_path / "roots"], remote=False)[0]
    assert c["verdict"] == "skipped: repo config runs commands"
    assert "include.path" in c["config_keys"]


def test_symlinks_out_of_a_root_are_not_followed(tmp_path):
    mod = load()
    outside = make_repo(tmp_path / "elsewhere" / "repo")
    roots = tmp_path / "roots"
    roots.mkdir()
    (roots / "link").symlink_to(outside.parent)
    make_repo(roots / "real")
    (roots / "gitlink").mkdir()
    (roots / "gitlink" / ".git").symlink_to(outside / ".git")
    found = [p.name for p in mod.find_checkouts(roots)]
    assert found == ["real"]


def test_ambient_git_variables_are_ignored(tmp_path, monkeypatch):
    mod = load()
    decoy = make_repo(tmp_path / "decoy")
    roots = tmp_path / "roots"
    work = make_repo(roots / "work")
    (work / "untracked.txt").write_text("u\n")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.fsmonitor=touch /nonexistent/x'")
    env = mod.git_env()
    assert {k for k in env if k.startswith("GIT_")} == {
        "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL"}
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    c = mod.scan_git([roots], remote=False)[0]
    assert c["untracked"] == 1 and "dirty" in c["flags"]


def test_network_env_is_batch_only(monkeypatch):
    mod = load()
    monkeypatch.setenv("SSH_ASKPASS", "/bin/x")
    monkeypatch.setenv("GIT_ASKPASS", "/bin/x")
    env = mod.git_env(network=True)
    assert env["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
    assert "SSH_ASKPASS" not in env and "GIT_ASKPASS" not in env


def test_run_closes_stdin_and_kills_the_process_group_on_timeout(tmp_path):
    mod = load()
    assert mod.run(["cat"], timeout=10) == (0, "")  # stdin is /dev/null, not the caller's
    pidfile = tmp_path / "child.pid"
    rc, _ = mod.run(["sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"], timeout=1)
    assert rc == 124
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError("the grandchild survived the timeout")


def test_fetch_downloads_the_tip_and_writes_no_refs(tmp_path):
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    roots = tmp_path / "roots"
    roots.mkdir()
    work, other = roots / "work", tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "first")
    git(work, "push", "-u", "origin", "main")
    git(tmp_path, "clone", str(origin), str(other))
    (other / "o.txt").write_text("o\n")
    git(other, "add", "o.txt")
    git(other, "commit", "-m", "elsewhere")
    git(other, "push", "origin", "main")
    tip = git(other, "rev-parse", "HEAD").strip()
    (work / "w.txt").write_text("w\n")
    git(work, "add", "w.txt")
    git(work, "commit", "-m", "local, unpushed")  # diverged: origin's tip is not an ancestor
    refs_before = git(work, "for-each-ref")
    c = mod.scan_git([roots], remote=True, fetch=False)[0]
    assert "origin tip not fetched" in c["flags"]
    mod._remote_cache.clear()
    c = mod.scan_git([roots], remote=True, fetch=True)[0]
    assert "origin tip not fetched" not in c["flags"]
    assert c["ahead_of_origin"] == 1
    git(work, "cat-file", "-e", tip)  # the objects arrived
    assert git(work, "for-each-ref") == refs_before  # no ref moved
    assert not (work / ".git" / "FETCH_HEAD").exists()


def test_phase0_scan_doc_never_makes_a_unique_report_scratch(tmp_path):
    doc = SCRIPT.parent.parent / "docs" / "ade-everywhere-phase0-scan-2026-10-20.md"
    names = []
    for line in doc.read_text().splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) > 3 and cells[2] == "unique" and cells[1] not in names:
            names.append(cells[1])
    assert len(names) >= 6
    refs = tmp_path / "docs"
    refs.mkdir()
    (refs / doc.name).write_text(doc.read_text())
    root = tmp_path / "bigteam"
    for n in names[:6]:
        (root / n).mkdir(parents=True)
        (root / n / "r-report.md").write_text("x\n")
    p = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--ref-root", str(refs), "--json"],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["summary"]["bigteam"]["verdicts"] == {"unique": 6}
    # --exclude adds to the built-in glob; it does not replace it
    p = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--ref-root", str(refs),
                        "--exclude", "other-*.md", "--json"], capture_output=True, text=True)
    assert json.loads(p.stdout)["summary"]["bigteam"]["verdicts"] == {"unique": 6}


def test_markdown_cells_are_escaped(tmp_path):
    mod = load()
    nasty = "a|b`c<img src=x>&d"
    res = {"checkouts": [{"path": f"/p/{nasty}", "branch": nasty, "modified": 0, "untracked": 0,
                          "unpushed": 0, "stashes": 0, "on_origin": True, "flags": ["dirty", nasty],
                          "verdict": "dirty"}],
           "bigteam": {"tasks": [{"task": nasty, "bytes": 1, "newest_mtime": 0.0, "claim": "open",
                                  "reports": [{"path": f"{nasty}-report.md", "bytes": 1,
                                               "done": False}],
                                  "open_job_records": [], "verdict": "unique"}]}}
    out = mod.markdown(res)
    for line in out.splitlines():
        if line.startswith("| /p/") or line.startswith("| a"):
            assert "<img" not in line and "&lt;img src=x&gt;&amp;d" in line
            assert line.replace("\\|", "").count("|") == (9 if line.startswith("| /p/") else 8)
            assert "\\`" in line and "`c" not in line.replace("\\`", "")


def test_scan_doc_generator_renders_a_scan_json(tmp_path):
    root = tmp_path / "bigteam"
    (root / "t|1").mkdir(parents=True)
    (root / "t|1" / "r-report.md").write_text("x\n")
    make_repo(tmp_path / "roots" / "r")
    scan = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--git-root", str(tmp_path / "roots"),
                           "--json"], capture_output=True, text=True)
    assert scan.returncode == 0, scan.stderr
    (tmp_path / "scan.json").write_text(scan.stdout)
    out = tmp_path / "doc.md"
    gen = subprocess.run([str(SCRIPT.parent / "ade-scan-state-doc"), str(tmp_path / "scan.json"),
                          str(out)], capture_output=True, text=True)
    assert gen.returncode == 0, gen.stderr
    text = out.read_text()
    assert text.startswith("# Phase 0 scan") and "| t\\|1 |" in text
    assert subprocess.run([str(SCRIPT.parent / "ade-scan-state-doc")], capture_output=True).returncode == 1
