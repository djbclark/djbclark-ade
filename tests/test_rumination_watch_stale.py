#!/usr/bin/env python3
"""`chain_staleness()` must compare the Tier 1 pointer's `head_sha` to `HEAD` by ANCESTRY.

The pointer is written at session boundaries; `HEAD` moves on every commit by the owner and by
every peer seat. An equality comparison (the old code) therefore disagrees in the normal case — the
repo simply moved on from a perfectly fine pointer — and the watcher announced "stale" on 82-98% of
passes on several days (2026-10-25 .. 2026-10-29), making its one voice functionally dark. These
tests pin the three-way ancestry check: ancestor-or-equal is silent, absent from the repo is stale
and names the sha, and a descendant (the repo rewound) is stale and names the sha too.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"


def git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return p.stdout.strip()


def commit(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "techno-euphora"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    return repo


def write_pointer(tmp_path: Path, repo: Path, sha: str) -> None:
    pointer = tmp_path / ".local/state/handoffs" / repo.name / "main" / "SESSION_LOG.md"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(f"head_sha: {sha}\n")


def load(monkeypatch, tmp_path: Path, repo: Path):
    loader = importlib.machinery.SourceFileLoader(
        "rumination_watch_stale", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    monkeypatch.setattr(rw, "HOME", tmp_path)
    monkeypatch.setattr(rw, "REPO", repo)
    return rw


def test_pointer_equal_to_head_is_not_stale(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    head = commit(repo, "a.txt", "1\n", "one")
    write_pointer(tmp_path, repo, head)
    rw = load(monkeypatch, tmp_path, repo)
    assert rw.chain_staleness() is None


def test_pointer_an_ancestor_of_head_is_not_stale(monkeypatch, tmp_path):
    """The regression this change exists for: HEAD ahead of the pointer is normal, not staleness."""
    repo = make_repo(tmp_path)
    old = commit(repo, "a.txt", "1\n", "one")
    commit(repo, "a.txt", "2\n", "two")
    write_pointer(tmp_path, repo, old)
    rw = load(monkeypatch, tmp_path, repo)
    assert rw.chain_staleness() is None


def test_a_sha_absent_from_the_repo_is_stale_and_named(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "a.txt", "1\n", "one")
    bogus = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    write_pointer(tmp_path, repo, bogus)
    rw = load(monkeypatch, tmp_path, repo)
    msg = rw.chain_staleness()
    assert msg is not None
    assert bogus[:12] in msg
    assert "not in this repo" in msg


def test_a_descendant_of_head_is_stale_and_named(monkeypatch, tmp_path):
    """The repo rewound under the pointer: the recorded sha is AHEAD of HEAD, not behind it."""
    repo = make_repo(tmp_path)
    old = commit(repo, "a.txt", "1\n", "one")
    new = commit(repo, "a.txt", "2\n", "two")
    write_pointer(tmp_path, repo, new)
    git(repo, "checkout", "-q", old)
    rw = load(monkeypatch, tmp_path, repo)
    msg = rw.chain_staleness()
    assert msg is not None
    assert new[:12] in msg
    assert "repo is behind the pointer" in msg


def test_an_unreadable_pointer_is_silent(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "a.txt", "1\n", "one")
    rw = load(monkeypatch, tmp_path, repo)       # no pointer file written at all
    assert rw.chain_staleness() is None


def test_a_pointer_missing_head_sha_is_silent(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "a.txt", "1\n", "one")
    pointer = tmp_path / ".local/state/handoffs" / repo.name / "main" / "SESSION_LOG.md"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("no head sha here\n")
    rw = load(monkeypatch, tmp_path, repo)
    assert rw.chain_staleness() is None


def test_a_git_failure_reading_head_is_silent(monkeypatch, tmp_path):
    repo = make_repo(tmp_path)
    commit(repo, "a.txt", "1\n", "one")
    write_pointer(tmp_path, repo, "abc1234")
    rw = load(monkeypatch, tmp_path, repo)
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (1, "", "boom"))
    assert rw.chain_staleness() is None


def _failing_on(real, verb: str, rc: int):
    """A run_split that really runs git, except for the one command named by `verb`."""
    def fake(cmd, timeout=20):
        if verb in cmd:
            return rc, "", "git could not answer"
        return real(cmd, timeout)
    return fake


def test_a_git_error_checking_the_recorded_sha_is_silent(monkeypatch, tmp_path):
    """rc 127 (run_split's timeout/OSError catch) is "no answer", NOT "not in this repo".

    A timeout under load is the ordinary way to get here, and the whole point of this fix is that
    the watcher must not state a fact it did not learn: this used to read any non-zero rc as
    "not in this repo".
    """
    repo = make_repo(tmp_path)
    commit(repo, "a.txt", "1\n", "one")
    write_pointer(tmp_path, repo, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    rw = load(monkeypatch, tmp_path, repo)
    monkeypatch.setattr(rw, "run_split", _failing_on(rw.run_split, "cat-file", 127))
    assert rw.chain_staleness() is None


def test_a_git_error_asking_ancestry_is_silent(monkeypatch, tmp_path):
    """Same for `merge-base --is-ancestor`: rc 1 is the only code that means "not an ancestor".

    Without this branch a git error would be announced as "repo is behind the pointer" — a claim
    about the repo that git never made.
    """
    repo = make_repo(tmp_path)
    old = commit(repo, "a.txt", "1\n", "one")
    commit(repo, "a.txt", "2\n", "two")
    write_pointer(tmp_path, repo, old)
    rw = load(monkeypatch, tmp_path, repo)
    monkeypatch.setattr(rw, "run_split", _failing_on(rw.run_split, "merge-base", 128))
    assert rw.chain_staleness() is None

