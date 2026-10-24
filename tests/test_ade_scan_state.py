"""Tests for bin/ade-scan-state: a temp bigteam dir and temp git repos, nothing real is read."""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import threading
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


def git_version() -> tuple[int, ...]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout
    return tuple(int(x) for x in re.findall(r"\d+", out)[:3])


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


def test_a_leftover_origin_ref_without_an_origin_remote_hides_nothing(tmp_path):
    """Codex pass 18 on PR 27, P1: origin removed from the config but `refs/remotes/origin/main` left behind at
    HEAD; the count excluded it and the only commit read as `clean and pushed`."""
    mod = load()
    roots = tmp_path / "roots"
    repo = make_repo(roots / "leftover")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    for remote in (False, True):
        c = mod.scan_git([roots], remote=remote)[0]
        assert c["has_origin"] is False and "no origin remote" in c["flags"]
        assert c["ahead_of_origin"] == 1 and c["local_only_commits"] == 1
        assert c["verdict"] == "orphan branch"


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


def test_a_repository_nested_inside_a_checkout_is_scanned_too(tmp_path):
    """Codex pass 22 on PR 27: discovery stopped at the outer checkout, so an ordinary repository nested in it
    (no submodule, no flag) was in no record and no capture row."""
    mod = load()
    roots = tmp_path / "roots"
    outer = make_repo(roots / "outer")
    inner = make_repo(outer / "inner")
    (inner / "work.txt").write_text("only here\n")
    (outer / "node_modules").mkdir()
    make_repo(outer / "node_modules" / "dep")  # a dependency tree's repository is not scanned
    recs = {r["path"]: r for r in mod.scan_git([roots], remote=False)}
    assert set(recs) == {str(outer), str(inner)}
    assert recs[str(inner)]["untracked"] == 1 and recs[str(inner)]["verdict"] != "clean and pushed"
    assert recs[str(outer)]["untracked"] == 2  # `inner/` and `node_modules/` show as untracked in the outer checkout


def test_an_unreadable_stash_reflog_is_a_scan_incomplete_not_one_stash(tmp_path):
    """Codex pass 22 on PR 27: an OSError on the reflog used to report exactly one stash."""
    if os.geteuid() == 0:
        pytest.skip("root reads anything")
    mod = load()
    repo = make_repo(tmp_path / "roots" / "stashy")
    (repo / "a.txt").write_text("x\n")
    git(repo, "stash", "push", "-m", "one")
    (repo / "a.txt").write_text("y\n")
    git(repo, "stash", "push", "-m", "two")
    reflog = repo / ".git" / "logs" / "refs" / "stash"
    assert reflog.is_file()
    reflog.chmod(0)
    try:
        c = scan_one(mod, tmp_path / "roots")
    finally:
        reflog.chmod(0o644)
    assert c["verdict"] == "scan incomplete: stash list rc=1" and c["stashes"] is None
    assert scan_one(mod, tmp_path / "roots")["stashes"] == 2


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
    monkeypatch.setattr(mod, "submodule_config_check", lambda path, common: (True, None, []))
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
    # Codex pass 38 on PR 27, P1: the symlinked `.git` made `gitlink` an ordinary directory with no record at all;
    # it is a checkout the scan refuses, with the whole-directory fallback (the link's target is never read)
    assert found == ["gitlink", "real"]
    c = mod.scan_checkout(roots / "gitlink", remote=False)
    assert c["verdict"] == mod.SKIP_GIT_SYMLINK == "skipped: .git is a symlink" and c["modified"] is None, c
    (roots / "gitlink" / ".git").unlink()
    (roots / "gitlink" / ".git").symlink_to(outside / ".git" / "HEAD")  # a link to a file is no safer
    assert mod.scan_checkout(roots / "gitlink", remote=False)["verdict"] == mod.SKIP_GIT_SYMLINK
    recs = {c["path"]: c["verdict"] for c in mod.scan_git([roots], remote=False)}
    assert recs[str((roots / "gitlink").resolve())] == mod.SKIP_GIT_SYMLINK


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
        "GIT_NO_LAZY_FETCH", "GIT_NO_REPLACE_OBJECTS", "GIT_GRAFT_FILE", "GIT_ADVICE"}
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

    def terminated() -> bool:
        # A reaped PID answers nothing; on Linux a killed grandchild no PID 1 will reap
        # stays in state Z, where it can never run again (Codex pass 11 on PR 27).
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            stat = None
        if stat is not None:
            return stat.rpartition(")")[2].split()[0] == "Z"
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False

    for _ in range(50):
        if terminated():
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
        def fake(argv, timeout=120, cwd=None, env=None, **kw):
            if word in argv:
                seen[word] = timeout
                return rc, ""
            return real(argv, timeout=timeout, cwd=cwd, env=env, **kw)
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
    assert mod.ORIGIN_UNREACHABLE in c["flags"]  # fell back to the local refs/remotes/origin/* for the count
    assert c["local_only_verified"] is False
    assert c["local_only_commits"] == 1
    assert c["local_only_branches"] == [{"branch": "feature", "count": 1}]
    # no origin branch list at all (not even local refs): the verdict is still not clean
    mod = load()
    monkeypatch.setattr(mod, "origin_branches", lambda path, remote: (None, False, 0, {}, False))
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


