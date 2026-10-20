"""Tests for bin/ade-scan-state: a temp bigteam dir and temp git repos, nothing real is read."""
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import time
import types
from pathlib import Path

import pytest

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


def marker_script(path: Path, marker: Path) -> Path:
    path.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    path.chmod(0o755)
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
        assert res[name]["verdict"] == f"skipped: unrecognised config {key}"
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


def test_config_allowlist_keys():
    mod = load()
    for key, value in (("core.fsmonitor", "/x/hook"), ("core.fsmonitor", "True"),
                       ("core.sshCommand", "ssh -i k"), ("remote.origin.uploadpack", "x"),
                       ("remote.o.receivepack", "x"), ("filter.lfs.clean", "x"),
                       ("diff.lfs.textconv", "x"), ("credential.helper", "!x"),
                       ("core.hooksPath", "/h"), ("include.path", "../x"),
                       ("includeIf.gitdir:/a/.path", "x"), ("remote.o.vcs", "x"),
                       ("gpg.program", "x"), ("gpg.ssh.program", "x"), ("log.showSignature", "true"),
                       ("alias.co", "checkout"), ("url.x.insteadOf", "y"), ("core.worktree", "/t"),
                       ("fetch.recurseSubmodules", "yes"), ("merge.x.driver", "x"),
                       ("extensions.partialclone", "origin"), ("branch.main.mergeoptions", "x")):
        assert not mod.key_is_safe(key, value), key
    for key, value in (("core.fsmonitor", "false"), ("core.fsmonitor", "true"),
                       ("remote.origin.url", "x"), ("remote.origin.gh-resolved", "base"),
                       ("branch.feature.x.merge", "refs/heads/x"), ("user.name", "x"),
                       ("core.bare", "false"), ("Core.FileMode", "true"),
                       ("submodule.sub.url", "u"), ("submodule.active", "."),
                       ("status.showUntrackedFiles", "no"), ("lfs.http://h/x.access", "basic")):
        assert mod.key_is_safe(key, value), key
    assert mod.key_is_safe("core.worktree", "../../../sub", in_submodule=True)
    assert not mod.key_is_safe("alias.co", "checkout", in_submodule=True)


def test_repo_with_only_safe_keys_is_scanned_and_an_alias_is_skipped(tmp_path):
    mod = load()
    roots = tmp_path / "roots"
    safe = make_repo(roots / "safe")
    alias = make_repo(roots / "alias")
    for repo in (safe, alias):
        git(repo, "config", "user.name", "t")
        git(repo, "config", "core.fsmonitor", "false")
        git(repo, "config", "status.showUntrackedFiles", "normal")
        git(repo, "config", "branch.main.gh-merge-base", "main")
    git(alias, "config", "alias.co", "checkout")
    assert mod.unsafe_config(safe) == []
    assert mod.unsafe_config(alias) == ["alias.co"]
    res = {Path(c["path"]).name: c for c in mod.scan_git([roots], remote=False)}
    assert res["safe"]["verdict"] == "orphan branch" and res["safe"]["untracked"] == 0
    assert res["alias"]["verdict"] == "skipped: unrecognised config alias.co"
    assert res["alias"]["config_keys"] == ["alias.co"]


def test_config_included_from_a_file_is_caught(tmp_path):
    mod = load()
    repo = make_repo(tmp_path / "roots" / "inc")
    extra = tmp_path / "extra.cfg"
    extra.write_text("[core]\n\tsshCommand = touch /nonexistent/x\n")
    git(repo, "config", "include.path", str(extra))
    c = mod.scan_git([tmp_path / "roots"], remote=False)[0]
    assert c["verdict"] == "skipped: unrecognised config include.path"
    assert "include.path" in c["config_keys"]


