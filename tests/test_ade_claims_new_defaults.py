"""`ade_claims.py new` defaults (queue 87): --owner-record, --id, --branch/--base-sha, and their error paths."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402

AGENT = "8ec213c7-f373-4829-88a2-5a1c8fe6b8b4"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    st = tmp_path / "state"
    monkeypatch.setenv("ADE_STATE_DIR", str(st))
    return st


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "wt-repo"
    d.mkdir()
    _git("init", "-q", "-b", "feat/x", cwd=d)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=d)
    return d


def _head(d):
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def _run(*args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PASEO_", "ADE_CLAIM", "CLAUDE_CODE"))}
    env["ADE_STATE_DIR"] = os.environ["ADE_STATE_DIR"]
    return subprocess.run([sys.executable, str(ROOT / "bin" / "ade_claims.py"), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_worker_one_liner_defaults_everything(repo):
    r = _run("new", "--path", str(repo), "--owner-agent", AGENT)
    assert r.returncode == 0, r.stderr
    claims = ade_claims.list_claims("active")
    assert len(claims) == 1
    c = claims[0]
    assert c["owner"]["agent"] == AGENT and c["owner"]["record"] == AGENT
    assert c["branch"] == "feat/x" and c["base_sha"] == _head(repo)
    assert c["id"].startswith("wt-repo-")
    assert ade_claims._bind_owner_shape(c) == AGENT


def test_owner_record_default_only_for_paseo_ids(repo):
    r = _run("new", "--path", str(repo), "--owner-agent", "codex", "--owner-session", "sess-1")
    assert r.returncode == 0, r.stderr
    assert ade_claims.list_claims("active")[0]["owner"]["record"] is None


def test_explicit_owner_record_wins(repo):
    r = _run("new", "--path", str(repo), "--owner-agent", AGENT, "--owner-record", "rec-1")
    assert r.returncode == 0, r.stderr
    assert ade_claims.list_claims("active")[0]["owner"]["record"] == "rec-1"


def test_reclaim_after_release_needs_no_new_id(repo):
    assert _run("new", "--path", str(repo), "--owner-agent", AGENT).returncode == 0
    first = ade_claims.list_claims("active")[0]["id"]
    assert _run("release", "--id", first).returncode == 0
    r = _run("new", "--path", str(repo), "--owner-agent", AGENT)
    assert r.returncode == 0, r.stderr
    active = ade_claims.list_claims("active")
    assert len(active) == 1 and active[0]["id"] != first
    assert ade_claims.read_claim(first)["state"] == "released"


def test_explicit_existing_id_exits_3_with_hint(repo):
    assert _run("new", "--id", "fixed-id", "--path", str(repo), "--owner-agent", AGENT).returncode == 0
    assert _run("release", "--id", "fixed-id").returncode == 0
    r = _run("new", "--id", "fixed-id", "--path", str(repo), "--owner-agent", AGENT)
    assert r.returncode == ade_claims.EXIT_EXISTS
    assert "omit --id" in r.stderr


def test_explicit_branch_and_sha_are_kept(repo):
    r = _run("new", "--path", str(repo), "--branch", "other", "--base-sha", "abc123", "--owner-agent", AGENT)
    assert r.returncode == 0, r.stderr
    c = ade_claims.list_claims("active")[0]
    assert (c["branch"], c["base_sha"]) == ("other", "abc123")


def test_only_missing_flag_is_defaulted(repo):
    r = _run("new", "--path", str(repo), "--branch", "other", "--owner-agent", AGENT)
    assert r.returncode == 0, r.stderr
    c = ade_claims.list_claims("active")[0]
    assert (c["branch"], c["base_sha"]) == ("other", _head(repo))


def test_not_a_git_worktree_errors_clearly(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    r = _run("new", "--path", str(d), "--owner-agent", AGENT)
    assert r.returncode == 2
    assert "not a git worktree" in r.stderr and "--branch" in r.stderr
    assert ade_claims.list_claims() == []


def test_missing_directory_errors_clearly(tmp_path):
    r = _run("new", "--path", str(tmp_path / "nope"), "--owner-agent", AGENT)
    assert r.returncode == 2
    assert "not a directory" in r.stderr


def test_detached_head_asks_for_branch(repo):
    _git("checkout", "-q", "--detach", cwd=repo)
    r = _run("new", "--path", str(repo), "--owner-agent", AGENT)
    assert r.returncode == 2
    assert "pass --branch" in r.stderr
    ok = _run("new", "--path", str(repo), "--branch", "detached-work", "--owner-agent", AGENT)
    assert ok.returncode == 0, ok.stderr


def test_unborn_head_asks_for_branch(tmp_path):
    d = tmp_path / "unborn"
    d.mkdir()
    _git("init", "-q", "-b", "main", cwd=d)
    r = _run("new", "--path", str(d), "--owner-agent", AGENT)
    assert r.returncode == 2
    assert "pass --branch" in r.stderr


def test_unborn_head_with_branch_asks_for_base_sha(tmp_path):
    d = tmp_path / "unborn2"
    d.mkdir()
    _git("init", "-q", "-b", "main", cwd=d)
    r = _run("new", "--path", str(d), "--branch", "main", "--owner-agent", AGENT)
    assert r.returncode == 2
    assert "pass --base-sha" in r.stderr


def test_generate_claim_id_is_valid_and_distinct(tmp_path):
    d = tmp_path / "we ird name!"
    d.mkdir()
    a, b = ade_claims.generate_claim_id(d), ade_claims.generate_claim_id(d)
    assert ade_claims.valid_id(a) and ade_claims.valid_id(b) and a != b
    assert a.startswith("we-ird-name-")


def test_is_paseo_agent_id():
    assert ade_claims.is_paseo_agent_id(AGENT)
    for bad in ("codex", "", None, AGENT.upper(), AGENT + "x", "pi"):
        assert not ade_claims.is_paseo_agent_id(bad)