def test_remote_scan_does_not_call_a_branch_preserved_by_a_live_tag_an_orphan(tmp_path):
    """Codex pass 19 on PR 27, P2: HEAD pushed only as an origin tag; the branch is not on origin, the local
    tracking refs hold nothing, so `ahead_of_origin` said 1 and the verdict was `orphan branch` while the
    live count was a verified 0 (the plan then asked for a needless branch push)."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "kept")
    commit_file(work, "k.txt")
    git(work, "push", "origin", "HEAD:refs/tags/kept-tag")
    c = scan_one(mod, roots)  # no live answer: the local refs/remotes/origin/* do not hold the tag
    assert c["verdict"] == "orphan branch" and c["ahead_of_origin"] == 1
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["ahead_of_origin"] == 0 and c["local_only_commits"] == 0 and c["local_only_verified"] is True
    assert c["on_origin"] is False and "orphan branch" not in c["flags"], c


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
    assert c["verdict"] == "unpushed commits" != "clean and pushed" and mod.ORIGIN_UNREACHABLE not in c["flags"]
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
        assert recs["wt"]["local_only_commits"] > 0 and mod.ORIGIN_UNREACHABLE not in recs["wt"]["flags"]


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
    assert mod.ORIGIN_UNREACHABLE not in c["flags"], c["flags"]
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
    assert "`` git -C '/p/c`o' -c core.hooksPath=/dev/null push -u origin refs/heads/'b`r':refs/heads/'b`r' `` or " in text  # shell-quoted since round 8


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


def unescape_span(text: str) -> str:
    """The shell text inside a markdown code span as a human pastes it: only the table cell's `\\|` is undone, because
    CommonMark and GFM decode no entity in a code span (adversary round 47: `html.unescape` here modelled a paste nobody
    can make)."""
    return text.replace("\\|", "|")


def unmark(span: str) -> str:
    """The shell text of one whole code span, fence included."""
    m = re.fullmatch(r"(`+) (.*) \1", span, re.S) or re.fullmatch(r"(`)(.*)\1", span, re.S)
    assert m, span
    return unescape_span(m.group(2))


PLAN_PREFIX = load_doc().PLAN_PREAMBLE + "; "
# the plan is pasted into bash or zsh: its preamble uses `<<<`, which dash (Ubuntu's `sh`) rejects (Codex pass 47 on PR 27, P1)
SHELLS = [s for s in ("bash", "zsh") if shutil.which(s)]


def plan_commands(row: str) -> list[str]:
    """The shell commands of a submodule row, in order, as a human would paste them: the code spans that open with the
    submodule guard, plus the `modules/` archive (the row's other commands belong to the checkout itself)."""
    spans = re.findall(r"(?<!`)(`+) (.+?) \1(?!`)|(?<!`)`([^`]+)`(?!`)", row)
    cmds = [unescape_span(fenced or single) for _fence, fenced, single in spans]
    return [c for c in cmds if c.startswith("{ [ -e ") or c.startswith("mkdir -p <DEST>/") and c.endswith(" modules")]


def run_plan(shell: str, cmd: str, dest: Path, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([shell, "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], cwd=cwd,
                          capture_output=True, text=True, env=GIT_ENV)


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
    assert "`git -C /p/work -c core.hooksPath=/dev/null push origin refs/heads/side:refs/heads/side`" in row
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
    assert "(no counts; listed in 3.2 with a whole-directory archive) | 2 |" in text  # Codex pass 29, P2
    assert "not in 3.2" not in text
    rows = section_3_2(text).splitlines()  # Codex pass 19, P1: no counts is not "nothing to capture"
    for path_, verdict in (("/p/skipped", "skipped: worktree redirected"), ("/p/broken", "scan incomplete: status rc=124")):
        row = next(r for r in rows if r.startswith(f"| {path_} "))
        row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
        assert f"counts unknown ({verdict})" in row and "re-scan once the cause is fixed" in row
        assert f"TAR_OPTIONS= \"$GTAR\" -C /p -cf <DEST>/checkouts/abs{path_}/whole.tar -- {path_.rsplit('/', 1)[1]}" in row
        assert "git" not in row.split("| re-scan")[1].split("(no git command")[0]
        assert row.rstrip().endswith("| yes: counts unknown; re-scan or archive whole |")
        # Codex pass 26: a `.git` file's target directory and its common directory are archived too
        assert (f'{{ IFS= read -r l || [ -n "$l" ]; }} < {path_}/.git && ! {{ IFS= read -r l1; IFS= read -r l2 || [ -n "$l2" ]; }} '
                f'< {path_}/.git && case "$l" in "gitdir: "*) g=${{l#gitdir: }}') in row  # round 43: a second line is refused
        assert f"g={path_}/$g" in row and "gitdir capture FAILED" in row  # adversary round 32: git's gitfile rules, loud failure
        # round 35, Codex pass 30: git checks `refs` and `objects` in the COMMON directory; round 36: resolved and
        # checked before anything is archived
        assert '[ -f "$g/HEAD" ] && c=$g && if [ -f "$g/commondir" ]; then { IFS= read -r c || [ -n "$c" ]; } < "$g/commondir"' in row
        assert f'[ -d "$c/objects" ] && [ -d "$c/refs" ] && TAR_OPTIONS= "$GTAR" -C "$g" -cf <DEST>/checkouts/abs{path_}/gitdir.tar .' in row
        assert f'then TAR_OPTIONS= "$GTAR" -C "$c" -cf <DEST>/checkouts/abs{path_}/commondir.tar .; fi' in row
        assert '&& [ -n "$g" ] && case "$g" in /*)' in row and "$g/commondir" in row  # round 33: a git directory only
    assert "is listed with a whole-directory archive" in section_3_2(text)
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
        def fake(argv, timeout=120, cwd=None, env=None, **kw):
            if argv[0] in ("rg", "grep"):
                return rc, ""
            return real(argv, timeout=timeout, cwd=cwd, env=env, **kw)
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
    assert "git -C '/p/evil dir' -c core.hooksPath=/dev/null push origin refs/heads/'side$(touch${IFS}PWNED)':refs/heads/'side$(touch${IFS}PWNED)'" in row.replace("\\$", "$").replace("\\{", "{").replace("\\}", "}").replace("\\(", "(").replace("\\)", ")")
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
            "> <DEST>/'checkouts/abs/p/u dir/untracked.list' && TAR_OPTIONS= \"$GTAR\" -C '/p/u dir' --null --no-recursion "
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
    # Codex pass 14 on PR 27: the rows read the scanned root (`--bigteam`), not a hard-coded default
    other = doc_scan([], tasks=[task]); other["bigteam"]["root"] = "/srv/bt root"
    text = mod.render(other)
    row = next(r for r in text.split("### 3.1")[1].split("### 3.2")[0].splitlines() if r.startswith("| big "))
    assert "(cd '/srv/bt root/big' && " in row and "~/.local/state/bigteam" not in row
    assert "## 1. bigteam (`/srv/bt root/<task>/`)" in text
    # Codex pass 13 on PR 27: an unclosed job record alone (no CLAIM, not mixed) is a decision, never "no (only DEST)"
    busy = dict(task, task="busy", open_job_records=["w.json"])
    text = mod.render(doc_scan([], tasks=[task, busy]))
    rows = text.split("### 3.1")[1].split("### 3.2")[0].splitlines()
    assert next(r for r in rows if r.startswith("| busy ")).rstrip().endswith("| yes: 1 job record(s) unclosed |")
    assert next(r for r in rows if r.startswith("| big ")).rstrip().endswith("| no (only DEST) |")


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
        def fake(argv, timeout=120, cwd=None, env=None, rc=rc, **kw):
            return (rc, "") if "get-url" in argv else real(argv, timeout=timeout, cwd=cwd, env=env, **kw)
        monkeypatch.setattr(mod, "run", fake)
        c = scan_one(mod, roots)
        assert c["verdict"] == f"scan incomplete: remote get-url origin rc={rc}", c["verdict"]
        assert "no origin remote" not in c["flags"]


def test_shquote_keeps_a_leading_tilde_outside_the_quotes():
    mod = load_doc()
    home = mod.Home
    assert mod.shquote(home("~/src/plain")) == "~/src/plain"
    assert mod.shquote(home("~/src/a b")) == "~/'src/a b'"
    assert mod.shquote(home("~/")) == "~/"
    assert mod.shquote("/abs/a b") == "'/abs/a b'"
    assert mod.shquote("x$(y)") == "'x$(y)'"
    assert mod.shcode("git -C {} add", home("~/src/a b")) == "`git -C ~/'src/a b' add`"
    # Codex pass 56 on PR 27, P2: a plain string that starts with `~/` is a name, never the home directory
    assert mod.shquote("~/report.md") == "'~/report.md'" and mod.shquote("~") == "'~'"
    assert mod.shquote(home("~/a") + "/b c") == "~/'a/b c'" and mod.shquote(home("~/a/").rstrip("/")) == "~/a"


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


def test_a_fifo_as_claim_or_job_record_is_unreadable_not_a_hang(tmp_path):
    """Codex finding 4365722733 (P2): `read_text()` on a bigteam task's `CLAIM` that is a FIFO, or a symlink to one, blocks
    forever (no writer); so did a FIFO `jobs/*.json`. Both reads are bounded and non-blocking now."""
    mod = load()
    root, refs = tmp_path / "bigteam", tmp_path / "refs"
    refs.mkdir()
    os.mkfifo(tmp_path / "elsewhere")
    fifos = [tmp_path / "elsewhere"]
    plain = root / "t-fifo"
    plain.mkdir(parents=True)
    os.mkfifo(plain / "CLAIM")
    linked = root / "t-link"
    linked.mkdir()
    (linked / "CLAIM").symlink_to(tmp_path / "elsewhere")
    jobs = root / "t-jobs"
    (jobs / "jobs").mkdir(parents=True)
    os.mkfifo(jobs / "jobs" / "x.json")
    fifos += [plain / "CLAIM", jobs / "jobs" / "x.json"]
    result: list = []
    t = threading.Thread(target=lambda: result.append(mod.scan_bigteam(root, [refs], [], 1_000_000, 10)), daemon=True)
    t.start()
    t.join(20)
    if t.is_alive():  # the old code sits in open(): release it with a writer, then fail
        for f in fifos:
            os.close(os.open(f, os.O_RDWR))
        t.join(10)
        raise AssertionError("scan_bigteam blocked on a FIFO")
    by = {x["task"]: x for x in result[0]["tasks"]}
    for name in ("t-fifo", "t-link"):
        assert by[name]["claim"] == "no CLAIM" and by[name]["verdict"].startswith(mod.INCOMPLETE_PREFIX), by[name]
        assert by[name]["verdict"].endswith("CLAIM"), by[name]["verdict"]
    assert by["t-jobs"]["open_job_records"] == ["x.json (unreadable)"], by["t-jobs"]


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
    # a code span shows `<i>` as typed (CommonMark decodes nothing in one, round 47): only text outside spans must be inert
    outside = re.sub(r"(`+).*?\1", "", text, flags=re.S)
    assert "<i>" not in outside and "<b>" not in outside
    rows = [ln for ln in text.splitlines() if "scandir EACCES" in ln and ln.startswith("| ")]
    # the 1.1 top-children table and the 1.3 every-task table; 1.2 lists only unique/mixed dirs
    assert len(rows) == 2, rows
    for ln in rows:
        assert "`s\\|<i>x/`" in ln or "s\\|&lt;i&gt;x" in ln, ln
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
    heads, tags, invalid = mod.ls_remote_refs("/nowhere")
    assert heads == {"main": good, "long": sha256} and tags == {} and invalid == 6


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
    assert mod.ORIGIN_UNREACHABLE in c["flags"] and c["local_only_verified"] is False
    assert c["verdict"] == mod.ORIGIN_UNREACHABLE != "clean and pushed"
    git(work, "remote", "remove", "origin")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert "no origin remote" in c["flags"] and c["local_only_verified"] is None


def test_ls_remote_gets_the_url_through_the_environment_never_argv(tmp_path, monkeypatch):
    """Codex pass 16, P1 (4325538238): the url sits in GIT_CONFIG_VALUE_0, the call names `origin`."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    real, calls = mod.run, []

    def spy(argv, timeout=120, cwd=None, env=None, stdin_text=None, **kw):
        if "ls-remote" in argv:
            calls.append((list(argv), dict(env or {})))
        return real(argv, timeout=timeout, cwd=cwd, env=env, stdin_text=stdin_text, **kw)
    monkeypatch.setattr(mod, "run", spy)
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "clean and pushed" and c["local_only_verified"] is True, c["flags"]
    (argv, env), = calls
    assert env["GIT_CONFIG_COUNT"] == "1" and env["GIT_CONFIG_KEY_0"] == "remote.origin.url"
    assert env["GIT_CONFIG_VALUE_0"] == str(origin)
    assert argv[-2:] == ["--", "origin"] and not any(str(origin) in a for a in argv), argv
    assert [k for k in env if k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_")] == [
        "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"]


def test_a_url_with_a_password_is_never_queried_and_never_leaks(tmp_path, monkeypatch):
    """Codex pass 16, P1: `https://u:FAKE-SECRET@...` makes the checkout unverified; the secret is in no
    argv, no environment of a spawned call, no JSON, no stderr and no rendered doc."""
    secret = "FAKE-SECRET"
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "config", "remote.origin.url", f"https://u:{secret}@127.0.0.1:9/x.git")
    real, seen = mod.run, []

    def spy(argv, timeout=120, cwd=None, env=None, stdin_text=None, **kw):
        seen.append((list(argv), dict(env or {})))
        return real(argv, timeout=timeout, cwd=cwd, env=env, stdin_text=stdin_text, **kw)
    monkeypatch.setattr(mod, "run", spy)
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert mod.ORIGIN_CREDENTIAL in c["flags"] and c["verdict"] == mod.ORIGIN_CREDENTIAL != "clean and pushed"
    assert c["local_only_verified"] is False and mod.ORIGIN_UNREACHABLE not in c["flags"]
    assert not any("ls-remote" in argv or "fetch" in argv for argv, _ in seen), "origin was asked"
    assert not any(secret in a for argv, env in seen for a in argv) and not any(
        secret in v for _, env in seen for v in env.values())
    assert secret not in json.dumps(c) and secret not in repr(list(mod._remote_cache))
    # without --remote the flag is not raised (nothing was asked), but --fetch still never fetches
    mod._remote_cache.clear()
    assert mod.ORIGIN_CREDENTIAL not in scan_one(mod, roots, fetch=True)["flags"]
    assert not any("fetch" in argv for argv, _ in seen)
    # through the CLI: stdout (JSON), stderr and the rendered doc
    bigteam = tmp_path / "bigteam"
    bigteam.mkdir()
    p = subprocess.run([str(SCRIPT), "--bigteam", str(bigteam), "--git-root", str(roots), "--remote",
                        "--fetch", "--json"], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert secret not in p.stdout and secret not in p.stderr
    rec = json.loads(p.stdout)["checkouts"][0]
    assert rec["verdict"] == mod.ORIGIN_CREDENTIAL and rec["local_only_verified"] is False
    scan = tmp_path / "scan.json"
    scan.write_text(p.stdout)
    out = tmp_path / "doc.md"
    gen = doc_cli(scan, out)
    assert gen.returncode == 0, gen.stderr
    text = out.read_text()
    assert secret not in text and secret not in gen.stderr and secret not in gen.stdout
    assert "origin url holds a credential" in text and mod.ORIGIN_CREDENTIAL in text


def test_url_holds_credential_reads_any_userinfo_or_query_on_a_non_ssh_scheme():
    """Adversary round 22 on PR 27: a token used as the username (`https://<token>@github.com/x`) reaches
    git-remote-https' argv like a password does; a query-string token too. ssh usernames are not secrets."""
    mod = load()
    for url, want in (("https://u:pw@host/x.git", True), ("https://u:@host/x.git", True),
                      ("ssh://git:pw@host/x", True), ("https://user@host/x.git", True),
                      ("https://ghp_FAKE0000@github.com/o/r.git", True), ("http://x@host/x.git", True),
                      ("https://host/x.git?private_token=FAKE", True), ("https://host/x?a=b@c:d", True),
                      ("ssh://git@host/x", False), ("git+ssh://git@host/x", False),
                      ("git@host:x/y.git", False), ("host:x/y.git", False), ("user:pw@host:x/y.git", True),  # round 58: the secret is in ssh's argv as the path
                      ("https://host:8443/x.git", False), ("https://host/x.git#frag", True),  # Codex pass 27: a fragment reaches argv too
                      ("/tmp/some/origin.git", False), ("file:///tmp/o.git", False),
                      ("https://u:pw@[::1/x", True), ("https://u@[::1/x", True),
                      # adversary round 23: a remote-helper prefix wraps the real address
                      ("https::https://ghp_FAKE0000@github.com/o/r.git", True),
                      ("ext::sh -c 'echo x'", False), ("https::https://host/x.git", False),
                      ("https::https://host/x.git?t=FAKE", True),
                      # round 24: git splits at the first `::`; the helper gets the rest whole, whatever it looks like
                      ("https::https::https://ghp_FAKE0000@host/x.git", True),
                      ("https::ssh://ghp_FAKE0000@host/x.git", True), ("https::ssh://host/x.git", False),
                      # Codex pass 25: an ssh query string lands in `git-upload-pack '/repo?...'` in the ssh argv
                      ("ssh://git@host/repo?private_token=FAKE", True), ("git+ssh://git@host/x?t=FAKE", True),
                      ("ssh://git@host/x?", False),  # an empty query carries nothing
                      # adversary round 31: an scp-like url hands its path to ssh verbatim, `?` and all
                      ("git@host:repo?token=FAKE", True), ("host:x?y", True), ("/tmp/o?x", False), ("x/y:z?q", False),
                      # Codex pass 27: a fragment, on every form; an empty one carries nothing
                      ("ssh://git@host/x#t=FAKE", True), ("git@host:repo#FAKE", True), ("https::https://host/x.git#t", True),
                      ("https://host/x.git#", False), ("/tmp/a#b", False),
                      # Codex pass 28: a control character anywhere: git hands the value on whole
                      ("ssh://git@host/repo\n?private_token=FAKE", True), ("https://host/x.git\n", True),
                      ("git@host:repo\t", True), ("/tmp/o\n", True),
                      # Cursor security review (2026-10-20): git decodes a percent-encoded separator on the transport
                      # side, so `%3F`, `%23`, `%40`, `%3A` and an encoded control character count on every form
                      ("ssh://git@127.0.0.1/repo%3Ftoken=FAKE", True), ("https://host/x.git%3Fprivate_token=FAKE", True),
                      ("ssh://git%3Apw@host/x", True), ("https://host/x%23t", True), ("git@host:a%3fb", True),
                      ("https://host/x%40y.git", True), ("https://host/x%0a.git", True), ("https::https://host/x%3Ft", True),
                      ("https://host/x%20y.git", False), ("https://host/x%2Fy.git", False), ("/tmp/o%3F", True)):
        assert mod.url_holds_credential(url) is want, url


def test_a_remote_helper_url_is_withheld_whatever_it_holds():
    """Codex pass 44 on PR 27, P1: `git push origin` on `evil::PAYLOAD` (or `evil://x`) runs `git-remote-evil` from PATH,
    and `ext::` runs the command it is given: such a url is never queried and never gets a push row."""
    mod = load()
    for url, want in (("evil::PAYLOAD", True), ("ext::sh -c 'touch /tmp/x'", True), ("fd::3", True), ("https::https://host/x.git", True),
                      ("evil://host/x", True), ("EVIL://host/x", True), ("hg+ssh://host/x", True), ("s3://bucket/x", True),
                      # round 50: git matches its own transports case-sensitively and lets a scheme start with a digit
                      ("SSH://host/x", True), ("Git://host/x", True), ("FILE:///tmp/x", True), ("HTTPS://host/x", True),
                      ("0day://host/x", True), ("Git+ssh://host/x", True),
                      ("https://host/x.git", False), ("http://host/x.git", False), ("ssh://git@host/x", False), ("git+ssh://git@host/x", False),
                      ("git://host/x", False), ("file:///tmp/o.git", False), ("ftp://host/x", False), ("git@host:x/y.git", False),
                      ("host:x/y.git", False), ("/tmp/some/origin.git", False), ("../relative/o.git", False), ("[::1]:x/y", False)):
        assert mod.url_names_remote_helper(url) is want, url
        assert mod.url_withheld(url) is (want or mod.url_holds_credential(url)), url


def test_an_old_git_is_never_given_the_url_in_argv(tmp_path, monkeypatch):
    """Before git 2.31 GIT_CONFIG_COUNT is ignored: the query is refused, the checkout is unreachable."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    real, asked = mod.run, []

    def old_git(argv, timeout=120, cwd=None, env=None, stdin_text=None, **kw):
        if argv[:2] == ["git", "--version"]:
            return 0, "git version 2.30.9\n"
        asked.append(argv)
        return real(argv, timeout=timeout, cwd=cwd, env=env, stdin_text=stdin_text, **kw)
    monkeypatch.setattr(mod, "run", old_git)
    c = scan_one(mod, roots, remote=True)
    assert mod.ORIGIN_UNREACHABLE in c["flags"] and c["local_only_verified"] is False
    assert c["verdict"] != "clean and pushed" and not any("ls-remote" in a for a in asked)


def test_remote_scan_with_an_unreachable_origin_is_never_clean_even_with_a_stale_tracking_ref(tmp_path):
    """Codex pass 15, P1 (4325359328): branch `x` was pushed, then deleted on origin before an outage; its stale
    `refs/remotes/origin/x` hides the only commit. `--remote` that cannot reach origin must not say clean."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "x")
    commit_file(work, "x.txt")
    git(work, "push", "origin", "x")
    git(work, "checkout", "main")
    git(origin, "branch", "-D", "x")
    git(work, "config", "remote.origin.url", str(tmp_path / "moved-away.git"))
    c = scan_one(mod, roots)  # plain scan: the documented caveat, the stale ref hides it, nothing was asked
    assert c["verdict"] == "clean and pushed" and c["local_only_verified"] is None
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == mod.ORIGIN_UNREACHABLE != "clean and pushed", c
    assert c["flags"] == [mod.ORIGIN_UNREACHABLE]
    assert c["local_only_verified"] is False
    assert c["local_only_commits"] == 0  # an undercount, which is what the primary flag says


def make_tag_only_commit(work: Path, tag: str = "v1", annotated: bool = False) -> None:
    """A commit no branch holds any more: reachable from a local tag only."""
    git(work, "checkout", "-b", "tmp-side")
    commit_file(work, f"{tag}.txt")
    git(work, "tag", *(["-a", "-m", tag] if annotated else []), tag)
    git(work, "checkout", "main")
    git(work, "branch", "-D", "tmp-side")


@pytest.mark.parametrize("annotated", [False, True])
def test_a_commit_reachable_only_from_a_local_tag_is_local_only_until_origin_has_the_tag(tmp_path, annotated):
    """Codex pass 15, P1 (4325359341): the branch was reset or deleted, the tag keeps the unpushed commit."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    make_tag_only_commit(work, "v1", annotated)
    c = scan_one(mod, roots)
    assert c["verdict"] == "unpushed commits" != "clean and pushed", c
    assert c["local_only_commits"] == 1 and c["local_only_tags"] == [{"tag": "v1", "count": 1}]
    assert c["local_only_branches"] == []
    assert any(f == "local-only commits: tag v1 1" for f in c["flags"]), c["flags"]
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)  # origin does not have the tag
    assert c["local_only_commits"] == 1 and c["local_only_verified"] is True and c["verdict"] != "clean and pushed"
    git(work, "push", "origin", "refs/tags/v1:refs/tags/v1")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)  # origin has it (an annotated tag through its peeled commit)
    assert c["verdict"] == "clean and pushed" and c["local_only_commits"] == 0, c
    assert c["local_only_tags"] == [] and c["local_only_verified"] is True and c["flags"] == []


def test_a_commit_reachable_only_from_a_note_or_another_local_ref_is_local_only(tmp_path):
    """Codex pass 25 on PR 27: `HEAD --branches --tags` ignored `refs/notes/*` and every other local namespace, so a
    checkout whose only unpushed work was a `git notes add` read `clean and pushed` and left the capture plan."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    git(work, "stash", "list")  # no stash yet
    git(work, "notes", "add", "-m", "a note", "HEAD")
    c = scan_one(mod, roots)
    assert c["verdict"] == "unpushed commits" and c["local_only_commits"] == 1, c
    assert c["local_only_branches"] == [] and c["local_only_tags"] == []
    assert "local-only commits: 1 in total" in c["flags"], c["flags"]
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)  # live tips are heads and tags only: the note stays local-only
    assert c["local_only_commits"] == 1 and c["verdict"] == "unpushed commits"
    # the stash is counted on its own and a remote-tracking ref of another remote is no local work
    git(work, "update-ref", "-d", "refs/notes/commits")  # `notes remove` would add one more notes commit
    (work / "s.txt").write_text("s\n")
    git(work, "add", "s.txt")
    git(work, "stash", "push", "-m", "wip")
    git(work, "checkout", "-q", "-b", "side")
    commit_file(work, "side.txt")
    side = git(work, "rev-parse", "HEAD").strip()
    git(work, "checkout", "-q", "main")
    git(work, "branch", "-D", "side")
    git(work, "update-ref", "refs/remotes/other/x", side)  # the only ref holding that commit
    c = scan_one(mod, roots)
    assert c["local_only_commits"] == 0 and c["stashes"] == 1 and "stash" in c["flags"], c
    assert c["verdict"] == "clean and pushed"  # the stash is an informational flag with its own capture row


def test_a_replace_ref_does_not_hide_a_local_commit(tmp_path):
    """Adversary round 31 on PR 27: `git replace` can make origin's tip appear to contain a local commit, so
    every count read the fake graph; GIT_NO_REPLACE_OBJECTS=1 makes the counts read the real objects."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    pushed = git(work, "rev-parse", "HEAD").strip()
    commit_file(work, "local.txt")  # one unpushed commit on main
    local = git(work, "rev-parse", "HEAD").strip()
    git(work, "replace", "--force", "origin/main", local)  # origin/main now "is" the local commit
    c = scan_one(mod, roots)
    assert c["verdict"] == "unpushed commits" and c["local_only_commits"] == 1, c
    assert c["local_only_branches"] == [{"branch": "main", "count": 1}], c
    assert git(work, "rev-parse", "origin/main").strip() == pushed


def test_an_origin_url_with_an_embedded_newline_is_read_whole_and_never_queried(tmp_path):
    """Codex pass 28 on PR 27: `splitlines()[0]` judged only the first line of `remote.origin.url`."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    url = "ssh://git@127.0.0.1:9/repo\n?private_token=FAKE"
    git(work, "config", "remote.origin.url", url)
    assert mod.queried_origin_url(work) == url
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert mod.ORIGIN_CREDENTIAL in c["flags"] and c["local_only_verified"] is False, c["flags"]


def test_an_untracked_graft_directory_counts_like_any_other_path():
    """Codex pass 28 on PR 27: a checkout whose only untracked path was `graft/` left the capture plan by name."""
    mod = load_doc()
    co = doc_checkout("/p/g", flags=["dirty"], verdict="dirty", untracked=1, untracked_sample=["graft/"])
    rows = [r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /p/g ")]
    assert len(rows) == 1 and "1 untracked (`graft/`)" in rows[0] and "untracked.tar" in rows[0]


def test_a_grafts_file_does_not_hide_a_local_commit(tmp_path):
    """Adversary round 32 on PR 27: a `.git/info/grafts` line can give origin's tip a local commit as a parent with no
    ref at all, so `--all` sees nothing and the checkout read `clean and pushed`; GIT_GRAFT_FILE=/dev/null."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    pushed = git(work, "rev-parse", "HEAD").strip()
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    git(other, "checkout", "-q", "main")
    commit_file(other, "o2.txt")
    git(other, "push", "-q", "origin", "main")
    o2 = git(other, "rev-parse", "HEAD").strip()
    commit_file(work, "local.txt")  # one unpushed commit on main
    local = git(work, "rev-parse", "HEAD").strip()
    git(work, "fetch", "-q", "origin")
    info = work / ".git" / "info"
    info.mkdir(exist_ok=True)
    (info / "grafts").write_text(f"{o2} {pushed} {local}\n")  # origin's tip "merged" the local commit
    c = scan_one(mod, roots)
    assert c["verdict"] == "unpushed commits" and c["local_only_commits"] == 1, c
    assert c["local_only_branches"] == [{"branch": "main", "count": 1}], c


def test_an_assume_unchanged_or_skip_worktree_edit_is_counted_and_archived(tmp_path):
    """Codex pass 32 on PR 27: `update-index --assume-unchanged f` (or `--skip-worktree`) then an edit of `f` gave
    `modified: 0`, no flags and `clean and pushed`; the bytes were in no patch and the checkout had no row."""
    import tarfile
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    (work / "a.txt").write_text("hidden edit\n")
    git(work, "update-index", "--assume-unchanged", "a.txt")
    assert git(work, "status", "--porcelain") == ""
    c = scan_one(mod, roots)
    assert c["verdict"] == "index-hidden paths: 1" and c["modified"] == 0 and c["index_hidden"] == 1, c
    git(work, "update-index", "--no-assume-unchanged", "a.txt")
    assert scan_one(mod, roots)["verdict"] == "dirty"
    git(work, "update-index", "--skip-worktree", "a.txt")
    c = scan_one(mod, roots)
    assert c["index_hidden"] == 1 and c["verdict"] == "index-hidden paths: 1", c
    row = next(r for r in section_3_2(doc.render(doc_scan([doc_checkout("/p/h", flags=["index-hidden paths: 1"],
                                                                        verdict="index-hidden paths: 1", index_hidden=1)]))).splitlines()
               if r.startswith("| /p/h "))
    row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
    assert "1 tracked path(s) marked assume-unchanged or skip-worktree" in row
    assert "\"$GSED\" -z -n 's/^[a-z] //p; t; s/^S //p' <DEST>/checkouts/abs/p/h/hidden.raw > <DEST>/checkouts/abs/p/h/hidden.list" in row
    # round 39: children through git's ignore rules, no recursion; Codex pass 34: tar's stderr fails the row
    assert ("< <DEST>/checkouts/abs/p/h/hidden.list xargs -0 -r git --literal-pathspecs -C /p/h ls-files -z --others "
            "--exclude-standard -- > <DEST>/checkouts/abs/p/h/hidden-children.list 2> <DEST>/checkouts/abs/p/h/hidden.err") in row  # round 40
    assert ("{ TAR_OPTIONS= LC_ALL=C \"$GTAR\" -cf <DEST>/checkouts/abs/p/h/hidden.tar -C <DEST>/checkouts/abs/p/h hidden.list hidden-children.list -C /p/h "
            "--null --no-recursion --ignore-failed-read -T <DEST>/checkouts/abs/p/h/hidden.list -T <DEST>/checkouts/abs/p/h/hidden-children.list "
            "2>> <DEST>/checkouts/abs/p/h/hidden.err || { cat <DEST>/checkouts/abs/p/h/hidden.err >&2; echo 'hidden capture FAILED' >&2; false; }; }") in row
    assert ("{ ! grep -qv -e ': Cannot stat: No such file or directory$' -e ': Cannot stat: Not a directory$' <DEST>/checkouts/abs/p/h/hidden.err || "
            "{ cat <DEST>/checkouts/abs/p/h/hidden.err >&2; echo 'hidden capture FAILED' >&2; false; }; }") in row
    assert doc.HIDDEN_FMT.count("{}") == len(doc.hidden_values("/p", "c"))
    ck = doc.checkout_dir(str(work))
    prefix = PLAN_PREFIX
    cmd = prefix + doc.HIDDEN_FMT.format(*map(doc.shquote, doc.hidden_values(str(work), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        tar = tarfile.open(tmp_path / "dest" / ck / "hidden.tar")
        assert set(tar.getnames()) == {"hidden.list", "hidden-children.list", "a.txt"}, tar.getnames()
        assert tar.extractfile("a.txt").read() == b"hidden edit\n"
    # Codex pass 33: the hidden path replaced by a directory: `status` reports neither the deletion nor the children,
    # the untracked count is 0, and `--no-recursion` archived an empty `a.txt/` entry without `a.txt/child`
    (work / "a.txt").unlink()
    (work / "a.txt").mkdir()
    (work / "a.txt" / "child").write_text("child\n")
    assert git(work, "status", "--porcelain") == ""
    c = scan_one(mod, roots)
    assert c["index_hidden"] == 1 and c["untracked"] == 0, c
    shutil.rmtree(tmp_path / "dest", ignore_errors=True)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    tar = tarfile.open(tmp_path / "dest" / ck / "hidden.tar")
    assert set(tar.getnames()) == {"hidden.list", "hidden-children.list", "a.txt", "a.txt/child"}, tar.getnames()
    assert tar.extractfile("a.txt/child").read() == b"child\n"
    # round 39: an ignored child, and an untracked file outside the hidden path, are not this row's business
    (work / "a.txt" / "secret.env").write_text("ignored\n")
    (work / "elsewhere.txt").write_text("untracked\n")
    (work / ".git" / "info" / "exclude").write_text("secret.env\n")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert set(tarfile.open(tmp_path / "dest" / ck / "hidden.tar").getnames()) == {"hidden.list", "hidden-children.list", "a.txt", "a.txt/child"}
    # Codex pass 34: an unreadable hidden file must fail the row, not vanish from the archive with rc 0
    if os.geteuid() != 0:
        (work / "a.txt" / "child").chmod(0)
        try:
            run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        finally:
            (work / "a.txt" / "child").chmod(0o644)
        assert run.returncode != 0 and "hidden capture FAILED" in run.stderr and "Permission denied" in run.stderr, run.stderr
        # round 40: an unreadable subdirectory under the replaced path: `ls-files --others` skips it with a warning
        # and rc 0, so the children step's stderr must fail the row, not vanish
        (work / "a.txt" / "s").mkdir()
        (work / "a.txt" / "s" / "deep").write_text("deep\n")
        (work / "a.txt" / "s").chmod(0)
        try:
            run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        finally:
            (work / "a.txt" / "s").chmod(0o755)
        assert run.returncode != 0 and "hidden capture FAILED" in run.stderr and "could not open directory" in run.stderr, run.stderr
        shutil.rmtree(work / "a.txt" / "s")
    # round 40: tar's own failure (an archive path it cannot write) is printed and fails the row
    shutil.rmtree(tmp_path / "dest")
    (tmp_path / "dest" / ck / "hidden.tar").mkdir(parents=True)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode != 0 and "hidden capture FAILED" in run.stderr and "hidden.tar" in run.stderr, run.stderr
    shutil.rmtree(tmp_path / "dest" / ck / "hidden.tar")
    # a hidden path with no file at all (sparse, or an assume-unchanged deletion) has no bytes to keep: no failure
    shutil.rmtree(work / "a.txt")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert set(tarfile.open(tmp_path / "dest" / ck / "hidden.tar").getnames()) == {"hidden.list", "hidden-children.list"}


def test_an_absent_skip_worktree_path_is_a_sparse_checkout_not_hidden_work(tmp_path):
    """Adversary round 38 on PR 27: a cone sparse-checkout's out-of-cone files are skip-worktree entries with no
    file, and every one was `index-hidden paths: <n>`; an assume-unchanged path that is gone still counts, and a
    tracked `S x` marked assume-unchanged made the sed print a second name `x`, archiving an unrelated file."""
    import tarfile
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "update-index", "--skip-worktree", "a.txt")
    (work / "a.txt").unlink()
    assert git(work, "status", "--porcelain") == ""
    c = scan_one(mod, roots)
    assert c["index_hidden"] == 0 and c["verdict"] == "clean and pushed", c
    git(work, "update-index", "--no-skip-worktree", "a.txt")
    git(work, "checkout", "--", "a.txt")
    git(work, "update-index", "--assume-unchanged", "a.txt")
    (work / "a.txt").unlink()
    assert scan_one(mod, roots)["index_hidden"] == 1
    git(work, "update-index", "--no-assume-unchanged", "a.txt")
    git(work, "checkout", "--", "a.txt")
    (work / "S x").write_text("tracked\n")
    git(work, "add", "S x")
    git(work, "commit", "-q", "-m", "S x")
    git(work, "update-index", "--assume-unchanged", "S x")
    (work / "x").write_text("not hidden work\n")
    ck = doc.checkout_dir(str(work))
    prefix = PLAN_PREFIX
    cmd = prefix + doc.HIDDEN_FMT.format(*map(doc.shquote, doc.hidden_values(str(work), ck))).replace("<DEST>", str(tmp_path / "dest"))
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    tar = tarfile.open(tmp_path / "dest" / ck / "hidden.tar")
    assert set(tar.getnames()) == {"hidden.list", "hidden-children.list", "S x"}, tar.getnames()


def test_a_reflog_only_commit_is_counted_and_packed(tmp_path):
    """Codex pass 32 on PR 27: a local commit followed by `reset --hard origin/main` stays at `HEAD@{1}` only; the
    scanner read `clean and pushed` and the capture plan had no row, so cleanup lost it."""
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    commit_file(work, "lost.txt")
    lost = git(work, "rev-parse", "HEAD").strip()
    git(work, "reset", "--hard", "origin/main")
    c = scan_one(mod, roots)
    assert c["verdict"] == "reflog-only commits: 1" and c["reflog_only_commits"] == 1 and c["local_only_commits"] == 0, c
    mod._remote_cache.clear()
    assert scan_one(mod, roots, remote=True)["reflog_only_commits"] == 1
    # stash entries are their own count: two stashes add nothing here, even though only stash@{0} is a ref
    (work / "a.txt").write_text("s1\n")
    git(work, "stash", "push", "-m", "one")
    (work / "a.txt").write_text("s2\n")
    git(work, "stash", "push", "-m", "two")
    c = scan_one(mod, roots)
    assert c["reflog_only_commits"] == 1 and c["stashes"] == 2, c
    row = next(r for r in section_3_2(doc.render(doc_scan([doc_checkout("/p/r", flags=["reflog-only commits: 3"],
                                                                        verdict="reflog-only commits: 3", reflog_only_commits=3)]))).splitlines()
               if r.startswith("| /p/r "))
    assert "3 reflog-only commit(s) (left by a reset, amend, rebase or squash-merge in the last ~30 days" in row
    assert ("GIT_ADVICE=0 GIT_NO_LAZY_FETCH=1 GIT_GRAFT_FILE=/dev/null GIT_NO_REPLACE_OBJECTS=1 git -C /p/r rev-list --objects "
            "--missing=allow-promisor --reflog --not --all > <DEST>/checkouts/abs/p/r/reflog-only.list") in row  # round 38
    assert "GIT_NO_LAZY_FETCH=1 GIT_GRAFT_FILE=/dev/null GIT_NO_REPLACE_OBJECTS=1 git -C /p/r pack-objects <DEST>/checkouts/abs/p/r/reflog-only < <DEST>/checkouts/abs/p/r/reflog-only.list" in row
    assert "then `git update-ref refs/recovered/<sha> <sha>` for each commit line of `reflog-only.list`" in row
    ck = doc.checkout_dir(str(work))
    cmd = doc.REFLOG_FMT.format(*map(doc.shquote, doc.reflog_values(str(work), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        if git_version() >= (2, 46):  # Codex pass 39: an older git ignores GIT_ADVICE and prints the grafts hint
            assert "hint:" not in run.stderr, run.stderr  # round 38: `GIT_ADVICE=0` silences the grafts deprecation hint
        idx = list((tmp_path / "dest" / ck).glob("reflog-only-*.idx"))
        assert len(idx) == 1
        assert lost in git(work, "verify-pack", "-v", str(idx[0]))
    # once the reflog has expired the commit is gone for good and the count says so
    git(work, "reflog", "expire", "--expire=now", "--all")
    assert scan_one(mod, roots)["reflog_only_commits"] == 0


def test_a_reflog_only_commit_on_an_unborn_head_is_counted(tmp_path):
    """Adversary round 38 on PR 27: commit X on `main`, never pushed, then `switch --orphan fresh` and
    `branch -D main`: no local ref is left, `unborn` is true, and the reflog count was skipped under it, so the
    checkout read `clean and pushed` while `git reflog` still recovered X."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    commit_file(work, "lost.txt")
    lost = git(work, "rev-parse", "HEAD").strip()
    git(work, "switch", "--orphan", "fresh")
    git(work, "branch", "-D", "main")
    assert git(work, "for-each-ref", "refs/heads", "refs/tags") == ""
    for remote in (False, True):
        mod._remote_cache.clear()
        c = scan_one(mod, roots, remote=remote)
        assert c["reflog_only_commits"] == 1 and "reflog-only commits: 1" in c["flags"], c
        assert c["verdict"] != "clean and pushed", c
    assert lost in git(work, "rev-list", "--reflog", "--not", "--all")


def test_a_local_tag_of_a_pushed_commit_is_not_local_only(tmp_path):
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "tag", "release")
    assert scan_one(mod, roots)["verdict"] == "clean and pushed"  # without --remote origin's tags are unknown


def test_a_local_tag_of_a_pushed_commit_is_unpushed_work_once_origin_is_asked(tmp_path):
    """Codex pass 31 on PR 27: an annotated tag on an already-pushed commit adds no commit, so every count was 0 and
    the checkout read `clean and pushed`; the tag's name, annotation and signature exist nowhere but here."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "tag", "-a", "-m", "the release", "release")
    git(work, "tag", "plain")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "unpushed tags" and c["local_only_commits"] == 0, c
    assert "unpushed tag names: plain, release" in c["flags"]  # round 37: one verdict bucket, the names in a second flag
    assert c["local_only_tags"] == [{"tag": "plain", "count": 0}, {"tag": "release", "count": 0}]
    assert c["local_only_verified"] is True
    git(work, "push", "origin", "refs/tags/release:refs/tags/release")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "unpushed tags" and c["local_only_tags"] == [{"tag": "plain", "count": 0}], c
    assert "unpushed tag names: plain" in c["flags"]
    git(work, "push", "origin", "refs/tags/plain:refs/tags/plain")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "clean and pushed" and c["local_only_tags"] == [] and c["flags"] == [], c
    # a tag origin has under the same name at another object is unpushed too
    git(work, "tag", "-d", "plain")
    git(work, "tag", "-a", "-m", "moved", "plain")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "unpushed tags", c


def test_a_tag_past_the_counting_budget_is_never_listed_as_count_zero(tmp_path, monkeypatch):
    """Adversary round 37 on PR 27: a tag the shared 100-ref budget left uncounted carries unknown commits; it was
    added as count 0 ("tag only") and counted again in the uncounted remainder."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-b", "side")
    commit_file(work, "side.txt")
    git(work, "checkout", "main")
    make_tag_only_commit(work, "has-local-commit", annotated=True)
    monkeypatch.setattr(mod, "MAX_BRANCH_COUNTS", 1)  # the one slot goes to the first branch
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert c["local_only_commits"] == 2 and c["local_only_tags"] == [] and c["local_only_branches_uncounted"] == 2, c
    assert "unpushed tags" not in c["flags"] and c["verdict"] == "unpushed commits"


def test_capture_plan_pushes_or_bundles_a_tag_object_on_a_pushed_commit():
    """Codex pass 31 on PR 27: count 0, no local-only commits, yet the tag must be pushed or bundled."""
    mod = load_doc()
    co = doc_checkout("/p/t", flags=["unpushed tags", "unpushed tag names: release, --force"], verdict="unpushed tags",
                      local_only_tags=[{"tag": "release", "count": 0}, {"tag": "--force", "count": 0}])
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /p/t "))
    assert "2 local tag(s) origin lacks: `release`, `--force`" in row
    # round 37: every tag in one push and one bundle, however many there are; no per-tag argv
    assert "`git -C /p/t -c core.hooksPath=/dev/null push origin --tags` or `mkdir" in row and "refs/tags/--force" not in row
    assert "git -C /p/t bundle create <DEST>/checkouts/abs/p/t/tags.bundle --tags" in row
    assert "rejected by the push: bundle it, or decide to force" in row
    assert row.rstrip().endswith("| yes: pushing a tag publishes it; pick push or bundle |")
    many = doc_checkout("/p/m", flags=["unpushed tags"], verdict="unpushed tags",
                        local_only_tags=[{"tag": f"t{i}", "count": 0} for i in range(9)])
    row = next(r for r in section_3_2(mod.render(doc_scan([many]))).splitlines() if r.startswith("| /p/m "))
    assert "9 local tag(s) origin lacks: `t0`, `t1`, `t2`, `t3`, `t4` and 4 more" in row and "t8" not in row
    # with local-only commits on other branches the existing push-or-bundle-all row carries the tag already
    both = doc_checkout("/p/b", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=2,
                        local_only_branches=[{"branch": "side", "count": 2}], local_only_tags=[{"tag": "v0", "count": 0}])
    row = next(r for r in section_3_2(mod.render(doc_scan([both]))).splitlines() if r.startswith("| /p/b "))
    assert "tag `v0` (tag only)" in row and "refs/tags/v0:refs/tags/v0" in row and "tags.bundle" not in row


def test_capture_plan_never_pushes_to_a_credential_bearing_origin():
    """Codex pass 33 on PR 27: a checkout flagged `origin url holds a credential: not queried` still got a
    `git push origin` command whenever a branch or tag was local-only; running it hands the credential-bearing url
    to the transport helper's argv. Every push variant is replaced by its bundle alone."""
    mod = load_doc()
    cred = mod.ORIGIN_CREDENTIAL
    head = doc_checkout("/p/h", flags=["unpushed commits", cred], verdict="unpushed commits", ahead_of_origin=2, unpushed=2)
    others = doc_checkout("/p/o", flags=["unpushed commits", cred], verdict="unpushed commits", local_only_commits=3,
                          local_only_branches=[{"branch": "side", "count": 3}], local_only_tags=[{"tag": "v1", "count": 0}])
    tags = doc_checkout("/p/t", flags=["unpushed tags", cred], verdict="unpushed tags",
                        local_only_tags=[{"tag": "release", "count": 0}])
    text = section_3_2(mod.render(doc_scan([head, others, tags])))
    assert "push -u" not in text and "push origin" not in text, text
    for p, bundle in (("/p/h", "branch-main.bundle refs/heads/main"), ("/p/o", "local-only.bundle --all"), ("/p/t", "tags.bundle --tags")):
        row = next(r for r in text.splitlines() if r.startswith(f"| {p} "))
        assert f"git -C {p} bundle create <DEST>/checkouts/abs{p}/{bundle}` (origin url holds a credential or names a remote helper: no push until it is removed from the url; bundle instead)" in row, row
        assert "| yes: bundle it; a push would hand the credential-bearing origin url to the transport |" in row, row
    # without the flag the same records keep their push-or-bundle rows
    for co in (head, others, tags):
        co["flags"].remove(cred)
    text = section_3_2(mod.render(doc_scan([head, others, tags])))
    assert text.count("git -C /p/h -c core.hooksPath=/dev/null push -u origin") == 1 and text.count("git -C /p/o -c core.hooksPath=/dev/null push origin") == 2
    assert text.count("git -C /p/t -c core.hooksPath=/dev/null push origin --tags") == 1 and "holds a credential" not in text


def test_a_credential_bearing_origin_gets_no_push_row_without_remote(tmp_path):
    """Adversary round 39 on PR 27: the `not queried` flag is `--remote`-only, so a default scan of a checkout
    whose origin url holds a token still rendered `git push origin` rows; the record now carries
    `origin_credential` in every mode and the plan keys its gate on it."""
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    commit_file(work, "ahead.txt")
    git(work, "config", "remote.origin.url", "https://u:FAKE-SECRET@127.0.0.1:9/x.git")
    c = scan_one(mod, roots)
    assert c["origin_credential"] is True and mod.ORIGIN_CREDENTIAL not in c["flags"] and "unpushed commits" in c["flags"], c
    text = section_3_2(doc.render(doc_scan([c])))
    assert "push -u" not in text and "push origin" not in text and "FAKE-SECRET" not in text, text
    assert "refs/heads/main` (origin url holds a credential or names a remote helper: no push until it is removed from the url; bundle instead)" in text
    # round 39 LOW: the untracked row's "commit and push" advice goes too
    (work / "new.txt").write_text("n\n")
    text = section_3_2(doc.render(doc_scan([scan_one(mod, roots)])))
    assert "untracked.tar" in text and "commit and push" not in text and "push origin" not in text, text
    # an older record without the field keeps its push row
    c.pop("origin_credential")
    assert "push -u origin refs/heads/main:refs/heads/main" in section_3_2(doc.render(doc_scan([c])))
    # a plain url records False
    git(work, "config", "remote.origin.url", "https://127.0.0.1:9/x.git")
    assert scan_one(mod, roots)["origin_credential"] is False


def test_stash_capture_command_keeps_each_entry_index_tree(tmp_path):
    """Codex pass 31 on PR 27: `stash show -p` is base against the stashed worktree; a version staged in the index
    and then edited further survived only in the stash's second parent, which no patch kept."""
    mod = load_doc()
    repo = make_repo(tmp_path / "w")
    (repo / "a.txt").write_text("stage-only\n")
    git(repo, "add", "a.txt")
    (repo / "a.txt").write_text("worktree-only\n")
    git(repo, "stash", "push", "-m", "both")
    ck = mod.checkout_dir(str(repo))
    cmd = mod.STASH_FMT.format(*map(mod.shquote, mod.stash_values(str(repo), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        work = (tmp_path / "dest" / ck / "stash0.patch").read_text()
        index = (tmp_path / "dest" / ck / "stash0-index.patch").read_text()
        assert "worktree-only" in work and "stage-only" in index and "worktree-only" not in index
    # the documented restore: the index patch into the index, the worktree patch into the worktree
    git(repo, "apply", "--allow-empty", "--cached", str(tmp_path / "dest" / ck / "stash0-index.patch"))
    git(repo, "apply", "--allow-empty", str(tmp_path / "dest" / ck / "stash0.patch"))
    assert "stage-only" in git(repo, "diff", "--cached") and (repo / "a.txt").read_text() == "worktree-only\n"
    # adversary round 37: the ordinary stash (unstaged edits only) has an EMPTY index patch; without `--allow-empty`
    # the first `git apply` exits 128 and the `&&` skips the worktree patch that holds the edits
    git(repo, "reset", "--hard")
    (repo / "a.txt").write_text("plain\n")
    git(repo, "stash", "push", "-m", "plain")
    shutil.rmtree(tmp_path / "dest")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / "dest" / ck / "stash0-index.patch").stat().st_size == 0
    restore = (f"git -C {mod.shquote(str(repo))} apply --allow-empty --cached {tmp_path / 'dest' / ck}/stash0-index.patch "
               f"&& git -C {mod.shquote(str(repo))} apply --allow-empty {tmp_path / 'dest' / ck}/stash0.patch")
    run = subprocess.run(["bash", "-c", restore], capture_output=True, text=True, env=GIT_ENV)
    assert run.returncode == 0, run.stderr
    assert (repo / "a.txt").read_text() == "plain\n" and git(repo, "diff", "--cached") == ""


def test_a_live_origin_tag_whose_objects_are_missing_is_one_more_unfetched_tip(tmp_path):
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    git(other, "checkout", "main")
    commit_file(other, "tagged.txt")
    git(other, "tag", "-a", "-m", "v9", "v9")
    git(other, "push", "origin", "refs/tags/v9:refs/tags/v9")
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] != "clean and pushed" and "origin tips not fetched: 1" in c["flags"], c["flags"]
    assert c["local_only_verified"] is False
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert c["verdict"] == "clean and pushed" and c["local_only_verified"] is True, c["flags"]
    assert git(work, "tag", "--list").strip() == ""  # --fetch wrote no local tag


def test_ls_remote_reads_tags_and_their_peeled_commits(monkeypatch):
    mod = load()
    a, b, c = "a" * 40, "b" * 40, "c" * 40
    out = "\n".join([f"{a}\trefs/heads/main", f"{b}\trefs/tags/light", f"{c}\trefs/tags/ann",
                     f"{a}\trefs/tags/ann^{{}}", f"{b}\trefs/tags/orphan^{{}}", f"{b}\trefs/tags/bad:name",
                     f"{b}\trefs/other/x"]) + "\n"
    monkeypatch.setattr(mod, "run", lambda argv, **kw: (0, out))
    heads, tags, invalid = mod.ls_remote_refs("/nowhere")
    assert heads == {"main": a} and tags == {"light": (b, b), "ann": (c, a)} and invalid == 3


def test_a_relative_bigteam_root_is_stored_absolute(tmp_path, monkeypatch):
    """Adversary round 20, LOW 4b: the rows rendered from `root` must not depend on the scan's cwd."""
    mod = load()
    (tmp_path / "bt" / "t").mkdir(parents=True)
    (tmp_path / "bt" / "t" / "r-report.md").write_text("x\n")
    monkeypatch.chdir(tmp_path)
    res = mod.scan_bigteam(Path("bt"), [], [], 10_000, 1)
    assert res["root"] == str(tmp_path / "bt")
    res = mod.scan_bigteam(Path("bt/../bt/"), [], [], 10_000, 1)
    assert res["root"] == str(tmp_path / "bt")


def test_a_newline_in_a_path_is_ansi_c_quoted_in_every_generated_command():
    """Codex pass 15, P2 (4325359354): `esc()` turned the newline `shlex.quote` kept into a space."""
    mod = load_doc()
    assert mod.shquote("a\nb") == "$'a\\nb'" and mod.shquote(mod.Home("~/a\nb")) == "~/$'a\\nb'"
    assert mod.shquote("it's\r\t\\\x01") == "$'it\\'s\\r\\t\\\\\\x01'"
    assert mod.shquote("plain path") == "'plain path'"
    task = {"task": "t-nl", "verdict": "unique", "claim": "no CLAIM", "bytes": 1, "reports": [
        {"path": "a\nb-report.md", "bytes": 1, "done": False}], "open_job_records": [], "fills": [],
        "unique_bytes": 1, "referenced_in": [], "newest_mtime": 0}
    co = doc_checkout("/p/a\nb", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=1,
                      local_only_branches=[{"branch": "side", "count": 1}])
    text = mod.render(doc_scan([co], tasks=[task]))
    row = next(r for r in text.split("### 3.1")[1].split("### 3.2")[0].splitlines() if r.startswith("| t-nl "))
    assert "-- $'a\\nb-report.md')" in row and row.count("|") == 5
    rows = section_3_2(text).splitlines()
    row = next(r for r in rows if r.startswith("| /p/a\\nb "))  # esc: the newline is shown as text, never a space
    assert "git -C $'/p/a\\nb' -c core.hooksPath=/dev/null push origin refs/heads/side:refs/heads/side" in row
    assert not any(ln.startswith("b'") for ln in rows)  # no row was split at the newline
    with pytest.raises(ValueError):
        mod.code("{}", "a\nb")  # refused, never turned into a space
    assert mod.visible("a\nb\x01") == "a\\nb\\x01"


def test_the_section_1_heading_escapes_the_bigteam_root():
    """Adversary round 20, LOW 4a: a root with a backtick must not close the code span."""
    mod = load_doc()
    scan = doc_scan([], tasks=[])
    scan["bigteam"]["root"] = "/srv/bt`x"
    text = mod.render(scan)
    assert "## 1. bigteam (`` /srv/bt`x/<task>/ ``)" in text


def test_capture_plan_pushes_a_local_only_tag_by_its_full_ref_name():
    mod = load_doc()
    co = doc_checkout("/p/tg", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=2,
                      local_only_tags=[{"tag": "v1", "count": 1}, {"tag": "--force", "count": 1}])
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /p/tg "))
    assert "2 local-only commits on tag `v1` (1), tag `--force` (1)" in row
    assert "git -C /p/tg -c core.hooksPath=/dev/null push origin refs/tags/v1:refs/tags/v1" in row
    assert "push origin refs/tags/--force:refs/tags/--force" in row


def test_an_unreachable_origin_checkout_always_gets_a_capture_row_even_with_zero_counts():
    """Adversary round 21, 1: origin down, a pushed branch deleted there, the stale tracking ref hides the
    commits and the count is 0; the plan used to list nothing and call the checkout `clean and pushed`."""
    mod = load_doc()
    flag = "origin unreachable: local-only count unverified"
    gone = doc_checkout("/p/gone", flags=[flag], verdict=flag, local_only_verified=False)
    dirty = doc_checkout("/p/dirt", flags=[flag, "dirty"], verdict=flag, local_only_verified=False,
                         modified=2)
    side = doc_checkout("/p/side", flags=["unpushed commits", "local-only commits: side 1", flag],
                        verdict="unpushed commits", local_only_commits=1, local_only_verified=False,
                        local_only_branches=[{"branch": "side", "count": 1}])
    clean = doc_checkout("/p/clean", local_only_verified=True)
    text = mod.render(doc_scan([gone, dirty, side, clean]))
    rows = section_3_2(text).splitlines()
    row = next(r for r in rows if r.startswith("| /p/gone "))
    assert "local-only count unverified: origin did not answer" in row
    assert "mkdir -p <DEST>/checkouts/abs/p/gone && GIT_ADVICE=0 GIT_GRAFT_FILE=/dev/null GIT_NO_REPLACE_OBJECTS=1 git -C /p/gone bundle create " \
           "<DEST>/checkouts/abs/p/gone/local-only.bundle --all" in row
    assert "re-scan with `--remote` once origin answers" in row and row.rstrip().endswith("| yes: origin did not answer; bundle, or re-scan |")
    assert "local-only count unverified" in next(r for r in rows if r.startswith("| /p/dirt "))
    both = next(r for r in rows if r.startswith("| /p/side "))
    assert "local-only count unverified" in both and both.count("local-only.bundle") == 1
    assert not [r for r in rows if r.startswith("| /p/clean ")]
    assert "A checkout flagged `origin unreachable` is always listed, whatever its counts" in section_3_2(text)


def test_a_symlinked_submodule_config_is_skipped_not_trusted(tmp_path):
    """Codex pass 37 on PR 27, P1: `.git/modules/sub/config` as a symlink was skipped as safe, so the plan told the
    human to run git inside a submodule whose real config (the link's target) set core.fsmonitor."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    real = moddir / "config"
    target = tmp_path / "elsewhere-config"
    target.write_text(real.read_text() + "[core]\n\tfsmonitor = /bin/true\n")
    real.unlink()
    real.symlink_to(target)
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"] == "skipped: submodule config unrecognised (symlink)", c
    real.unlink()
    real.symlink_to(tmp_path)  # a link to a directory is no safer
    c = mod.scan_git([roots], remote=False)[0]
    assert c["verdict"] == "skipped: submodule config unrecognised (symlink)", c


def test_a_submodule_git_dir_read_elsewhere_is_skipped_not_trusted(tmp_path):
    """Codex pass 38 on PR 27 (P1) and adversary round 42 (MEDIUM): the walk read `modules/<sub>/config` only, so a
    symlinked module directory, a `config.worktree`, a `commondir` or a gitlink whose git dir is outside `modules/`
    passed as safe and the plan told the human to run git where a planted core.fsmonitor would run."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    bad = "[core]\n\tfsmonitor = /bin/true\n"

    def verdict():
        return next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))["verdict"]

    assert not verdict().startswith("skipped")
    # config.worktree: read once extensions.worktreeConfig (an allowlisted key) is set
    git(moddir, "config", "extensions.worktreeConfig", "true")
    (moddir / "config.worktree").write_text(bad)
    assert verdict() == "skipped: submodule config unrecognised core.fsmonitor"
    (moddir / "config.worktree").unlink()
    git(moddir, "config", "--unset", "extensions.worktreeConfig")
    # commondir: the module's config and objects live in another directory
    (moddir / "commondir").write_text("../../../elsewhere\n")
    assert verdict() == "skipped: submodule config unrecognised (commondir)"
    (moddir / "commondir").unlink()
    # a symlinked module directory: os.walk never descends into it
    target = tmp_path / "elsewhere-module"
    moddir.rename(target)
    moddir.symlink_to(target)
    assert verdict() == "skipped: submodule config unrecognised (symlink)"
    moddir.unlink()
    target.rename(moddir)
    # a gitlink whose `.git` is a gitfile pointing outside modules/, a directory (an unabsorbed submodule), a symlink
    gitfile = sup / "sub" / ".git"
    original = gitfile.read_text()
    gitfile.write_text(f"gitdir: {tmp_path / 'elsewhere-gitdir'}\n")
    assert verdict() == "skipped: submodule config unrecognised (gitdir outside modules)"
    gitfile.unlink()
    gitfile.mkdir()
    assert verdict() == "skipped: submodule config unrecognised (gitdir outside modules)"
    gitfile.rmdir()
    gitfile.symlink_to(moddir)
    assert verdict() == "skipped: submodule config unrecognised (symlink)"
    gitfile.unlink()
    gitfile.write_text("not a gitfile\n")
    assert verdict() == "skipped: submodule config unrecognised (gitdir unreadable)"
    gitfile.write_text(original)
    assert not verdict().startswith("skipped")
    # adversary round 43 (MEDIUM): git reads the WHOLE gitfile after `gitdir: `, the scanner read its first line, so
    # a second line (or a form feed, which `splitlines` also splits on) named a vetted dir to the scanner and another
    # to git; a gitfile into a module dir's pruned `objects/` passed the `modules/` prefix test without a config read
    gitfile.write_bytes(original.encode().rstrip(b"\n") + b"\n/../../../../../evil\n")
    assert verdict() == "skipped: submodule config unrecognised (gitdir unreadable)"
    gitfile.write_bytes(original.encode().rstrip(b"\n") + b"\x0c/x\n")
    assert verdict().startswith("skipped: submodule config unrecognised (gitdir ")
    # round 44 (LOW): git stops at a NUL and uses the path before it; `realpath` once raised and aborted the scan
    gitfile.write_bytes(b"gitdir: " + str(tmp_path / "evil").encode() + b"\0../.git/modules/sub\n")
    assert verdict() == "skipped: submodule config unrecognised (gitdir unreadable)"
    gitfile.write_bytes(original.encode().rstrip(b"\n") + b"\r\n")  # a CRLF ending is what git accepts
    assert not verdict().startswith("skipped")
    (moddir / "objects" / "evil").mkdir()
    gitfile.write_text("gitdir: ../.git/modules/sub/objects/evil\n")
    assert verdict() == "skipped: submodule config unrecognised (gitdir outside modules)"
    gitfile.write_text(original)
    # round 44 (MEDIUM 1.2, 1.3): a case-insensitive file system opens `CONFIG` as `config` and `Commondir` as
    # `commondir`, names the exact-name walk never read
    (moddir / "config").rename(moddir / "CONFIG")
    assert verdict() == "skipped: submodule config unrecognised (unrecognised entry)"
    (moddir / "CONFIG").rename(moddir / "config")
    (moddir / "Commondir").write_text("../../evil\n")
    assert verdict() == "skipped: submodule config unrecognised (unrecognised entry)"
    (moddir / "Commondir").unlink()
    assert not verdict().startswith("skipped")
    # round 45 (MEDIUM 1): APFS folds the `ﬁ` ligature to `fi`, which `str.lower` does not, so `conﬁg` opened as
    # `config`; the check now asks the file system for the exact name. A case-sensitive file system (Linux CI) does
    # not open it, and git does not read it there either
    (moddir / "config").rename(moddir / "con\ufb01g")
    if (moddir / "config").exists():
        assert verdict() == "skipped: submodule config unrecognised (unrecognised entry)"
    (moddir / "con\ufb01g").rename(moddir / "config")
    assert (moddir / "config").is_file() and not verdict().startswith("skipped")
    # round 44 (MEDIUM 1.1): a gitlink whose work-tree entry is a symlink: `git -C <sup>/sub` would run in a
    # repository the walk never vetted
    elsewhere = make_repo(tmp_path / "elsewhere")
    (sup / "sub").rename(tmp_path / "sub-aside")
    (sup / "sub").symlink_to(elsewhere)
    assert verdict() == "skipped: submodule config unrecognised (symlink)"
    (sup / "sub").unlink()
    (tmp_path / "sub-aside").rename(sup / "sub")
    assert not verdict().startswith("skipped")
    # a `.gitmodules` path that is not an index gitlink (the plan's listing reads `.gitmodules`): an ordinary nested
    # repository there would get the plan's by-hand git commands without any vetting
    gitmodules = (sup / ".gitmodules").read_text()
    (sup / ".gitmodules").write_text(gitmodules + '[submodule "nested"]\n\tpath = nested\n\turl = ./nested\n')
    (sup / "nested").mkdir()
    git(sup / "nested", "init", "-q")
    assert verdict() == "skipped: submodule config unrecognised (gitmodules path not a gitlink)"
    shutil.rmtree(sup / "nested")
    assert not verdict().startswith("skipped")  # listed, nothing there: the plan's guard refuses it
    # round 44 (MEDIUM 1.1): `l/../nested` is `nested` to normpath but `a/b/../nested` to the kernel when `l` is a
    # symlink, so a listed path that holds `..`, is absolute or is empty is refused before any lookup
    for unusual in ("l/../nested", str(tmp_path / "abs"), ""):
        (sup / ".gitmodules").write_text(gitmodules + f'[submodule "x"]\n\tpath = {unusual}\n\turl = ./x\n')
        assert verdict() == "skipped: submodule config unrecognised (gitmodules path unusual)", unusual
    (sup / ".gitmodules").write_text(gitmodules)
    assert not verdict().startswith("skipped")
    # round 45 (MEDIUM 2): the plan's listing of `.gitmodules` prints keys and values raw, so a value holding a newline
    # (git config's `\n` escape in a quoted value) or a subsection holding ESC and CR shows the human a second path the
    # scan never vetted
    for entry in ('[submodule "x"]\n\tpath = "x\\nsubmodule.evil.path a/nested"\n\turl = ./x\n',
                  '[submodule "a\x1b[2K\rsubmodule.evil"]\n\tpath = y\n\turl = ./y\n',
                  '[submodule "z"]\n\tpath = y\u202e/detsen\n\turl = ./y\n',  # a bidi override redraws the path
                  '[submodule "z"]\n\tpath = y\u200b\n\turl = ./y\n'):  # a zero-width space is invisible
        (sup / ".gitmodules").write_text(gitmodules + entry)
        assert verdict() == "skipped: submodule config unrecognised (gitmodules path unusual)", entry
    (sup / ".gitmodules").write_bytes(gitmodules.encode() + b'[submodule "z"]\n\tpath = y\x85\n\turl = ./y\n')  # a C1 byte, not UTF-8
    assert verdict() == "skipped: submodule config unrecognised (gitmodules path unusual)"
    (sup / ".gitmodules").write_text(gitmodules)
    assert not verdict().startswith("skipped")
    # a de-initialised submodule (no `.git` at all, an empty directory) runs nothing here: the plan's guard covers it
    git(sup, "submodule", "deinit", "-f", "sub")
    assert not (sup / "sub" / ".git").exists() and not verdict().startswith("skipped")
    # round 43 (LOW): files there with no `.git` would be in no capture; the checkout is skipped so the whole-directory
    # archive keeps them
    (sup / "sub" / "left-behind.txt").write_text("edited\n")
    assert verdict() == "skipped: submodule config unrecognised (submodule has files but no .git)"