def test_stash_count_runs_no_gpg_program(tmp_path):
    """R2-1a: log.showSignature + gpg.program ran during `stash list` on a signed stash commit."""
    mod = load()
    repo = make_repo(tmp_path / "roots" / "stashy")
    marker = tmp_path / "PWNED-gpg"
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    parent = git(repo, "rev-parse", "HEAD").strip()
    commit = (f"tree {tree}\nparent {parent}\nauthor t <t@example.com> 1 +0000\n"
              "committer t <t@example.com> 1 +0000\n"
              "gpgsig -----BEGIN PGP SIGNATURE-----\n \n bogus\n -----END PGP SIGNATURE-----\n\nWIP\n")
    p = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"], cwd=repo,
                       env=GIT_ENV, input=commit, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    git(repo, "update-ref", "--create-reflog", "-m", "WIP", "refs/stash", p.stdout.strip())
    git(repo, "config", "log.showSignature", "true")
    git(repo, "config", "gpg.program", str(marker_script(tmp_path / "gpg.sh", marker)))
    # the scan skips it, and the counting layer on its own runs no program either
    c = mod.scan_git([tmp_path / "roots"], remote=False)[0]
    assert c["verdict"].startswith("skipped: unrecognised config ")
    assert c["config_keys"] and not marker.exists()
    assert mod.stash_count(repo, mod.git_common_dir(repo)) == 1
    assert not marker.exists()
    # control: the plain command does run it (if this git does not, the test has no teeth here)
    subprocess.run(["git", "stash", "list"], cwd=repo, env=GIT_ENV, capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run gpg.program for `stash list`; nothing to guard")


def make_super_with_submodule(tmp_path: Path):
    sub_origin = make_repo(tmp_path / "sub-origin", "f.txt")
    roots = tmp_path / "roots"
    sup = make_repo(roots / "super")
    git(sup, "-c", "protocol.file.allow=always", "submodule", "add", str(sub_origin), "sub")
    git(sup, "commit", "-m", "add submodule")
    return roots, sup, sup / ".git" / "modules" / "sub"


def test_submodule_filter_in_module_config_is_skipped_and_never_run(tmp_path):
    """R2-1b: filter.* in .git/modules/sub/config ran during the superproject's `status`."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    marker = tmp_path / "PWNED-subfilter"
    # a clean checkout whose submodule config is only safe keys: scanned, never "clean and pushed"
    c = mod.scan_git([roots], remote=False)[0]
    assert mod.SUBMODULES_FLAG in c["flags"] and c["verdict"] != "clean and pushed"
    git(moddir, "config", "filter.x.clean", str(marker_script(tmp_path / "clean.sh", marker)))
    (sup / "sub" / ".gitattributes").write_text("f.txt filter=x\n")
    (sup / "sub" / "f.txt").write_text("a\n")  # new mtime: git must re-hash through the filter
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"] == "skipped: submodule config unrecognised filter.x.clean"
    assert not marker.exists()
    # second layer: the status call itself ignores submodules
    mod.git(sup, "status", "--porcelain", "--ignore-submodules=all", "--untracked-files=normal")
    assert not marker.exists()
    subprocess.run(["git", "status", "--porcelain"], cwd=sup, env=GIT_ENV, capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run the submodule's filter during status")


def test_fetch_does_not_recurse_into_submodules(tmp_path, monkeypatch):
    """R2-1c: fetch.recurseSubmodules=yes made --fetch run remote.origin.uploadpack of a submodule."""
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    sub_origin = make_repo(tmp_path / "sub-origin", "f.txt")
    roots = tmp_path / "roots"
    roots.mkdir()
    work, other = roots / "work", tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    git(work, "-c", "protocol.file.allow=always", "submodule", "add", str(sub_origin), "sub")
    git(work, "commit", "-m", "first")
    git(work, "push", "-u", "origin", "main")
    git(tmp_path, "clone", str(origin), str(other))
    (other / "o.txt").write_text("o\n")
    git(other, "add", "o.txt")
    git(other, "commit", "-m", "elsewhere")
    git(other, "push", "origin", "main")
    (work / "w.txt").write_text("w\n")
    git(work, "add", "w.txt")
    git(work, "commit", "-m", "local, unpushed")  # diverged: origin's tip must be fetched
    marker = tmp_path / "PWNED-J"
    git(work, "config", "fetch.recurseSubmodules", "yes")
    git(work / ".git" / "modules" / "sub", "config", "remote.origin.uploadpack",
        f"touch {marker}; git-upload-pack")
    # 1. the allowlist keeps the scan away from this checkout altogether
    c = mod.scan_git([roots], remote=True, fetch=True)[0]
    assert c["verdict"] == "skipped: unrecognised config fetch.recursesubmodules"
    assert not marker.exists()
    # 2. with both guards bypassed, the fetch itself still does not recurse
    monkeypatch.setattr(mod, "unsafe_config", lambda path: [])
    monkeypatch.setattr(mod, "submodule_config_check", lambda path, common: (True, None))
    mod._remote_cache.clear()
    c = mod.scan_git([roots], remote=True, fetch=True)[0]
    assert "origin tip not fetched" not in c["flags"] and not marker.exists()
    # control: a recursing fetch would have run it
    git(work, "update-ref", "-d", "refs/remotes/origin/main")
    subprocess.run(["git", "fetch", "origin"], cwd=work, env=GIT_ENV, capture_output=True)
    if not marker.exists():
        pytest.skip("this git does not run the submodule's uploadpack on a recursing fetch")


def test_status_ignores_untracked_config_and_worktree_redirect_is_skipped(tmp_path):
    """R2-2: status.showUntrackedFiles=no hid files; core.worktree reported another tree."""
    mod = load()
    roots = tmp_path / "roots"
    hid = make_repo(roots / "hid")
    git(hid, "config", "status.showUntrackedFiles", "no")
    (hid / "precious.txt").write_text("p\n")
    redirected = make_repo(roots / "redir")
    elsewhere = make_repo(tmp_path / "elsewhere")
    git(redirected, "config", "core.worktree", str(elsewhere))
    (redirected / "precious.txt").write_text("p\n")
    res = {Path(c["path"]).name: c for c in mod.scan_git([roots], remote=False)}
    assert res["hid"]["untracked"] == 1 and "dirty" in res["hid"]["flags"]
    assert res["redir"]["verdict"] == "skipped: worktree redirected"
    assert res["redir"]["untracked"] is None
    # the toplevel check on its own: a scanned path that is not git's work tree is skipped
    sub = hid / "nested"
    sub.mkdir()
    c = mod.scan_checkout(sub, remote=False)  # git discovers `hid` above it
    assert c["verdict"] == "skipped: worktree redirected"


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
        "GIT_TERMINAL_PROMPT", "GIT_OPTIONAL_LOCKS", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL",
        "GIT_NO_LAZY_FETCH"}
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


def make_pushed_checkout(tmp_path: Path):
    """(roots, work, origin): a checkout whose branch is pushed and whose upstream is set."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    roots = tmp_path / "roots"
    roots.mkdir()
    work = roots / "work"
    git(tmp_path, "clone", str(origin), str(work))
    git(work, "checkout", "-b", "main")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-m", "first")
    git(work, "push", "-u", "origin", "main")
    return roots, work, origin


def test_a_failed_or_timed_out_git_call_is_never_clean_and_pushed(tmp_path, monkeypatch):
    """Round 3, 1: a garbage index or a timed-out `status` read as "nothing found"."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"] == "clean and pushed"  # a healthy repo is unchanged
    assert mod.summarize({"checkouts": [c]})["checkouts"]["incomplete"] == 0
    (work / "precious-untracked.txt").write_text("keep\n")
    (work / "a.txt").write_text("changed\n")
    (work / ".git" / "index").write_bytes(b"junk" * 64)
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"].startswith("scan incomplete: status rc="), c["verdict"]
    assert c["flags"] == [c["verdict"]] and c["verdict"] != "clean and pushed"
    assert c["modified"] is None and c["untracked"] is None and c["ahead_of_origin"] is None
    assert mod.summarize({"checkouts": [c]})["checkouts"]["incomplete"] == 1
    assert mod.summarize({"checkouts": [c]})["checkouts"]["skipped"] == 0
    assert "scan incomplete" in mod.markdown({"checkouts": [c]})

    (work / ".git" / "index").unlink()  # rebuild a healthy index, then fail each call in turn
    git(work, "reset", "-q")
    git(work, "checkout", "--", "a.txt")
    (work / "precious-untracked.txt").unlink()
    assert mod.scan_git([roots], remote=False)[0]["verdict"] == "clean and pushed"
    real, seen = mod.run, {}

    def failing(word, rc):
        def fake(argv, timeout=120, cwd=None, env=None):
            if word in argv:
                seen[word] = timeout
                return rc, ""
            return real(argv, timeout=timeout, cwd=cwd, env=env)
        return fake

    for word, rc, want in (("status", 124, "scan incomplete: status rc=124"),
                           ("rev-list", 128, "scan incomplete: rev-list --count @{u}..HEAD rc=128")):
        monkeypatch.setattr(mod, "run", failing(word, rc))
        c = mod.scan_git([roots], remote=False)[0]
        assert c["verdict"] == want and c["unpushed"] is None, c["verdict"]
    assert seen["status"] == 600 and seen["rev-list"] == 60  # status has its own, longer limit
    monkeypatch.setattr(mod, "run", failing("--abbrev-ref", 128))
    assert mod.scan_git([roots], remote=False)[0]["verdict"].startswith("scan incomplete: rev-parse")


def test_a_repository_with_no_commit_yet_is_not_scan_incomplete(tmp_path):
    mod = load()
    roots = tmp_path / "roots"
    (roots / "fresh").mkdir(parents=True)
    git(roots / "fresh", "init", "-b", "main")
    (roots / "fresh" / "f.txt").write_text("x\n")
    c = mod.scan_git([roots], remote=False)[0]
    assert c["branch"] == "main" and c["verdict"] == "dirty" and c["untracked"] == 1


def commit_file(repo: Path, name: str) -> None:
    (repo / name).write_text(name + "\n")
    git(repo, "add", name)
    git(repo, "commit", "-m", name)


def scan_one(mod, roots: Path, **kw) -> dict:
    recs = mod.scan_git([roots], **{"remote": False, **kw})
    assert len(recs) == 1
    return recs[0]


def test_detached_head_with_local_commits_is_not_clean_and_pushed(tmp_path):
    """Round 4, 1a (S1)."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "--detach")
    commit_file(work, "detached.txt")
    c = scan_one(mod, roots)
    assert c["branch"] == "HEAD" and c["on_origin"] == "unknown"
    assert c["verdict"] == "unpushed commits" and "detached" in c["flags"]
    assert c["local_only_commits"] == 1
    assert {"branch": "HEAD", "count": 1} in c["local_only_branches"]
    assert any(f.startswith("local-only commits: HEAD 1") for f in c["flags"])
    assert mod.summarize({"checkouts": [c]})["checkouts"]["with_local_only_commits"] == 1


def test_remote_scan_with_an_origin_that_does_not_answer_is_not_clean_and_pushed(tmp_path, monkeypatch):
    """Round 4, 1b (S2): ls-remote fails, the branch has no upstream and a commit origin lacks."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "feature")
    commit_file(work, "f.txt")
    git(work, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] != "clean and pushed" and c["verdict"] == "orphan branch"
    assert "origin unreachable" in c["flags"]  # fell back to the local refs/remotes/origin/*
    assert c["local_only_commits"] == 1
    assert c["local_only_branches"] == [{"branch": "feature", "count": 1}]
    # no origin branch list at all (not even local refs): the verdict is still not clean
    mod = load()
    monkeypatch.setattr(mod, "origin_branches", lambda path, remote: (None, False, 0))
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "unpushed commits" and "origin unknown" in c["flags"], c["flags"]
    assert c["local_only_branches"] == [{"branch": "feature", "count": 1}]


def test_a_commit_on_another_local_branch_is_not_clean_and_pushed(tmp_path):
    """Round 4, 1c (S3): HEAD is on a pushed main, branch `side` holds 2 commits no origin ref has."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "side")
    commit_file(work, "s1.txt")
    commit_file(work, "s2.txt")
    git(work, "checkout", "main")
    c = scan_one(mod, roots)
    assert c["branch"] == "main" and c["ahead_of_origin"] == 0
    assert c["verdict"] == "unpushed commits" != "clean and pushed"
    assert c["local_only_commits"] == 2 and c["local_only_branches"] == [{"branch": "side", "count": 2}]
    assert "local-only commits: side 2" in c["flags"]
    # the same branch, once pushed, makes the checkout clean again
    git(work, "push", "origin", "side")
    c = scan_one(mod, roots)
    assert c["verdict"] == "clean and pushed", c["flags"]
    assert c["local_only_commits"] == 0 and c["local_only_branches"] == []


def test_origin_tips_from_ls_remote_are_not_local_only(tmp_path):
    """A branch pushed from here whose remote-tracking ref is gone is only local-only without --remote."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "x")
    commit_file(work, "x.txt")
    git(work, "push", "origin", "x")
    git(work, "update-ref", "-d", "refs/remotes/origin/x")
    git(work, "checkout", "main")
    assert scan_one(mod, roots)["local_only_branches"] == [{"branch": "x", "count": 1}]
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "clean and pushed" and c["local_only_commits"] == 0, c["flags"]


def test_remote_scan_trusts_live_tips_over_a_stale_tracking_ref(tmp_path):
    """Codex pass 9 (4324741577): a branch deleted on origin keeps its `refs/remotes/origin/x`; with --remote
    its commits are local-only, without it the stale ref still hides them (the documented caveat)."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "x")
    commit_file(work, "x.txt")
    git(work, "push", "origin", "x")
    git(origin, "branch", "-D", "x")
    assert git(work, "rev-parse", "--verify", "refs/remotes/origin/x").strip()  # the stale ref stays
    c = scan_one(mod, roots)  # without --remote: origin's refs are the local ones
    assert c["local_only_commits"] == 0 and c["on_origin"] is True  # the stale ref still says x is on origin
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["local_only_commits"] == 1 and c["local_only_branches"] == [{"branch": "x", "count": 1}], c
    assert c["verdict"] == "unpushed commits" != "clean and pushed" and "origin unreachable" not in c["flags"]
    assert c["on_origin"] is False


def test_worktrees_with_different_worktree_scoped_origins_are_judged_by_their_own(tmp_path):
    """Codex pass 9 (4324741588): the remote cache was keyed by the shared git dir only. Each worktree has
    only its own worktree-scoped url (git uses the FIRST url in config order, so a worktree url under a
    local one is never fetched from: scan-fix-11)."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    empty = tmp_path / "empty.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(empty))
    git(work, "config", "extensions.worktreeConfig", "true")
    git(work, "config", "--worktree", "remote.origin.url", str(origin))
    git(work, "config", "--unset-all", "remote.origin.url")  # the local file keeps no url
    wt = roots / "wt"
    git(work, "worktree", "add", "-b", "side", str(wt))
    git(wt, "config", "--worktree", "remote.origin.url", str(empty))
    assert git(wt, "config", "--get", "remote.origin.url").strip() == str(empty)  # what ls-remote is given
    assert git(work, "config", "--get", "remote.origin.url").strip() == str(origin)
    for order in (roots / "work", roots / "wt"), (roots / "wt", roots / "work"):
        mod._remote_cache.clear()
        recs = {Path(r["path"]).name: r for r in mod.scan_git(list(order), remote=True)}
        assert recs["work"]["verdict"] == "clean and pushed", recs["work"]
        assert recs["wt"]["verdict"] == "unpushed commits", recs["wt"]
        assert recs["wt"]["local_only_commits"] > 0 and "origin unreachable" not in recs["wt"]["flags"]


def push_from_another_clone(tmp_path: Path, origin: Path, *branches: str, name: str = "other") -> None:
    """Another clone of origin pushes one more commit to each branch (this checkout never fetches it)."""
    other = tmp_path / name
    git(tmp_path, "clone", str(origin), str(other))
    for b in branches:
        git(other, "checkout", b)
        commit_file(other, f"{name}-{b}.txt")
        git(other, "push", "origin", b)


def test_remote_scan_of_a_clone_that_is_behind_origin_is_not_clean_until_fetched(tmp_path):
    """Adversary round 15, 1 (L2), revised for Codex pass 11: 5 commits pushed, someone else pushes 1 more to
    origin, not fetched here. The live tip's objects are missing, so the stale tracking ref cannot be
    verified as an ancestor of it: the verdict is not clean (it was `clean and pushed` before pass 11);
    --fetch downloads the tip, proves the ancestry and the checkout is clean again."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    for i in range(4):
        commit_file(work, f"c{i}.txt")
    git(work, "push", "origin", "main")
    push_from_another_clone(tmp_path, origin, "main")
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] != "clean and pushed" and "origin tips not fetched: 1" in c["flags"], c["flags"]
    assert c["local_only_verified"] is False
    mod._remote_cache.clear()
    assert "origin tips not fetched: 1" not in scan_one(mod, roots)["flags"]  # no --remote: no live tips
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert c["verdict"] == "clean and pushed", c["flags"]
    assert c["local_only_commits"] == 0 and c["local_only_branches"] == [] and c["flags"] == []
    assert c["local_only_verified"] is True


