"""Contract tests for precompact_handoff.py workspace resolution."""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


HOOKS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HOOKS_DIR))

import precompact_handoff  # noqa: E402
from precompact_handoff import resolve_workspace  # noqa: E402


def git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "standalone-repo"
    root.mkdir()
    git(["init", "-q"], root)
    git(["-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"], root)
    return root


def assert_resolved(directory):
    result = resolve_workspace(directory)
    assert result is not None
    repo, task = result
    assert isinstance(repo, str) and repo
    assert isinstance(task, str) and task
    return result


def expected_slug(value):
    slug = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)))
    slug = slug.strip("-") or "root"
    if len(slug) > 120:
        slug = f"{slug[:80]}-{hashlib.sha1(slug.encode('utf-8')).hexdigest()[:8]}"
    return slug


def test_recognized_ops_shapes_preserve_existing_results(tmp_path, monkeypatch):
    fake_home = tmp_path
    worktree = fake_home / "src" / "ops-worktrees" / "main" / "stayturgid"
    ops_repo = fake_home / "ops" / "site-djbclark"
    worktree.mkdir(parents=True)
    ops_repo.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    assert assert_resolved(worktree) == ("stayturgid", "main")
    assert assert_resolved(ops_repo) == ("site-djbclark", "ops")


def test_normal_repo_resolution_is_deterministic(repo):
    directory = repo / "nested" / "directory"
    directory.mkdir(parents=True)

    first = assert_resolved(directory)
    assert first == assert_resolved(directory)
    assert first[0] == "standalone-repo"


def test_git_root_uses_root_task(repo):
    resolved = assert_resolved(repo)
    assert resolved == ("standalone-repo", "root")


def test_deep_git_subdirectory_uses_relative_task(repo):
    directory = repo / "one" / "two" / "three"
    directory.mkdir(parents=True)

    resolved = assert_resolved(directory)
    assert resolved[0] == "standalone-repo"
    assert "one" in resolved[1] and "three" in resolved[1]
    assert resolved[1] != "root"


def test_git_worktree_checkout_is_detected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(["init", "-q"], source)
    git(["-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"], source)
    checkout = tmp_path / "linked-checkout"
    git(["worktree", "add", "-q", "-b", "linked-branch", str(checkout)],
        source)
    subdirectory = checkout / "subdir"
    subdirectory.mkdir()

    resolved = assert_resolved(subdirectory)
    assert resolved[0] == "linked-checkout"
    assert resolved[0] != "no-git"


def test_bare_repository_is_detected(tmp_path):
    bare = tmp_path / "archive.git"
    git(["init", "--bare", "-q", str(bare)], tmp_path)

    resolved = assert_resolved(bare)
    assert resolved == ("archive.git", "root")


def test_non_git_directory_uses_full_path_slug(tmp_path):
    directory = tmp_path / "not a repo" / "here"
    directory.mkdir(parents=True)

    repo_name, task = assert_resolved(directory)
    assert repo_name == "no-git"
    assert task == expected_slug(directory.resolve())


def test_unrelated_non_ops_directories_do_not_collide(tmp_path):
    first = tmp_path / "unrelated-one"
    second = tmp_path / "unrelated-two"
    first.mkdir()
    second.mkdir()

    assert assert_resolved(first) != assert_resolved(second)


def test_long_path_slug_is_bounded_hashed_and_deterministic(tmp_path):
    directory = tmp_path / ("a" * 80) / ("b" * 80)
    directory.mkdir(parents=True)

    first = assert_resolved(directory)
    assert first == assert_resolved(directory)
    assert first[0] == "no-git"
    assert len(first[1]) == 89
    assert re.fullmatch(r"[A-Za-z0-9._-]{80}-[0-9a-f]{8}", first[1])
    original = re.sub(r"-+", "-", re.sub(
        r"[^A-Za-z0-9._-]+", "-", str(directory.resolve()))).strip("-")
    assert first[1].endswith("-" + hashlib.sha1(
        original.encode("utf-8")).hexdigest()[:8])


def _run_hook(monkeypatch, tmp_path, repo_dir, session_id, nudge_state=None):
    state_root = tmp_path / "handoffs"
    nudge_path = tmp_path / "context-nudges.json"
    if nudge_state is not None:
        nudge_path.write_text(nudge_state if isinstance(nudge_state, str) else json.dumps(nudge_state))
    monkeypatch.setattr(precompact_handoff, "STATE_ROOT", state_root)
    monkeypatch.setattr(precompact_handoff, "NUDGE_STATE_PATH", nudge_path)
    monkeypatch.setenv("HANDOFF_ENRICH", "0")
    monkeypatch.chdir(repo_dir)
    payload = json.dumps({"session_id": session_id, "trigger": "auto", "transcript_path": ""})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    precompact_handoff.hook_main()
    files = list(state_root.rglob("precompact-*.md"))
    assert len(files) == 1
    return files[0].read_text()


def test_hook_main_stamps_pending_hard_handoff_for_level_2(monkeypatch, tmp_path, repo):
    content = _run_hook(
        monkeypatch, tmp_path, repo, "sess-hard",
        {"sess-hard": {"level": 2, "peak": 264_919, "last": 264_000}},
    )
    assert "pending_hard_handoff: true\n" in content
    assert "pending_hard_peak: 264919\n" in content
    assert "Hard handoff was already pending before compaction (peak 264,919 tokens)" in content
    assert "/self-handoff" in content


def test_hook_main_stamps_pending_hard_handoff_for_handoff_due(monkeypatch, tmp_path, repo):
    content = _run_hook(
        monkeypatch, tmp_path, repo, "sess-due",
        {"sess-due": {"level": 0, "handoff_due": {"peak": 251_000, "wall": 267_000, "level": 2}}},
    )
    assert "pending_hard_handoff: true\n" in content
    assert "pending_hard_peak: 251000\n" in content
    assert "peak 251,000 tokens" in content


def test_hook_main_omits_pending_hard_handoff_below_hard_tier(monkeypatch, tmp_path, repo):
    content = _run_hook(
        monkeypatch, tmp_path, repo, "sess-early",
        {"sess-early": {"level": 1, "peak": 150_000, "last": 150_000}},
    )
    assert "pending_hard_handoff" not in content
    assert "pending_hard_peak" not in content


@pytest.mark.parametrize("case", ["missing", "corrupt", "oversized", "symlink"])
def test_hook_main_nudge_state_failures_fail_silent(monkeypatch, tmp_path, repo, case):
    state_root = tmp_path / f"handoffs-{case}"
    nudge_path = tmp_path / f"nudges-{case}.json"
    if case == "corrupt":
        nudge_path.write_text("{not valid json")
    elif case == "oversized":
        nudge_path.write_bytes(b" " * (precompact_handoff.NUDGE_STATE_MAX_BYTES + 16))
    elif case == "symlink":
        if not hasattr(os, "O_NOFOLLOW"):
            pytest.skip("O_NOFOLLOW unavailable")
        target = tmp_path / "real-nudges.json"
        target.write_text(json.dumps({"sess-x": {"level": 2, "peak": 250_000}}))
        nudge_path.symlink_to(target)
    monkeypatch.setattr(precompact_handoff, "STATE_ROOT", state_root)
    monkeypatch.setattr(precompact_handoff, "NUDGE_STATE_PATH", nudge_path)
    monkeypatch.setenv("HANDOFF_ENRICH", "0")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sess-x", "trigger": "auto"})))
    precompact_handoff.hook_main()
    files = list(state_root.rglob("precompact-*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "compacted: true\n" in content
    assert "pending_hard_handoff" not in content