def test_a_skip_worktree_path_with_a_non_utf8_name_is_counted(tmp_path):
    """Codex pass 38 on PR 27, P1: git's output was decoded with replacement characters, so the existence test for
    a skip-worktree entry whose name is not UTF-8 looked at a different path and dropped its edit."""
    mod = load()
    repo = make_repo(tmp_path / "r")
    name = os.fsdecode(b"\xff-hidden.txt")
    try:
        (repo / name).write_text("committed\n")
    except (OSError, UnicodeEncodeError):
        pytest.skip("this filesystem refuses a non-UTF-8 file name")
    git(repo, "add", "--", name)
    git(repo, "commit", "-q", "-m", "non-utf8 name")
    git(repo, "update-index", "--skip-worktree", "--", name)
    (repo / name).write_text("hidden edit\n")
    assert git(repo, "status", "--porcelain") == ""
    c = mod.scan_checkout(repo, remote=False)
    assert c["index_hidden"] == 1 and "index-hidden paths: 1" in c["flags"], c


def test_the_submodule_row_refuses_a_deinitialised_submodule_and_archives_its_git_dir(tmp_path):
    """Adversary round 42 on PR 27 (MEDIUM): with the submodule de-initialised (an empty directory) every command of
    the row ran against the superproject at rc 0, and the module git dir's unpushed commits were in no capture."""
    import tarfile
    doc = load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    (sup / "sub" / "g.txt").write_text("unpushed\n")
    git(sup / "sub", "add", "g.txt")
    git(sup / "sub", "commit", "-q", "-m", "unpushed-sub-commit")
    sha = git(sup / "sub", "rev-parse", "HEAD").strip()
    git(sup, "submodule", "deinit", "-f", "sub")
    assert not (sup / "sub" / ".git").exists() and (moddir / "HEAD").is_file()
    prefix = PLAN_PREFIX
    dest = str(tmp_path / "dest")
    raw = str(sup)
    # the scan itself no longer lists the de-initialised path: the row has no per-submodule command for it
    rec = load().scan_checkout(sup, remote=False)
    assert rec["submodules_vetted"] == [] and "submodules not inspected" in rec["flags"], rec
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "no submodule is checked out" in row and "{ [ -e" not in row and "<sub>" not in row
    # and a record that does list it (the submodule was removed after the scan) still fails each command, saying so
    for span in doc.submodule_commands(raw, "c", "sub"):
        cmd = prefix + unmark(span).replace("<DEST>", dest)
        run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        assert run.returncode != 0 and run.stdout == "", (cmd, run.stdout, run.stderr)
        assert "submodule sub: not a checked-out submodule (skipped)" in run.stderr, run.stderr
    assert not (tmp_path / "dest").exists()
    cmd = prefix + doc.MODULES_FMT.format(*map(doc.shquote, doc.modules_values(raw, "c"))).replace("<DEST>", dest)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    names = tarfile.open(tmp_path / "dest" / "c" / "modules.tar").getnames()
    assert "modules/sub/HEAD" in names and f"modules/sub/objects/{sha[:2]}/{sha[2:]}" in names, names
    assert doc.MODULES_FMT.count("{}") == len(doc.modules_values("/p", "c"))