def force_push_unrelated_main(tmp_path: Path, origin: Path) -> None:
    """Another clone replaces origin's `main` with a commit unrelated to anything here (never fetched here)."""
    other = tmp_path / "forcer"
    git(tmp_path, "clone", str(origin), str(other))
    git(other, "checkout", "--orphan", "rewritten")
    git(other, "rm", "-rf", "--quiet", ".")
    commit_file(other, "rewritten.txt")
    git(other, "push", "--force", "origin", "rewritten:main")


def test_remote_scan_does_not_trust_the_tracking_ref_of_a_force_pushed_live_branch(tmp_path):
    """Codex pass 11 (4324923677): origin force-pushed a still-live branch; the stale tracking ref equals HEAD
    but none of those commits remain on origin. Not `clean and pushed`; --fetch counts HEAD as local-only."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    commit_file(work, "b.txt")
    git(work, "push", "origin", "main")
    assert git(work, "rev-parse", "HEAD") == git(work, "rev-parse", "refs/remotes/origin/main")
    force_push_unrelated_main(tmp_path, origin)
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] != "clean and pushed", c
    assert "origin tips not fetched: 1" in c["flags"] and "unpushed commits" in c["flags"], c["flags"]
    assert c["local_only_commits"] == 2 and c["local_only_verified"] is False
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert c["verdict"] == "unpushed commits", c["flags"]
    assert c["local_only_commits"] == 2 and c["local_only_branches"] == [{"branch": "main", "count": 2}], c
    assert any(f.startswith("local-only commits: main 2") for f in c["flags"])
    assert c["local_only_verified"] is True and not any(f.startswith("origin tips not fetched") for f in c["flags"])


def test_remote_scan_of_a_clone_behind_origin_on_two_branches_still_counts_the_deleted_one(tmp_path):
    """Adversary round 15, 1 (probe20): origin is ahead on main and side; `gone` was deleted on origin."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    for b in ("side", "gone"):
        git(work, "checkout", "-b", b, "main")
        commit_file(work, f"{b}.txt")
        git(work, "push", "origin", b)
    git(work, "checkout", "main")
    git(origin, "branch", "-D", "gone")
    push_from_another_clone(tmp_path, origin, "main", "side")
    c = scan_one(mod, roots, remote=True)
    assert "origin tips not fetched: 2" in c["flags"] and c["local_only_verified"] is False, c
    assert c["verdict"] == "unpushed commits"  # unfetched tips exclude nothing: an overcount, never clean
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert c["local_only_branches"] == [{"branch": "gone", "count": 1}], c
    assert c["local_only_verified"] is True and c["verdict"] == "unpushed commits"


def test_remote_scan_asks_the_first_origin_url_like_git_fetch(tmp_path):
    """Adversary round 15, 2 (L5): two urls in one file, git fetches from the first (a: has main; b: empty)."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    empty = tmp_path / "empty.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(empty))
    git(work, "config", "--add", "remote.origin.url", str(empty))
    assert git(work, "config", "--get", "remote.origin.url").strip() == str(empty)  # the last, not queried
    assert git(work, "ls-remote", "--heads", "origin").split()[1] == "refs/heads/main"  # git fetches the first
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "clean and pushed" and c["local_only_commits"] == 0, c["flags"]


def test_remote_scan_resolves_a_bare_relative_origin_url_against_the_checkout(tmp_path):
    """Adversary round 15, 3: `sib.git` (no `./`) used to resolve against the neutral cwd: origin unreachable."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(tmp_path, "clone", "--bare", str(origin), str(work / "sib.git"))
    (work / ".git" / "info" / "exclude").write_text("sib.git/\n")
    git(work, "remote", "set-url", "origin", "sib.git")
    git(work, "commit", "--allow-empty", "-m", "local only")  # not on sib.git
    c = scan_one(mod, roots, remote=True)
    assert "origin unreachable" not in c["flags"], c["flags"]
    assert c["verdict"] == "unpushed commits" and c["local_only_commits"] == 1, c


def test_a_head_naming_no_ref_while_refs_exist_is_not_unborn(tmp_path):
    """Round 4, 2 (S4): HEAD -> refs/heads/gone, a branch holds a commit origin lacks."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "work")
    commit_file(work, "w.txt")
    git(work, "symbolic-ref", "HEAD", "refs/heads/gone")
    c = scan_one(mod, roots)
    assert c["verdict"].startswith("scan incomplete: rev-parse --abbrev-ref HEAD rc="), c["verdict"]
    assert c["verdict"] != "clean and pushed" and c["local_only_commits"] is None


def test_a_garbage_head_file_is_reported_as_unreadable_not_as_no_work_tree(tmp_path):
    """Round 4, 3a (S6)."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    (work / ".git" / "HEAD").write_text("garbage\n")
    c = scan_one(mod, roots)
    assert c["verdict"] == "skipped: HEAD unreadable" and c["local_only_commits"] is None


def test_remote_scan_of_a_partial_clone_downloads_nothing(tmp_path):
    """Round 3, 2: promisor lazy fetch ran during `rev-list --count HEAD --not --remotes=origin <tip>`."""
    mod = load()
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    git(origin, "config", "uploadpack.allowFilter", "true")
    git(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
    seed = tmp_path / "seed"
    git(tmp_path, "clone", str(origin), str(seed))
    git(seed, "checkout", "-b", "main")
    (seed / "a.txt").write_text("a\n")
    git(seed, "add", "a.txt")
    git(seed, "commit", "-m", "first")
    git(seed, "push", "-u", "origin", "main")
    roots = tmp_path / "roots"
    roots.mkdir()
    work = roots / "work"
    git(tmp_path, "clone", "--filter=blob:none", f"file://{origin}", str(work))
    (work / "w.txt").write_text("w\n")
    git(work, "add", "w.txt")
    git(work, "commit", "-m", "local, unpushed")
    (seed / "o.txt").write_text("o\n")
    git(seed, "add", "o.txt")
    git(seed, "commit", "-m", "elsewhere")
    git(seed, "push", "origin", "main")
    tip = git(seed, "rev-parse", "HEAD").strip()
    probe = {**GIT_ENV, "GIT_NO_LAZY_FETCH": "1"}  # the check itself must not download either

    def has_tip() -> bool:
        return subprocess.run(["git", "cat-file", "-e", tip], cwd=work, env=probe,
                              capture_output=True).returncode == 0

    assert not has_tip()
    c = mod.scan_git([roots], remote=True, fetch=False)[0]
    assert not has_tip(), "the scan downloaded the origin tip"
    # the tip cannot be compared, so the count stays the local one and the flag says so
    assert "origin tip not fetched" in c["flags"] and c["verdict"] == "unpushed commits"
    assert c["ahead_of_origin"] == 1


def test_a_submodule_named_like_a_git_internal_dir_is_inspected(tmp_path):
    """Round 3, 3: the walk pruned `objects`, `refs`, ... at every level, `modules/objects` included."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    # a directory below a module's git dir named `refs` is still pruned: nothing is read there
    (moddir / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    git(moddir / "refs" / "heads", "config", "--file", "config", "filter.x.clean", "evil")
    assert mod.scan_git([roots], remote=False)[0]["verdict"] != \
        "skipped: submodule config unrecognised filter.x.clean"
    named = sup / ".git" / "modules" / "objects"
    named.mkdir()
    (named / "HEAD").write_text("ref: refs/heads/main\n")
    git(named, "config", "--file", "config", "filter.y.clean", "evil")
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"] == "skipped: submodule config unrecognised filter.y.clean"


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


def load_doc() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("ade_scan_state_doc", str(SCRIPT.parent / "ade-scan-state-doc"))
    spec = importlib.util.spec_from_loader("ade_scan_state_doc", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def doc_cli(*args: Path | str) -> subprocess.CompletedProcess:
    return subprocess.run([str(SCRIPT.parent / "ade-scan-state-doc"), *map(str, args)],
                          capture_output=True, text=True)


def test_scan_doc_generator_refuses_to_clobber(tmp_path):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({"scanned_at": "x", "bigteam": {"tasks": [], "loose_files": []},
                                "checkouts": [], "summary": {
                                    "bigteam": {"tasks": 0, "verdicts": {}, "total_bytes": 0,
                                                "unique_bytes": 0, "scratch_bytes": 0},
                                    "checkouts": {"count": 0, "verdicts": {}, "with_unpushed_work": 0,
                                                  "with_untracked": 0, "with_stash": 0}}}))
    before = scan.read_text()
    assert doc_cli(scan, scan).returncode == 1  # OUT is the input
    assert doc_cli(scan, tmp_path / "." / "scan.json").returncode == 1  # same file, other spelling
    assert scan.read_text() == before
    assert doc_cli(scan, tmp_path / "out.txt").returncode == 1  # not markdown
    assert not (tmp_path / "out.txt").exists()
    existing = tmp_path / "keep.md"
    existing.write_text("keep me\n")
    assert doc_cli(scan, existing).returncode == 1  # exists, no --force
    assert existing.read_text() == "keep me\n"
    p = doc_cli(scan, existing, "--force")
    assert p.returncode == 0, p.stderr
    assert existing.read_text().startswith("# Phase 0 scan")
    assert doc_cli(scan, tmp_path / "new.md").returncode == 0
    adir = tmp_path / "adir.md"
    adir.mkdir()
    (adir / "keep.txt").write_text("keep\n")
    for extra in ((), ("--force",)):
        p = doc_cli(scan, adir, *extra)
        assert p.returncode == 1 and "refusing: OUT" in p.stderr and "is a directory" in p.stderr
        assert "Traceback" not in p.stderr
        assert (adir / "keep.txt").read_text() == "keep\n"
    assert not [f for f in tmp_path.iterdir() if f.name.endswith(".tmp")]


def test_scan_doc_generator_writes_atomically(tmp_path, monkeypatch):
    mod = load_doc()
    out = tmp_path / "out.md"
    out.write_text("old content\n")

    def boom(src, dst):
        raise OSError("simulated failure at the move")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        mod.write_atomic(out, "new content\n")
    assert out.read_text() == "old content\n"
    assert [f.name for f in tmp_path.iterdir()] == ["out.md"]  # the temp file is gone
    monkeypatch.undo()
    mod.write_atomic(out, "new content\n")
    assert out.read_text() == "new content\n"


def test_scan_doc_generator_code_spans_survive_backticks():
    mod = load_doc()
    assert mod.code("git -C {} add", "/p/a") == "`git -C /p/a add`"
    assert mod.code("{}", "we`ird") == "`` we`ird ``"
    assert mod.code("{}", "a``b`c") == "``` a``b`c ```"
    assert mod.code("<DEST>/{}/", "x|y") == "`<DEST>/x\\|y/`"
    assert mod.esc("a`b") == "a\\`b"  # outside a code span the backtick is backslash-escaped
    scan_text = {"scanned_at": "x",
                 "bigteam": {"tasks": [{"task": "t`k", "bytes": 3_000_000, "newest_mtime": 0.0,
                                        "claim": "open", "reports": [{"path": "r`eport.md", "bytes": 1,
                                                                       "done": False}],
                                        "open_job_records": [], "verdict": "unique",
                                        "unique_bytes": 1,
                                        "fills": [{"name": "c`h", "bytes": 10}]}],
                             "loose_files": []},
                 "checkouts": [{"path": "/p/c`o", "branch": "b`r", "modified": 0, "untracked": 1,
                                "untracked_sample": ["u`n.txt"], "unpushed": 1, "ahead_of_origin": 1,
                                "stashes": 0, "on_origin": False, "flags": ["orphan branch"],
                                "verdict": "orphan branch"}],
                 "summary": {"bigteam": {"tasks": 1, "verdicts": {"unique": 1}, "total_bytes": 3_000_000,
                                         "unique_bytes": 1, "scratch_bytes": 0},
                             "checkouts": {"count": 1, "verdicts": {"orphan branch": 1},
                                           "with_unpushed_work": 1, "with_untracked": 1,
                                           "with_stash": 0}}}
    text = mod.render(scan_text)
    for span in ("`` c`h ``", "`` u`n.txt ``", "`` b`r ``"):
        assert span in text, span
    # a report path is an argument of the row's copy command now: shell-quoted, inside one double-backtick span
    assert "&& \"$GCP\" --parents -t <DEST>/bigteam/'t`k' -- 'r`eport.md') ``" in text
    assert "`` git -C '/p/c`o' push -u origin refs/heads/'b`r':refs/heads/'b`r' `` or " in text  # shell-quoted since round 8


def doc_scan(checkouts, tasks=(), **summary):
    """A minimal scan JSON for the doc generator."""
    return {"scanned_at": "x",
            "bigteam": {"tasks": list(tasks), "loose_files": []},
            "checkouts": checkouts,
            "summary": {"bigteam": {"tasks": len(tasks), "verdicts": {}, "total_bytes": 0,
                                    "unique_bytes": 0, "scratch_bytes": 0},
                        "checkouts": {"count": len(checkouts), "verdicts": {}, "with_unpushed_work": 0,
                                      "with_untracked": 0, "with_stash": 0, **summary}}}


def doc_checkout(path, **kw):
    return {"path": path, "branch": "main", "modified": 0, "untracked": 0, "untracked_sample": [],
            "modified_sample": [], "unpushed": 0, "ahead_of_origin": 0, "stashes": 0,
            "on_origin": True, "flags": ["clean and pushed"], "verdict": "clean and pushed",
            "local_only_commits": 0, "local_only_branches": [], "local_only_branches_uncounted": 0,
            **kw}


def section_3_2(text: str) -> str:
    return text.split("### 3.2")[1].split("## 4.")[0]


def test_capture_plan_keeps_a_checkout_whose_only_unpushed_work_is_on_another_branch():
    """Codex PR 27, P1: main is pushed, branch `side` holds commits no origin ref has."""
    mod = load_doc()
    side = doc_checkout("/p/work", flags=["unpushed commits", "local-only commits: side 2"],
                        verdict="unpushed commits", local_only_commits=2,
                        local_only_branches=[{"branch": "side", "count": 2}])
    many = doc_checkout("/p/many", flags=["unpushed commits", "local-only commits: a 1"],
                        verdict="unpushed commits", local_only_commits=4,
                        local_only_branches=[{"branch": "a", "count": 1}],
                        local_only_branches_uncounted=3)
    clean = doc_checkout("/p/clean")
    rows = section_3_2(mod.render(doc_scan([side, many, clean]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/work "))
    assert "2 local-only commits on `side` (2)" in row
    assert "`git -C /p/work push origin refs/heads/side:refs/heads/side`" in row
    assert "commit(s) on `main`" not in row  # HEAD's own branch is pushed: no "0 commit(s)" row
    assert "and 3 more branches" in next(r for r in rows if r.startswith("| /p/many "))
    assert not [r for r in rows if r.startswith("| /p/clean ")]


def test_doc_generator_survives_skipped_and_incomplete_records():
    """Codex PR 27, P2: their counts are null; the generator used to raise TypeError."""
    mod = load_doc()
    nulls = dict(modified=None, untracked=None, unpushed=None, ahead_of_origin=None, stashes=None,
                 local_only_commits=None, on_origin=None, untracked_sample=[], modified_sample=[])
    skipped = doc_checkout("/p/skipped", flags=["skipped: worktree redirected"],
                           verdict="skipped: worktree redirected", **nulls)
    broken = doc_checkout("/p/broken", flags=["scan incomplete: status rc=124"],
                          verdict="scan incomplete: status rc=124", **nulls)
    task = {"task": "t-incomplete", "bytes": 1, "newest_mtime": 0.0, "claim": "no CLAIM",
            "reports": [{"path": "a-report.md", "bytes": 1, "done": True}], "open_job_records": [],
            "verdict": "scan incomplete: reference search rc=2", "unique_bytes": 0,
            "reference_search": "incomplete: rc=2"}
    text = mod.render(doc_scan([skipped, broken], [task], skipped=1, incomplete=1))
    assert "| /p/skipped |" in text and "| /p/broken |" in text  # listed in the section 2 table
    assert "/p/skipped" not in section_3_2(text) and "/p/broken" not in section_3_2(text)
    assert "t-incomplete" in text.split("### 1.3")[1].split("## 2.")[0]
    assert "reference search failed" in text and "never `unique`, `mixed` or `scratch`" in text


def bigteam_with_one_report(tmp_path: Path) -> tuple[Path, Path]:
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    (root / "t-1").mkdir(parents=True)
    (root / "t-1" / "a-report.md").write_text("x\n")
    refs.mkdir()
    return root, refs


def test_a_failed_reference_search_is_scan_incomplete_not_unique_or_scratch(tmp_path, monkeypatch):
    """Codex PR 27, P2: rg/grep exit 1 = no match, above 1 = error, 124 = timeout."""
    mod = load()
    root, refs = bigteam_with_one_report(tmp_path)
    real = mod.run

    def search_exits(rc):
        def fake(argv, timeout=120, cwd=None, env=None):
            if argv[0] in ("rg", "grep"):
                return rc, ""
            return real(argv, timeout=timeout, cwd=cwd, env=env)
        return fake

    for rc in (2, 124):
        monkeypatch.setattr(mod, "run", search_exits(rc))
        res = mod.scan_bigteam(root, [refs], [], 5 * 1024 * 1024, 1)
        t = res["tasks"][0]
        assert t["verdict"] == f"scan incomplete: reference search rc={rc}", t["verdict"]
        assert t["reference_search"] == f"incomplete: rc={rc}" and t["unique_bytes"] == 0
        assert mod.summarize({"bigteam": res})["bigteam"]["incomplete"] == 1
    monkeypatch.setattr(mod, "run", search_exits(1))  # no match: the plain unreferenced answer
    res = mod.scan_bigteam(root, [refs], [], 5 * 1024 * 1024, 1)
    assert res["tasks"][0]["verdict"] == "unique" and res["tasks"][0]["reference_search"] is None
    assert mod.summarize({"bigteam": res})["bigteam"]["incomplete"] == 0
    # a real `rg` that errors out, through the CLI: the scan completes (exit 0) and says it is incomplete
    monkeypatch.undo()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "rg").write_text("#!/bin/sh\nexit 2\n")
    (fake_bin / "rg").chmod(0o755)
    p = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--ref-root", str(refs), "--json"],
                       capture_output=True, text=True,
                       env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"})
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert out["bigteam"]["tasks"][0]["verdict"] == "scan incomplete: reference search rc=2"
    assert out["summary"]["bigteam"]["incomplete"] == 1


def test_capture_plan_commands_shell_quote_paths_and_branch_names():
    """Adversary round 8 on PR 27: a branch or path shaped like a shell expansion must not run when pasted."""
    mod = load_doc()
    evil = doc_checkout("/p/evil dir", flags=["unpushed commits", "local-only commits: side$(touch${IFS}PWNED) 1"],
                        verdict="unpushed commits", local_only_commits=1,
                        local_only_branches=[{"branch": "side$(touch${IFS}PWNED)", "count": 1}])
    rows = section_3_2(mod.render(doc_scan([evil]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/evil dir ") or r.startswith("| /p/evil\\ dir "))
    assert "git -C '/p/evil dir' push origin refs/heads/'side$(touch${IFS}PWNED)':refs/heads/'side$(touch${IFS}PWNED)'" in row.replace("\\$", "$").replace("\\{", "{").replace("\\}", "}").replace("\\(", "(").replace("\\)", ")")
    assert "push origin side$(touch" not in row


def test_option_shaped_branch_names_never_reach_gits_option_parser():
    # Codex pass 7 on PR 27: `git push -u origin --mirror` exits 0 and pushes every ref
    mod = load_doc()
    co = doc_checkout("/p/opt", branch="--mirror", flags=["unpushed commits"], verdict="unpushed commits",
                      ahead_of_origin=1, local_only_commits=2,
                      local_only_branches=[{"branch": "--mirror", "count": 1}, {"branch": "-f", "count": 1}])
    rows = section_3_2(mod.render(doc_scan([co]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/opt "))
    assert "push -u origin refs/heads/--mirror:refs/heads/--mirror" in row
    assert ("bundle create <DEST>/checkouts/abs/p/opt/branch---mirror.bundle refs/heads/--mirror") in row
    assert "push origin refs/heads/-f:refs/heads/-f" in row
    assert "push -u origin --mirror" not in row and "push origin -f" not in row and "bundle --mirror" not in row


def test_untracked_files_get_a_lossless_archive_command_not_a_bare_git_add():
    # Codex pass 7 on PR 27: `git add` without a pathspec stages nothing, and the row shows three of N paths
    mod = load_doc()
    co = doc_checkout("/p/u dir", flags=["untracked"], verdict="untracked", untracked=5,
                      untracked_sample=["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"])
    rows = section_3_2(mod.render(doc_scan([co]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/u dir ") or r.startswith("| /p/u\\ dir "))
    assert ("mkdir -p <DEST>/'checkouts/abs/p/u dir' && git -C '/p/u dir' ls-files -z --others --exclude-standard "
            "> <DEST>/'checkouts/abs/p/u dir/untracked.list' && \"$GTAR\" -C '/p/u dir' --null "
            "-T <DEST>/'checkouts/abs/p/u dir/untracked.list' -cf <DEST>/'checkouts/abs/p/u dir/untracked.tar'`") in row
    # Codex pass 9: no pipe, so ls-files' own status decides (`ls-files | gtar` exits 0 when ls-files fails)
    assert "|" not in row.replace("|", "", 5) and "\\|" not in row
    assert row.count("|") == 5  # leading, three inner, trailing: four cells
    assert "git -C '/p/u dir' add -A -- ." in row
    assert "add` them" not in row


def test_bigteam_rows_copy_every_report_never_a_plus_n_more():
    # Codex pass 8 on PR 27 (4324602317): the row listed four paths and "+N more"
    mod = load_doc()
    files = [f"r{i}-report.md" for i in range(5)] + ["sub dir/last report.md"]
    task = {"task": "big", "verdict": "unique", "claim": "no CLAIM", "bytes": 1, "reports": [
        {"path": f, "bytes": 1, "done": False} for f in files], "open_job_records": [], "fills": [],
        "unique_bytes": 1, "referenced_in": [], "newest_mtime": 0}
    text = mod.render(doc_scan([], tasks=[task]))
    row = next(r for r in text.split("### 3.1")[1].split("### 3.2")[0].splitlines() if r.startswith("| big "))
    assert "more" not in row
    for f in files:
        assert mod.shquote(f) in row
    assert "\"$GCP\" --parents -t <DEST>/bigteam/big -- " in row and "| 6 |" in row
    assert "GCP=$(command -v gcp || command -v cp); GTAR=$(command -v gtar || command -v tar)" in text  # Codex pass 12
    assert "(cd ~/.local/state/bigteam/big && " in row


def test_checkouts_with_one_basename_never_share_an_artifact_path():
    # Codex pass 8 on PR 27 (4324602321): `~/src/foo` and `~/.cow/pastures/x/foo` both produced <DEST>/foo-*.patch
    mod = load_doc()
    home = mod.HOME
    paths = [f"{home}/src/foo", f"{home}/.cow/pastures/x/foo", "/srv/foo", "/home/foo"]
    cos = [doc_checkout(p, flags=["unpushed commits"], verdict="unpushed commits", ahead_of_origin=1,
                        modified=1, stashes=1, untracked=1, untracked_sample=["u.txt"],
                        local_only_commits=1, local_only_branches=[{"branch": "side/x", "count": 1}])
           for p in paths]
    rows = section_3_2(mod.render(doc_scan(cos))).splitlines()
    dests = []
    for p in paths:
        row = next(r for r in rows if r.startswith(f"| {mod.esc(mod.tilde(p))} "))
        found = re.findall(r"<DEST>/(?:'([^']+)'|(\S+?))[`\s;]", row)
        arts = [a or b for a, b in found if "." in (a or b).rsplit("/", 1)[-1]]
        assert len(arts) >= 5 and all("/foo/" in "/" + a for a in arts), (row, arts)
        dests.append(set(arts))
    for i, a in enumerate(dests):
        for b in dests[i + 1:]:
            assert not a & b


def test_a_detached_head_gets_a_bundle_of_head_never_a_push_of_refs_heads_head():
    # adversary round 13 / Codex pass 8 (4324602329): `git push origin refs/heads/HEAD:refs/heads/HEAD` fails
    mod = load_doc()
    co = doc_checkout("/p/det", branch="HEAD", flags=["unpushed commits", "detached"], verdict="unpushed commits",
                      ahead_of_origin=2, local_only_commits=2,
                      local_only_branches=[{"branch": "HEAD", "count": 2}])
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /p/det "))
    assert "refs/heads/HEAD" not in row and "push" not in row
    assert "git -C /p/det bundle create <DEST>/checkouts/abs/p/det/HEAD.bundle HEAD" in row
    assert "detached HEAD: bundle, or create a branch first" in row and "git -C /p/det switch -c <name>" in row


def test_branch_bundles_of_slash_and_underscore_branches_do_not_collide():
    mod = load_doc()
    a = doc_checkout("/p/a", branch="feat/x", flags=["unpushed commits"], verdict="unpushed commits", ahead_of_origin=1)
    b = doc_checkout("/p/b", branch="feat_x", flags=["unpushed commits"], verdict="unpushed commits", ahead_of_origin=1)
    rows = section_3_2(mod.render(doc_scan([a, b]))).splitlines()
    assert "branch-feat%2Fx.bundle" in next(r for r in rows if r.startswith("| /p/a "))
    assert "branch-feat_x.bundle" in next(r for r in rows if r.startswith("| /p/b "))


def test_a_repo_without_origin_stays_an_orphan_but_a_failed_origin_lookup_is_scan_incomplete(tmp_path, monkeypatch):
    # Codex pass 8 on PR 27 (4324602334): rc 124 / 128 of `git remote get-url origin` read as "no origin"
    mod = load()
    roots = tmp_path / "roots"
    (roots / "w").mkdir(parents=True)
    git(roots / "w", "init", "-b", "main")
    commit_file(roots / "w", "a.txt")
    c = scan_one(mod, roots)
    assert c["verdict"] == "orphan branch" and "no origin remote" in c["flags"]
    real = mod.run
    for rc in (124, 128, 1):
        def fake(argv, timeout=120, cwd=None, env=None, rc=rc):
            return (rc, "") if "get-url" in argv else real(argv, timeout=timeout, cwd=cwd, env=env)
        monkeypatch.setattr(mod, "run", fake)
        c = scan_one(mod, roots)
        assert c["verdict"] == f"scan incomplete: remote get-url origin rc={rc}", c["verdict"]
        assert "no origin remote" not in c["flags"]


def test_shquote_keeps_a_leading_tilde_outside_the_quotes():
    mod = load_doc()
    assert mod.shquote("~/src/plain") == "~/src/plain"
    assert mod.shquote("~/src/a b") == "~/'src/a b'"
    assert mod.shquote("~/") == "~/"
    assert mod.shquote("/abs/a b") == "'/abs/a b'"
    assert mod.shquote("x$(y)") == "'x$(y)'"
    assert mod.shcode("git -C {} add", "~/src/a b") == "`git -C ~/'src/a b' add`"


def test_a_missing_git_root_is_a_usage_error_not_zero_checkouts(tmp_path):
    """Codex PR 27 pass 5, P1 (4324259451): `--git-root /nowhere` used to exit 0 with count 0."""
    for bad in (tmp_path / "definitely-not-a-root", tmp_path / "a-file"):
        (tmp_path / "a-file").write_text("x\n")
        p = subprocess.run([str(SCRIPT), "--git-root", str(bad), "--json"], capture_output=True, text=True)
        assert p.returncode == 2 and p.stdout == "", (p.returncode, p.stdout)
        assert f"--git-root {bad}" in p.stderr, p.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_an_unlistable_directory_under_a_git_root_is_scan_incomplete(tmp_path):
    """Codex PR 27 pass 5, P1 (4324259451): a directory scandir cannot open is not "no checkouts"."""
    roots = tmp_path / "roots"
    locked = roots / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        p = subprocess.run([str(SCRIPT), "--git-root", str(roots), "--json"], capture_output=True, text=True)
    finally:
        locked.chmod(0o755)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    assert [c["verdict"] for c in out["checkouts"]] == ["scan incomplete: scandir EACCES"], out["checkouts"]
    assert out["checkouts"][0]["path"] == str(locked.resolve()) and out["checkouts"][0]["flags"] == [
        "scan incomplete: scandir EACCES"]
    assert out["summary"]["checkouts"]["incomplete"] == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_an_unlistable_task_subtree_is_scan_incomplete_never_scratch(tmp_path):
    """Codex PR 27 pass 5, P1 (4324259461): the only report may sit in the subtree that could not be listed."""
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    sub = root / "t-locked" / "sub"
    sub.mkdir(parents=True)
    (root / "t-ok").mkdir()
    (root / "t-ok" / "a-report.md").write_text("x\n")
    refs.mkdir()
    sub.chmod(0)
    try:
        p = subprocess.run([str(SCRIPT), "--bigteam", str(root), "--ref-root", str(refs), "--json"],
                           capture_output=True, text=True)
    finally:
        sub.chmod(0o755)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)
    by = {t["task"]: t for t in out["bigteam"]["tasks"]}
    assert by["t-locked"]["verdict"] == "scan incomplete: scandir EACCES sub", by["t-locked"]["verdict"]
    assert by["t-locked"]["traversal"] == "incomplete: scandir EACCES sub"
    assert by["t-locked"]["unique_bytes"] == 0
    assert by["t-ok"]["verdict"] == "unique" and by["t-ok"]["traversal"] is None
    assert out["summary"]["bigteam"]["incomplete"] == 1


def run_main(mod, capsys, *argv: Path | str) -> tuple[int, str, str]:
    """`mod.main` in this interpreter, so the Python version under test is the one that scans."""
    try:
        rc = mod.main([str(a) for a in argv])
    except SystemExit as exc:
        rc = int(exc.code)
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_a_checkout_under_a_listable_but_unsearchable_directory_is_scan_incomplete(tmp_path, capsys):
    """Adversary round 11, 1 (MEDIUM): `Path.exists()` is False on any OSError from Python 3.13, so a
    checkout under a `r--` directory (listable, not searchable) vanished and `incomplete` stayed 0."""
    mod = load()
    roots = tmp_path / "roots"
    locked = roots / "locked"
    make_repo(locked / "repo")
    locked.chmod(0o444)
    try:
        rc, out, err = run_main(mod, capsys, "--git-root", roots, "--json")
    finally:
        locked.chmod(0o755)
    assert rc == 0, err
    res = json.loads(out)
    assert [c["verdict"] for c in res["checkouts"]] == ["scan incomplete: scandir EACCES"], res["checkouts"]
    assert res["checkouts"][0]["path"] == str(locked.resolve())
    assert res["summary"]["checkouts"]["incomplete"] == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_a_git_root_that_cannot_be_searched_is_scan_incomplete_not_a_crash(tmp_path, capsys):
    """Adversary round 11, 2A: a mode 000 --git-root made Python 3.12 exit 1 with a traceback."""
    mod = load()
    roots = tmp_path / "roots"
    make_repo(roots / "repo")
    roots.chmod(0)
    try:
        rc, out, err = run_main(mod, capsys, "--git-root", roots, "--json")
    finally:
        roots.chmod(0o755)
    assert rc == 0, err
    res = json.loads(out)
    assert [c["verdict"] for c in res["checkouts"]] == ["scan incomplete: scandir EACCES"], res["checkouts"]
    assert res["summary"]["checkouts"]["incomplete"] == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_an_unlistable_bigteam_root_is_a_usage_error(tmp_path, capsys):
    """Adversary round 11, 2C: `scan_bigteam` used to raise out of `os.scandir(root)` (exit 1, traceback)."""
    mod = load()
    root = tmp_path / "bigteam"
    (root / "t-1").mkdir(parents=True)
    root.chmod(0)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--json")
    finally:
        root.chmod(0o755)
    assert rc == 2 and out == "", (rc, out)
    assert f"--bigteam {root}" in err and "cannot be listed" in err, err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_a_task_dir_that_cannot_be_searched_is_scan_incomplete_not_a_crash(tmp_path, capsys):
    """Adversary round 11, 2D: the `jobs` and `CLAIM` probes of a `r--` task dir raised on Python 3.12 and
    read as "absent" on 3.13+; both now give the traversal-incomplete verdict."""
    mod = load()
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    task = root / "t-locked"
    (task / "jobs").mkdir(parents=True)
    claim_only = root / "t-claim-only"  # no jobs/ subdirectory for the walk to trip on: only the CLAIM probe
    claim_only.mkdir()
    (claim_only / "CLAIM").write_text("session: x\n")
    (root / "t-ok").mkdir()
    refs.mkdir()
    task.chmod(0o444)
    claim_only.chmod(0o444)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--json")
    finally:
        task.chmod(0o755)
        claim_only.chmod(0o755)
    assert rc == 0, err
    by = {t["task"]: t for t in json.loads(out)["bigteam"]["tasks"]}
    for name in ("t-locked", "t-claim-only"):
        assert by[name]["verdict"].startswith("scan incomplete: scandir EACCES "), by[name]["verdict"]
        assert by[name]["unique_bytes"] == 0
    assert by["t-ok"]["verdict"] == "scratch"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_a_verdict_naming_a_hostile_directory_is_escaped_in_every_doc_table(tmp_path, capsys):
    """Adversary round 11, 3: the verdict now carries a directory name from the disk."""
    mod = load()
    nasty = "s|<i>x"
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    sub = root / "t|<b>" / nasty
    sub.mkdir(parents=True)
    refs.mkdir()
    make_repo(tmp_path / "roots" / "r")
    sub.chmod(0)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--git-root",
                                tmp_path / "roots", "--json")
    finally:
        sub.chmod(0o755)
    assert rc == 0, err
    (tmp_path / "scan.json").write_text(out)
    doc = tmp_path / "doc.md"
    gen = subprocess.run([str(SCRIPT.parent / "ade-scan-state-doc"), str(tmp_path / "scan.json"), str(doc)],
                         capture_output=True, text=True)
    assert gen.returncode == 0, gen.stderr
    text = doc.read_text()
    assert "<i>" not in text and "<b>" not in text
    rows = [ln for ln in text.splitlines() if "scandir EACCES" in ln and ln.startswith("| ")]
    # the 1.1 top-children table and the 1.3 every-task table; 1.2 lists only unique/mixed dirs
    assert len(rows) == 2, rows
    for ln in rows:
        assert "s\\|&lt;i&gt;x" in ln, ln
    cells = sorted(ln.replace("\\|", "").count("|") for ln in rows)
    assert cells == [6, 8], cells  # 5 and 7 columns: no extra cell from the name's `|`


def _task_with_a_locked_big_subdir(tmp_path):
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    task = root / "t-big"
    (task / "sub").mkdir(parents=True)
    (task / "a-report.md").write_text("x\n")
    (task / "sub" / "blob").write_bytes(b"\0" * (2 * 1024 * 1024))
    refs.mkdir()
    return root, refs, task / "sub"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_a_failed_du_is_scan_incomplete_even_when_its_partial_total_is_small(tmp_path, capsys, monkeypatch):
    """Codex PR 27 pass 6, P1 (4324328054): `du` exits nonzero on an unreadable subtree but still prints a
    partial total; that total sat under --unique-max-bytes, so a `mixed` task read `unique`. `walk` is masked
    so that `du` is the only thing that notices the locked directory."""
    mod = load()
    root, refs, sub = _task_with_a_locked_big_subdir(tmp_path)
    real_walk = mod.walk
    monkeypatch.setattr(mod, "walk", lambda p, d, skip_checkouts=True, failures=None: real_walk(p, d, skip_checkouts, None))
    sub.chmod(0)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--unique-max-bytes", 1024 * 1024,
                                "--json")
    finally:
        sub.chmod(0o755)
    assert rc == 0, err
    res = json.loads(out)
    t = res["bigteam"]["tasks"][0]
    assert t["bytes"] < 1024 * 1024, t["bytes"]  # the partial total that used to decide `unique`
    assert t["verdict"].startswith("scan incomplete: du rc=") and t["verdict"] != "scan incomplete: du rc=0", t["verdict"]
    assert t["traversal"] == "incomplete: " + t["verdict"][len("scan incomplete: "):]
    assert t["unique_bytes"] == 0
    assert res["summary"]["bigteam"]["incomplete"] == 1


def test_only_a_zero_du_exit_is_a_complete_size(tmp_path, monkeypatch):
    mod = load()
    monkeypatch.setattr(mod, "run", lambda argv, timeout=120, cwd=None, env=None: (0, "12\t/x\n"))
    assert mod.du_bytes(tmp_path) == (12 * 1024, None)
    monkeypatch.setattr(mod, "run", lambda argv, timeout=120, cwd=None, env=None: (1, "12\t/x\n"))
    assert mod.du_bytes(tmp_path) == (12 * 1024, 1)
    monkeypatch.setattr(mod, "run", lambda argv, timeout=120, cwd=None, env=None: (124, ""))
    assert mod.du_bytes(tmp_path) == (0, 124)


def test_a_missing_ref_root_is_a_usage_error_not_a_narrower_search(tmp_path, capsys):
    """Codex PR 27 pass 6, P2 (4324328066): a missing --ref-root was dropped, so a task cited only there read `unique`."""
    mod = load()
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    (root / "t-1").mkdir(parents=True)
    refs.mkdir()
    gone = tmp_path / "nowhere"
    (tmp_path / "a-file").write_text("x\n")
    for bad in (gone, tmp_path / "a-file"):
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--ref-root", bad, "--json")
        assert rc == 2 and out == "", (rc, out)
        assert f"--ref-root {bad} is not a directory" in err, err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_an_unsearchable_ref_root_is_a_usage_error(tmp_path, capsys):
    mod = load()
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    (root / "t-1").mkdir(parents=True)
    refs.mkdir()
    refs.chmod(0o444)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--json")
    finally:
        refs.chmod(0o755)
    assert rc == 2 and out == "", (rc, out)
    assert f"--ref-root {refs} cannot be searched" in err, err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode 000 directory")
def test_an_unsearchable_checkout_inside_a_task_tree_is_scan_incomplete(tmp_path, capsys):
    """Codex PR 27 pass 6, P2 (4324328066): `os.path.exists(<dir>/.git)` in `walk` read EACCES as "no checkout"
    on Python 3.13+ and descended; it is a traversal failure naming the directory whose `.git` could not be inspected."""
    mod = load()
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    locked = root / "t-1" / "sub"
    (locked / "child").mkdir(parents=True)
    refs.mkdir()
    locked.chmod(0o444)
    try:
        rc, out, err = run_main(mod, capsys, "--bigteam", root, "--ref-root", refs, "--json")
    finally:
        locked.chmod(0o755)
    assert rc == 0, err
    t = json.loads(out)["bigteam"]["tasks"][0]
    assert t["verdict"] == "scan incomplete: scandir EACCES sub", t["verdict"]


def test_tilde_abbreviates_only_home_itself_or_a_path_below_it(monkeypatch):
    mod = load_doc()
    monkeypatch.setattr(mod, "HOME", "/root")
    assert mod.tilde("/root") == "~"
    assert mod.tilde("/root/repo") == "~/repo"
    assert mod.tilde("/tmp/root/repo") == "/tmp/root/repo"
    assert mod.tilde("/rootfs/x") == "/rootfs/x"
    assert mod.shquote(mod.tilde("/root")) == "~"
    assert mod.shcode("git -C {} status", mod.tilde("/root")) == "`git -C ~ status`"
    assert mod.shquote("~") == "~"


GOOD_BRANCH_NAMES = ["main", "feature/x", "a-b_c.d", "v1.2.3", "x@y", "@x", "a@", "HEAD", "-dash", "\u00e9t\u00e9",
                     "a/b/c", "lock", "a.lock.b", "x{y}", "a'b"]
BAD_BRANCH_NAMES = ["", "x:refs/heads/side", "x:y", "a b", "a\tb", "a\x01b", "a\x7fb", "a..b", "a@{b", "a?b", "a*b",
                    "a[b", "a\\b", "a^b", "a~b", "/a", "a/", "a//b", ".a", "a/.b", "a.", "a/b.", "x.lock", "a/x.lock/b",
                    "a/.", "..", "a\nb"]


@pytest.mark.parametrize("name", GOOD_BRANCH_NAMES + BAD_BRANCH_NAMES)
def test_valid_branch_name_agrees_with_git_check_ref_format(name):
    """Round 17, 1: the Python rule is git's, for names origin advertises (`@` alone is also refused here,
    as `git branch` does, though check-ref-format accepts `refs/heads/@`)."""
    mod = load()
    p = subprocess.run(["git", "check-ref-format", f"refs/heads/{name}"], env=GIT_ENV, capture_output=True)
    assert mod.valid_branch_name(name) is (p.returncode == 0), name
    assert (name in GOOD_BRANCH_NAMES) is (p.returncode == 0), name


def test_an_at_sign_alone_is_not_a_branch_name():
    assert load().valid_branch_name("@") is False


def test_a_hostile_origin_cannot_make_fetch_write_local_refs(tmp_path):
    """Adversary round 17, 1 (probe23): origin advertises `refs/heads/x:refs/heads/side` (a loose ref file) and
    `refs/heads/x:refs/remotes/origin/keep` (a packed-refs line), both at a commit this checkout lacks. A
    refspec built from those names would fast-forward `side` and create the tracking ref `keep`; the names
    are dropped and flagged instead, and every local ref is byte-identical after `--remote --fetch`."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "branch", "side")
    git(work, "branch", "keep")
    attacker = tmp_path / "attacker"
    git(tmp_path, "clone", str(origin), str(attacker))
    commit_file(attacker, "evil.txt")
    git(attacker, "push", "origin", "main:refs/heads/x")
    evil = git(attacker, "rev-parse", "HEAD").strip()
    loose = origin / "refs" / "heads" / "x:refs" / "heads"
    loose.mkdir(parents=True)
    (loose / "side").write_text(evil + "\n")
    packed = origin / "packed-refs"
    if not packed.exists():
        packed.write_text("# pack-refs with: peeled fully-peeled sorted\n")
    with packed.open("a") as fh:
        fh.write(f"{evil} refs/heads/x:refs/remotes/origin/keep\n")
    advertised = git(tmp_path, "ls-remote", "--heads", str(origin))
    if "refs/heads/x:refs/heads/side" not in advertised or "refs/heads/x:refs/remotes/origin/keep" not in advertised:
        pytest.skip("this git does not advertise ref names it would refuse to create")
    refs_before = git(work, "for-each-ref", "--format=%(refname) %(objectname)")
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert git(work, "for-each-ref", "--format=%(refname) %(objectname)") == refs_before
    assert not (work / ".git" / "FETCH_HEAD").exists()
    assert "origin advertised invalid ref names: 2" in c["flags"] and c["invalid_origin_refs"] == 2, c
    assert c["verdict"] != "clean and pushed"
    # a plain scan never asked origin: no invalid names counted, nothing verified
    mod._remote_cache.clear()
    c = scan_one(mod, roots)
    assert c["invalid_origin_refs"] == 0 and not any(f.startswith("origin advertised") for f in c["flags"])