def test_the_modified_row_packs_unmerged_index_blobs(tmp_path):
    """Codex pass 39 on PR 27, P1: an unmerged entry's stage-2/3 blobs reachable from no ref were in no patch
    (`Binary files differ`, `* Unmerged path`), the tar keeps the worktree file only, and the index copy names
    objects the deleted checkout no longer has."""
    import tarfile
    doc = load_doc()
    repo = make_repo(tmp_path / "r")

    def blob(data: bytes) -> str:
        p = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, env=GIT_ENV, input=data, capture_output=True)
        assert p.returncode == 0, p.stderr
        return p.stdout.decode().strip()

    ours, theirs = blob(b"\x00ours\n"), blob(b"\x00theirs\n")
    p = subprocess.run(["git", "update-index", "--index-info"], cwd=repo, env=GIT_ENV, capture_output=True,
                       input=f"100644 {ours} 2\tb.bin\n100644 {theirs} 3\tb.bin\n".encode())
    assert p.returncode == 0, p.stderr
    (repo / "b.bin").write_bytes(b"\x00work\n")
    assert git(repo, "ls-files", "-u").count("b.bin") == 2
    assert ours not in git(repo, "rev-list", "--objects", "--all")  # reachable from no ref: only the pack keeps it
    ck = doc.checkout_dir(str(repo))
    prefix = PLAN_PREFIX
    cmd = prefix + doc.modified_fmt().format(*map(doc.shquote, doc.modified_values(str(repo), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        assert sorted((tmp_path / "dest" / ck / "unmerged.ids").read_text().split()) == sorted([ours, theirs])
        idx = list((tmp_path / "dest" / ck).glob("unmerged-*.idx"))
        assert len(idx) == 1, idx
        packed = git(repo, "verify-pack", "-v", str(idx[0]))
        assert ours in packed and theirs in packed
    # no unmerged entry: an empty list, an empty pack, rc 0 (every dirty checkout runs this row)
    git(repo, "reset", "-q", "--", "b.bin")
    (repo / "b.bin").unlink()
    shutil.rmtree(tmp_path / "dest", ignore_errors=True)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / "dest" / ck / "unmerged.ids").read_text() == ""
    assert len(list((tmp_path / "dest" / ck).glob("unmerged-*.pack"))) == 1
    assert doc.modified_fmt().count("{}") == len(doc.modified_values("/p", "c"))


def test_a_gitfile_with_a_second_line_is_refused_by_the_gitdir_capture(tmp_path):
    """Adversary round 43 on PR 27 (INFO, with MEDIUM 1.1): git takes the whole gitfile after `gitdir: `, the row's
    `read` took its first line, so a crafted second line made the row archive a decoy directory."""
    mod = load_doc()
    main = make_repo(tmp_path / "main")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", str(wt), "-b", "side")
    ck = mod.checkout_dir(str(wt))
    prefix = PLAN_PREFIX
    cmd = prefix + mod.GITDIR_FMT.format(*map(mod.shquote, mod.gitdir_values(str(wt), ck))).replace("<DEST>", str(tmp_path / "dest"))
    one_line = (wt / ".git").read_bytes()
    (wt / ".git").write_bytes(one_line.rstrip(b"\n") + b"\n/../../../../decoy\n")
    for shell in ("bash", "zsh"):  # the preamble is bash/zsh (`<<<`)
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        (tmp_path / "dest" / ck).mkdir(parents=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode != 0 and "gitdir capture FAILED" in run.stderr, (shell, run.stderr)
        assert not list((tmp_path / "dest" / ck).iterdir())
    (wt / ".git").write_bytes(one_line.rstrip(b"\n"))  # one line, no final newline: still accepted
    shutil.rmtree(tmp_path / "dest", ignore_errors=True)
    (tmp_path / "dest" / ck).mkdir(parents=True)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (tmp_path / "dest" / ck / "gitdir.tar").is_file()
    assert mod.GITDIR_FMT.count("{}") == len(mod.gitdir_values("/p", "c"))


def test_a_symlinked_git_entry_row_archives_the_links_target(tmp_path):
    """Adversary round 43 on PR 27 (LOW): the `skipped: .git is a symlink` row's whole-directory archive kept the link
    itself and GITDIR_FMT (`-f`) archived nothing, so a local commit behind the link was in no capture."""
    import tarfile
    doc = load_doc()
    flag = "skipped: .git is a symlink"
    rows = section_3_2(doc.render(doc_scan([doc_checkout("/p/l", flags=[flag], verdict=flag)]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/l "))
    assert "the `.git` symlink's target holds the history" in row
    assert ('g=/p/l/.git && [ -f "$g/HEAD" ] && c=$g && if [ -f "$g/commondir" ]; then { IFS= read -r c || [ -n "$c" ]; } < "$g/commondir" '
            "&& c=${c%$'\\r'} && case \"$c\" in /*) ;; *) c=\"$g/$c\" ;; esac; fi "
            '&& [ -d "$c/objects" ] && [ -d "$c/refs" ] && TAR_OPTIONS= "$GTAR" -C "$g" -cf <DEST>/checkouts/abs/p/l/gitdir.tar . '
            '&& if [ -f "$g/commondir" ]; then TAR_OPTIONS= "$GTAR" -C "$c" -cf <DEST>/checkouts/abs/p/l/commondir.tar .; fi') in row.replace("\\|", "|")
    real = make_repo(tmp_path / "real")
    gd = tmp_path / "gitdirs-r.git"
    (real / ".git").rename(gd)
    (real / ".git").symlink_to(gd)
    ck = doc.checkout_dir(str(real))
    prefix = PLAN_PREFIX
    cmd = prefix + doc.SYMLINK_GITDIR_FMT.format(*map(doc.shquote, (str(real), f"{ck}/gitdir.tar", f"{ck}/commondir.tar"))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):  # the preamble is bash/zsh (`<<<`)
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        (tmp_path / "dest" / ck).mkdir(parents=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        names = set(tarfile.open(tmp_path / "dest" / ck / "gitdir.tar").getnames())
        assert "./HEAD" in names and any(n.startswith("./objects/") for n in names), names
    # a link to a file (a gitfile elsewhere) or to a plain directory is no git directory: loud, nothing archived
    for target in (gd / "HEAD", tmp_path):
        (real / ".git").unlink()
        (real / ".git").symlink_to(target)
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        (tmp_path / "dest" / ck).mkdir(parents=True)
        run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        assert run.returncode != 0 and "gitdir capture FAILED" in run.stderr, run.stderr
        assert not list((tmp_path / "dest" / ck).iterdir())
    # Codex pass 45: a link to a linked worktree's administration directory (`HEAD` and `commondir`, no objects or refs of its
    # own) archives that directory and the common directory
    main = make_repo(tmp_path / "main")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", "--detach", str(wt))
    admin = next((main / ".git" / "worktrees").iterdir())
    (wt / ".git").unlink()
    (wt / ".git").symlink_to(admin)
    ck2 = doc.checkout_dir(str(wt))
    cmd2 = prefix + doc.SYMLINK_GITDIR_FMT.format(*map(doc.shquote, (str(wt), f"{ck2}/gitdir.tar", f"{ck2}/commondir.tar"))).replace("<DEST>", str(tmp_path / "dest2"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest2", ignore_errors=True)
        (tmp_path / "dest2" / ck2).mkdir(parents=True)
        run = subprocess.run([shell, "-c", cmd2], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        assert "./HEAD" in tarfile.open(tmp_path / "dest2" / ck2 / "gitdir.tar").getnames()
        common = set(tarfile.open(tmp_path / "dest2" / ck2 / "commondir.tar").getnames())
        assert any(n.startswith("./objects/") for n in common) and any(n.startswith("./refs") for n in common), common
    # a commondir naming a directory that is no git directory archives nothing, loudly
    (admin / "commondir").write_text(str(tmp_path) + "\n")
    shutil.rmtree(tmp_path / "dest2", ignore_errors=True)
    (tmp_path / "dest2" / ck2).mkdir(parents=True)
    run = subprocess.run(["bash", "-c", cmd2], capture_output=True, text=True)
    assert run.returncode != 0 and "gitdir capture FAILED" in run.stderr, run.stderr
    assert not list((tmp_path / "dest2" / ck2).iterdir())


def test_every_archive_ignores_the_operators_tar_options(tmp_path):
    """Codex pass 37 on PR 27, P1: with `TAR_OPTIONS=--exclude=*` in the environment GNU tar wrote an empty
    untracked archive and exited 0; every emitted tar now runs with `TAR_OPTIONS=` cleared."""
    import re, tarfile
    doc = load_doc()
    src = (Path(__file__).resolve().parent.parent / "bin" / "ade-scan-state-doc").read_text(encoding="utf-8")
    assert src.count("$GTAR") == len(re.findall(r'TAR_OPTIONS= (?:LC_ALL=C )?\\"\$GTAR', src)), "a tar call without TAR_OPTIONS="
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "u.txt").write_text("untracked\n")
    prefix = PLAN_PREFIX
    cmd = prefix + doc.UNTRACKED_FMT.format(*map(doc.shquote, doc.untracked_values(str(repo), "c"))).replace("<DEST>", str(tmp_path / "dest"))
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env={**os.environ, "TAR_OPTIONS": "--exclude=*"})
    assert run.returncode == 0, run.stderr
    assert tarfile.open(tmp_path / "dest" / "c" / "untracked.tar").getnames() == ["u.txt"]
    assert doc.UNTRACKED_FMT.count("{}") == len(doc.untracked_values("/p", "c"))


def test_the_submodule_row_archives_an_index_hidden_edit(tmp_path):
    """Codex pass 36 on PR 27, P1: inside a submodule an assume-unchanged edit is in no status, diff, `ls-files
    --modified` or `--others` output, so the submodule row's bundle, patches and untracked archive all missed it."""
    import tarfile
    doc = load_doc()
    sup = tmp_path / "sup"
    sub = sup / "sub"
    sub.mkdir(parents=True)
    git(sub, "init", "-q")
    (sub / "a.txt").write_text("committed\n")
    git(sub, "add", "a.txt")
    git(sub, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "one")
    (sub / "a.txt").write_text("hidden edit\n")
    git(sub, "update-index", "--assume-unchanged", "a.txt")
    assert git(sub, "status", "--porcelain") == "" and git(sub, "ls-files", "--modified") == ""
    prefix = PLAN_PREFIX
    cmd = prefix + unmark(doc.submodule_commands(str(sup), "c", "sub")[4]).replace("<DEST>", str(tmp_path / "dest"))
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    tar = tarfile.open(tmp_path / "dest" / "c" / "submodules" / "sub" / "hidden.tar")
    assert "a.txt" in tar.getnames() and tar.extractfile("a.txt").read() == b"hidden edit\n", tar.getnames()


def test_a_checkout_with_submodules_always_gets_a_capture_row():
    """Codex pass 18 on PR 27, P1: every count is 0 for a superproject whose only work is inside a submodule;
    the plan listed nothing and discovery never reaches the submodule."""
    mod = load_doc()
    flag = "submodules not inspected"
    quiet = doc_checkout("/p/sup", flags=[flag], verdict=flag, submodules_vetted=["sub"])
    dirty = doc_checkout("/p/both", flags=["dirty", flag], verdict="dirty", modified=1)
    text = mod.render(doc_scan([quiet, dirty, doc_checkout("/p/clean")]))
    rows = section_3_2(text).splitlines()
    row = next(r for r in rows if r.startswith("| /p/sup "))
    row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
    assert "submodules not inspected: their modified, untracked or unpushed content is in no count here" in row
    # adversary rounds 43-46: no `<sub>` template and no `.gitmodules` listing for the human to read and paste back
    assert "<sub>" not in row and "--get-regexp" not in row and "list them with" not in row
    sp, d = "/p/sup/sub", "<DEST>/checkouts/abs/p/sup/submodules/sub"
    guard = "{ [ -e /p/sup/sub/.git ] || { printf '%s\\n' 'submodule sub: not a checked-out submodule (skipped)' >&2; false; }; } && "
    assert f"git -C {sp} status --porcelain" in row and f"git -C {sp} log --oneline --branches --tags --not --remotes" in row
    assert f"git -C {sp} bundle create {d}/all.bundle --all" in row
    # Codex pass 26: a bundle holds commits only; the dirty worktree needs the patches and the untracked archive
    assert f"git -C {sp} diff --no-ext-diff --no-textconv --no-color --binary > {d}/modified.patch" in row
    assert f"git -C {sp} diff --no-ext-diff --no-textconv --no-color --binary --cached > {d}/staged.patch" in row
    assert f"-C {sp} --null --no-recursion --ignore-failed-read -T {d}/modified.list" in row  # Codex pass 30
    assert f'"$(git -C {sp} rev-parse --absolute-git-dir)/index" {d}/index' in row
    # Codex pass 36: an assume-unchanged or skip-worktree edit inside the submodule needs the index-hidden archive too
    assert f"git -C {sp} ls-files -z -v > {d}/hidden.raw" in row
    assert f"-C {sp} --null --no-recursion --ignore-failed-read -T {d}/hidden.list" in row
    assert mod.modified_fmt().count("{}") == len(mod.modified_values("/p", "c"))
    assert mod.HIDDEN_FMT.count("{}") == len(mod.hidden_values("/p", "c"))
    assert (f"git -C {sp} ls-files -z --others --exclude-standard > {d}/untracked.list "
            f"&& TAR_OPTIONS= \"$GTAR\" -C {sp} --null --no-recursion -T {d}/untracked.list -cf {d}/untracked.tar") in row
    assert "the scanner skips absorbed submodules" in row
    # adversary round 42: a de-initialised submodule is an empty directory; every command is gated on its `.git`,
    # and the module git dirs are archived
    assert row.count(guard) == 6
    assert guard + f"git -C {sp} status --porcelain" in row
    assert guard + f"git -C {sp} log --oneline" in row
    assert guard + f"mkdir -p {d} && GIT_ADVICE=0" in row
    assert guard + f"mkdir -p {d} && git -C {sp} diff" in row
    assert guard + f"mkdir -p {d} && git -C {sp} ls-files -z -v" in row
    assert guard + f"mkdir -p {d} && git -C {sp} ls-files -z --others" in row
    assert ("mkdir -p <DEST>/checkouts/abs/p/sup && d=$(git -C /p/sup rev-parse --git-common-dir) && TAR_OPTIONS= \"$GTAR\" "
            "-cf <DEST>/checkouts/abs/p/sup/modules.tar -C /p/sup -C \"$d\" modules") in row
    assert row.count("modules.tar") == 1  # once per superproject, not per submodule
    both = next(r for r in rows if r.startswith("| /p/both "))
    assert "1 modified tracked file(s)" in both and "submodules not inspected" in both
    assert both.rstrip().endswith("| yes: decide whether they are work |")
    assert not [r for r in rows if r.startswith("| /p/clean ")]
    assert "A checkout flagged `submodules not inspected` is always listed too" in section_3_2(text)
    # adversary round 25 (MEDIUM): the by-hand commands went through code(), not shcode(); a path shaped like a
    # shell expansion ran when pasted
    evil = doc_checkout("/p/sub$(touch PWNED_SUB)", flags=[flag], verdict=flag, submodules_vetted=["sub"])
    rows = section_3_2(mod.render(doc_scan([evil]))).splitlines()
    row = next(r for r in rows if r.startswith("| /p/sub"))
    row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
    plain = row.replace("\\$", "$").replace("\\(", "(").replace("\\)", ")")
    assert "git -C '/p/sub$(touch PWNED_SUB)/sub' status --porcelain" in plain
    assert "git -C '/p/sub$(touch PWNED_SUB)/sub' log --oneline" in plain
    assert "git -C '/p/sub$(touch PWNED_SUB)/sub' bundle create" in plain
    assert "-C /p/sub$(touch" not in plain
    # round 25 (LOW): a basename starting with `-` was read by tar as an option; `--` ends the options
    dash = doc_checkout("/p/-opt", flags=["scan incomplete: status rc=124"], verdict="scan incomplete: status rc=124",
                        modified=None, untracked=None, unpushed=None, ahead_of_origin=None, stashes=None,
                        local_only_commits=None, on_origin=None)
    row = next(r for r in section_3_2(mod.render(doc_scan([dash]))).splitlines() if r.startswith("| /p/-opt "))
    row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
    assert "-cf <DEST>/checkouts/abs/p/-opt/whole.tar -- -opt" in row


def test_the_submodule_row_renders_quoted_commands_for_each_vetted_path_only(tmp_path):
    """Adversary rounds 43-46 on PR 27 (MEDIUM, four times): the row was a template (`<sub>`, unquoted) plus a listing of
    `.gitmodules` for the human to read and paste back, so a subsection name with spaces spoofed the listing and a
    value with `$(...)`, a backtick, `;` or a glob ran a command or reached an unvetted repository's
    `core.fsmonitor`. The scan now records the vetted paths and the row names each one, quoted; every hostile entry
    either refuses the checkout or leaves `sub` the only path with commands, and every command of the row runs in bash,
    zsh and sh without a marker or a PWNED file."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    marker = tmp_path / "MARKER"
    script = marker_script(tmp_path / "fsm.sh", marker)
    for name in ("a/nested", "xnested"):
        nested = make_repo(sup / name)
        git(nested, "config", "core.fsmonitor", str(script))
    (sup / ".gitignore").write_text("a/\nxnested/\n")
    git(sup / "a" / "nested", "status", "--porcelain")
    if not marker.exists():
        pytest.skip("this git does not run core.fsmonitor on `status`; nothing to guard")
    marker.unlink()
    base = (sup / ".gitmodules").read_text()
    hostile = {
        "spaced key": '[submodule "x.path a/nested' + " " * 300 + 'submodule.y"]\n\tpath = zzz\n\turl = ./zzz\n',
        "dollar": '[submodule "d"]\n\tpath = "$(touch PWNED-dollar)"\n\turl = ./d\n',
        "backtick": '[submodule "b"]\n\tpath = "`touch PWNED-bt`"\n\turl = ./b\n',
        "semicolon": '[submodule "s"]\n\tpath = "x;touch PWNED-semi"\n\turl = ./s\n',
        "glob": '[submodule "g"]\n\tpath = "x*"\n\turl = ./g\n',
        "word joiner": '[submodule "w"]\n\tpath = "a\u2060/nested"\n\turl = ./w\n',
        "none": "",
    }
    rendered = []
    for label, entry in hostile.items():
        (sup / ".gitmodules").write_text(base + entry)
        rec = next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))
        if rec["verdict"].startswith("skipped"):
            assert rec["verdict"] == "skipped: submodule config unrecognised (gitmodules path unusual)", (label, rec["verdict"])
            continue
        rendered.append(label)
        assert rec["submodules_vetted"] == ["sub"], (label, rec["submodules_vetted"])
        text = doc.render(doc_scan([rec]))
        row = next(r for r in section_3_2(text).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
        cmds = plan_commands(row)
        assert len(cmds) == 7 and sum(c.startswith("{ [ -e ") for c in cmds) == 6, (label, cmds)
        assert "<sub>" not in row and "--get-regexp" not in row
        ck = doc.checkout_dir(rec["path"])
        for shell in SHELLS:
            dest = tmp_path / f"dest-{label.replace(' ', '-')}-{shell}"
            for cmd in cmds:
                run = run_plan(shell, cmd, dest, tmp_path)
                assert run.returncode == 0, (shell, label, cmd, run.stderr)
            for name in ("all.bundle", "modified.patch", "staged.patch", "hidden.tar", "untracked.tar"):
                assert (dest / ck / "submodules" / "sub" / name).is_file(), (shell, label, name)
            assert (dest / ck / "modules.tar").is_file()
        assert not list(tmp_path.rglob("PWNED*")) and not marker.exists(), label
    assert "none" in rendered and "spaced key" not in rendered and "word joiner" not in rendered


def test_a_submodule_path_with_a_space_a_quote_or_an_invisible_character_skips_the_checkout(tmp_path):
    """Round 46 on PR 27 (MEDIUM 1, LOW 3): a path git accepts but a person cannot read or retype as it is
    (a space, either quote, a no-break space, a word joiner) is `(gitmodules path unusual)`, whether `.gitmodules`
    lists it or only the index holds the gitlink."""
    mod = load()
    for i, name in enumerate(("my sub", "it's", 'say"hi', "a\u00a0b", "a\u2060b")):
        base = tmp_path / f"c{i}"
        origin = make_repo(base / "origin", "f.txt")
        sup = make_repo(base / "roots" / "super")
        p = subprocess.run(["git", "-c", "protocol.file.allow=always", "submodule", "add", str(origin), name],
                           cwd=sup, env=GIT_ENV, capture_output=True, text=True)
        assert p.returncode == 0, (name, p.stderr)
        git(sup, "commit", "-m", "add submodule")
        rec = mod.scan_checkout(sup, remote=False)
        assert rec["verdict"] == "skipped: submodule config unrecognised (gitmodules path unusual)", (name, rec["verdict"])
        assert rec.get("submodules_vetted") is None
        # the index alone: a gitlink the `.gitmodules` file does not list
        (sup / ".gitmodules").write_text('[submodule "other"]\n\tpath = other\n\turl = ./other\n')
        assert mod.scan_checkout(sup, remote=False)["verdict"] == rec["verdict"], name


def test_a_non_utf8_gitlink_path_is_refused_and_never_reaches_the_record(tmp_path):
    """The index holds raw bytes: a path that is not UTF-8 decodes (surrogateescape) to a lone surrogate, which
    `json.dump` cannot write as UTF-8; it is `(gitmodules path unusual)`, never a `submodules_vetted` entry."""
    mod = load()
    repo = make_repo(tmp_path / "roots" / "r")
    sha = git(repo, "rev-parse", "HEAD").strip()
    name = os.fsdecode(b"\xff-sub")
    p = subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"160000,{sha},{name}"], cwd=repo, env=GIT_ENV,
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    (repo / ".gitmodules").write_text('[submodule "x"]\n\tpath = x\n\turl = ./x\n')
    rec = mod.scan_checkout(repo, remote=False)
    assert rec["verdict"] == "skipped: submodule config unrecognised (gitmodules path unusual)", rec["verdict"]
    assert rec.get("submodules_vetted") is None
    json.dumps(rec, ensure_ascii=False).encode("utf-8")


def test_unusual_char_covers_the_invisible_and_space_classes_of_round_46():
    """Round 46 (LOW 3): word joiner, soft hyphen, CGJ, the Hangul fillers, variation selectors, tags, interlinear
    annotation, any space, and the categories Cf, Co, Cn, Zs, Zl, Zp; ordinary text in any script stays."""
    mod = load()
    refused = [0x20, 0x09, 0x0A, 0xA0, 0xAD, 0x34F, 0x115F, 0x1160, 0x180E, 0x2002, 0x200D, 0x2028, 0x2029, *range(0x2060, 0x2070),
               0x3164, *range(0xFE00, 0xFE10), 0xFFA0, 0xFFF9, 0xFFFA, 0xFFFB, 0xE000, 0x0378, 0xE0000, 0xE0020, 0xE007F,
               0xE0100, 0xE01EF, 0xD800]
    for o in refused:
        assert mod.unusual_char(chr(o)), hex(o)
    for ch in "aZ09-_./~é日한" + "\u0928\u093f":
        assert not mod.unusual_char(ch), hex(ord(ch))
    assert mod.unusual_path("a b") and mod.unusual_path("it's") and mod.unusual_path('a"b') and not mod.unusual_path("dir/sub-1.x")


def test_a_vetted_path_with_shell_and_markdown_metacharacters_is_quoted_in_every_command(tmp_path):
    """The path the record names is the only value the row carries; a real directory named like an injection runs
    nothing and gets its own destination below `submodules/`."""
    doc = load_doc()
    weird = "w $(touch PWNED-q) 'x\"y;* a|b&c<d>`bt`"
    sup = tmp_path / "sup"
    nested = make_repo(sup / weird)
    (nested / "u.txt").write_text("untracked\n")
    cmds = [unmark(s) for s in doc.submodule_commands(str(sup), "c", weird)]
    assert len(cmds) == 6 and all(c.startswith("{ [ -e ") for c in cmds)
    for shell in SHELLS:
        dest = tmp_path / f"dest-{shell}"
        for cmd in cmds:
            run = run_plan(shell, cmd, dest, tmp_path)
            assert run.returncode == 0, (shell, cmd, run.stderr)
        got = dest / "c" / "submodules" / weird
        assert (got / "all.bundle").is_file() and (got / "hidden.tar").is_file(), (shell, list(dest.rglob("*")))
    assert not list(tmp_path.rglob("PWNED*"))


def test_a_record_without_submodules_vetted_renders_the_rescan_note_and_no_per_submodule_command():
    """An older scan JSON has no list of vetted paths: the row names none and says to re-scan; an empty list from this
    version says no submodule is checked out. Either way the `modules/` archive stays."""
    doc = load_doc()
    flag = "submodules not inspected"
    archive = "d=$(git -C /p/sup rev-parse --git-common-dir)"
    old = doc_checkout("/p/sup", flags=[flag], verdict=flag)
    row = next(r for r in section_3_2(doc.render(doc_scan([old]))).splitlines() if r.startswith("| /p/sup "))
    assert "re-scan with this version to get per-submodule commands" in row and archive in row
    for gone in ("{ [ -e", "status --porcelain", "<sub>", "--get-regexp", "submodules/"):
        assert gone not in row, gone
    none = doc_checkout("/p/sup", flags=[flag], verdict=flag, submodules_vetted=[])
    row = next(r for r in section_3_2(doc.render(doc_scan([none]))).splitlines() if r.startswith("| /p/sup "))
    assert "no submodule is checked out" in row and archive in row and "{ [ -e" not in row and "re-scan with this" not in row


def test_capture_plan_keeps_staged_changes_and_every_stash():
    """Codex pass 20 on PR 27, two P1s: `git diff` alone misses the index; `stash show -p stash@{0}` kept one
    stash without its untracked files and dropped the older entries."""
    mod = load_doc()
    co = doc_checkout("/p/w", flags=["dirty", "stash"], verdict="dirty", modified=2, stashes=3)
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /p/w "))
    row = row.replace("\\|", "|")  # a rendered cell writes `\|` for a literal pipe (round 48)
    assert "git -C /p/w diff --no-ext-diff --no-textconv --no-color --binary > <DEST>/checkouts/abs/p/w/modified.patch && " \
           "git -C /p/w diff --no-ext-diff --no-textconv --no-color --binary --cached > <DEST>/checkouts/abs/p/w/staged.patch" in row
    # Codex pass 21: a plain diff drops a binary file's bytes; pass 30: a textconv filter replaces them, and an
    # unmerged entry's bytes are in no patch at all, so the changed files and the index are archived too
    assert ('{ TAR_OPTIONS= LC_ALL=C "$GTAR" -cf <DEST>/checkouts/abs/p/w/modified.tar -C <DEST>/checkouts/abs/p/w modified.list -C /p/w --null '
            '--no-recursion --ignore-failed-read -T <DEST>/checkouts/abs/p/w/modified.list 2>> <DEST>/checkouts/abs/p/w/modified.err || '
            "{ cat <DEST>/checkouts/abs/p/w/modified.err >&2; echo 'modified capture FAILED' >&2; false; }; }") in row  # round 40: tar's own failure is printed
    assert "2> <DEST>/checkouts/abs/p/w/modified.err" in row  # round 36
    # Codex pass 39: an unmerged entry's stage blobs may be in no ref; every object `ls-files -u` names is packed
    assert "git -C /p/w ls-files -u > <DEST>/checkouts/abs/p/w/unmerged.list" in row
    assert "<DEST>/checkouts/abs/p/w/unmerged.list > <DEST>/checkouts/abs/p/w/unmerged.ids" in row
    assert "GIT_NO_LAZY_FETCH=1 git -C /p/w pack-objects <DEST>/checkouts/abs/p/w/unmerged < <DEST>/checkouts/abs/p/w/unmerged.ids" in row
    assert "{ ! grep -qv -e '^warning: ' -e ': Cannot stat: No such file or directory$' -e ': Cannot stat: Not a directory$' <DEST>/checkouts/abs/p/w/modified.err || " \
           "{ cat <DEST>/checkouts/abs/p/w/modified.err >&2; echo 'modified capture FAILED' >&2; false; }; }" in row  # round 37: loud, and a plain warning is no failure
    assert "--ignore-failed-read -T <DEST>/checkouts/abs/p/w/modified.list 2>> <DEST>/checkouts/abs/p/w/modified.err || { cat <DEST>/checkouts/abs/p/w/modified.err >&2; echo 'modified capture FAILED' >&2; false; }; } && { ! grep" in row  # Codex pass 34: tar's stderr too; round 40: its failure printed
    assert mod.modified_fmt().count("{}") == len(mod.modified_values("/p", "c"))
    assert '"$GCP" -- "$(git -C /p/w rev-parse --absolute-git-dir)/index" <DEST>/checkouts/abs/p/w/index' in row
    assert "3 stashes" in row and "stash0.patch" not in row and "bundle create <DEST>/checkouts/abs/p/w/stashes" not in row
    assert "log -g --format=%gd refs/stash" in row and "stash show -p --no-ext-diff --no-textconv --no-color --binary --include-untracked" in row
    assert 'diff --no-ext-diff --no-textconv --no-color --binary "$r^1" "$r^2" > <DEST>/checkouts/abs/p/w/stash${r//[^0-9]/}-index.patch' in row
    assert "git apply --allow-empty --cached <index patch> && git apply --allow-empty <patch>" in row  # Codex pass 31, round 37


def test_stash_capture_command_really_saves_every_stash_with_its_untracked_files(tmp_path):
    """Adversary round 26 on PR 27: the bundle form failed (`bundle create` wants refs, not reflog ids), so no stash
    was saved and the text-only test did not notice. This one runs the row's command against a real checkout."""
    mod = load_doc()
    repo = make_repo(tmp_path / "w")
    (repo / "a.txt").write_text("first stash\n")
    git(repo, "stash", "push", "-m", "older")
    (repo / "a.txt").write_text("second stash\n")
    (repo / "new file.bin").write_bytes(b"\x00\x01binary\n")
    git(repo, "stash", "push", "-u", "-m", "newer")
    assert git(repo, "stash", "list").count("\n") == 2
    ck = mod.checkout_dir(str(repo))
    cmd = mod.STASH_FMT.format(*map(mod.shquote, mod.stash_values(str(repo), ck))).replace("<DEST>", str(tmp_path / "dest"))
    # adversary round 27: a stash pushed after the scan must be saved too (the entries are listed at run time)
    (repo / "a.txt").write_text("third stash\n")
    git(repo, "stash", "push", "-m", "newest")
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        p0 = (tmp_path / "dest" / ck / "stash0.patch").read_text()
        p1 = (tmp_path / "dest" / ck / "stash1.patch").read_text()
        p2 = (tmp_path / "dest" / ck / "stash2.patch").read_text()
        assert "third stash" in p0
        assert "second stash" in p1 and "new file.bin" in p1 and "GIT binary patch" in p1  # untracked and binary kept
        assert "first stash" in p2 and "new file.bin" not in p2
        assert not list((tmp_path / "dest" / ck).glob("stash3.patch"))
    # the loop runs in a subshell: a failure ends the loop with rc 1 and nothing else (no `exit` of the caller)
    bad = cmd.replace("--include-untracked", "--no-such-option")
    run = subprocess.run(["bash", "-c", bad + "; echo still-here"], capture_output=True, text=True)
    assert "still-here" in run.stdout and run.returncode == 0
    # Codex pass 23: a failed or empty enumeration must fail the command, never run an empty loop with rc 0
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        gone = cmd.replace("refs/stash", "refs/no-such-ref")  # `log -g` fails: nothing to iterate
        assert subprocess.run([shell, "-c", gone], capture_output=True).returncode != 0
        git(repo, "stash", "clear")
        assert subprocess.run([shell, "-c", cmd], capture_output=True).returncode != 0  # no entries left: fails


def test_gitdir_capture_archives_a_linked_worktree_without_its_own_refs(tmp_path):
    """Adversary round 35 and Codex pass 30 on PR 27: the round-34 guard wanted `refs/` in the per-worktree git
    directory, which a linked worktree made before git 2.44 does not have (git checks `refs` and `objects` in the
    COMMON directory); it refused such a worktree with `gitdir capture FAILED`. A `.git` file naming a directory
    that is no git directory still fails, loudly, with no archive."""
    import tarfile
    mod = load_doc()
    main = make_repo(tmp_path / "main")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", str(wt), "-b", "side")
    (wt / "a.txt").write_text("worktree only\n")
    git(wt, "commit", "-am", "local-only in the worktree")
    admin = Path(git(wt, "rev-parse", "--absolute-git-dir").strip())
    shutil.rmtree(admin / "refs", ignore_errors=True)  # the pre-2.44 layout: HEAD and commondir, no refs/
    assert not (admin / "refs").exists() and (admin / "commondir").is_file()
    assert git(wt, "status", "--porcelain") == ""  # git itself still accepts the worktree
    ck = mod.checkout_dir(str(wt))
    prefix = PLAN_PREFIX
    cmd = prefix + mod.GITDIR_FMT.format(*map(mod.shquote, mod.gitdir_values(str(wt), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        (tmp_path / "dest" / ck).mkdir(parents=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        names = set(tarfile.open(tmp_path / "dest" / ck / "gitdir.tar").getnames())
        assert "./HEAD" in names and "./commondir" in names
        common = set(tarfile.open(tmp_path / "dest" / ck / "commondir.tar").getnames())
        assert "./refs/heads/side" in common and any(n.startswith("./objects/") for n in common)
    # a `.git` file naming a directory with a HEAD file but no objects, refs or commondir is not a git directory
    fake = tmp_path / "fake"
    (fake / "gd").mkdir(parents=True)
    (fake / "gd" / "HEAD").write_text("ref: refs/heads/main\n")
    (fake / ".git").write_text("gitdir: gd\n")
    ck2 = mod.checkout_dir(str(fake))
    bad = prefix + mod.GITDIR_FMT.format(*map(mod.shquote, mod.gitdir_values(str(fake), ck2))).replace("<DEST>", str(tmp_path / "dest2"))
    (tmp_path / "dest2" / ck2).mkdir(parents=True)
    run = subprocess.run(["bash", "-c", bad], capture_output=True, text=True)
    assert run.returncode != 0 and "gitdir capture FAILED" in run.stderr
    assert not list((tmp_path / "dest2" / ck2).iterdir())
    # adversary round 36: HEAD plus a `commondir` naming a non-git directory, next to private files: nothing archived
    (fake / "gd" / "commondir").write_text("/no/such/dir\n")
    (fake / "gd" / "private-notes.txt").write_text("secret\n")
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        run = subprocess.run([shell, "-c", bad], capture_output=True, text=True)
        assert run.returncode != 0 and "gitdir capture FAILED" in run.stderr, shell
        assert not list((tmp_path / "dest2" / ck2).iterdir()), shell


def test_modified_capture_archives_an_unmerged_binary_file_and_ignores_textconv(tmp_path):
    """Codex pass 30 on PR 27: an unresolved binary conflict's worktree bytes are in neither patch (`Binary files
    differ` / `* Unmerged path`), and an attribute-selected textconv turned a changed binary file into an empty
    patch. The row now archives every changed worktree file with the index and diffs with `--no-textconv`."""
    import tarfile
    mod = load_doc()
    repo = make_repo(tmp_path / "w")
    (repo / "b.bin").write_bytes(b"\x00A\n")
    (repo / "c.bin").write_bytes(b"\x00C0\n")
    git(repo, "add", "b.bin", "c.bin")
    git(repo, "commit", "-m", "binaries")
    git(repo, "checkout", "-b", "side")
    (repo / "b.bin").write_bytes(b"\x00B\n")
    git(repo, "commit", "-am", "side")
    git(repo, "checkout", "main")
    (repo / "b.bin").write_bytes(b"\x00M\n")
    git(repo, "commit", "-am", "main")
    merge = subprocess.run(["git", "merge", "side"], cwd=repo, env=GIT_ENV, capture_output=True, text=True)
    assert merge.returncode != 0 and "UU b.bin" in git(repo, "status", "--porcelain")
    (repo / "b.bin").write_bytes(b"\x00RESOLVED\n")  # a resolution typed into the worktree, not yet added
    (repo / "c.bin").write_bytes(b"\x00C1\n")
    git(repo, "config", "diff.const.textconv", "echo constant;true")
    (repo / ".gitattributes").write_text("*.bin diff=const\n")
    ck = mod.checkout_dir(str(repo))
    prefix = PLAN_PREFIX
    cmd = prefix + mod.modified_fmt().format(*map(mod.shquote, mod.modified_values(str(repo), ck))).replace("<DEST>", str(tmp_path / "dest"))
    for shell in ("bash", "zsh"):
        if shutil.which(shell) is None:
            continue
        shutil.rmtree(tmp_path / "dest", ignore_errors=True)
        run = subprocess.run([shell, "-c", cmd], capture_output=True, text=True)
        assert run.returncode == 0, (shell, run.stderr)
        dest = tmp_path / "dest" / ck
        assert "GIT binary patch" in (dest / "modified.patch").read_text()  # c.bin's bytes, textconv ignored
        tar = tarfile.open(dest / "modified.tar")
        names = set(tar.getnames())
        assert {"modified.list", "b.bin", "c.bin"} <= names
        assert tar.extractfile("b.bin").read() == b"\x00RESOLVED\n" and tar.extractfile("c.bin").read() == b"\x00C1\n"
        assert (dest / "index").stat().st_size > 0 and (dest / "staged.patch").exists()
    # a worktree deletion has no bytes to keep and must not fail the archive; an all-deletions list still archives
    (repo / "c.bin").unlink()
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "b.bin" in tarfile.open(tmp_path / "dest" / ck / "modified.tar").getnames()
    # adversary round 36: a tracked file replaced by a directory is listed but not recursed into (its content is
    # another row's business, and a directory's ignored files must not be copied)
    (repo / "c.bin").mkdir()
    (repo / "c.bin" / "inner.txt").write_text("not archived\n")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    names = tarfile.open(tmp_path / "dest" / ck / "modified.tar").getnames()
    assert "c.bin" in names and not any(n.startswith("c.bin/") for n in names)
    # round 36: git's own read error on a path that still exists (an unsearchable directory) fails the row loudly
    if os.geteuid() != 0:
        (repo / "d").mkdir()
        (repo / "d" / "f.txt").write_text("tracked\n")
        git(repo, "add", "d/f.txt")
        (repo / "d" / "f.txt").write_text("changed\n")
        (repo / "d").chmod(0o600)
        try:
            run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        finally:
            (repo / "d").chmod(0o755)
        assert run.returncode != 0 and (tmp_path / "dest" / ck / "modified.err").stat().st_size > 0, run.stderr
        assert "modified capture FAILED" in run.stderr and "cannot lstat" in run.stderr  # round 37: says why
        # Codex pass 34: an unreadable changed file: `--ignore-failed-read` gave rc 0 with the file left out
        (repo / "b.bin").chmod(0)
        try:
            run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        finally:
            (repo / "b.bin").chmod(0o644)
        assert run.returncode != 0 and "Permission denied" in run.stderr, run.stderr
    # round 37: a plain `warning:` line on stderr (an ambiguous ref name) is not a read error and must not fail the row
    git(repo, "update-ref", "refs/heads/HEAD", "HEAD")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "warning:" in (tmp_path / "dest" / ck / "modified.err").read_text()
    # round 40: a tracked path whose parent directory is now a file (`Cannot stat: Not a directory`) has nothing to
    # keep, like a missing one: no failure
    (repo / "e").mkdir()
    (repo / "e" / "f.txt").write_text("tracked\n")
    git(repo, "add", "e/f.txt")
    shutil.rmtree(repo / "e")
    (repo / "e").write_text("now a file\n")
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert "Not a directory" in (tmp_path / "dest" / ck / "modified.err").read_text()
    # round 40: tar's own failure (an archive path it cannot write) is printed and fails the row
    (tmp_path / "dest" / ck / "modified.tar").unlink()
    (tmp_path / "dest" / ck / "modified.tar").mkdir()
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode != 0 and "modified capture FAILED" in run.stderr and "modified.tar" in run.stderr, run.stderr


def test_a_cow_pasture_gets_its_own_patch_and_archive_rows():
    """Codex pass 24 on PR 27: a path containing `djbclark-ade` or `forgejo-ci-2026-10` used to get "preserved in the
    primary checkout" with no command, and the phase0-scan pasture no row at all; names prove nothing."""
    mod = load_doc()
    rows = []
    for p in ("/h/.cow/pastures/djbclark-ade/phase0-scan", "/h/.cow/pastures/hermes-agent/forgejo-ci-2026-10", "/h/src/djbclark-ade"):
        co = doc_checkout(p, flags=["dirty"], verdict="dirty", modified=1, untracked=1, untracked_sample=["x.txt"])
        rows += [r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith(f"| {p} ")]
    assert len(rows) == 3
    for row in rows:
        assert "preserve once there" not in row and "preserved there" not in row
        assert "diff --no-ext-diff --no-textconv --no-color --binary > <DEST>/checkouts/abs" in row and "untracked.tar" in row


def test_a_checkout_named_one_offs_hermes_gets_its_own_bundle_row():
    """Adversary round 30 on PR 27: a path ending in `/one-offs/Hermes` used to get "see `~/src/one-offs`" and no
    command, whatever repository it was; its unpushed commits had no capture command."""
    mod = load_doc()
    co = doc_checkout("/srv/other/one-offs/Hermes", flags=["orphan branch", "no origin remote"], verdict="orphan branch",
                      ahead_of_origin=5, unpushed=5, on_origin=False)
    rows = [r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| /srv/other/one-offs/Hermes ")]
    assert len(rows) == 1
    assert "see `~/src/one-offs`" not in rows[0] and "branch `Hermes`" not in rows[0]
    assert "bundle create" in rows[0] and "--all" in rows[0] and "all 5 commits (no remote)" in rows[0]


def test_stash_count_treats_only_a_missing_ref_as_zero(monkeypatch, tmp_path):
    """Codex pass 24 on PR 27: on the reftable path every nonzero `rev-parse --verify refs/stash` read as no stash."""
    mod = load()
    answers = {}
    monkeypatch.setattr(mod, "git", lambda path, *args, **kw: answers[args[0]])
    answers["rev-parse"] = (1, "")
    assert mod.stash_count(tmp_path, None) == 0
    for rc in (124, 128):
        answers["rev-parse"] = (rc, "")
        assert mod.stash_count(tmp_path, None) is None
    answers["rev-parse"], answers["stash"] = (0, "abc\n"), (0, "a\nb\n")
    assert mod.stash_count(tmp_path, None) == 2
    answers["stash"] = (128, "")
    assert mod.stash_count(tmp_path, None) is None


def test_section_1_verdict_rows_sum_to_the_checkout_count():
    """Adversary round 21, INFO 5: three verdicts appeared in no row."""
    mod = load_doc()
    verdicts = {"clean and pushed": 4, "dirty": 2, "origin tips not fetched: 2": 3,
                "origin advertised invalid ref names: 1": 1, "origin unreachable: local-only count unverified": 5,
                "skipped: unrecognised config core.x": 1}
    cos = [doc_checkout(f"/p/{i}") for i in range(sum(verdicts.values()))]
    scan = doc_scan(cos)
    scan["summary"]["checkouts"]["verdicts"] = verdicts
    rows = [r for r in mod.render(scan).split("## 1.")[0].splitlines() if r.startswith("| checkouts, verdict ")]
    total = sum(int(r.rstrip(" |").rsplit("|", 1)[1]) for r in rows)
    assert total == len(cos) == 16, rows
    assert any("origin unreachable: local-only count unverified" in r and r.endswith("| 5 |") for r in rows)
    assert any("unpushed commits" in r and r.endswith("| 0 |") for r in rows)  # the four fixed rows stay


def test_esc_renders_every_control_character_as_text_so_a_cr_cannot_split_a_row():
    """Adversary round 21, 3: CommonMark ends a line at a bare CR."""
    doc, scan_mod = load_doc(), load()
    for esc in (doc.esc, scan_mod.esc):
        text = esc("a\rb\nc\td\x0be\x01f\x7fg")
        assert text == "a\\rb\\nc\\td\\x0be\\x01f\\x7fg" and not re.search(r"[\x00-\x1f\x7f]", text)
    co = doc_checkout("/p/a\rb", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=1,
                      local_only_branches=[{"branch": "side", "count": 1}])
    text = doc.render(doc_scan([co]))
    assert "\r" not in text.replace("\r\n", "")  # no raw CR anywhere in the rendered doc
    assert not [ln for ln in text.splitlines() if ln.startswith("b")]
    assert len([ln for ln in text.splitlines() if ln.startswith("| /p/a\\rb |")]) == 2  # section 2 and 3.2 rows
    md = scan_mod.markdown({"checkouts": [{"path": "/p/a\rb", "branch": "main", "modified": 0, "untracked": 0,
                                           "unpushed": 0, "stashes": 0, "on_origin": True, "flags": ["x"],
                                           "verdict": "x"}]})
    assert "\r" not in md and "| /p/a\\rb |" in md


def test_a_tag_on_a_tree_or_blob_is_not_an_unfetched_tip_but_an_absent_commit_still_is(tmp_path):
    """Adversary round 21, 2: `rev-list --count --no-walk` counts commits only, so a tag on a tree or blob
    (git.git `junio-gpg-pub`, linux `v2.6.11-tree`) left `origin tips not fetched` on for good."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    git(other, "checkout", "main")
    git(other, "tag", "-a", "-m", "tree", "treetag", "HEAD^{tree}")
    git(other, "tag", "blobtag", git(other, "rev-parse", "HEAD:a.txt").strip())
    git(other, "tag", "-a", "-m", "blob", "annblob", git(other, "rev-parse", "HEAD:a.txt").strip())
    git(other, "push", "origin", "refs/tags/treetag", "refs/tags/blobtag", "refs/tags/annblob")
    assert git(work, "cat-file", "-t", git(work, "rev-parse", "HEAD^{tree}").strip()).strip() == "tree"
    c = scan_one(mod, roots, remote=True)
    assert c["verdict"] == "clean and pushed" and c["flags"] == [], c["flags"]
    assert c["local_only_verified"] is True
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)  # nothing to fetch for them, and no flag after
    assert c["verdict"] == "clean and pushed" and c["local_only_verified"] is True, c["flags"]
    assert git(work, "tag", "--list").strip() == ""
    # a tag whose commit is really absent here still counts, next to the tree and blob tags, and --fetch clears it
    commit_file(other, "tagged.txt")
    git(other, "tag", "-a", "-m", "v9", "v9")
    git(other, "push", "origin", "refs/tags/v9:refs/tags/v9")
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert "origin tips not fetched: 1" in c["flags"] and c["local_only_verified"] is False, c["flags"]
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True, fetch=True)
    assert c["verdict"] == "clean and pushed" and c["flags"] == [] and c["local_only_verified"] is True, c["flags"]


def test_a_credential_in_a_push_url_or_a_second_url_gets_no_push_row(tmp_path):
    """Codex pass 41 on PR 27, P1: a clean fetch url with a token in `remote.origin.pushurl` (or in a second `url`,
    or reached through `pushInsteadOf`) left `origin_credential` false, and the plan printed `git push origin`."""
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    commit_file(work, "ahead.txt")
    assert scan_one(mod, roots)["origin_credential"] is False
    git(work, "config", "remote.origin.pushurl", "https://127.0.0.1:9/clean.git")
    assert scan_one(mod, roots)["origin_credential"] is False
    git(work, "config", "--add", "remote.origin.pushurl", "https://u:FAKE-SECRET@127.0.0.1:9/x.git")
    c = scan_one(mod, roots)
    assert c["origin_credential"] is True, c
    text = section_3_2(doc.render(doc_scan([c])))
    assert "push origin" not in text and "push -u" not in text and "FAKE-SECRET" not in text, text
    git(work, "config", "--unset-all", "remote.origin.pushurl")
    git(work, "config", "--add", "remote.origin.url", "https://u:FAKE-SECRET@127.0.0.1:9/y.git")
    assert scan_one(mod, roots)["origin_credential"] is True
    git(work, "config", "--unset-all", "remote.origin.url")
    git(work, "config", "remote.origin.url", "https://127.0.0.1:9/x.git")
    assert scan_one(mod, roots)["origin_credential"] is False
    # Codex pass 44: a remote-helper url (`evil::PAYLOAD`) is withheld like a credential: no push row, the bundle instead
    git(work, "config", "remote.origin.url", "evil::PAYLOAD-FAKE")
    c = scan_one(mod, roots)
    assert c["origin_credential"] is True, c
    text = section_3_2(doc.render(doc_scan([c])))
    assert "push origin" not in text and "push -u" not in text and "PAYLOAD-FAKE" not in text and "bundle create" in text, text
    git(work, "config", "remote.origin.url", "https://127.0.0.1:9/x.git")
    assert scan_one(mod, roots)["origin_credential"] is False
    # a `url.<base>.pushInsteadOf` rewrite: the config allowlist refuses any `url.*` section, so the checkout is a
    # skipped record that never reaches a push row; `push_urls_hold_credential` still resolves it (defence in depth)
    git(work, "config", "url.https://u:FAKE-SECRET@127.0.0.1:9/.pushInsteadOf", "https://127.0.0.1:9/")
    assert mod.push_urls_hold_credential(work) is True
    assert "origin_credential" not in scan_one(mod, roots)


def test_a_symlinked_modules_directory_or_a_symlink_inside_a_module_is_skipped(tmp_path):
    """Cursor security review and Codex pass 41 (P1) on PR 27: `.git/modules` itself as a symlink was followed, and a
    symlinked `objects`, `refs` or anything below them was pruned before the symlink check, so `modules.tar`
    archived a link instead of the commits at its target."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)

    def verdict():
        return next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))["verdict"]

    assert not verdict().startswith("skipped")
    want = "skipped: submodule config unrecognised (symlink)"
    # a symlink below refs/ (the pruned tree)
    outside_refs = tmp_path / "outside-heads"
    (moddir / "refs" / "heads").rename(outside_refs)
    (moddir / "refs" / "heads").symlink_to(outside_refs)
    assert verdict() == want
    (moddir / "refs" / "heads").unlink()
    outside_refs.rename(moddir / "refs" / "heads")
    assert not verdict().startswith("skipped")
    # a symlinked objects directory itself
    outside_obj = tmp_path / "outside-objects"
    (moddir / "objects").rename(outside_obj)
    (moddir / "objects").symlink_to(outside_obj)
    assert verdict() == want
    (moddir / "objects").unlink()
    outside_obj.rename(moddir / "objects")
    assert not verdict().startswith("skipped")
    # `.git/modules` itself a symlink
    modules = moddir.parent
    assert modules.name == "modules"
    outside_mod = tmp_path / "outside-modules"
    modules.rename(outside_mod)
    modules.symlink_to(outside_mod)
    assert verdict() == want


def test_a_submodule_path_with_an_ampersand_or_angle_brackets_is_captured_not_skipped(tmp_path):
    """Adversary round 47 on PR 27 (MEDIUM): `esc(in_code=True)` wrote `&amp;`/`&lt;`/`&gt;` into the code span, which no
    markdown view decodes, so a real checked-out submodule `R&D` reached its guard as `R&amp;D` and was reported "not a
    checked-out submodule (skipped)" while its modified and untracked files went uncaptured."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    for name in ("R&D", "a<b>c"):
        origin = make_repo(tmp_path / f"origin-{abs(hash(name))}", "f.txt")
        git(sup, "-c", "protocol.file.allow=always", "submodule", "add", str(origin), name)
    git(sup, "commit", "-m", "more submodules")
    for name in ("R&D", "a<b>c"):
        (sup / name / "f.txt").write_text("edited in " + name + "\n")
        (sup / name / "u.txt").write_text("untracked in " + name + "\n")
    rec = next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))
    assert not rec["verdict"].startswith("skipped"), rec["verdict"]
    assert {"R&D", "a<b>c", "sub"} <= set(rec["submodules_vetted"]), rec["submodules_vetted"]
    text = doc.render(doc_scan([rec]))
    row = next(r for r in section_3_2(text).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "&amp;" not in row and "&lt;" not in row and "&gt;" not in row, row
    ck = doc.checkout_dir(rec["path"])
    for shell in SHELLS:
        dest = tmp_path / f"dest-{shell}"
        for cmd in plan_commands(row):
            run = run_plan(shell, cmd, dest, tmp_path)
            assert run.returncode == 0, (shell, cmd, run.stderr)
        for name in ("R&D", "a<b>c"):
            sd = dest / ck / "submodules" / name
            assert "edited in" in (sd / "modified.patch").read_text(), (shell, name)
            assert (sd / "untracked.tar").stat().st_size > 0, (shell, name)


def test_the_submodule_guard_prints_a_path_with_backslashes_literally(tmp_path):
    """Round 47 LOW 2: the guard's `echo` made zsh and macOS `/bin/sh` interpret `\\e`, `\\033` and `\\c` in the path
    (a raw ESC, an OSC 52 clipboard write, a truncated message); `printf '%s\\n'` shows it as written."""
    doc = load_doc()
    sub = "x\\e[31mRED\\cHIDDEN"
    cmds = doc.submodule_commands("/nonexistent/p", "ck", sub)
    for shell in SHELLS:
        run = subprocess.run([shell, "-c", unescape_span(cmds[0].strip("` "))], capture_output=True, text=True)
        assert run.returncode != 0 and f"submodule {sub}: not a checked-out submodule (skipped)" in run.stderr, (shell, run.stderr)
        assert "\x1b" not in run.stderr


def test_a_hand_edited_record_with_an_absolute_or_dotdot_vetted_path_gets_no_commands_for_it(tmp_path):
    """Round 47 LOW 3 (defence in depth): `os.path.join(raw_p, "/x")` discards the checkout."""
    doc = load_doc()
    assert doc.vettable("sub") and doc.vettable("a/b") and not doc.vettable("/evil") and not doc.vettable("../x")
    assert not doc.vettable("a/../b") and not doc.vettable("") and not doc.vettable(None)


def test_an_absolute_index_gitlink_or_a_symlinked_file_or_alternates_in_a_module_skips_the_checkout(tmp_path):
    """Round 47 LOW 3 and 4: the gitlink rule matches the `.gitmodules` rule, and `modules.tar` (no dereference) must not
    archive a link or a pointer where the refs or objects should be."""
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)

    def verdict():
        return next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))["verdict"]

    assert not verdict().startswith("skipped")
    packed = moddir / "packed-refs"
    packed.write_text("")
    outside = tmp_path / "outside-packed"
    packed.rename(outside)
    packed.symlink_to(outside)
    assert verdict() == "skipped: submodule config unrecognised (symlink)"
    packed.unlink()
    outside.rename(packed)
    packed.unlink()
    assert not verdict().startswith("skipped")
    alt = moddir / "objects" / "info" / "alternates"
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text(str(tmp_path / "elsewhere") + "\n")
    assert verdict() == "skipped: submodule config unrecognised (alternates)"
    alt.write_text("")
    assert not verdict().startswith("skipped")
    real_git = mod.git

    def fake(path, *args, **kw):
        if args[:1] == ("ls-files",) and "-s" in args:
            return 0, "160000 " + "a" * 40 + " 0\t/tmp/evil\0"
        return real_git(path, *args, **kw)

    mod.git = fake
    try:
        assert verdict() == "skipped: submodule config unrecognised (gitmodules path unusual)"
    finally:
        mod.git = real_git


def diverged_checkout(tmp_path: Path):
    """(roots, tip): a pushed checkout with one more local commit, origin's tip (another clone's commit) not in it."""
    roots, work, origin = make_pushed_checkout(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    commit_file(other, "o.txt")
    git(other, "push", "origin", "main")
    commit_file(work, "w.txt")
    return roots, git(other, "rev-parse", "HEAD").strip()


REV_LIST_TIP = "rev-list --count HEAD --not --remotes=origin <tip>"


def test_only_a_missing_tip_object_reads_as_origin_tip_not_fetched_any_other_failed_rev_list_is_incomplete(tmp_path):
    """Codex thread 7 on PR 27: a timed-out (124) or damaged-repository (128) second `rev-list --count HEAD --not
    --remotes=origin <tip>` read as `origin tip not fetched`; git's own "bad object <tip>" is the only honest reading."""
    mod = load()
    roots, tip = diverged_checkout(tmp_path)
    real_git = mod.git
    calls = []

    def scan(fail_on, rc, stderr, fetch=False):
        calls.clear()

        def fake(path, *args, **kw):
            if len(args) == 6 and args[:5] == ("rev-list", "--count", "HEAD", "--not", "--remotes=origin"):
                calls.append(args[5])
                if len(calls) in fail_on:
                    if "err" in kw:
                        kw["err"].append(stderr)
                    return rc, ""
            return real_git(path, *args, **kw)
        mod.git = fake
        mod._remote_cache.clear()
        try:
            return scan_one(mod, roots, remote=True, fetch=fetch)
        finally:
            mod.git = real_git

    c = scan(set(), 0, "")  # the honest case: the tip's objects are not here
    assert c["verdict"] == "unpushed commits" and "origin tip not fetched" in c["flags"] and calls == [tip]
    for rc, stderr in ((124, ""), (128, "fatal: unable to read tree\n"), (128, "fatal: bad object " + "1" * 40 + "\n"),
                       (1, f"fatal: bad object {tip}\n"), (0, "")):  # another object, another rc, a count that is no number
        c = scan({1}, rc, stderr)
        assert c["verdict"] == f"scan incomplete: {REV_LIST_TIP} rc={rc or 65}", (rc, c["verdict"])
        assert c["flags"] == [c["verdict"]] and c["ahead_of_origin"] is None and "origin tip not fetched" not in c["flags"]
    for stderr in (f"fatal: bad object {tip}\n", f"fatal: not a valid object name {tip}\n",
                   f"fatal: ambiguous argument '{tip}': unknown revision or path not in the working tree.\nUse '--'\n"):
        c = scan({1}, 128, stderr)  # git says the object is missing: the honest reading again
        assert c["verdict"] == "unpushed commits" and "origin tip not fetched" in c["flags"], (stderr, c["verdict"])
    # --fetch: the second call is the one that fails (the real fetch ran in between)
    c = scan({2}, 124, "", fetch=True)
    assert len(calls) == 2 and c["verdict"] == f"scan incomplete: {REV_LIST_TIP} rc=124", c["verdict"]
    c = scan(set(), 0, "", fetch=True)  # the earlier fetch left the tip here: one call, a real count, nothing failed
    assert len(calls) == 1 and c["verdict"] == "unpushed commits" and "origin tip not fetched" not in c["flags"]
    assert c["ahead_of_origin"] == 1


def scan_super(mod, roots: Path, **kw) -> dict:
    """The record of `roots/super` alone: a checked-out submodule is a checkout of its own (`skipped: worktree redirected`)."""
    want = str((roots / "super").resolve())
    return next(c for c in mod.scan_git([roots], **{"remote": False, **kw}) if c["path"] == want)


def make_nested_submodules(tmp_path: Path):
    """(roots, super, mid worktree, inner worktree): super -> mid -> inner, every level checked out."""
    inner_origin = make_repo(tmp_path / "inner-origin", "i.txt")
    mid_origin = make_repo(tmp_path / "mid-origin", "m.txt")
    allow = ("-c", "protocol.file.allow=always")
    git(mid_origin, *allow, "submodule", "add", str(inner_origin), "inner")
    git(mid_origin, "commit", "-m", "add inner")
    roots = tmp_path / "roots"
    sup = make_repo(roots / "super")
    git(sup, *allow, "submodule", "add", str(mid_origin), "mid")
    git(sup, *allow, "submodule", "update", "--init", "--recursive")
    git(sup, "commit", "-m", "add mid")
    return roots, sup, sup / "mid", sup / "mid" / "inner"


NESTED = "skipped: submodule config unrecognised (nested submodule)"


def test_a_submodule_with_submodules_of_its_own_skips_the_checkout_and_gets_the_whole_directory_archive(tmp_path):
    """Codex thread 9 on PR 27: `submodules_vetted` held only the outer path, so an edit inside the inner submodule's
    worktree was in no artifact (the per-submodule commands run with `--no-recursion`)."""
    mod = load()
    roots, sup, mid, inner = make_nested_submodules(tmp_path)
    (inner / "i.txt").write_text("edited in the inner submodule\n")
    (inner / "untracked-in-inner.txt").write_text("new\n")
    c = scan_super(mod, roots)
    assert c["verdict"] == NESTED and c["flags"] == [NESTED] and c["config_keys"] == ["(nested submodule)"], c
    assert not c.get("submodules_vetted") and c["modified"] is None
    # the rendered row archives the whole directory, which holds the inner worktree, and the git directory
    doc = load_doc()
    row = next(r for r in section_3_2(doc.render(doc_scan([c]))).splitlines() if r.startswith(f"| {doc.tilde(c['path'])} "))
    assert "whole.tar" in row and f"counts unknown ({NESTED})" in row.replace("\\|", "|") and "gitdir.tar" in row
    # a clean nested tree is skipped too: the rule is the structure, not the dirt
    (inner / "i.txt").write_text("i.txt\n")
    (inner / "untracked-in-inner.txt").unlink()
    assert scan_super(mod, roots)["verdict"] == NESTED


def test_a_submodule_with_a_gitlink_of_its_own_but_no_gitmodules_is_nested_and_a_plain_one_is_not(tmp_path):
    mod = load()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    assert not scan_super(mod, roots)["verdict"].startswith("skipped")  # a submodule with nothing inside it is scanned
    sub = sup / "sub"
    make_repo(sub / "embedded", "e.txt")
    git(sub, "add", "embedded")  # a gitlink in the submodule's index, no `.gitmodules` anywhere
    assert not (sub / ".gitmodules").exists()
    assert scan_super(mod, roots)["verdict"] == NESTED
    git(sub, "rm", "--cached", "-q", "-f", "embedded")
    shutil.rmtree(sub / "embedded")  # no longer a gitlink, and a repository left there untracked is nested too (below)
    assert not scan_super(mod, roots)["verdict"].startswith("skipped")
    (sub / ".gitmodules").write_text("")  # a `.gitmodules` file of its own is enough, whatever it lists
    assert scan_super(mod, roots)["verdict"] == NESTED


def test_an_untracked_repository_inside_a_submodule_is_nested_and_gets_the_whole_directory_archive(tmp_path, monkeypatch):
    """Adversary round 64 on PR 27, MEDIUM: an inner repository that was simply cloned into a submodule's worktree has
    no gitlink and no `.gitmodules`; the per-submodule untracked archive keeps it as a bare directory entry, so its
    commits were in no artifact."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    sub = sup / "sub"
    emb = make_repo(sub / "embedded", "e.txt")
    (emb / "e2.txt").write_text("second\n")
    git(emb, "add", "e2.txt")
    git(emb, "commit", "-m", "local only work")
    assert not (sub / ".gitmodules").exists() and "embedded" not in git(sub, "ls-files", "-s")  # never added
    c = scan_super(mod, roots)
    assert c["verdict"] == NESTED and not c.get("submodules_vetted"), c
    row = skipped_row(doc, c)
    assert "whole.tar" in row and f"counts unknown ({NESTED})" in row
    # the walk failing (a timeout, an unreadable subdirectory) is never a scanned submodule; a timeout says so (round 65, INFO 3)
    real = mod.embedded_repositories
    monkeypatch.setattr(mod, "embedded_repositories", lambda p, within=None: (124, [], []) if p.name == "sub" else real(p, within))
    assert scan_super(mod, roots)["verdict"] == f"skipped: submodule config unrecognised {mod.SUBMODULE_CHECK_FAILED}" == (
        "skipped: submodule config unrecognised (unreadable, timed out or too large)")
    monkeypatch.setattr(mod, "embedded_repositories", real)
    # round 66, INFO 1: the `ls-files -z -s` of the submodule failing (a timeout is rc 124) has the same one label
    real_git = mod.git
    monkeypatch.setattr(mod, "git", lambda p, *a, **kw: (124, "") if p.name == "sub" and a[:3] == ("ls-files", "-z", "-s") else real_git(p, *a, **kw))
    assert scan_super(mod, roots)["verdict"] == "skipped: submodule config unrecognised (unreadable, timed out or too large)"
    monkeypatch.setattr(mod, "git", real_git)
    shutil.rmtree(emb)  # a plain submodule with only an ordinary untracked file is still scanned
    (sub / "notes.txt").write_text("not a repository\n")
    c = scan_super(mod, roots)
    assert not c["verdict"].startswith("skipped") and c["submodules_vetted"] == ["sub"], c


def test_a_repository_at_an_index_hidden_path_inside_a_submodule_is_nested_and_gets_the_whole_directory_archive(tmp_path, monkeypatch):
    """Adversary round 65 on PR 27, MEDIUM, and Codex pass 65, P1: `ls-files --others` lists nothing for a directory that
    replaces a skip-worktree or assume-unchanged tracked path, so the nested check passed a submodule whose inner
    repository (a local-only commit) was in no artifact. The top level already walks those directories; the submodule gets
    the same walk."""
    mod, doc = load(), load_doc()
    for flag in ("--skip-worktree", "--assume-unchanged"):
        base = tmp_path / flag.strip("-")
        roots, sup, moddir = make_super_with_submodule(base)
        sub = sup / "sub"
        git(sub, "update-index", flag, "f.txt")
        (sub / "f.txt").unlink()
        inner = sub / "f.txt"  # a directory that took the hidden file's place, holding a repository of its own
        inner.mkdir()
        git(inner, "init", "-b", "main")
        (inner / "precious.txt").write_text("local only\n")
        git(inner, "add", "precious.txt")
        git(inner, "commit", "-m", "precious local-only commit")
        assert mod.embedded_repositories(sub) == (0, [], [])  # the premise: the plain walk is blind to it
        c = scan_super(mod, roots)
        assert c["verdict"] == NESTED and not c.get("submodules_vetted"), (flag, c)
        row = skipped_row(doc, c)
        assert "whole.tar" in row and f"counts unknown ({NESTED})" in row
        whole = unescape_span(re.search(r"`(mkdir -p [^`]*whole\.tar[^`]*)`", row).group(1))
        dest, home = tmp_path / ("dest" + flag.strip("-")), tmp_path / ("home" + flag.strip("-"))
        dest.mkdir()
        home.mkdir()
        run = subprocess.run(["bash", "-c", PLAN_PREFIX + whole.replace("<DEST>", str(dest))], capture_output=True, text=True,
                             env={**GIT_ENV, "HOME": str(home)})
        assert run.returncode == 0, run.stderr
        import tarfile
        names = tarfile.open(next(dest.rglob("whole.tar"))).getnames()
        assert any(n.endswith("sub/f.txt/precious.txt") for n in names), names  # the inner commit's worktree and `.git` are in it
        assert any("sub/f.txt/.git/" in n for n in names), names
        # the walk failing is not a scanned submodule either
        real = mod.index_hidden_repositories
        monkeypatch.setattr(mod, "index_hidden_repositories",
                            lambda p: (0, [], [], ("ls-files --others under index-hidden paths", 124)) if p.name == "sub" else real(p))
        assert scan_super(mod, roots)["verdict"] == "skipped: submodule config unrecognised (unreadable, timed out or too large)"
        monkeypatch.undo()
        # more hidden directories than MAX_EMBEDDED is a failure of the walk (rc 0), with the same label
        monkeypatch.setattr(mod, "MAX_EMBEDDED", 0)
        assert scan_super(mod, roots)["verdict"] == "skipped: submodule config unrecognised (unreadable, timed out or too large)"
        monkeypatch.undo()
        # a hidden path that is a plain directory finds nothing: the submodule stays vetted
        shutil.rmtree(inner)
        inner.mkdir()
        (inner / "plain.txt").write_text("x\n")
        c = scan_super(mod, roots)
        assert not c["verdict"].startswith("skipped") and c["submodules_vetted"] == ["sub"], (flag, c)


ALTERNATES = "skipped: submodule config unrecognised (alternates)"
ALTERNATES_WARNING = ("objects/info/alternates points outside this checkout; the store it names is NOT archived: do not "
                      "delete the checkout or that store until its commits are bundled")


def skipped_row(doc, c) -> str:
    row = next(r for r in section_3_2(doc.render(doc_scan([c]))).splitlines() if r.startswith(f"| {doc.tilde(c['path'])} "))
    return row.replace("\\|", "|")


def test_the_alternates_skip_names_its_store_and_refuses_a_cleanup_other_skips_do_not(tmp_path):
    """Codex thread 10 on PR 27: the skipped row archived the worktree and git directories and said nothing about the
    object store `objects/info/alternates` names, which no archive holds."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    alt = moddir / "objects" / "info" / "alternates"
    alt.parent.mkdir(parents=True, exist_ok=True)
    alt.write_text("# a comment\n\n/stores/one\n/stores/with space $(x)\n/stores/three\n/stores/four\n")
    c = scan_super(mod, roots)
    assert c["verdict"] == ALTERNATES
    assert c["alternates"] == ["/stores/one", "/stores/with space $(x)", "/stores/three"]  # the first three, comments and blanks gone
    row = skipped_row(doc, c)
    assert ALTERNATES_WARNING in row and "do not clean up" in row.split("| yes:")[1]
    assert "/stores/one" in row and "'/stores/with space $(x)'" in row and "/stores/three" in row and "/stores/four" not in row
    assert "and the alternate object store" in row and "whole.tar" in row  # the generic archives are still there
    # a record from an older scan (no targets): the same warning, naming the file instead
    del c["alternates"]
    row = skipped_row(doc, c)
    assert ALTERNATES_WARNING in row and "`<gitdir>/objects/info/alternates`" in row
    # no other skipped or incomplete reason carries it
    for verdict in (NESTED, "skipped: submodule config unrecognised (symlink)", mod.SKIP_WORKTREE, mod.SKIP_GIT_SYMLINK,
                    "scan incomplete: status rc=124"):
        other = dict(c, verdict=verdict, flags=[verdict])
        row = skipped_row(doc, other)
        assert "NOT archived" not in row and "alternate object store" not in row and "objects/info/alternates" not in row
        assert "do not clean up" not in row, verdict
        assert row.rstrip().endswith("| yes: counts unknown; re-scan or archive whole |"), verdict


def test_every_skipped_or_incomplete_row_of_a_checkout_that_borrows_objects_warns_and_an_ordinary_one_does_not(tmp_path, monkeypatch):
    """Adversary round 64 on PR 27, LOW 3: the warning was for a module's alternates only; a `clone --shared` checkout
    skipped for any other reason offered `whole.tar` and the git-dir archive, neither of which holds the borrowed store."""
    mod, doc = load(), load_doc()
    origin = make_repo(tmp_path / "origin")
    store = str((origin / ".git" / "objects").resolve())
    roots = tmp_path / "roots"
    roots.mkdir()
    shared, plain = roots / "shared", roots / "plain"
    git(tmp_path, "clone", "-q", "--shared", str(origin), str(shared))
    git(tmp_path, "clone", "-q", str(origin), str(plain))
    assert (shared / ".git" / "objects" / "info" / "alternates").read_text().strip() == store
    ordinary = mod.scan_checkout(shared.resolve(), remote=False)  # borrowing alone skips nothing
    assert not ordinary["verdict"].startswith("skipped") and "alternates" not in ordinary, ordinary["verdict"]
    # skipped before the scan trusted any git call (an alias is an unrecognised config key)
    git(shared, "config", "alias.co", "checkout")
    git(plain, "config", "alias.co", "checkout")
    rec = mod.scan_checkout(shared.resolve(), remote=False)
    assert rec["verdict"] == "skipped: unrecognised config alias.co" and rec["alternates"] == [store]
    row = skipped_row(doc, rec)
    assert ALTERNATES_WARNING in row and store in row and "do not clean up" in row.split("| yes:")[1] and "whole.tar" in row
    # the same checkout without borrowed objects: the same skip, no key, no warning
    other = mod.scan_checkout(plain.resolve(), remote=False)
    assert other["verdict"] == rec["verdict"] and "alternates" not in other
    row = skipped_row(doc, other)
    assert "NOT archived" not in row and "do not clean up" not in row
    # a linked worktree reads its common directory's store (its `.git` is a file with a `commondir` behind it)
    wt = tmp_path / "wt"
    git(shared, "worktree", "add", "-q", "-b", "wt", str(wt))
    assert mod.scan_checkout(wt.resolve(), remote=False)["alternates"] == [store]
    # a skip after the scan trusted git: `scan incomplete` carries it too
    git(shared, "config", "--unset", "alias.co")
    monkeypatch.setattr(mod, "stash_count", lambda path, common: None)
    rec = mod.scan_checkout(shared.resolve(), remote=False)
    assert rec["verdict"].startswith("scan incomplete") and rec["alternates"] == [store], rec["verdict"]
    assert ALTERNATES_WARNING in skipped_row(doc, rec)
    monkeypatch.undo()
    # a nonempty file holding only a comment: borrowed, targets unknown; the row names the file instead
    (shared / ".git" / "objects" / "info" / "alternates").write_text("# nothing but a comment\n")
    git(shared, "config", "alias.co", "checkout")
    rec = mod.scan_checkout(shared.resolve(), remote=False)
    assert rec["alternates"] == []
    row = skipped_row(doc, rec)
    assert ALTERNATES_WARNING in row and "`<gitdir>/objects/info/alternates` of the checkout's git directory" in row
    # a record from an older scan has no key: it renders, with no warning
    del rec["alternates"]
    row = skipped_row(doc, rec)
    assert "NOT archived" not in row and "do not clean up" not in row


def test_a_skipped_checkouts_row_warns_about_a_store_its_git_dir_links_to_outside_the_checkout(tmp_path):
    """Adversary round 65 on PR 27, LOW 2: a checkout whose `.git/objects` (git-new-workdir, objects moved to another disk),
    `refs` or `packed-refs` is a symlink out is archived by `whole.tar` and the git-dir archive as the link alone, and the
    skipped row said nothing, where a borrowed (alternates) store gets a warning."""
    mod, doc = load(), load_doc()
    origin = make_repo(tmp_path / "origin")
    roots = tmp_path / "roots"
    roots.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    for member in ("objects", "refs", "packed-refs"):
        co = roots / member
        git(tmp_path, "clone", "-q", str(origin), str(co))
        commit_file(co, "local.txt")  # a local-only commit: the history lives in the store the link names
        git(co, "pack-refs", "--all")
        moved = outside / f"{member}-moved"
        os.rename(co / ".git" / member, moved)
        os.symlink(moved, co / ".git" / member)
        ordinary = mod.scan_checkout(co.resolve(), remote=False)  # a link alone skips nothing, and a bundle reads through it
        assert not ordinary["verdict"].startswith("skipped") and "linked_stores" not in ordinary, (member, ordinary["verdict"])
        git(co, "config", "alias.co", "checkout")  # now skipped before any git call
        rec = mod.scan_checkout(co.resolve(), remote=False)
        assert rec["verdict"] == "skipped: unrecognised config alias.co", member
        assert rec["linked_stores"] == [f"{member} -> {os.path.realpath(moved)}"], (member, rec.get("linked_stores"))
        assert "alternates" not in rec
        row = skipped_row(doc, rec)
        assert "is NOT archived" in row and "do not clean up" in row.split("| yes:")[1] and "whole.tar" in row, row
        assert f"{member} -> {os.path.realpath(moved)}" in row and "objects/info/alternates" not in row, row
    # a skip after the scan trusted git: `scan incomplete` carries it too
    plain = roots / "plain"
    git(tmp_path, "clone", "-q", str(origin), str(plain))
    other = mod.scan_checkout(plain.resolve(), remote=False)
    assert "linked_stores" not in other and not other["verdict"].startswith("skipped")
    git(plain, "config", "alias.co", "checkout")
    other = mod.scan_checkout(plain.resolve(), remote=False)
    assert other["verdict"].startswith("skipped") and "linked_stores" not in other
    assert "NOT archived" not in skipped_row(doc, other)
    # a record from an older scan has no key: it renders with no warning
    del rec["linked_stores"]
    assert "NOT archived" not in skipped_row(doc, rec)


def test_an_error_reading_a_skipped_checkouts_git_dir_leaves_the_generic_alternates_warning_not_silence(tmp_path):
    """Adversary round 65 on PR 27, INFO 1: an unreadable `objects/info`, an unreadable gitfile or a FIFO `commondir` made
    the warning code read nothing and stay quiet, where the conservative reading (tar fails loudly, but only later) is the
    generic warning that names the file."""
    mod, doc = load(), load_doc()
    origin = make_repo(tmp_path / "origin")
    roots = tmp_path / "roots"
    roots.mkdir()

    def warns(rec) -> None:
        assert rec["alternates"] == [], rec
        row = skipped_row(doc, rec)
        assert ALTERNATES_WARNING in row and "`<gitdir>/objects/info/alternates` of the checkout's git directory" in row, row

    fifo = roots / "fifo"
    git(tmp_path, "clone", "-q", str(origin), str(fifo))
    os.mkfifo(fifo / ".git" / "commondir")
    rec = mod.scan_checkout(fifo.resolve(), remote=False)
    assert rec["verdict"] == mod.SKIP_COMMONDIR, rec["verdict"]
    warns(rec)
    if os.geteuid() == 0:
        return  # root reads a mode 0 file: the permission cases below cannot be made
    info = roots / "noinfo"
    git(tmp_path, "clone", "-q", str(origin), str(info))
    git(info, "config", "alias.co", "checkout")
    os.chmod(info / ".git" / "objects" / "info", 0)
    try:
        rec = mod.scan_checkout(info.resolve(), remote=False)
        assert rec["verdict"] == "skipped: unrecognised config alias.co", rec["verdict"]
        warns(rec)
    finally:
        os.chmod(info / ".git" / "objects" / "info", 0o755)
    work = tmp_path / "wt"
    git(info, "worktree", "add", "-q", "-b", "wt", str(work))
    os.chmod(work / ".git", 0)
    try:
        rec = mod.scan_checkout(work.resolve(), remote=False)
        assert rec["verdict"].startswith("skipped"), rec["verdict"]
        warns(rec)
    finally:
        os.chmod(work / ".git", 0o644)


def test_a_git_dir_with_a_commondir_file_is_skipped_before_any_git_call_and_a_linked_worktree_is_not(tmp_path, monkeypatch):
    """Cursor security review on PR 27, MEDIUM: `.git/commondir` in a `.git` DIRECTORY names another git directory, and
    every later `git -C` call, `--fetch` among them (it writes objects), then acted on that store. A linked worktree's
    `.git` is a gitfile, so it is not this case."""
    mod, doc = load(), load_doc()
    roots, work, origin = make_pushed_checkout(tmp_path)  # `work`: the store the planted file will name
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    commit_file(other, "o.txt")
    git(other, "push", "origin", "main")  # origin's tip: its objects are not in `work`, so a --fetch would download them
    commit_file(work, "w.txt")  # diverged and unpushed: the tip must be compared
    victim = (work / ".git").resolve()
    decoy = roots / "decoy"
    decoy.mkdir()
    git(decoy, "init", "-b", "main")
    (decoy / ".git" / "commondir").write_text(str(victim) + "\n")
    objects_before = sorted(str(p) for p in (victim / "objects").rglob("*"))
    # a fake `git` that logs every call before running the real one
    real = shutil.which("git")
    fakebin, log = tmp_path / "fakebin", tmp_path / "git.log"
    fakebin.mkdir()
    (fakebin / "git").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
    (fakebin / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    mod._remote_cache.clear()
    rec = mod.scan_checkout(decoy.resolve(), remote=True, fetch=True)
    assert rec["verdict"] == mod.SKIP_COMMONDIR == "skipped: git dir redirected (commondir)", rec["verdict"]
    assert not log.exists(), log.read_text()  # not one git call, `fetch` least of all
    assert sorted(str(p) for p in (victim / "objects").rglob("*")) == objects_before
    assert rec["linked_stores"] == [f"commondir -> {victim}"]  # the row says the named store is archived nowhere
    assert "is NOT archived" in skipped_row(doc, rec)
    # control: the same `--fetch` scan of the real store downloads origin's tip (so the guard above is what stopped it)
    mod._remote_cache.clear()
    real_rec = mod.scan_checkout(work.resolve(), remote=True, fetch=True)
    assert not real_rec["verdict"].startswith("skipped") and "fetch" in log.read_text(), real_rec["verdict"]
    # a linked worktree: `.git` is a file, its admin dir holds a `commondir`, and it is scanned as before
    monkeypatch.undo()
    wt = tmp_path / "wt"
    git(work, "worktree", "add", "-q", "-b", "wt", str(wt))
    assert (wt / ".git").is_file() and (work / ".git" / "worktrees").is_dir()
    c = mod.scan_checkout(wt.resolve(), remote=False)
    assert not c["verdict"].startswith("skipped") and "linked_stores" not in c, c["verdict"]
    # and an empty `commondir` file in a `.git` directory is still a redirect attempt: refused too
    (decoy / ".git" / "commondir").write_text("")
    assert mod.scan_checkout(decoy.resolve(), remote=False)["verdict"] == mod.SKIP_COMMONDIR


def counting_git(tmp_path: Path, monkeypatch) -> Path:
    """Put a `git` first on PATH that logs each call's arguments, then runs the real one. The log file does not exist while
    no call was made."""
    real = shutil.which("git")
    fakebin, log = tmp_path / "fakebin", tmp_path / "git.log"
    fakebin.mkdir()
    (fakebin / "git").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
    (fakebin / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    return log


def test_a_gitfile_whose_git_dir_does_not_point_back_is_skipped_before_any_git_call_and_fetch_writes_nothing(tmp_path, monkeypatch):
    """Adversary round 66 on PR 27, MEDIUM: the commondir repair closed the `.git` directory form only. A gitfile naming
    another checkout's `.git` (or a planted admin dir holding a `commondir`) made every later git call, `--fetch`
    (it writes objects) among them, act on that store, and came back as an ordinary row under the decoy's path. The git
    dir must point back to the checkout."""
    mod, doc = load(), load_doc()
    roots, work, origin = make_pushed_checkout(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", str(origin), str(other))
    commit_file(other, "o.txt")
    git(other, "push", "origin", "main")  # origin's tip: its objects are not in `work`, so a --fetch would download them
    commit_file(work, "w.txt")  # diverged and unpushed: the tip must be compared
    victim = (work / ".git").resolve()
    wt = tmp_path / "wt"
    git(work, "worktree", "add", "-q", "-b", "wt", str(wt))
    wt_admin = Path(git(wt, "rev-parse", "--absolute-git-dir").strip()).resolve()
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(bare))
    stores = [victim, bare.resolve()]
    before = {s: sorted(str(p) for p in (s / "objects").rglob("*")) for s in stores}
    log = counting_git(tmp_path, monkeypatch)

    def decoy(name: str, text: str | None = None) -> Path:
        d = roots / name
        d.mkdir()
        if text is not None:
            (d / ".git").write_text(text)
        return d

    def planted(name: str, config: bool) -> tuple[Path, Path]:
        """The decoy with its own admin dir: `HEAD`, `commondir` naming the victim, and a back-pointer that is right
        (`gitdir`, or `core.worktree` in `config`) - the Cursor layout with one more hop."""
        d = decoy(name, "gitdir: .admin\n")
        admin = d / ".admin"
        admin.mkdir()
        (admin / "HEAD").write_text("ref: refs/heads/main\n")
        (admin / "commondir").write_text(f"{victim}\n")
        if config:
            (admin / "config").write_text(f"[core]\n\tworktree = {d}\n")
        else:
            (admin / "gitdir").write_text(f"{d / '.git'}\n")
        return d, admin.resolve()

    cases = []  # (checkout, linked_stores wanted: None when the record carries none)
    cases.append((decoy("direct", f"gitdir: {victim}\n"), [f"git dir -> {victim}"]))
    cases.append((decoy("relative", "gitdir: ../work/.git\n"), [f"git dir -> {victim}"]))
    cases.append((decoy("bare", f"gitdir: {bare}\n"), [f"git dir -> {bare.resolve()}"]))
    nowhere = tmp_path.resolve() / "nowhere"  # a target that does not exist
    cases.append((decoy("gone", f"gitdir: {nowhere}\n"), [f"git dir -> {nowhere}"]))
    cases.append((decoy("another-worktree", f"gitdir: {wt_admin}\n"), [f"git dir -> {wt_admin}", f"commondir -> {victim}"]))
    d, admin = planted("planted-admin", config=False)
    cases.append((d, [f"git dir -> {admin}", f"commondir -> {victim}"]))
    d, admin = planted("planted-config", config=True)
    cases.append((d, [f"git dir -> {admin}", f"commondir -> {victim}"]))
    cases.append((decoy("garbage", "not a gitfile\n"), None))
    for checkout, linked in cases:
        mod._remote_cache.clear()
        rec = mod.scan_checkout(checkout.resolve(), remote=True, fetch=True)
        assert rec["verdict"] == mod.SKIP_GIT_DIR_FOREIGN == "skipped: git dir redirected (does not point back to this checkout)", \
            (checkout.name, rec["verdict"])
        assert not log.exists(), (checkout.name, log.read_text())  # not one git call, `fetch` least of all
        assert rec.get("linked_stores") == linked, (checkout.name, rec.get("linked_stores"))
        if linked:
            assert "is NOT archived" in skipped_row(doc, rec), checkout.name
    for store in stores:
        assert sorted(str(p) for p in (store / "objects").rglob("*")) == before[store], store
    # control: the same `--fetch` scan of the real store downloads origin's tip (so the guard above is what stopped it)
    mod._remote_cache.clear()
    real_rec = mod.scan_checkout(work.resolve(), remote=True, fetch=True)
    assert not real_rec["verdict"].startswith("skipped") and "fetch" in log.read_text(), real_rec["verdict"]


def test_a_git_dir_that_points_back_to_the_checkout_stays_scanned_and_a_stale_back_pointer_does_not(tmp_path):
    """Adversary round 66 on PR 27: the layouts git itself builds must not be skipped for the redirect check: a main
    checkout, `git worktree add`, an absorbed submodule (`core.worktree` in the module's config) and any git dir whose
    `core.worktree` names the checkout. git writes NO back-pointer for `clone --separate-git-dir` or `init
    --separate-git-dir` (git 2.56: neither `gitdir` nor `core.worktree`), so nothing tells such a gitfile from a decoy
    naming another checkout's store: those are skipped, with the whole-directory row."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    # a main checkout and a linked worktree
    assert mod.git_dir_foreign(work) is None and not mod.scan_checkout(work.resolve(), remote=False)["verdict"].startswith("skipped")
    wt = tmp_path / "wt"
    git(work, "worktree", "add", "-q", "-b", "wt", str(wt))
    assert mod.git_dir_foreign(wt.resolve()) is None
    c = mod.scan_checkout(wt.resolve(), remote=False)
    assert not c["verdict"].startswith("skipped") and "linked_stores" not in c, c["verdict"]
    # moved without `git worktree repair`: the admin dir's `gitdir` still names the old place, so it no longer points back
    moved = tmp_path / "wt-moved"
    wt.rename(moved)
    assert mod.git_dir_foreign(moved.resolve()) == mod.SKIP_GIT_DIR_FOREIGN
    git(work, "worktree", "repair", str(moved))
    assert mod.git_dir_foreign(moved.resolve()) is None
    # an absorbed submodule, made by `submodule add` and by `absorbgitdirs`: `core.worktree` in the module's config
    sroots, sup, moddir = make_super_with_submodule(tmp_path / "s")
    emb_origin = make_repo(tmp_path / "emb-origin")
    git(sup, "clone", "-q", str(emb_origin), "emb")
    git(sup, "config", "-f", ".gitmodules", "submodule.emb.path", "emb")
    git(sup, "config", "-f", ".gitmodules", "submodule.emb.url", str(emb_origin))
    git(sup, "add", ".gitmodules", "emb")
    git(sup, "-c", "protocol.file.allow=always", "submodule", "absorbgitdirs")
    assert (sup / "emb" / ".git").is_file() and "worktree" in (sup / ".git" / "modules" / "emb" / "config").read_text()
    for sub in (sup / "sub", sup / "emb"):
        assert mod.git_dir_foreign(sub) is None, sub
        assert mod.scan_checkout(sub.resolve(), remote=False)["verdict"] == mod.SKIP_WORKTREE, sub  # git's own core.worktree: as before
    # the submodule's gitfile naming ANOTHER module's git dir does not point back
    (sup / "emb" / ".git").write_text(f"gitdir: {moddir}\n")
    assert mod.git_dir_foreign(sup / "emb") == mod.SKIP_GIT_DIR_FOREIGN
    # `--separate-git-dir`: no back-pointer exists
    for how in ("clone", "init"):
        sep, gd = tmp_path / f"sep-{how}", tmp_path / f"gd-{how}"
        if how == "clone":
            git(tmp_path, "clone", "-q", f"--separate-git-dir={gd}", str(origin), str(sep))
        else:
            make_repo(sep)
            git(sep, "init", "-q", f"--separate-git-dir={gd}")
        assert (sep / ".git").is_file() and gd.is_dir()
        assert mod.git_dir_foreign(sep.resolve()) == mod.SKIP_GIT_DIR_FOREIGN, how
        assert mod.scan_checkout(sep.resolve(), remote=False)["verdict"] == mod.SKIP_GIT_DIR_FOREIGN, how
        # a `core.worktree` naming the checkout is the back-pointer (older git, `git config`): the last value of `core`
        base = (gd / "config").read_text()
        elsewhere = tmp_path / "elsewhere"
        for text, want in ((f'[core]\n\tworktree = "{sep}" # back\n', None),
                           (f"[CORE]\n\tWorkTree = {sep}\n", None),
                           (f"[core] worktree = {sep}\n", None),
                           (f"[core]\n\tworktree = {elsewhere}\n\tworktree = {sep}\n", None),
                           (f"[core]\n\tworktree = {sep}\n\tworktree = {elsewhere}\n", mod.SKIP_GIT_DIR_FOREIGN),
                           (f'[core "x"]\n\tworktree = {sep}\n', mod.SKIP_GIT_DIR_FOREIGN),
                           (f"[remote]\n\tworktree = {sep}\n", mod.SKIP_GIT_DIR_FOREIGN),
                           (f"[core]\n\tworktree = {elsewhere}\n", mod.SKIP_GIT_DIR_FOREIGN),
                           (f"[core]\n\tworktree = {sep}\\\n", mod.SKIP_GIT_DIR_FOREIGN),
                           ("[core]\n\tworktree =\n", mod.SKIP_GIT_DIR_FOREIGN)):
            (gd / "config").write_text(base + text)
            assert mod.git_dir_foreign(sep.resolve()) == want, (how, text)
        (gd / "config").write_text(base + f"[core]\n\tworktree = {sep}\n")
        assert mod.scan_checkout(sep.resolve(), remote=False)["verdict"] == mod.SKIP_WORKTREE
        # and a `commondir` in a git dir that names the checkout back is still refused unless it sits under `worktrees/`
        (gd / "commondir").write_text(f"{(work / '.git').resolve()}\n")
        assert mod.git_dir_foreign(sep.resolve()) == mod.SKIP_GIT_DIR_FOREIGN


def test_a_symlink_anywhere_inside_objects_refs_or_logs_is_listed_on_a_skipped_row_and_a_failed_walk_warns(tmp_path, monkeypatch):
    """Adversary round 66 on PR 27, LOW 1: only the top-level `objects`, `refs` and `packed-refs` were checked, so a moved
    and linked `objects/pack`, `refs/heads` or `logs` (the stash reflog) was archived as a link with nothing said."""
    mod, doc = load(), load_doc()
    origin = make_repo(tmp_path / "origin")
    roots = tmp_path / "roots"
    roots.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    for member in ("objects/pack", "refs/heads", "logs", "logs/refs", "shallow"):
        co = roots / member.replace("/", "_")
        git(tmp_path, "clone", "-q", str(origin), str(co))
        moved = outside / member.replace("/", "_")
        if member == "shallow":
            (co / ".git" / "shallow").write_text("")
        os.rename(co / ".git" / member, moved)
        os.symlink(moved, co / ".git" / member)
        if member != "shallow":  # git itself reads through the link; an empty `shallow` file is read as no shallow commits
            ordinary = mod.scan_checkout(co.resolve(), remote=False)
            assert not ordinary["verdict"].startswith("skipped") and "linked_stores" not in ordinary, (member, ordinary["verdict"])
        git(co, "config", "alias.co", "checkout")  # now skipped before any git call
        rec = mod.scan_checkout(co.resolve(), remote=False)
        assert rec["verdict"] == "skipped: unrecognised config alias.co", member
        assert rec["linked_stores"] == [f"{member} -> {os.path.realpath(moved)}"], (member, rec.get("linked_stores"))
        row = skipped_row(doc, rec)
        assert "is NOT archived" in row and f"{member} -> {os.path.realpath(moved)}" in row, row
    # at most 4 are recorded, in name order, and a plain skipped checkout carries none
    many = roots / "many"
    git(tmp_path, "clone", "-q", str(origin), str(many))
    for i in range(6):
        os.symlink(outside, many / ".git" / "refs" / "tags" / f"t{i}")
    git(many, "config", "alias.co", "checkout")
    rec = mod.scan_checkout(many.resolve(), remote=False)
    assert rec["linked_stores"] == [f"refs/tags/t{i} -> {os.path.realpath(outside)}" for i in range(4)], rec.get("linked_stores")
    plain = roots / "plain"
    git(tmp_path, "clone", "-q", str(origin), str(plain))
    git(plain, "config", "alias.co", "checkout")
    assert "linked_stores" not in mod.scan_checkout(plain.resolve(), remote=False)
    # more entries than the walk may visit: the generic warning, never silence
    monkeypatch.setattr(mod, "MAX_STORE_WALK", 3)
    rec = mod.scan_checkout(plain.resolve(), remote=False)
    assert rec["alternates"] == [], rec
    assert ALTERNATES_WARNING in skipped_row(doc, rec)
    monkeypatch.undo()
    # an unreadable directory inside the trees: the same
    if os.geteuid() != 0:
        heads = plain / ".git" / "refs" / "heads"
        os.chmod(heads, 0)
        try:
            rec = mod.scan_checkout(plain.resolve(), remote=False)
            assert rec["alternates"] == [], rec
            assert ALTERNATES_WARNING in skipped_row(doc, rec)
        finally:
            os.chmod(heads, 0o755)


def test_a_stash_whose_reflog_expired_is_captured_from_refs_stash_by_the_generated_row(tmp_path):
    """Codex pass 65 on PR 27, P2: after `git reflog expire --expire=now --all` `refs/stash` survives with a zero-byte log;
    the scan counts a stash, and the row's capture command enumerated the reflog only, failed its nonempty-list guard
    with rc 1 and saved nothing."""
    mod, doc = load(), load_doc()
    roots, work, origin = make_pushed_checkout(tmp_path)
    (work / "a.txt").write_text("stashed edit\n")
    (work / "new.bin").write_bytes(b"\x00\x01untracked\n")
    git(work, "stash", "push", "-u", "-m", "kept")
    git(work, "reflog", "expire", "--expire=now", "--all")
    assert git(work, "log", "-g", "--format=%gd", "refs/stash") == ""  # the premise: a ref, no entries
    c = scan_one(mod, roots)
    assert c["stashes"] == 1 and "stash" in c["flags"], c  # the checkout is listed for its stash alone
    row = next(r for r in section_3_2(doc.render(doc_scan([c]))).splitlines() if r.startswith("| " + doc.tilde(c["path"])))
    assert "1 stash" in row
    spans = re.findall(r"(?<!`)(`+) (.+?) \1(?!`)|(?<!`)`([^`]+)`(?!`)", row)
    cmd = next(unescape_span(fenced or single) for _f, fenced, single in spans if "log -g --format=%gd refs/stash" in (fenced or single))
    home = tmp_path / "home"
    dest = tmp_path / "dest"
    home.mkdir()
    dest.mkdir()
    for shell in SHELLS:
        run = subprocess.run([shell, "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True,
                             env={**GIT_ENV, "HOME": str(home)})
        assert run.returncode == 0, (shell, run.stderr)
        patch = next(dest.rglob("stash.patch")).read_text()
        assert "stashed edit" in patch and "new.bin" in patch and "GIT binary patch" in patch, (shell, patch)  # the commit's content, untracked file too
        assert next(dest.rglob("stash-index.patch")).is_file()
        shutil.rmtree(dest)
        dest.mkdir()
    # no stash left at all (`refs/stash` gone): the command still fails loudly, with nothing saved
    git(work, "stash", "clear")
    for shell in SHELLS:
        assert subprocess.run([shell, "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True,
                              env={**GIT_ENV, "HOME": str(home)}).returncode != 0


def fake_git_flooding_ls_remote(tmp_path: Path, monkeypatch, nbytes: int, sigpipe_proof: bool = False) -> Path:
    """A `git` ahead of the real one on PATH: `ls-remote` prints valid refs forever (`nbytes` 0) or `nbytes` bytes of them,
    everything else runs the real git. The pid of the writer goes to the returned file."""
    real = shutil.which("git")
    assert real
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    pidfile = tmp_path / "writer.pid"
    script = fakebin / "git"
    script.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        '*" ls-remote "*)\n'
        '  line=$(printf \'%040d\\trefs/heads/flood\' 1)\n'
        + (f'  trap \'\' PIPE; ( while :; do echo "$line" 2>/dev/null; done ) &\n' if sigpipe_proof and not nbytes
           else f'  if [ {nbytes} -eq 0 ]; then yes "$line" & else yes "$line" | head -c {nbytes} & fi\n') +
        f'  echo $! > "{pidfile}"; wait $!; exit 0;;\n'
        "esac\n"
        f'exec "{real}" "$@"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ['PATH']}")
    return pidfile


def test_an_ls_remote_answer_past_the_byte_cap_is_killed_and_reads_as_origin_unreachable(tmp_path, monkeypatch):
    """Codex thread 11 on PR 27: `run` buffered all of `ls-remote`'s stdout and every valid ref was kept; an origin that
    advertises without end could not be bounded. The prefix of an advertisement is never read as the whole answer."""
    mod = load()
    roots, work, origin = make_pushed_checkout(tmp_path)
    assert scan_one(mod, roots, remote=True)["verdict"] == "clean and pushed"  # the real ls-remote, under the cap
    monkeypatch.setattr(mod, "LS_REMOTE_MAX_BYTES", 1024 * 1024, raising=False)
    fake_git_flooding_ls_remote(tmp_path, monkeypatch, 2 * 1024 * 1024)  # 2 MiB of valid refs, finite
    mod._remote_cache.clear()
    assert mod.ls_remote_refs(str(origin)) is None
    mod._remote_cache.clear()
    c = scan_one(mod, roots, remote=True)
    assert mod.ORIGIN_UNREACHABLE in c["flags"] and c["verdict"] != "clean and pushed", c["flags"]
    assert c["local_only_verified"] is False
    # the same fake under the cap is an answer: the cap is a size, not a ban
    (tmp_path / "small").mkdir()
    fake_git_flooding_ls_remote(tmp_path / "small", monkeypatch, 58 * 70)  # 70 whole lines of 58 bytes
    mod._remote_cache.clear()
    heads, tags, invalid = mod.ls_remote_refs(str(origin))
    assert heads == {"flood": "0" * 39 + "1"} and tags == {} and invalid == 0


def test_run_with_max_bytes_kills_an_endless_writer_and_its_group_and_keeps_every_exact_fit(tmp_path, monkeypatch):
    mod = load()
    # the writer ignores SIGPIPE and keeps writing into a closed pipe, so only the group kill ends it (a `yes` would die
    # of the SIGPIPE when `run` closes stdout, whether or not the kill happened: adversary round 64, LOW 2)
    pidfile = fake_git_flooding_ls_remote(tmp_path, monkeypatch, 0, sigpipe_proof=True)  # prints without end
    env = dict(os.environ)
    result: list = []
    t = threading.Thread(target=lambda: result.append(mod.run(["git", "ls-remote"], timeout=30, env=env, max_bytes=100_000)),
                         daemon=True)
    t.start()
    t.join(20)
    ypid = int(pidfile.read_text())
    if t.is_alive():  # without the group kill `run` waits for a child that never ends: free it, then fail
        os.kill(ypid, 9)
        t.join(10)
        raise AssertionError("run() did not return: the endless writer was not killed")
    assert result == [(mod.RC_OUTPUT_CAP, "")]
    for _ in range(100):  # the writer died with its parent's process group
        try:
            os.kill(ypid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(ypid, 9)
        raise AssertionError("the writer survived the cap")
    assert mod.run(["printf", "%s", "abcd"], max_bytes=4) == (0, "abcd")  # exactly the cap fits
    assert mod.run(["printf", "%s", "abcde"], max_bytes=4) == (mod.RC_OUTPUT_CAP, "")
    assert mod.run(["sh", "-c", "printf ab; exit 3"], max_bytes=4) == (3, "ab")  # the child's own rc survives
    start = time.monotonic()
    assert mod.run(["sleep", "30"], timeout=0.3, max_bytes=4) == (124, "")  # and the time limit still applies
    assert time.monotonic() - start < 5, "the timeout did not kill the child's group: run() waited for it"


def test_the_plan_runs_git_in_the_scanners_environment_not_the_operators(tmp_path):
    """Codex pass 42 (P1): with `GIT_DIR` pointing at another repository, `git -C <checkout> ls-files` listed that
    repository's files and the tar that followed succeeded without the checkout's only untracked file."""
    doc = load_doc()
    other = make_repo(tmp_path / "other", "o.txt")
    work = make_repo(tmp_path / "work", "w.txt")
    (work / "mine.txt").write_text("untracked in the checkout\n")
    cmd = doc.shcode(doc.UNTRACKED_FMT, "ck", str(work), "ck/untracked.list", str(work), "ck/untracked.list", "ck/untracked.tar")
    cmd = unescape_span(cmd.strip("` "))
    for shell in SHELLS:
        dest = tmp_path / f"dest-{shell}"
        env = {**GIT_ENV, "GIT_DIR": str(other / ".git"), "GIT_INDEX_FILE": str(other / ".git" / "index")}
        run = subprocess.run([shell, "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], cwd=tmp_path,
                             capture_output=True, text=True, env=env)
        assert run.returncode == 0, (shell, run.stderr)
        assert (dest / "ck" / "untracked.list").read_bytes() == b"mine.txt\0", (shell, (dest / "ck" / "untracked.list").read_bytes())


def test_the_preamble_clears_every_git_variable_without_a_pipeline_and_survives_hostile_values(tmp_path):
    """Codex pass 44 on PR 27, P1: `unset $(env | grep | cut)` hid a failure of `env` behind a pipeline. The loop clears
    each `GIT_*` name from `env` (a multi-line value cannot name anything but a plain variable), reports an `env` that fails,
    and leaves PATH and the GNU tool names alone."""
    doc = load_doc()
    assert " | " not in doc.PLAN_PREAMBLE and "grep" not in doc.PLAN_PREAMBLE and "cut " not in doc.PLAN_PREAMBLE
    probe = ('; printf "%s|" "${GIT_DIR-unset}" "${GIT_INDEX_FILE-unset}" "${GIT_CONFIG_COUNT-unset}" "${GIT_KEY_0-unset}" '
             '"${GIT_CONFIG_GLOBAL-unset}" "${GIT_CONFIG_NOSYSTEM-unset}" "${XYZ+kept}" "${_E-unset}" "${_L-unset}"; '
             'test -n "$GTAR" && command -v git >/dev/null && echo ok')
    hostile = "v\nGIT_Q PATH\nGIT_A$(touch " + str(tmp_path / "PWN") + ")=x\nGIT_*=y\nGIT_Z=1"
    for shell in SHELLS:
        if shell == "sh":
            continue  # `<<<` is bash and zsh; the plan is pasted into one of those
        env = {**os.environ, "GIT_DIR": "/x", "GIT_INDEX_FILE": "/y", "GIT_CONFIG_COUNT": "1", "GIT_KEY_0": "k", "XYZ": hostile}
        run = subprocess.run([shell, "-c", doc.PLAN_PREAMBLE + probe], capture_output=True, text=True, env=env)
        # a git older than 2.45 makes the preamble warn, by design (Codex pass 47 on PR 27, P1: Ubuntu's git is 2.43)
        assert run.returncode == 0 and (run.stderr == "" or (git_version() < (2, 45) and run.stderr.startswith("git older than 2.45"))), (shell, run.stderr)
        assert run.stdout == "unset|unset|unset|unset|/dev/null|1|kept|unset|unset|ok\n", (shell, run.stdout)
        assert not (tmp_path / "PWN").exists()
        # round 50: an `IFS` holding `_` or a letter of a variable name must not split the name `unset` is given
        run = subprocess.run([shell, "-c", "IFS=_G; " + doc.PLAN_PREAMBLE + probe.replace("test -n", "IFS=' '; test -n")],
                             capture_output=True, text=True, env=env)
        assert run.returncode == 0 and run.stdout.startswith("unset|unset|unset|unset|"), (shell, run.stdout, run.stderr)
        # an `env` that fails is reported, and the fixed floor still clears the variables that matter most
        run = subprocess.run([shutil.which(shell), "-c", doc.PLAN_PREAMBLE + '; printf "%s|" "${GIT_DIR-unset}" "${GIT_CONFIG_COUNT-unset}"'],
                             capture_output=True, text=True,
                             env={"PATH": "/nonexistent", "GIT_DIR": "/x", "GIT_CONFIG_COUNT": "1"})  # no BASH_ENV: it may define `env`
        assert "env failed: GIT_* not cleared" in run.stderr and run.stdout == "unset|unset|", (shell, run.stdout, run.stderr)


def test_the_preamble_disables_lazy_fetch_and_warns_on_a_git_that_ignores_it(tmp_path):
    """Codex pass 45 on PR 27, P1: in a partial clone `git bundle create --all` ran `git fetch origin` (a promisor
    download), so even the bundle alternative for a credential-bearing or helper-backed origin could contact it."""
    doc = load_doc()
    assert "GIT_NO_LAZY_FETCH=1" in doc.PLAN_PREAMBLE
    for version, warned in (("2.30.0", True), ("2.44.9", True), ("2.45.0", False), ("2.50.1 (Apple Git-155)", False),
                            ("3.0.1", False), ("2.5.0", True), ("2.100.0", False), ("10.0.0", False), ("2.450.0", False)):
        fake = tmp_path / f"bin-{version.split()[0]}"
        fake.mkdir()
        (fake / "git").write_text(f"#!/bin/sh\necho 'git version {version}'\n")
        (fake / "git").chmod(0o755)
        for shell in ("bash", "zsh"):
            if shutil.which(shell) is None:
                continue
            run = subprocess.run([shutil.which(shell), "-c", doc.PLAN_PREAMBLE + '; printf "%s" "$GIT_NO_LAZY_FETCH"'],
                                 capture_output=True, text=True,
                                 env={"PATH": f"{fake}:/usr/bin:/bin", "GIT_NO_LAZY_FETCH": "0"})
            assert run.stdout == "1", (version, shell, run.stdout)
            assert ("older than 2.45" in run.stderr) is warned, (version, shell, run.stderr)


def test_a_commit_only_the_stash_remembers_is_local_work(tmp_path):
    """Adversary round 51 on PR 27, MEDIUM: a commit reachable only through the stash (the base an entry was made on, once
    its branch is deleted) was excluded from every count with the stash itself, and no capture holds it."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    c = scan_one(mod, roots)
    assert c["verdict"] == "clean and pushed"
    git(work, "switch", "-c", "x")
    (work / "secret.txt").write_text("ONLY-IN-B\n")
    git(work, "add", "secret.txt")
    git(work, "commit", "-m", "B")
    (work / "a.txt").write_text("dirty\n")
    git(work, "stash")
    git(work, "switch", "main")
    git(work, "branch", "-D", "x")
    c = scan_one(mod, roots)
    assert c["stashes"] == 1 and c["local_only_commits"] == 1 and c["verdict"] != "clean and pushed", c
    # an ordinary stash on a pushed base stays what it was: no local-only commit
    git(work, "stash", "drop")
    (work / "a.txt").write_text("dirty again\n")
    git(work, "stash")
    c = scan_one(mod, roots)
    assert c["stashes"] == 1 and c["local_only_commits"] == 0, c


def _stash_on_deleted_branch(work, name):
    git(work, "switch", "-c", name)
    (work / f"{name}.txt").write_text(f"ONLY-IN-{name}\n")
    git(work, "add", f"{name}.txt")
    git(work, "commit", "-m", name)
    (work / "a.txt").write_text(f"dirty {name}\n")
    git(work, "stash")
    git(work, "switch", "main")
    git(work, "branch", "-D", name)


def test_the_base_of_an_older_stash_entry_is_counted_and_gets_the_reflog_pack(tmp_path):
    """Adversary round 52 on PR 27, MEDIUM 1: stash@{1}'s base was counted local-only, but the plan's `--all` bundle
    reaches only stash@{0}'s and no reflog pack row was emitted, so the row claimed work it did not capture."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    _stash_on_deleted_branch(work, "x")
    _stash_on_deleted_branch(work, "y")
    c = scan_one(mod, roots)
    assert c["stashes"] == 2 and c["local_only_commits"] == 1 and c["verdict"] != "clean and pushed", c
    assert c["reflog_only_commits"] == 1, c  # counted once: the tip's base above, the older entry's here  # the older entry's base: no ref holds it, `--all` does not reach it
    # an ordinary pair of stashes on a pushed base stays free of both counts
    (tmp_path / "plain").mkdir()
    roots, work, _ = make_pushed_checkout(tmp_path / "plain")
    for n in (1, 2):
        (work / "a.txt").write_text(f"dirty {n}\n")
        git(work, "stash")
    c = scan_one(mod, roots)
    assert c["stashes"] == 2 and c["local_only_commits"] == 0 and c["reflog_only_commits"] == 0, c


def test_a_stash_ref_with_an_expired_reflog_is_still_a_stash_with_its_base_counted(tmp_path):
    """Adversary round 52 on PR 27, MEDIUM 2: `git reflog expire --expire=now --all` leaves `refs/stash` and a
    zero-byte log; the count saw no entries, so no base, and the whole stash ancestry was excluded."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    _stash_on_deleted_branch(work, "x")
    git(work, "reflog", "expire", "--expire=now", "--all")
    c = scan_one(mod, roots)
    assert c["stashes"] >= 1 and c["local_only_commits"] == 1 and c["verdict"] != "clean and pushed", c


def test_a_branch_name_that_is_not_utf8_gets_one_bundle_of_every_ref_and_no_push():
    """Codex pass 48 on PR 27, P1: the scanner decodes a non-UTF-8 ref name to U+FFFD, so `refs/heads/<name>` named no
    ref and both alternatives failed; only `bundle create --all` can hold the commits."""
    doc = load_doc()
    odd = "b\ufffd"
    head = doc_checkout("/p/o", branch=odd, unpushed=2, ahead_of_origin=2, flags=["unpushed commits"], verdict="unpushed commits")
    other = doc_checkout("/p/q", local_only_commits=1, flags=["unpushed commits", "local-only commits: 1 in total"],
                         verdict="unpushed commits", local_only_branches=[{"branch": odd, "count": 1}])
    text = doc.render(doc_scan([head, other]))
    rows = {r.split("|")[1].strip(): r for r in section_3_2(text).splitlines() if r.startswith("| ")}
    for path in ("/p/o", "/p/q"):
        row = next(r for p, r in rows.items() if p.endswith(path))
        assert "refs/heads/" not in row and not re.search(r"git -C \S+ (?:-c \S+ )?push", row), row
        assert "bundle create" in row and "--all" in row and "not valid UTF-8" in row, row


def test_every_generated_push_runs_without_hooks():
    """Codex pass 48 on PR 27, P1: a checkout's or the operator's `pre-push` hook ran during a preservation step."""
    doc = load_doc()
    c = doc_checkout("/p/t", branch="side", unpushed=1, ahead_of_origin=1, flags=["unpushed commits", "unpushed tags", "unpushed tag names: v1"],
                     verdict="unpushed commits", local_only_commits=1, local_only_branches=[{"branch": "other", "count": 1}],
                     local_only_tags=[{"tag": "v1", "count": 0}])
    text = doc.render(doc_scan([c]))
    pushes = re.findall(r"git -C \S+ (?:-c core\.hooksPath=/dev/null )?push", text)
    assert pushes and all("-c core.hooksPath=/dev/null" in p for p in pushes), pushes


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory")
def test_an_unreadable_untracked_subtree_is_scan_incomplete_not_clean(tmp_path):
    """Codex pass 49 on PR 27, P1: `git status` exits 0 with a `could not open directory` warning on stderr and the
    unreadable files left out, so the checkout read `clean and pushed` with untracked work in it."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    secret = work / "a" / "b" / "secret"
    secret.mkdir(parents=True)
    (secret / "work.txt").write_text("ONLY-HERE\n")
    secret.chmod(0)
    try:
        rec = mod.scan_checkout(work, remote=False)
    finally:
        secret.chmod(0o755)
    assert rec["verdict"].startswith("scan incomplete: status"), rec["verdict"]
    assert mod.scan_checkout(work, remote=False)["verdict"] != rec["verdict"]  # readable again: a real answer


def test_url_is_local_path_follows_gits_own_classification():
    mod = load()
    for url in ("/srv/git/x.git", "../origin.git", "origin.git", "file:///srv/x.git", "./a:b", "C/x"):
        assert mod.url_is_local_path(url), url
    for url in ("https://h/x.git", "ssh://git@h/x.git", "git@host:x/y.git", "host:x", "ext::sh -c x", "git://h/x", "SSH://h/x", ""):
        assert not mod.url_is_local_path(url), url


def test_a_push_to_a_local_path_origin_gets_the_bundle_only_because_receive_hooks_would_run(tmp_path):
    """Adversary round 54 on PR 27, MEDIUM: `-c core.hooksPath=/dev/null` does not reach the `receive-pack` git runs
    locally for a path or `file://` origin, so that repository's hooks and `core.alternateRefsCommand` ran."""
    mod = load()
    doc = load_doc()
    roots, work, origin = make_pushed_checkout(tmp_path)
    for url in (str(origin), os.path.relpath(origin, work), f"file://{origin}"):
        git(work, "config", "remote.origin.url", url)
        commit_file(work, f"f-{abs(hash(url))}.txt")
        rec = mod.scan_checkout(work, remote=False)
        assert rec["origin_local_path"] is True and not rec["origin_credential"], (url, rec)
        text = doc.render(doc_scan([rec]))
        row = next(r for r in section_3_2(text).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
        assert not re.search(r"git -C \S+ (?:-c \S+ )?push", row) and "bundle create" in row and "local path" in row, (url, row)
    git(work, "config", "remote.origin.url", "https://127.0.0.1:9/x.git")
    assert mod.scan_checkout(work, remote=False)["origin_local_path"] is False


def test_a_local_path_origin_gets_no_push_command_for_any_row_and_no_add_advice():
    """Adversary round 55 on PR 27, LOW 2 and 3: the other-branches row, the zero-tag row and the untracked row each
    must stay bundle-only for a local-path origin (a push, or `add -A ... commit and push`, runs its receive hooks)."""
    mod = load_doc()
    side = doc_checkout("/p/work", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=2,
                        local_only_branches=[{"branch": "side", "count": 2}], origin_local_path=True)
    tags = doc_checkout("/p/t", flags=["unpushed tags"], verdict="unpushed tags",
                        local_only_tags=[{"tag": "release", "count": 0}], origin_local_path=True)
    untr = doc_checkout("/p/u", flags=["untracked"], verdict="untracked", untracked=1, untracked_sample=["u.txt"],
                        origin_local_path=True)
    rows = section_3_2(mod.render(doc_scan([side, tags, untr]))).splitlines()
    for p, want in (("/p/work", "refs/heads/side"), ("/p/t", "tag(s) origin lacks"), ("/p/u", "archive every untracked path")):
        row = next(r for r in rows if r.startswith(f"| {p} "))
        assert want in row.replace("local-only commits on `side`", "refs/heads/side"), row
        assert not re.search(r"git -C \S+ (?:-c \S+ )?push", row) and "add -A" not in row, row
        assert p == "/p/u" or "local path" in row, row  # the untracked row has no push to refuse
    assert "bundle create" in next(r for r in rows if r.startswith("| /p/work "))
    assert "bundle create" in next(r for r in rows if r.startswith("| /p/t "))


def test_an_edited_tracked_file_in_a_readable_but_unsearchable_directory_is_not_clean(tmp_path):
    """Adversary round 55 on PR 27, MEDIUM: `git status` reports a tracked path it cannot lstat with a bare
    `<path>: Permission denied` (no `warning:` prefix), skips the file and exits 0."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    (work / "sub").mkdir()
    (work / "sub" / "f.txt").write_text("tracked\n")
    git(work, "add", "sub/f.txt")
    git(work, "commit", "-q", "-m", "sub")
    git(work, "push", "-q", "origin", "main")
    (work / "sub" / "f.txt").write_text("LOCAL EDIT\n")
    for mode in (0o644, 0o444):
        (work / "sub").chmod(mode)
        try:
            rec = mod.scan_checkout(work, remote=False)
        finally:
            (work / "sub").chmod(0o755)
        assert rec["verdict"].startswith("scan incomplete: status"), (oct(mode), rec["verdict"])
    assert mod.scan_checkout(work, remote=False)["verdict"] == "dirty"
    # round 56 LOW 2: a directory named like git's own hint prefix must not hide the same fault
    (work / "hint:d").mkdir()
    (work / "hint:d" / "f.txt").write_text("tracked\n")
    git(work, "add", "hint:d/f.txt")
    git(work, "commit", "-q", "-m", "hint dir")
    git(work, "push", "-q", "origin", "main")
    (work / "hint:d" / "f.txt").write_text("LOCAL EDIT\n")
    (work / "hint:d").chmod(0o644)
    try:
        rec = mod.scan_checkout(work, remote=False)
    finally:
        (work / "hint:d").chmod(0o755)
    assert rec["verdict"].startswith("scan incomplete: status"), rec["verdict"]


def test_a_ref_name_that_is_not_utf8_makes_the_checkout_scan_incomplete(tmp_path):
    """Adversary round 54 on PR 27, LOW 2: two non-UTF-8 tag names collide on U+FFFD and hide an unpushed tag."""
    mod = load()
    work = tmp_path / "roots" / "w"
    work.mkdir(parents=True)
    p = subprocess.run(["git", "init", "-q", "-b", "main", "--ref-format=reftable", str(work)], capture_output=True, env=GIT_ENV)
    if p.returncode != 0:
        pytest.skip("this git cannot make a reftable repository, the only way to hold a non-UTF-8 ref on APFS")
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-q", "-m", "first")
    q = subprocess.run(["git", "update-ref", os.fsdecode(b"refs/tags/t\xfe"), "HEAD"], cwd=work, capture_output=True, env=GIT_ENV)
    assert q.returncode == 0, q.stderr
    rec = mod.scan_checkout(work, remote=False)
    assert rec["verdict"].startswith("scan incomplete: for-each-ref (a ref name is not valid UTF-8)"), rec["verdict"]


def test_an_embedded_repository_added_as_a_gitlink_without_gitmodules_is_not_clean(tmp_path):
    """Codex pass 50 on PR 27, P1: no `.gitmodules` and no `modules/` directory returned before the index was read, so
    work inside the gitlink's repository was in no count and no capture."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    inner = work / "inner"
    inner.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(inner)], check=True, env=GIT_ENV)
    (inner / "i.txt").write_text("i\n")
    git(inner, "add", "i.txt")
    git(inner, "commit", "-q", "-m", "i")
    git(work, "add", "inner")
    git(work, "commit", "-q", "-m", "gitlink")
    git(work, "push", "-q", "origin", "main")
    (inner / "ONLY-HERE.txt").write_text("work\n")
    assert not (work / ".gitmodules").exists()
    rec = mod.scan_checkout(work, remote=False)
    assert rec["verdict"] != "clean and pushed" and rec["verdict"].startswith("skipped: submodule config unrecognised"), rec["verdict"]


def test_an_untracked_embedded_repository_is_flagged_and_its_ignored_files_stay_out_of_the_archive(tmp_path):
    """Codex pass 50 on PR 27, P2: `ls-files --others` names `inner/`, and tar recursed into it, ignored files and
    `.git` included, into the non-ignored capture."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    inner = work / "inner"
    inner.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(inner)], check=True, env=GIT_ENV)
    (inner / ".gitignore").write_text("secret.env\n")
    (inner / "secret.env").write_text("TOKEN-FAKE\n")
    (inner / "i.txt").write_text("i\n")
    (work / "plain.txt").write_text("plain\n")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["embedded_repos"] == ["inner/"] and "embedded repositories: 1" in rec["flags"], rec
    assert rec["verdict"] == "embedded repositories: 1", rec["verdict"]
    text = doc.render(doc_scan([rec]))
    row = next(r for r in section_3_2(text).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "embedded repository" in row and "embedded-0.tar" in row, row
    ck = doc.checkout_dir(rec["path"])
    cmd = PLAN_PREFIX + doc.UNTRACKED_FMT.format(*map(doc.shquote, doc.untracked_values(rec["path"], ck))).replace("<DEST>", str(tmp_path / "dest"))
    (tmp_path / "dest" / ck).mkdir(parents=True)
    run = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    names = subprocess.run(["tar", "-tf", str(tmp_path / "dest" / ck / "untracked.tar")], capture_output=True, text=True).stdout
    assert "plain.txt" in names and "secret.env" not in names and "i.txt" not in names, names


def test_a_repository_below_an_untracked_directory_and_odd_names_are_found_and_archived_whole(tmp_path):
    """Adversary round 56 on PR 27, MEDIUM and LOW 3: `status` shows `outer/` only, so a repository below it was found
    by nothing and the `--no-recursion` archive kept an empty entry; a name holding `"` was a C-quoted string."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    (work / "outer").mkdir()
    (work / "outer" / "notes.txt").write_text("notes\n")
    names = ["outer/inner", 'q"x', "-dash", "sp ace"]
    for n in names:
        d = work / n
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True, env=GIT_ENV)
        (d / "work.txt").write_text("committed work\n")
        git(d, "add", "work.txt")
        git(d, "commit", "-q", "-m", "inner work")
    rec = mod.scan_checkout(work, remote=False)
    assert sorted(rec["embedded_repos"]) == sorted(n + "/" for n in names), rec["embedded_repos"]
    text = doc.render(doc_scan([rec]))
    ck = doc.checkout_dir(rec["path"])
    row = next(r for r in section_3_2(text).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "embedded-3.tar" in row, row
    dest = tmp_path / "dest"
    (dest / ck).mkdir(parents=True)
    plan = [unescape_span(m) for m in re.findall(r"`(mkdir -p [^`]*embedded-\d\.tar[^`]*)`", row)]
    assert len(plan) == 4, plan
    for shell in SHELLS:
        for c in plan:
            run = subprocess.run([shell, "-c", PLAN_PREFIX + c.replace("<DEST>", str(dest))], capture_output=True, text=True, env=GIT_ENV)
            assert run.returncode == 0, (shell, c, run.stderr)
    held = "".join(subprocess.run(["tar", "-tf", str(p)], capture_output=True, text=True).stdout
                   for p in sorted((dest / ck).glob("embedded-*.tar")))
    assert held.count("work.txt") >= 4 and "inner/work.txt" in held, held


def test_an_unreadable_directory_under_an_untracked_one_makes_the_embedded_search_incomplete(tmp_path):
    """Adversary round 57 on PR 27, MEDIUM: `status -unormal` stops at `outer/` and prints nothing, `ls-files --others`
    warns `could not open directory` with rc 0; its stderr was discarded and the record read complete."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    deep = work / "outer" / "zz" / "deep"
    (deep / "inner").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(deep / "inner")], check=True, env=GIT_ENV)
    (work / "outer" / "a").mkdir()
    (work / "outer" / "a" / "f").write_text("a\n")  # found first, so `status -unormal` stops there and prints nothing
    deep.chmod(0)
    try:
        rec = mod.scan_checkout(work, remote=False)
    finally:
        deep.chmod(0o755)
    # whichever git step meets the unreadable directory first says so (`ls-files --others` on git 2.4x on macOS, the
    # `status` step on the Linux CI's git): the record must read incomplete, never complete
    assert rec["verdict"].startswith(("scan incomplete: ls-files --others", "scan incomplete: status")), rec["verdict"]


def test_embedded_repositories_keep_cr_names_every_one_of_many_and_pointer_gitdirs_are_not_archived_as_commits(tmp_path):
    """Adversary round 57 on PR 27, LOW 2-4 and Codex pass 52 P2: a CR in a name was read back as a newline, only 50
    embedded repositories were kept, and an archive of a directory whose `.git` is a gitfile holds no commits."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    (work / "u").mkdir()
    cr = work / "u" / "c\rr"
    cr.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(cr)], check=True, env=GIT_ENV)
    for i in range(54):
        d = work / "many" / f"r{i:03d}"
        d.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(d)], check=True, env=GIT_ENV)
    sep = work / "u" / "sep"
    subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir", str(tmp_path / "sepgit"), str(sep)], check=True, env=GIT_ENV)
    rec = mod.scan_checkout(work, remote=False)
    assert len(rec["embedded_repos"]) == 56 and "u/c\rr/" in rec["embedded_repos"], len(rec["embedded_repos"])
    assert rec["embedded_pointer_repos"] == ["u/sep/"], rec["embedded_pointer_repos"]
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert row.count("embedded-") == 55 and "r053" in row and "points elsewhere" in row, row.count("embedded-")


def test_git_lfs_payloads_of_unpushed_commits_get_an_archive_row(tmp_path):
    """Codex pass 52 on PR 27, P1: a bundle holds LFS pointers and the generated push runs with hooks off, so the
    payloads under `<gitdir>/lfs/objects` were in no artifact."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    obj = work / ".git" / "lfs" / "objects" / "ab" / "cd"
    obj.mkdir(parents=True)
    (obj / "abcd0123").write_text("PAYLOAD\n")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["lfs_store"] == str(work / ".git" / "lfs" / "objects") and rec["verdict"] == "clean and pushed", rec  # nothing to capture: no row
    commit_file(work, "unpushed.txt")
    rec = mod.scan_checkout(work, remote=False)
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "lfs.tar" in row, row
    ck = doc.checkout_dir(rec["path"])
    dest = tmp_path / "dest"
    (dest / ck).mkdir(parents=True)
    cmd = unescape_span(re.search(r"`(mkdir -p [^`]*lfs\.tar[^`]*)`", row).group(1))
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True, env=GIT_ENV)
    assert run.returncode == 0, run.stderr
    held = subprocess.run(["tar", "-tf", str(dest / ck / "lfs.tar")], capture_output=True, text=True).stdout
    assert "./ab/cd/abcd0123" in held, held  # the objects directory itself (round 60 LOW 1)
    # a symlink inside the store is kept as a link, never followed (no `tar -h`): the target outside it stays out
    outside = tmp_path / "outside-secret"
    outside.write_text("NOT-PART-OF-THE-STORE\n")
    (work / ".git" / "lfs" / "objects" / "ab" / "evil").symlink_to(outside)
    shutil.rmtree(dest)
    (dest / ck).mkdir(parents=True)
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True, env=GIT_ENV)
    assert run.returncode == 0, run.stderr
    listing = subprocess.run(["tar", "-tvf", str(dest / ck / "lfs.tar")], capture_output=True, text=True).stdout
    assert re.search(r"^l\S* .*\./ab/evil -> ", listing, re.M), listing
    assert b"NOT-PART-OF-THE-STORE" not in (dest / ck / "lfs.tar").read_bytes()
    (work / ".git" / "lfs" / "objects" / "ab" / "evil").unlink()
    # every capture reason, not only unpushed commits: a stash holds pointers only (adversary round 58, MEDIUM)
    git(work, "reset", "-q", "--hard", "origin/main")
    (work / "a.txt").write_text("edited\n")
    git(work, "stash", "push", "-q")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["stashes"] == 1
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "lfs.tar" in row, row
    # a symlinked `lfs` is archived through the link (round 58 LOW 3): tar would keep the link only
    real = tmp_path / "real-store"
    shutil.move(str(work / ".git" / "lfs"), str(real))
    (work / ".git" / "lfs").symlink_to(real)
    rec = mod.scan_checkout(work, remote=False)
    assert rec["lfs_store"] == os.path.realpath(real / "objects"), rec["lfs_store"]


def test_a_bracketed_or_password_scp_url_is_a_credential():
    """Adversary round 57 on PR 27, LOW 5: ssh got `git:secret@host` in its argv for `[git:secret@host]:repo`."""
    mod = load()
    for url in ("[git:secret@host]:repo", "[git:secret@host:22]:repo", "user:pw@[host]:repo", "user:pw@host:repo"):
        assert mod.url_holds_credential(url) is True, url
    for url in ("git@host:repo", "git@[::1]:repo", "[::1]:repo", "host:path", "./a:b", "/x/y"):
        assert mod.url_holds_credential(url) is False, url


def test_commits_only_a_custom_ref_holds_force_the_bundle_instead_of_a_branch_push(tmp_path):
    """Codex pass 53 on PR 27, P1: `refs/custom/save` holds the child B of the unpushed `other` branch's commit A; the plan
    offered a push of `other`, which leaves B behind."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "checkout", "-q", "-b", "other")
    commit_file(work, "a-commit.txt")
    commit_file(work, "b-commit.txt")
    git(work, "update-ref", "refs/custom/save", "HEAD")
    git(work, "reset", "-q", "--hard", "HEAD~1")
    git(work, "checkout", "-q", "main")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["local_only_commits"] == 2 and rec["local_only_other_refs"] == 1, rec
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert not re.search(r"git -C \S+ (?:-c \S+ )?push", row) and "bundle create" in row and "refs/custom" not in row.split("(some")[0], row
    # the local-path origin is no_push on its own: pin the new branch with a pushable origin (adversary round 59, LOW 4)
    open_rec = dict(rec, origin_local_path=False)
    row = next(r for r in section_3_2(doc.render(doc_scan([open_rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert not re.search(r"git -C \S+ (?:-c \S+ )?push", row) and "outside refs/heads and refs/tags" in row, row
    # branches and tags alone keep the push alternative
    git(work, "update-ref", "-d", "refs/custom/save")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["local_only_other_refs"] == 0, rec


def test_branches_past_the_cap_force_the_bundle_and_a_symlinked_objects_dir_is_archived_through_the_link(tmp_path, monkeypatch):
    """Adversary round 59 on PR 27, MEDIUM, LOW 2 and LOW 4: refs past MAX_BRANCH_COUNTS are in no itemised push; a
    symlinked `lfs/objects` was archived as the link; `lfs.storage` was untested."""
    mod = load()
    doc = load_doc()
    co = doc_checkout("/p/cap", flags=["unpushed commits"], verdict="unpushed commits", local_only_commits=3,
                      local_only_branches=[{"branch": "a", "count": 1}, {"branch": "b", "count": 1}],
                      local_only_branches_uncounted=2)
    row = next(r for r in section_3_2(doc.render(doc_scan([co]))).splitlines() if r.startswith("| /p/cap "))
    assert not re.search(r"git -C \S+ (?:-c \S+ )?push", row) and "bundle create" in row and "2 more branches or tags are not itemised" in row, row
    assert row.rstrip().endswith("| yes: bundle it; a push would leave commits on other refs behind |"), row  # round 60, LOW 3
    roots, work, _ = make_pushed_checkout(tmp_path)
    ext = tmp_path / "ext-objects" / "ab" / "cd"
    ext.mkdir(parents=True)
    (ext / "abcd0123").write_text("PAYLOAD\n")
    (work / ".git" / "lfs").mkdir()
    (work / ".git" / "lfs" / "objects").symlink_to(tmp_path / "ext-objects")
    commit_file(work, "unpushed.txt")
    rec = mod.scan_checkout(work, remote=False)
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    ck = doc.checkout_dir(rec["path"])
    dest = tmp_path / "dest"
    (dest / ck).mkdir(parents=True)
    cmd = unescape_span(re.search(r"`(mkdir -p [^`]*lfs\.tar[^`]*)`", row).group(1))
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True, env=GIT_ENV)
    assert run.returncode == 0, run.stderr
    held = subprocess.run(["tar", "-tf", str(dest / ck / "lfs.tar")], capture_output=True, text=True).stdout
    assert "abcd0123" in held, held
    # `lfs.storage` from the operator's config: absolute, and relative to the git dir
    store = tmp_path / "elsewhere"
    (store / "objects" / "11").mkdir(parents=True)
    (store / "objects" / "11" / "x").write_text("p\n")
    (work / ".git" / "lfs" / "objects").unlink()
    gcfg = tmp_path / "gitconfig"
    gcfg.write_text(f"[lfs]\n\tstorage = {store}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gcfg))
    assert mod.scan_checkout(work, remote=False)["lfs_store"] == os.path.realpath(store / "objects")
    gcfg.write_text("[lfs]\n\tstorage = ../rel-store\n")
    (work / "rel-store" / "objects" / "22").mkdir(parents=True)
    (work / "rel-store" / "objects" / "22" / "y").write_text("p\n")
    assert mod.scan_checkout(work, remote=False)["lfs_store"] == os.path.realpath(work / "rel-store" / "objects")


def test_a_url_rewrite_key_never_reports_its_credential_and_a_scheme_less_scp_url_with_a_password_is_one(tmp_path):
    """Codex pass 54 on PR 27, P1: `url.https://user:TOKEN@host/.insteadOf` put the token in `config_keys`, flags and
    verdict; adversary round 59, INFO 5: `user:pw@host:path://x` was read as a scheme url."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "config", "url.https://user:FAKE-TOKEN-1234@host/.insteadOf", "https://host/")
    git(work, "config", "url.https://h/?token=FAKE-QUERY-5678.insteadOf", "https://q/")
    rec = mod.scan_checkout(work, remote=False)
    blob = json.dumps(rec)
    assert "FAKE-TOKEN-1234" not in blob and "FAKE-QUERY-5678" not in blob and "<redacted>" in blob, blob
    assert mod.url_holds_credential("user:pw@host:path://x") is True
    assert mod.url_holds_credential("git@host:path://x") is False


def test_a_global_push_rewrite_to_a_helper_gets_no_push_row(tmp_path, monkeypatch):
    """Codex pass 46 on PR 27, P1: the url checks ran with the global config switched off, but the printed push runs in
    the operator's shell, where `url.<base>.pushInsteadOf` can turn a clean url into a helper or credential url."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    commit_file(work, "ahead.txt")
    git(work, "config", "remote.origin.url", "https://127.0.0.1:9/x.git")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    assert mod.push_urls_hold_credential(work) is False
    (home / ".gitconfig").write_text('[url "evil::PAYLOAD-FAKE/"]\n\tpushInsteadOf = https://127.0.0.1:9/\n')
    assert mod.push_urls_hold_credential(work) is True
    (home / ".gitconfig").write_text('[url "https://u:FAKE-SECRET@127.0.0.1:9/"]\n\tpushInsteadOf = https://127.0.0.1:9/\n')
    assert mod.push_urls_hold_credential(work) is True


def test_only_the_operator_config_call_sees_the_operators_git_config_variables(tmp_path, monkeypatch):
    """Adversary round 53 INFO 6 on PR 27: the push-URL call restores the operator's `GIT_CONFIG_*`; no other call may."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.pager=cat'")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.x.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "y")
    seen = []
    real = mod.run

    def spy(argv, *a, **kw):
        env = kw.get("env") or {}
        seen.append((" ".join(argv), "GIT_CONFIG_PARAMETERS" in env, env.get("GIT_CONFIG_GLOBAL")))
        return real(argv, *a, **kw)

    monkeypatch.setattr(mod, "run", spy)
    mod.push_urls_hold_credential(work)
    carrying = [a for a, has, _ in seen if has]
    assert len(carrying) == 1 and "get-url" in carrying[0] and carrying[0].count("--push") == 1, seen
    assert all(g == os.devnull for a, has, g in seen if not has), seen


def test_a_stash_reflog_that_is_not_a_regular_file_is_incomplete_not_a_hang(tmp_path):
    """Codex pass 46 on PR 27, P2: `.git/logs/refs/stash` as a symlink to a FIFO or `/dev/zero` blocked or filled memory."""
    mod = load()
    work = make_repo(tmp_path / "w", "w.txt")
    log = work / ".git" / "logs" / "refs" / "stash"
    log.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(tmp_path / "fifo")
    for target in (tmp_path / "fifo", Path("/dev/zero")):
        log.unlink(missing_ok=True)
        log.symlink_to(target)
        assert mod.stash_count(work, work / ".git") is None, target
    log.unlink()
    log.write_text("0000 1111 a <a@b> 1 +0000\tWIP\n" * 3)
    assert mod.stash_count(work, work / ".git") == 3
    with pytest.raises(ValueError):
        mod.read_regular_file(log, 10)


def test_a_submodule_core_worktree_must_resolve_to_its_own_checkout(tmp_path):
    """Cursor security review on PR 27, MEDIUM: any `core.worktree` was accepted in a module config, so the plan's
    `git -C <checkout>/<sub>` read whatever directory that key named."""
    mod = load()
    sub_src = make_repo(tmp_path / "subsrc", "s.txt")
    sup = make_repo(tmp_path / "roots" / "sup", "p.txt")
    git(sup, "-c", "protocol.file.allow=always", "submodule", "add", str(sub_src), "sub")
    git(sup, "commit", "-m", "add sub")
    rec = mod.scan_checkout(sup, remote=False)
    assert rec["submodules_vetted"] == ["sub"], rec
    cfg = sup / ".git" / "modules" / "sub" / "config"
    text = cfg.read_text()
    assert "worktree = ../../../sub" in text
    cfg.write_text(text.replace("worktree = ../../../sub", f"worktree = {tmp_path}"))
    rec = mod.scan_checkout(sup, remote=False)
    assert rec["verdict"] == "skipped: submodule config unrecognised (core.worktree outside)", rec["verdict"]
    assert rec.get("submodules_vetted") is None, rec
    cfg.write_text(text)
    assert mod.scan_checkout(sup, remote=False)["submodules_vetted"] == ["sub"]
    # adversary round 53, MEDIUM: `config.worktree` is ignored by git without `extensions.worktreeConfig`, so a correct
    # value there cannot vouch for an outside one in `config`
    (cfg.parent / "config.worktree").write_text("[core]\n\tworktree = ../../../sub\n")
    cfg.write_text(text.replace("worktree = ../../../sub", f"worktree = {tmp_path}"))
    rec = mod.scan_checkout(sup, remote=False)
    assert rec["verdict"] == "skipped: submodule config unrecognised (core.worktree outside)", rec["verdict"]
    # git's own duplicate-line rule (the last wins) is honoured: an outside line followed by the right one is fine
    (cfg.parent / "config.worktree").unlink()
    cfg.write_text(text.replace("worktree = ../../../sub", f"worktree = {tmp_path}\n\tworktree = ../../../sub"))
    assert mod.scan_checkout(sup, remote=False)["submodules_vetted"] == ["sub"]


def test_an_unborn_head_still_counts_every_other_ref_as_local_work(tmp_path):
    """Codex pass 45 on PR 27, P1: HEAD on a new unborn branch with the old commit kept only at `refs/custom/save` was
    `clean and pushed`: the aggregate count was skipped for an unborn HEAD, so section 3.2 emitted no bundle."""
    mod = load()
    roots = tmp_path / "roots"
    work = make_repo(roots / "work", "w.txt")
    git(work, "update-ref", "refs/custom/save", "HEAD")
    branch = git(work, "rev-parse", "--abbrev-ref", "HEAD").strip()
    git(work, "symbolic-ref", "HEAD", "refs/heads/fresh")
    git(work, "update-ref", "-d", f"refs/heads/{branch}")
    assert git(work, "for-each-ref", "refs/heads", "refs/tags").strip() == ""  # unborn by the scanner's own test
    c = scan_one(mod, roots)
    assert c["local_only_commits"] and c["verdict"] != "clean and pushed", c


def test_a_non_utf8_checkout_path_is_quoted_as_its_bytes_and_the_document_is_written(tmp_path):
    """Codex pass 42 (P2): the scan JSON carries a non-UTF-8 name as a lone surrogate, which the markdown writer refused."""
    doc = load_doc()
    assert doc.shquote("/p/\udcffx") == "$'/p/\\xffx'" and doc.shquote(doc.Home("~/\udc80")) == "~/$'\\x80'"
    rec = doc_checkout("/p/\udcffx")
    out = tmp_path / "out.md"
    doc.write_atomic(out, doc.render(doc_scan([rec])))
    assert out.read_text(encoding="utf-8")


def test_a_submodule_label_in_the_command_cell_is_inert_when_pasted():
    """Adversary round 49 on PR 27, LOW: the label before a submodule's commands was an unquoted code span of a repository
    controlled path, so a paste (alone or after `cd`) ran `$(...)` in it. It is quoted like every command's path."""
    doc = load_doc()
    sub = "x$(touch${IFS}PWN)y"
    flag = "submodules not inspected"
    text = doc.render(doc_scan([doc_checkout("/p/sup", flags=[flag], verdict=flag, submodules_vetted=[sub])]))
    row = next(r for r in section_3_2(text).splitlines() if r.startswith("| /p/sup ")).replace("\\|", "|")
    assert "`'x$(touch${IFS}PWN)y'`: " in row and "`x$(touch" not in row, row


def gfm_cells(row: str) -> list[str]:
    """The cells of one table row as GitHub's renderer splits it: an unescaped `|` ends a cell, inside a code span too."""
    cells = re.split(r"(?<!\\)\|", row.strip())
    assert cells[0] == "" and cells[-1] == "", row
    return [c.strip().replace("\\|", "|") for c in cells[1:-1]]


def test_every_3_2_row_is_four_cells_in_a_gfm_view_with_every_command_in_the_command_cell(tmp_path):
    """Adversary round 48 (MEDIUM): the formats' own `|` ended the command cell in a rendered view, dropping the
    untracked archive, the stash capture, every submodule command and the needs-decision cell without an error."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    (sup / "a.txt").write_text("modified\n")
    (sup / "new.txt").write_text("untracked\n")
    git(sup, "stash", "push", "-m", "s", "a.txt")
    (sup / "a.txt").write_text("modified again\n")
    rec = next(c for c in mod.scan_git([roots], remote=False) if c["path"] == str(sup.resolve()))
    text = doc.render(doc_scan([rec]))
    rows = [r for r in section_3_2(text).splitlines() if r.startswith("| ") and not r.startswith("| checkout")]
    assert rows
    for row in rows:
        cells = gfm_cells(row)
        assert len(cells) == 4, (len(cells), row)
        command = cells[2]
        assert "untracked.tar" in command and "stash" in command and "modules.tar" in command, command
        assert command.count("`") % 2 == 0 and cells[3].lstrip("*").startswith(("yes", "no")), cells
        # the commands the tests run are exactly the spans of the command cell
        assert len(plan_commands(row)) == 7, plan_commands(row)


def test_a_percent_encoded_subsection_never_reports_its_secret(tmp_path):
    """Adversary round 60 on PR 27, LOW 2: `%3F`, `%23` and `%40` stand for `?`, `#` and `@` in a url, so the key's
    subsection carried the token past the redaction."""
    mod = load()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "config", "url.https://h/%3Ftoken=FAKE-PCT-1111.insteadOf", "https://a/")
    git(work, "config", "url.https://u:FAKE-PCT-2222%40h/x.insteadOf", "https://b/")
    git(work, "config", "url.https://h/%23FAKE-PCT-3333.insteadOf", "https://c/")
    blob = json.dumps(mod.scan_checkout(work, remote=False))
    for secret in ("FAKE-PCT-1111", "FAKE-PCT-2222", "FAKE-PCT-3333"):
        assert secret not in blob, blob
    assert "<redacted>" in blob


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_a_repository_that_replaces_an_index_hidden_path_is_found(tmp_path, flag):
    """Codex pass 55 on PR 27, P2: `status` and `ls-files --others` both show nothing for a directory that is a
    repository itself, so one standing where a skip-worktree or assume-unchanged tracked file was went uncounted."""
    mod = load()
    doc = load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    git(work, "update-index", flag, "a.txt")
    (work / "a.txt").unlink()
    (work / "a.txt").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work / "a.txt")], check=True, env=GIT_ENV)
    rec = mod.scan_checkout(work, remote=False)
    assert rec["embedded_repos"] == ["a.txt/"] and rec["index_hidden"] == 1, rec
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "embedded repository" in row and "a.txt/" in row and "embedded-0.tar" in row, row
    # a pointer `.git` (a separate gitdir) is named as one
    shutil.rmtree(work / "a.txt")
    (work / "a.txt").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir", str(tmp_path / "sep"), str(work / "a.txt")],
                   check=True, env=GIT_ENV)
    rec = mod.scan_checkout(work, remote=False)
    assert rec["embedded_repos"] == ["a.txt/"] and rec["embedded_pointer_repos"] == ["a.txt/"], rec
    # a hidden path that is a plain file or an ordinary directory finds none
    shutil.rmtree(work / "a.txt")
    (work / "a.txt").mkdir()
    (work / "a.txt" / "f").write_text("x\n")
    assert mod.scan_checkout(work, remote=False)["embedded_repos"] == []


def replace_with_repository(parent: Path, name: str) -> Path:
    """A tracked file `name` deleted and a repository with a committed file in its place (no `git rm`: the index keeps it)."""
    (parent / name).unlink()
    d = parent / name
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    (d / "only-work").write_text("local only\n")
    git(d, "add", "only-work")
    git(d, "commit", "-q", "-m", "inner work")
    return d


def test_a_repository_that_replaces_an_ordinary_tracked_file_is_found_and_archived_whole(tmp_path):
    """Codex pass 66 on PR 27, P1: `status` shows only ` D a.txt` and `ls-files --others` lists nothing for a directory that
    is a repository, so the scan said `modified: 1`, `untracked: 0`, no embedded repository, and the modified-files capture
    kept an empty directory entry (`--no-recursion`): the repository's commits and files were in no artifact."""
    mod, doc = load(), load_doc()
    roots, work, _ = make_pushed_checkout(tmp_path)
    replace_with_repository(work, "a.txt")
    rec = mod.scan_checkout(work, remote=False)
    assert rec["embedded_repos"] == ["a.txt/"] and rec["embedded_pointer_repos"] == [], rec
    assert rec["modified"] == 1 and rec["index_hidden"] == 0, rec  # an ordinary path: no hidden-path count
    row = next(r for r in section_3_2(doc.render(doc_scan([rec]))).splitlines() if r.startswith("| " + doc.tilde(rec["path"])))
    assert "embedded repository" in row and "a.txt/" in row and "embedded-0.tar" in row, row
    ck = doc.checkout_dir(rec["path"])
    dest = tmp_path / "dest"
    (dest / ck).mkdir(parents=True)
    plan = [unescape_span(m) for m in re.findall(r"`(mkdir -p [^`]*embedded-\d\.tar[^`]*)`", row)]
    assert len(plan) == 1, plan
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + plan[0].replace("<DEST>", str(dest))], capture_output=True, text=True, env=GIT_ENV)
    assert run.returncode == 0, run.stderr
    held = subprocess.run(["tar", "-tf", str(dest / ck / "embedded-0.tar")], capture_output=True, text=True).stdout
    assert "a.txt/only-work" in held and "a.txt/.git/HEAD" in held, held
    # a pointer `.git` (a separate gitdir) is named as one
    shutil.rmtree(work / "a.txt")
    (work / "a.txt").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir", str(tmp_path / "sep"), str(work / "a.txt")],
                   check=True, env=GIT_ENV)
    rec = mod.scan_checkout(work, remote=False)
    assert rec["embedded_repos"] == ["a.txt/"] and rec["embedded_pointer_repos"] == ["a.txt/"], rec
    # a plain deletion, a plain directory and a symlink to a repository are no embedded repository
    shutil.rmtree(work / "a.txt")
    assert mod.scan_checkout(work, remote=False)["embedded_repos"] == []
    (work / "a.txt").mkdir()
    (work / "a.txt" / "f").write_text("x\n")
    assert mod.scan_checkout(work, remote=False)["embedded_repos"] == []
    shutil.rmtree(work / "a.txt")
    target = tmp_path / "elsewhere"
    target.mkdir()
    git(target, "init", "-q", "-b", "main")
    (work / "a.txt").symlink_to(target, target_is_directory=True)
    assert mod.scan_checkout(work, remote=False)["embedded_repos"] == []


def test_a_repository_replacing_a_tracked_file_inside_a_submodule_is_nested_and_a_moved_gitlink_is_not(tmp_path):
    """Codex pass 66 on PR 27, P1: the submodule check shares the walk, so a repository standing where an ordinary
    tracked file of the submodule was no longer passes it; a submodule whose own HEAD moved (a modified gitlink, a directory
    with a `.git`) is not read as an embedded repository of the super project."""
    mod, doc = load(), load_doc()
    roots, sup, moddir = make_super_with_submodule(tmp_path)
    sub = sup / "sub"
    (sub / "g.txt").write_text("g\n")
    git(sub, "add", "g.txt")
    git(sub, "commit", "-q", "-m", "move the submodule head")  # the super's gitlink is now modified
    c = scan_super(mod, roots)
    assert c["embedded_repos"] == [] and c["submodules_vetted"] == ["sub"], c
    replace_with_repository(sub, "f.txt")
    c = scan_super(mod, roots)
    assert c["verdict"] == NESTED and not c.get("submodules_vetted"), c
    row = skipped_row(doc, c)
    whole = unescape_span(re.search(r"`(mkdir -p [^`]*whole\.tar[^`]*)`", row).group(1))
    dest, home = tmp_path / "dest", tmp_path / "home"
    dest.mkdir()
    home.mkdir()
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + whole.replace("<DEST>", str(dest))], capture_output=True, text=True,
                         env={**GIT_ENV, "HOME": str(home)})
    assert run.returncode == 0, run.stderr
    import tarfile
    names = tarfile.open(next(dest.rglob("whole.tar"))).getnames()
    assert any(n.endswith("sub/f.txt/only-work") for n in names), names
    # a plain deletion of the tracked file leaves the submodule vetted
    shutil.rmtree(sub / "f.txt")
    c = scan_super(mod, roots)
    assert not c["verdict"].startswith("skipped") and c["submodules_vetted"] == ["sub"], c


def test_the_doc_lists_a_checkout_whose_only_finding_is_an_embedded_repository():
    """Codex pass 55 on PR 27, P2: the row skip and the embedded loop both required untracked paths."""
    doc = load_doc()
    only = doc_checkout("/p/emb", embedded_repos=["x/"], embedded_pointer_repos=[])
    row = next(r for r in section_3_2(doc.render(doc_scan([only]))).splitlines() if r.startswith("| /p/emb "))
    assert "embedded repository" in row and "embedded-0.tar" in row and row.rstrip().endswith("| yes: decide whether they are work |"), row
    assert "| /p/emb " not in section_3_2(doc.render(doc_scan([doc_checkout("/p/emb")])))  # an older record: no row


def test_render_accepts_a_scan_with_one_category_only():
    """Codex pass 55 on PR 27, P2: `render` read `d["bigteam"]`, `d["checkouts"]` and both summary entries."""
    doc = load_doc()
    git_only = doc_scan([doc_checkout("/p/g", modified=1, flags=["dirty"], verdict="dirty")])
    del git_only["bigteam"], git_only["summary"]["bigteam"]
    assert "/p/g" in doc.render(git_only)
    bigteam_only = doc_scan([])
    del bigteam_only["checkouts"], bigteam_only["summary"]["checkouts"]
    assert isinstance(doc.render(bigteam_only), str)
    no_summary = doc_scan([])
    del no_summary["summary"]
    assert isinstance(doc.render(no_summary), str)


def test_a_report_or_embedded_directory_named_tilde_is_quoted_not_expanded(tmp_path):
    """Codex pass 56 on PR 27, P2: a relative report path `~/report.md` came out unquoted in the section 3.1 copy
    command, so the shell copied `$HOME/report.md` instead of the report below the task directory."""
    mod = load_doc()
    task = {"task": "tt", "verdict": "unique", "claim": "no CLAIM", "bytes": 1, "reports": [
        {"path": "~/report.md", "bytes": 1, "done": False}], "open_job_records": [], "fills": [],
        "unique_bytes": 1, "referenced_in": [], "newest_mtime": 0}
    other = doc_scan([], tasks=[task])
    other["bigteam"]["root"] = str(tmp_path / "bt")
    text = mod.render(other)
    row = next(r for r in text.split("### 3.1")[1].split("### 3.2")[0].splitlines() if r.startswith("| tt "))
    cmd = unescape_span(re.search(r"`(mkdir -p [^`]*)`", row).group(1))
    assert "'~/report.md'" in cmd and " -- ~/report.md" not in cmd, cmd
    (tmp_path / "bt" / "tt" / "~").mkdir(parents=True)
    (tmp_path / "bt" / "tt" / "~" / "report.md").write_text("THE REPORT\n")
    home = tmp_path / "home"
    home.mkdir()
    (home / "report.md").write_text("UNRELATED HOME FILE\n")
    dest = tmp_path / "dest"
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True,
                         env={**GIT_ENV, "HOME": str(home)})
    assert run.returncode == 0, run.stderr
    assert (dest / "bigteam" / "tt" / "~" / "report.md").read_text() == "THE REPORT\n"
    # a task root below HOME keeps its abbreviation through the join
    below = doc_scan([], tasks=[task])
    below["bigteam"]["root"] = os.path.join(mod.HOME, ".local/state/bigteam")
    row = next(r for r in mod.render(below).split("### 3.1")[1].split("### 3.2")[0].splitlines() if r.startswith("| tt "))
    assert "(cd ~/.local/state/bigteam/tt && " in row, row
    # an embedded directory named `~` below a checkout under HOME: the checkout path keeps its tilde, the name does not
    co = doc_checkout(os.path.join(mod.HOME, "src", "emb"), embedded_repos=["~/"], embedded_pointer_repos=[])
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| ~/src/emb "))
    assert "-C ~/src/emb " in row and "-- '~'" in row and "-- ~ " not in row, row


def test_home_destinations_and_a_checkout_at_home_expand_in_the_shell(tmp_path, monkeypatch):
    """Adversary round 62 on PR 27: F1 the no-origin bundle row wrote `all.bundle` into a directory named `~` inside the
    checkout (Codex pass 57 P1); F2 a checkout at HOME itself was archived as the literal `~`; F4 the split's parent
    must stay home-abbreviated."""
    mod = load_doc()
    home = tmp_path / "home"
    (home / "src").mkdir(parents=True)
    monkeypatch.setattr(mod, "HOME", str(home))
    repo = home / "src" / "one offs"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit_file(repo, "f.txt")
    co = doc_checkout(str(repo), flags=["orphan branch", "no origin remote"], verdict="orphan branch", ahead_of_origin=1,
                      local_only_commits=1)
    row = next(r for r in section_3_2(mod.render(doc_scan([co]))).splitlines() if r.startswith("| ~/src/one offs "))
    cmd = unescape_span(re.search(r"`(mkdir -p [^`]*bundle create[^`]*)`", row).group(1))
    assert "'~/ops" not in cmd, cmd
    dest = tmp_path / "dest"
    dest.mkdir()
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + cmd.replace("<DEST>", str(dest))], capture_output=True, text=True,
                         cwd=repo, env={**GIT_ENV, "HOME": str(home)})
    assert run.returncode == 0, run.stderr
    assert (home / "ops/site-private/bundles/home/src/one offs/all.bundle").is_file()
    assert not (repo / "~").exists() and git(repo, "status", "--porcelain").strip() == ""
    # a skipped checkout below HOME: the parent of the whole archive keeps its abbreviation
    skipped = doc_checkout(str(repo), flags=["skipped: x"], verdict="skipped: x")
    row = next(r for r in section_3_2(mod.render(doc_scan([skipped]))).splitlines() if r.startswith("| ~/src/one offs "))
    assert "-C ~/src " in row and "'~/src'" not in row, row
    # a checkout at HOME itself
    git(home, "init", "-q", "-b", "main")
    top = doc_checkout(str(home), flags=["skipped: x"], verdict="skipped: x")
    row = next(r for r in section_3_2(mod.render(doc_scan([top]))).splitlines() if r.startswith("| ~ "))
    whole = unescape_span(re.search(r"`(mkdir -p [^`]*whole\.tar[^`]*)`", row).group(1))
    dest2 = tmp_path / "dest2"
    dest2.mkdir()
    run = subprocess.run(["bash", "-c", PLAN_PREFIX + whole.replace("<DEST>", str(dest2))], capture_output=True, text=True,
                         env={**GIT_ENV, "HOME": str(home)})
    assert run.returncode == 0, run.stderr
    assert any(dest2.rglob("whole.tar"))