def test_ls_remote_drops_malformed_oids_and_names(monkeypatch):
    """Round 17, 1: a null or short oid, an uppercase one, a line with no tab and a name with a `:` are all
    dropped and counted; sha-256 object ids (64 hex digits) pass."""
    mod = load()
    good, sha256, zero = "a" * 40, "b" * 64, "0" * 40
    out = "\n".join([f"{good}\trefs/heads/main", f"{sha256}\trefs/heads/long", f"{zero}\trefs/heads/null",
                     f"{'A' * 40}\trefs/heads/upper", f"{'c' * 39}\trefs/heads/short",
                     f"{good}\trefs/heads/x:refs/heads/side", f"{good} refs/heads/notab", "refs/heads/bare"]) + "\n"
    monkeypatch.setattr(mod, "run", lambda argv, **kw: (0, out))
    heads, invalid = mod.ls_remote_heads("/nowhere")
    assert heads == {"main": good, "long": sha256} and invalid == 6


def test_local_only_verified_needs_a_live_origin_answer(tmp_path):
    """Round 17, 2: null for a scan that asked origin nothing (plain, origin down, no origin), true or false
    only after `--remote` got an answer."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    assert scan_one(mod, roots)["local_only_verified"] is None
    mod._remote_cache.clear()
    assert scan_one(mod, roots, remote=True)["local_only_verified"] is True
    push_from_another_clone(tmp_path, origin, "main")
    mod._remote_cache.clear()
    assert scan_one(mod, roots, remote=True)["local_only_verified"] is False
    mod._remote_cache.clear()
    git(work, "config", "remote.origin.url", str(tmp_path / "gone.git"))
    c = scan_one(mod, roots, remote=True)
    assert "origin unreachable" in c["flags"] and c["local_only_verified"] is None
    git(work, "remote", "remove", "origin")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert "no origin remote" in c["flags"] and c["local_only_verified"] is None
