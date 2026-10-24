"""bin/ade-git-guard + bin/ade_claims.py: the claim library and the exit-77 git guard (isolation slice W1).

Everything runs in temp repos under pytest's tmp_path with ADE_STATE_DIR pointed at a temp dir, so the
real ~/.local/state/ade is never read or written. Two simulated agents are `ADE_CLAIM_ID=A` and
`ADE_CLAIM_ID=B` (with ACP_RUN_AGENT=1); "human" is a shell with neither variable.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))  # bin/ is not a package
import ade_claims  # pyright: ignore[reportMissingImports]  # noqa: E402

SHIM = ROOT / "libexec" / "agent-bin" / "git"
GUARD = ROOT / "bin" / "ade-git-guard"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """A private claims registry and guard.log for every test."""
    st = tmp_path / "state"
    monkeypatch.setenv("ADE_STATE_DIR", str(st))
    return st


def base_env(state_dir, who=None, **extra):
    """A clean environment: no inherited GIT_*/ADE_*/ACP_* variable (this suite runs inside agents too)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "ADE_", "ACP_", "CLAUDE_CODE", "PASEO", "PRE_COMMIT"))}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                "ADE_STATE_DIR": str(state_dir)})
    if who == "run-only":
        env["ACP_RUN_AGENT"] = "1"
    elif who:
        env["ADE_CLAIM_ID"] = who
        env["ACP_RUN_AGENT"] = "1"
    env.update(extra)
    return env


def run(state_dir, args, cwd, who=None, **extra):
    """`git ARGS` through the shim symlink, as `who` (None = a human shell)."""
    return subprocess.run([str(SHIM), *args], cwd=cwd, env=base_env(state_dir, who, **extra),
                          capture_output=True, text=True, timeout=60)


def plain(state_dir, args, cwd):
    """Setup git: the real binary found by the shim itself, as a human."""
    r = run(state_dir, args, cwd)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def mk_repo(tmp_path, state_dir, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    plain(state_dir, ["init", "-q", "-b", "main"], repo)
    (repo / "f").write_text("base\n")
    (repo / "g").write_text("other\n")
    plain(state_dir, ["add", "f", "g"], repo)
    plain(state_dir, ["commit", "-qm", "init"], repo)
    return repo


def claim(repo, cid="A", branch="main", agent="codex", model="gpt-x", allow=(), origin="", **kw):
    c = ade_claims.make_claim(id=cid, path=repo, branch=branch, base_sha="deadbeef", repo_origin=origin,
                              owner_record=cid, owner_agent=agent, owner_model=model, allow=allow, **kw)
    ade_claims.write_claim(c)
    ade_claims.write_pointer(repo, cid)
    return c


def dirty(repo):
    (repo / "f").write_text("base\nOWNER EDIT, uncommitted\n")
    (repo / "u.txt").write_text("untracked owner file\n")


def guard_log(state_dir):
    p = Path(state_dir) / "guard.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


DESTRUCTIVE = [
    ["reset", "--hard"], ["stash"], ["stash", "-u"], ["checkout", "--", "."], ["clean", "-fd"],
    ["commit", "-a", "-m", "x"], ["restore", "."], ["add", "-A"], ["add", "."], ["pull", "--autostash"],
    ["switch", "-f", "main"], ["commit", "--allow-empty", "-m", "x"], ["tag", "t1"], ["branch", "newb"],
    ["config", "user.name", "x"], ["rebase", "main"],
]


# --------------------------------------------------------------------------------------------
# the shim, acceptance (design 4.2.1)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", DESTRUCTIVE, ids=lambda c: " ".join(c))
def test_foreign_agent_is_refused_and_owner_edit_is_byte_identical(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    before = (repo / "f").read_bytes(), (repo / "u.txt").read_bytes(), plain(state, ["status", "--porcelain"], repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert "codex" in r.stderr and "(A)" in r.stderr and "claim A" in r.stderr   # names the owner
    assert "Safe alternative" in r.stderr
    assert "exit 77" in r.stderr and "relay.py" in r.stderr
    after = (repo / "f").read_bytes(), (repo / "u.txt").read_bytes(), plain(state, ["status", "--porcelain"], repo)
    assert before == after
    assert plain(state, ["stash", "list"], repo) == ""
    log = guard_log(state)
    assert log[-1]["outcome"] == "refused" and log[-1]["ident"] == "B" and log[-1]["claim"] == "A"
    assert log[-1]["cmd"].startswith("git ")


@pytest.mark.parametrize("cmd,check", [
    (["reset", "--hard"], lambda repo: (repo / "f").read_text() == "base\n"),
    (["stash"], lambda repo: (repo / "f").read_text() == "base\n"),
    (["checkout", "--", "."], lambda repo: (repo / "f").read_text() == "base\n"),
    (["clean", "-fd"], lambda repo: not (repo / "u.txt").exists()),
    (["commit", "-a", "-m", "own work"], lambda repo: (repo / "f").read_text().endswith("uncommitted\n")),
    (["add", "-A"], lambda repo: True),
], ids=lambda x: " ".join(x) if isinstance(x, list) else "")
def test_owners_own_destructive_git_is_allowed(tmp_path, state, cmd, check):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    r = run(state, cmd, repo, who="A")
    assert r.returncode == 0, r.stderr
    assert check(repo)
    assert guard_log(state) == []


@pytest.mark.parametrize("cmd", DESTRUCTIVE, ids=lambda c: " ".join(c))
def test_human_shell_is_untouched_in_a_claimed_workspace(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    if cmd[0] == "branch" or cmd[0] == "tag":
        plain(state, ["commit", "-qam", "wip"], repo)
    r = run(state, cmd, repo)  # no ADE_CLAIM_ID, no ACP_RUN_AGENT
    assert "REFUSED" not in r.stderr and r.returncode != 77
    assert not (Path(state) / "guard.log").exists()


def test_human_reset_hard_really_runs(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    assert run(state, ["reset", "--hard"], repo).returncode == 0
    assert (repo / "f").read_text() == "base\n"


def test_run_only_agent_without_claim_id_is_foreign_in_a_claimed_workspace(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    r = run(state, ["reset", "--hard"], repo, who="run-only")
    assert r.returncode == 77
    assert (repo / "f").read_text().endswith("uncommitted\n")


def test_acp_run_agent_zero_is_not_an_agent(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    r = run(state, ["reset", "--hard"], repo, ACP_RUN_AGENT="0")
    assert r.returncode == 0


@pytest.mark.parametrize("cmd", [
    ["status"], ["diff"], ["log", "--oneline"], ["show", "HEAD"], ["ls-files"], ["rev-parse", "HEAD"],
    ["branch", "--list"], ["branch"], ["config", "--get", "core.bare"], ["config", "user.name"],
    ["worktree", "list"], ["stash", "list"], ["tag", "-l"], ["remote", "-v"], ["grep", "base"],
    ["-C", ".", "status"], ["--no-pager", "log", "-1"], ["cat-file", "-t", "HEAD"],
], ids=lambda c: " ".join(c))
def test_foreign_agent_may_read(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_allow_list_member_is_mine(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A", allow=["B"])
    dirty(repo)
    assert run(state, ["commit", "-a", "-m", "lead commit"], repo, who="B").returncode == 0
    assert run(state, ["reset", "--hard"], repo, who="C").returncode == 77


def test_a_read_only_call_never_starts_python(tmp_path, state):
    """The fast path: with python unusable a foreign agent's `git status` still works, silently."""
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = run(state, ["status", "--short"], repo, who="B", ADE_PYTHON="/nonexistent/python3")
    assert r.returncode == 0 and r.stderr == ""
    r = run(state, ["-C", str(repo), "-c", "color.ui=never", "log", "-1", "--format=%s"], tmp_path, who="B",
            ADE_PYTHON="/nonexistent/python3")
    assert r.returncode == 0 and r.stdout.strip() == "init" and r.stderr == ""


def test_broken_guard_fails_open_with_a_warning(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = run(state, ["commit", "--allow-empty", "-m", "x"], repo, who="B", ADE_PYTHON="/nonexistent/python3")
    assert r.returncode == 0
    assert "unguarded" in r.stderr


def test_real_git_exit_status_passes_through(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    r = run(state, ["rev-parse", "--verify", "nope^{commit}"], repo, who="B")
    assert r.returncode == 128
    r = run(state, ["commit", "-m", "nothing to commit"], repo, who="B")  # unclaimed: allowed; git itself says 1
    assert r.returncode == 1


def test_git_hook_and_pre_commit_context_are_not_refused(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    assert run(state, ["checkout", "--", "f"], repo, who="B", PRE_COMMIT="1").returncode == 0
    assert (repo / "f").read_text() == "base\n"


def test_operator_override_allows_and_logs(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    r = run(state, ["reset", "--hard"], repo, who="B", ACP_OPERATOR_APPROVED="route-override,git-guard")
    assert r.returncode == 0 and "git-guard" in r.stderr
    assert (repo / "f").read_text() == "base\n"
    assert guard_log(state)[-1]["outcome"] == "override"
    r = run(state, ["reset", "--hard"], repo, who="B", ACP_OPERATOR_APPROVED="route-override")
    assert r.returncode == 77


def test_shim_works_on_path_and_finds_the_real_git(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    env = base_env(state, "B")
    env["PATH"] = f"{SHIM.parent}{os.pathsep}{env['PATH']}"
    r = subprocess.run(["git", "reset", "--hard"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 77
    r = subprocess.run(["git", "--version"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.startswith("git version")
    r = subprocess.run([str(GUARD), "--real-git"], cwd=repo, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and Path(r.stdout.strip()).name == "git" and "agent-bin" not in r.stdout


def test_shim_is_a_relative_symlink_to_the_guard():
    assert SHIM.is_symlink() and os.readlink(SHIM) == "../../bin/ade-git-guard"
    assert SHIM.resolve() == GUARD.resolve() and os.access(GUARD, os.X_OK)


def test_guard_help_documents_exit_77():
    r = subprocess.run([str(GUARD), "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "77" in r.stdout and "--check" in r.stdout


# --------------------------------------------------------------------------------------------
# shared checkouts (no claim): the written rules as code (design 3.5.4.3.2)
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    ["reset", "--hard"], ["reset", "--merge"], ["stash"], ["stash", "push", "-m", "x"], ["checkout", "--", "f"],
    ["checkout", "."], ["checkout", "-f", "main"], ["restore", "f"], ["restore", "--staged", "--worktree", "f"],
    ["switch", "--discard-changes", "main"], ["clean", "-fdx"], ["clean", "-f"], ["commit", "-a", "-m", "x"],
    ["commit", "-am", "x"], ["add", "-A"], ["add", "--all"], ["add", "."], ["pull", "--autostash"],
    ["rebase", "--autostash", "main"], ["-c", "rebase.autoStash=true", "pull", "--rebase"],
    ["-c", "merge.autoStash=true", "pull"], ["-c", "pull.rebase=true", "-c", "rebase.autoStash=true", "pull"],
    ["merge", "--autostash", "main"],
], ids=lambda c: " ".join(c))
def test_agent_destructive_git_is_refused_in_a_shared_checkout(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert "no active claim" in r.stderr
    assert (repo / "f").read_text().endswith("uncommitted\n") and (repo / "u.txt").exists()


@pytest.mark.parametrize("cmd", [
    ["add", "f"], ["add", "-A", "f"], ["commit", "-m", "-a is just text"], ["commit", "-m", "x", "--amend"],
    ["stash", "list"], ["reset", "--soft", "HEAD"], ["reset", "--mixed"], ["restore", "--staged", "f"],
    ["clean", "-nfd"], ["clean", "-n"], ["checkout", "-b", "feature"], ["switch", "-c", "feature2"],
    ["checkout", "main"], ["pull", "--ff-only", "--no-autostash"], ["branch", "newb"], ["tag", "t1"],
], ids=lambda c: " ".join(c))
def test_agent_ordinary_git_is_allowed_in_a_shared_checkout(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    (repo / "f").write_text("base\nstaged\n")
    plain(state, ["add", "f"], repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_alias_to_a_destructive_command_is_refused(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    plain(state, ["config", "alias.nuke", "reset --hard"], repo)
    dirty(repo)
    r = run(state, ["nuke"], repo, who="B")
    assert r.returncode == 77 and (repo / "f").read_text().endswith("uncommitted\n")


def test_stash_is_refused_in_a_linked_worktree_even_for_its_owner(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    wt = tmp_path / "wt"
    plain(state, ["worktree", "add", "-q", "-b", "wtb", str(wt)], repo)
    claim(wt, "A", branch="wtb")
    (wt / "f").write_text("wip\n")
    assert run(state, ["stash"], wt, who="A").returncode == 77
    assert (wt / "f").read_text() == "wip\n"
    assert run(state, ["reset", "--hard"], wt, who="A").returncode == 0  # the rest is the owner's business
    assert (wt / "f").read_text() == "base\n"
    assert run(state, ["reset", "--hard"], wt, who="B").returncode == 77


def test_stash_is_allowed_in_the_owners_own_pasture(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    assert run(state, ["stash"], repo, who="A").returncode == 0


def test_a_released_claim_stops_protecting_the_workspace(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    ade_claims.set_state("A", "released")
    r = run(state, ["commit", "--allow-empty", "-m", "x"], repo, who="B")
    assert r.returncode == 0  # unclaimed now: ordinary git is allowed, destructive git is the shared rule
    assert run(state, ["reset", "--hard"], repo, who="B").returncode == 77
    assert "no active claim" in run(state, ["reset", "--hard"], repo, who="B").stderr


def test_copied_pointer_does_not_confer_ownership(tmp_path, state):
    """cow clones .git, pointer included: the copy must not read as A's workspace, nor as B's."""
    src = mk_repo(tmp_path, state, "src")
    claim(src, "A")
    cp = tmp_path / "copy"
    subprocess.run(["cp", "-R", str(src), str(cp)], check=True)
    assert (cp / ".git" / "ade-claim").read_text().strip() == "A"
    ws = ade_claims.find_workspace(cp)
    assert ade_claims.find_claim(ws) is None
    dirty(cp)
    r = run(state, ["reset", "--hard"], cp, who="A")
    assert r.returncode == 77 and "no active claim" in r.stderr   # shared rule, not A's own workspace
    claim(cp, "B", branch="b-branch", agent="omp")
    assert ade_claims.find_claim(ade_claims.find_workspace(cp))["id"] == "B"
    assert run(state, ["reset", "--hard"], cp, who="B").returncode == 0
    # and the source is still A's
    assert run(state, ["reset", "--hard"], src, who="B").returncode == 77


def test_claim_found_without_a_pointer_by_path(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    (repo / ".git" / "ade-claim").unlink()
    dirty(repo)
    assert run(state, ["reset", "--hard"], repo, who="B").returncode == 77
    assert run(state, ["reset", "--hard"], repo, who="A").returncode == 0


def test_refusal_log_never_holds_positional_values(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    secret = "tok3n-SECRET-xyz"
    r = run(state, ["push", f"https://user:{secret}@example.invalid/x.git", "HEAD:main"], repo, who="B")
    assert r.returncode == 77
    text = (Path(state) / "guard.log").read_text()
    assert secret not in text and secret not in r.stderr


# --------------------------------------------------------------------------------------------
# push of another claim's branch (row 2)
# --------------------------------------------------------------------------------------------

def test_push_of_another_claims_branch_is_refused_from_an_unclaimed_checkout(tmp_path, state):
    bare = tmp_path / "origin.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(bare)], tmp_path)
    owner = mk_repo(tmp_path, state, "owner")
    plain(state, ["remote", "add", "origin", str(bare)], owner)
    plain(state, ["checkout", "-q", "-b", "feat"], owner)
    claim(owner, "A", branch="feat", origin=str(bare))
    assert run(state, ["push", "-q", "origin", "feat"], owner, who="A").returncode == 0
    sha = plain(state, ["rev-parse", "feat"], owner).strip()
    primary = tmp_path / "primary"
    plain(state, ["clone", "-q", str(bare), str(primary)], tmp_path)
    plain(state, ["checkout", "-q", "feat"], primary)
    (primary / "x").write_text("merge-from-primary\n")
    plain(state, ["add", "x"], primary)
    plain(state, ["commit", "-qm", "from primary"], primary)
    for args in (["push", "origin", "HEAD:feat"], ["push", "origin", "+HEAD:refs/heads/feat"], ["push", "origin"],
                 ["push", "origin", "feat"], ["push", "--force", "origin", "HEAD:feat"]):
        r = run(state, args, primary, who="B")
        assert r.returncode == 77, (args, r.stderr)
        assert "branch 'feat' is claimed" in r.stderr and "codex gpt-x (A)" in r.stderr
    remote_sha = plain(state, ["--git-dir", str(bare), "rev-parse", "feat"], tmp_path).strip()
    assert remote_sha == sha
    assert run(state, ["push", "-q", "origin", "HEAD:scratch-b"], primary, who="B").returncode == 0
    assert run(state, ["push", "-q", "origin", "HEAD:feat"], primary, who="A").returncode == 0  # the owner may


def test_push_claim_is_per_repository(tmp_path, state):
    """A claim on `feat` in repo X must not block pushing `feat` in an unrelated repo Y."""
    owner = mk_repo(tmp_path, state, "owner")
    claim(owner, "A", branch="feat", origin="https://example.invalid/x/one.git")
    bare = tmp_path / "other.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(bare)], tmp_path)
    other = mk_repo(tmp_path, state, "other")
    plain(state, ["remote", "add", "origin", str(bare)], other)
    assert run(state, ["push", "-q", "origin", "HEAD:feat"], other, who="B").returncode == 0


# --------------------------------------------------------------------------------------------
# --check: shell command strings (the Claude hook, slice W5)
# --------------------------------------------------------------------------------------------

def check(state_dir, cmd, cwd, who="B"):
    return subprocess.run([str(GUARD), "--check", cmd, "--cwd", str(cwd)], env=base_env(state_dir, who),
                          capture_output=True, text=True, timeout=60)


def test_check_refuses_every_destructive_git_in_a_command(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    assert check(state, "git reset --hard", repo).returncode == 77
    assert check(state, f"cd {repo} && git stash", tmp_path).returncode == 77
    assert check(state, f"echo hi; git -C {repo} clean -fd", tmp_path).returncode == 77
    assert check(state, f"bash -c 'git checkout -- .'", repo).returncode == 77
    assert check(state, "FOO=1 git reset --hard | cat", repo).returncode == 77
    ok = check(state, "git status && git diff | head -3", repo)
    assert ok.returncode == 0, ok.stderr
    assert check(state, "git reset --hard", repo, who="A").returncode == 0
    assert check(state, "echo 'git reset --hard'", repo).returncode == 0   # text, not a command


def test_check_refuses_pathspec_commit_after_apply_cached_in_a_shared_checkout(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    cmd = "git apply --cached p.patch && git commit -m msg -- f"
    assert check(state, cmd, repo).returncode == 77
    assert check(state, "git apply --cached p.patch && git commit -m msg", repo).returncode == 0
    assert check(state, "git commit -m msg -- f", repo).returncode == 0   # alone it is not the row-3 shape
    claim(repo, "A")
    assert check(state, cmd, repo, who="A").returncode == 0


# --------------------------------------------------------------------------------------------
# the claim library
# --------------------------------------------------------------------------------------------

def test_claim_schema_is_exactly_design_3_4(tmp_path):
    c = ade_claims.make_claim(id="x1", path=tmp_path, branch="b", base_sha="abc", repo_origin="o",
                              owner_record="rec", owner_agent="codex", owner_model="m", lead="L", allow=["L"],
                              role="builder", purpose="p", created_by="me")
    assert set(c) == {"v", "id", "path", "repo_origin", "branch", "base_sha", "owner", "lead", "allow", "role",
                      "purpose", "created_at", "created_by", "state", "released_at", "inherited_dirt_patch"}
    assert set(c["owner"]) == {"record", "session", "agent", "model"}
    assert c["v"] == 1 and c["state"] == "active" and c["released_at"] is None
    assert c["path"] == str(tmp_path.resolve()) and c["created_at"].endswith("Z")


def test_claim_write_is_atomic_and_round_trips(tmp_path, state):
    c = ade_claims.make_claim(id="x1", path=tmp_path, branch="b", base_sha="abc")
    target = ade_claims.write_claim(c)
    assert target == state / "claims" / "x1.json"
    assert ade_claims.read_claim("x1") == c
    assert [p.name for p in (state / "claims").iterdir()] == ["x1.json"]   # no temp file left behind
    ade_claims.write_claim({**c, "branch": "b2"})
    assert ade_claims.read_claim("x1")["branch"] == "b2"
    assert [p.name for p in (state / "claims").iterdir()] == ["x1.json"]


def test_invalid_ids_are_rejected_so_a_pointer_cannot_escape_the_registry(tmp_path, state):
    for bad in ("../evil", "a/b", "", ".hidden", "x" * 200, "a b"):
        with pytest.raises(ValueError):
            ade_claims.make_claim(id=bad, path=tmp_path, branch="b", base_sha="s")
        assert ade_claims.read_claim(bad) is None
    (tmp_path / "secret.json").write_text('{"id":"s","path":"%s","state":"active"}' % tmp_path)
    repo = mk_repo(tmp_path, state, "r2")
    (repo / ".git" / "ade-claim").write_text("../../secret\n")
    assert ade_claims.read_pointer(ade_claims.find_workspace(repo)) is None


def test_old_or_partial_records_load_with_get(tmp_path, state):
    (state / "claims").mkdir(parents=True)
    (state / "claims" / "old.json").write_text(json.dumps({"id": "old", "path": str(tmp_path)}))   # v0-style: no state, owner
    (state / "claims" / "junk.json").write_text("{not json")
    (state / "claims" / "list.json").write_text("[1,2]")
    got = ade_claims.list_claims()
    assert [c["id"] for c in got] == ["old"]
    c = got[0]
    assert ade_claims.claim_state_active(c)            # a missing state reads as active
    assert ade_claims.owner_label(c) == "old" and not ade_claims.is_mine(c, "B") and ade_claims.is_mine(c, "old")
    assert ade_claims.owner_ids({"id": "z", "owner": "not-a-dict", "allow": "nope"}) == {"z"}
    assert not ade_claims.is_mine({"id": "z", "allow": "nope"}, "q")


def test_update_and_set_state(tmp_path, state):
    ade_claims.write_claim(ade_claims.make_claim(id="x1", path=tmp_path, branch="b", base_sha="s"))
    c = ade_claims.set_state("x1", "merged")
    assert c["state"] == "merged" and c["released_at"].endswith("Z")
    assert ade_claims.set_state("x1", "active")["released_at"] is None
    assert ade_claims.update_claim("nope", state="x") is None
    with pytest.raises(ValueError):
        ade_claims.set_state("x1", "bogus")
    assert [c["id"] for c in ade_claims.list_claims("active")] == ["x1"]
    assert ade_claims.list_claims("released") == []


def test_claims_for_branch_filters_by_origin_and_state(tmp_path, state):
    for cid, branch, origin in (("a", "feat", "git@github.com:me/r.git"), ("b", "feat", "https://github.com/other/z"),
                                ("c", "feat", ""), ("d", "other", "https://github.com/me/r")):
        ade_claims.write_claim(ade_claims.make_claim(id=cid, path=tmp_path / cid, branch=branch, base_sha="s",
                                                     repo_origin=origin))
    ids = lambda o: sorted(c["id"] for c in ade_claims.claims_for_branch("feat", o))   # noqa: E731
    assert ids("https://github.com/me/r.git") == ["a", "c"]    # same repo, other URL form; unknown origin counts
    assert ids("") == ["a", "b", "c"]
    ade_claims.set_state("a", "released")
    assert ids("https://github.com/me/r") == ["c"]
    assert ade_claims.normalize_origin("ssh://git@Host.com/a/b.git/") == "host.com/a/b"


def test_caller_identity_prefers_the_explicit_claim_id():
    env = {"ADE_CLAIM_ID": "slice-1", "CLAUDE_CODE_SESSION_ID": "lead-session"}
    assert ade_claims.caller_ident(env) == "slice-1"
    assert ade_claims.caller_ident({"CLAUDE_CODE_SESSION_ID": "s"}) == "s"
    assert ade_claims.caller_ident({}) is None
    assert ade_claims.is_agent_env({"ACP_RUN_AGENT": "1"}) and ade_claims.is_agent_env({"ADE_CLAIM_ID": "x"})
    assert not ade_claims.is_agent_env({"ACP_RUN_AGENT": "0"}) and not ade_claims.is_agent_env({})


def test_cli_new_show_find_list_set_state(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    env = base_env(state)
    cli = [sys.executable, str(ROOT / "bin" / "ade_claims.py")]

    def call(*a):
        return subprocess.run([*cli, *a], cwd=repo, env=env, capture_output=True, text=True, timeout=60)

    r = call("new", "--id", "w1", "--path", str(repo), "--branch", "b", "--base-sha", "abc", "--owner-record", "w1",
             "--owner-agent", "omp", "--allow", "lead1", "--purpose", "demo")
    assert r.returncode == 0 and Path(r.stdout.strip()) == state / "claims" / "w1.json"
    assert (repo / ".git" / "ade-claim").read_text().strip() == "w1"
    assert json.loads(call("find").stdout)["id"] == "w1"
    assert call("show", "w1", "--field", "branch").stdout.strip() == "b"
    assert call("show", "nope").returncode == 1
    assert "w1\tactive\tb" in call("list").stdout
    assert call("set-state", "w1", "released").returncode == 0
    assert call("find").returncode == 1                       # released: not active
    assert json.loads(call("list", "--state", "released", "--json").stdout)[0]["state"] == "released"
    assert call("new", "--id", "../x", "--path", str(repo), "--branch", "b", "--base-sha", "a").returncode == 2


# ============================================================================================
# repair round (adversary BLOCK at 1695488, 2026-10-24): one regression per finding
# ============================================================================================

def untouched(repo):
    return (repo / "f").read_text().endswith("uncommitted\n") and (repo / "u.txt").exists()


def setup_linked(tmp_path, state, claim_branch="wtb"):
    """Primary P (unclaimed) and a linked worktree W claimed by A with an uncommitted edit."""
    repo = mk_repo(tmp_path, state, "P")
    wt = tmp_path / "W"
    plain(state, ["worktree", "add", "-q", "-b", "wtb", str(wt)], repo)
    claim(wt, "A", branch=claim_branch)
    dirty(wt)
    return repo, wt


# --- BLOCK-1: every discard spelling in a shared checkout ---------------------------------

@pytest.mark.parametrize("cmd", [
    ["checkout", "f"], ["checkout", "HEAD", "f"], ["checkout", "./"], ["checkout", "main", "g"], ["checkout", "-p"],
    ["checkout", "--ours", "f"], ["checkout", ":/"], ["checkout", "*"],
    ["rm", "-f", "f"], ["rm", "--force", "f"], ["add", "-u"], ["add", "--update"], ["add", "-u", "."],
    ["clean"], ["clean", "-d"], ["-c", "clean.requireForce=false", "clean"], ["clean", "-fdx"], ["clean", "-q"],
    ["reset", "--keep"], ["switch", "-f", "main"], ["-c", "merge.autoStash=true", "merge", "main"],
], ids=lambda c: " ".join(c))
def test_shared_checkout_discard_spellings_are_refused(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert untouched(repo)


@pytest.mark.parametrize("cmd", [
    ["clean", "-n"], ["clean", "-dn"], ["clean", "--dry-run"], ["rm", "--cached", "g"], ["rm", "-n", "g"], ["add", "-u", "g"],
    ["checkout", "main"], ["checkout", "-b", "feat2"], ["checkout", "-"], ["switch", "main"],
], ids=lambda c: " ".join(c))
def test_shared_checkout_non_destructive_spellings_stay_allowed(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    (repo / "f").write_text("base\nedit\n")
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_a_repo_config_autostash_is_read_too(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    plain(state, ["config", "rebase.autoStash", "true"], repo)
    dirty(repo)
    assert run(state, ["pull", "--rebase"], repo, who="B").returncode == 77
    assert untouched(repo)


# --- BLOCK-2: abbreviated long options ----------------------------------------------------

@pytest.mark.parametrize("cmd", [
    ["reset", "--har"], ["reset", "--h"], ["reset", "--kee"], ["reset", "--mer"], ["checkout", "--forc", "main"],
    ["switch", "--disc", "main"], ["switch", "--forc", "main"], ["commit", "--al", "-m", "x"], ["add", "--al"],
    ["add", "--upd"], ["pull", "--autos"], ["merge", "--autos", "main"], ["rebase", "--autost", "main"],
    ["rm", "--forc", "f"], ["restore", "--work", "f"], ["restore", "f"],
], ids=lambda c: " ".join(c))
def test_abbreviated_long_options_count_as_the_option_they_prefix(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert untouched(repo)


@pytest.mark.parametrize("cmd", [["restore", "--stag", "f"], ["restore", "--staged", "f"], ["clean", "--dry", "-d"],
                                 ["rm", "--cache", "g"], ["pull", "--no-autos", "--ff-only"]],
                         ids=lambda c: " ".join(c))
def test_abbreviated_safe_options_are_not_falsely_refused(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    (repo / "f").write_text("base\nedit\n")
    plain(state, ["add", "f"], repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_abbreviated_write_options_are_refused_in_a_foreign_workspace(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    for cmd in (["branch", "--set-up=origin/x", "main"], ["branch", "--del", "x"], ["tag", "--del", "x"],
                ["config", "--unset-a", "user.name"]):
        assert run(state, cmd, repo, who="B").returncode == 77, cmd


@pytest.mark.parametrize("flag", ["--all", "--al", "--mirror", "--mir", "--branches", "--br"])
def test_push_all_and_mirror_spellings_cover_claimed_branches(tmp_path, state, flag):
    bare = tmp_path / "origin.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(bare)], tmp_path)
    owner = mk_repo(tmp_path, state, "owner")
    plain(state, ["remote", "add", "origin", str(bare)], owner)
    plain(state, ["checkout", "-q", "-b", "feat"], owner)
    claim(owner, "A", branch="feat", origin=str(bare))
    primary = mk_repo(tmp_path, state, "primary")
    plain(state, ["remote", "add", "origin", str(bare)], primary)
    plain(state, ["branch", "feat"], primary)
    r = run(state, ["push", flag, "origin"], primary, who="B")
    assert r.returncode == 77, r.stderr
    assert plain(state, ["--git-dir", str(bare), "branch", "--list"], tmp_path).strip() == ""


# --- BLOCK-3: the target's workspace, not the cwd's -----------------------------------------

@pytest.mark.parametrize("cmd", [
    ["worktree", "remove", "--force", "{wt}"], ["worktree", "remove", "{wt}"], ["worktree", "move", "{wt}", "{wt}2"],
    ["worktree", "remove", "-f", "-f", "{wt}"], ["worktree", "remove", "--forc", "{wt}"],
    ["branch", "-D", "wtb"], ["branch", "-m", "wtb", "gone"], ["branch", "-f", "wtb", "HEAD"], ["branch", "--delete", "--force", "wtb"],
    ["update-ref", "-d", "refs/heads/wtb"], ["update-ref", "refs/heads/wtb", "HEAD"],
], ids=lambda c: " ".join(c))
@pytest.mark.parametrize("claim_branch", ["wtb", "some-other-name"])
def test_target_workspace_claim_protects_a_worktree_and_its_branch(tmp_path, state, cmd, claim_branch):
    repo, wt = setup_linked(tmp_path, state, claim_branch)
    r = run(state, [c.format(wt=wt) for c in cmd], repo, who="B")
    assert r.returncode == 77, r.stderr
    assert wt.is_dir() and (wt / "f").read_text().endswith("uncommitted\n") and (wt / "u.txt").exists()
    assert "wtb" in plain(state, ["branch", "--list"], repo)


def test_worktree_prune_is_refused_for_a_claimed_stale_entry(tmp_path, state):
    import shutil
    repo, wt = setup_linked(tmp_path, state)
    shutil.rmtree(wt)
    assert run(state, ["worktree", "prune"], repo, who="B").returncode == 77
    assert (repo / ".git" / "worktrees" / "W").is_dir()
    assert run(state, ["worktree", "prune"], repo, who="A").returncode == 0


def test_worktree_remove_by_its_owner_and_force_on_unclaimed(tmp_path, state):
    repo, wt = setup_linked(tmp_path, state)
    assert run(state, ["worktree", "remove", "--force", str(wt)], repo, who="A").returncode == 0
    assert not wt.exists()
    other = tmp_path / "W2"
    plain(state, ["worktree", "add", "-q", "-b", "w2", str(other)], repo)
    (other / "f").write_text("dirty\n")
    assert run(state, ["worktree", "remove", "--force", str(other)], repo, who="B").returncode == 77
    assert (other / "f").read_text() == "dirty\n"
    assert run(state, ["worktree", "remove", str(other)], repo, who="B").returncode != 77   # git itself refuses dirty


# --- BLOCK-4: --check ------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "echo hi\ngit reset --hard",
    "true\n\n  git reset --hard\necho done",
    "echo `git reset --hard`",
    'echo "$(git reset --hard)"',
    "echo $(git reset --hard)",
    'echo "a $(echo `git reset --hard`) b"',
    "env -i git reset --hard",
    "env -i FOO=1 git reset --hard",
    "timeout 5 git reset --hard",
    "xargs git reset --hard",
    "sudo -u nobody git reset --hard",
    "nice -n 5 git reset --hard",
    "watch -n1 git reset --hard",
    "watch 'git reset --hard'",
    'bash -lc "git reset --hard"',
    "sh -ec 'git reset --hard'",
    "zsh -c 'cd . && git reset --hard'",
    "eval git reset --hard",
    "eval 'git reset --hard'",
    "if true; then git reset --hard; fi",
    "(git reset --hard)",
    "{ git reset --hard; }",
    "true && /opt/homebrew/bin/git reset --hard",
    "git status\ngit stash",
    "git status # comment\ngit clean -fd",
    "git commit -m 'msg\nwith a second line'\ngit reset --hard",
], ids=lambda c: c.replace("\n", "⏎")[:40])
def test_check_sees_git_after_line_one_and_inside_wrappers(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = check(state, cmd, repo)
    assert r.returncode == 77, (cmd, r.stderr)
    assert check(state, cmd, repo, who="A").returncode == 0


@pytest.mark.parametrize("cmd", [
    "git $CMD", "git ${SUB} --hard", 'git "$X"', "D=/tmp/x; git -C $D reset --hard", 'git -C "$D" reset --hard',
    'cd "$D" && git reset --hard', "cd $D; git reset --hard", "cd ~someone && git reset --hard", "cd - && git reset --hard",
    "cd $(mktemp -d) && git reset --hard", "git reset --hard 'unterminated", 'git "reset --hard',
    "GIT_DIR=$X git reset --hard", "GIT_WORK_TREE=$(pwd)/x git checkout -f",
], ids=lambda c: c[:40])
def test_check_fails_closed_on_what_it_cannot_read(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "B", branch="b")   # B's own workspace: a plain `git reset --hard` there is fine
    assert check(state, "git reset --hard", repo).returncode == 0
    r = check(state, cmd, repo)
    assert r.returncode == 77, (cmd, r.stderr)
    assert "spell" in r.stderr


@pytest.mark.parametrize("cmd", [
    "git commit -m \"git reset --hard\"", "echo 'git reset --hard' | cat", "which git", "command -v git", "git --version",
    "echo git status", "brew install git", "git commit -F- <<'EOF'\nfix: git reset --hard is refused\nEOF",
    'git commit -m "$(cat <<\'EOF\'\nfix\n\ngit reset --hard\nEOF\n)"', "cd /tmp && git --version",
    'cd "$D" && git status', "git status && git diff | head", "grep -rn git README.md", "ls git-docs",
], ids=lambda c: c.replace("\n", "⏎")[:40])
def test_check_does_not_refuse_text_that_merely_mentions_git(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "B", branch="b")
    r = check(state, cmd, repo)
    assert r.returncode == 0, (cmd, r.stderr)


def test_check_inline_work_tree_and_git_dir_select_the_other_workspace(tmp_path, state):
    a = mk_repo(tmp_path, state, "a")
    b = mk_repo(tmp_path, state, "b")
    claim(a, "A")
    claim(b, "B", branch="b")
    dirty(a)
    for cmd in (f"GIT_WORK_TREE={a} git checkout -f", f"env GIT_WORK_TREE={a} git reset --hard",
                f"GIT_DIR={a}/.git git reset --hard", f"git --work-tree={a} checkout -f"):
        r = check(state, cmd, b)
        assert r.returncode == 77, (cmd, r.stderr)
    assert untouched(a)


# --- MEDIUM-1: aliases and config -------------------------------------------------------------

def test_aliases_given_with_dash_c_or_config_env_are_resolved(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    for args in (["-c", "alias.zz=reset --hard", "zz"], ["-calias.zz=reset --hard", "zz"],
                 ["-c", "alias.zz=!git reset --hard", "zz"], ["-c", "alias.zz=!echo hi", "zz"]):
        assert run(state, args, repo, who="B").returncode == 77, args
    r = run(state, ["--config-env=alias.zz=ZZ", "zz"], repo, who="B", ZZ="reset --hard")
    assert r.returncode == 77
    r = run(state, ["--config-env", "alias.zz=ZZ", "zz"], repo, who="B", ZZ="clean -fd")
    assert r.returncode == 77
    assert untouched(repo)


def test_a_repo_bang_alias_is_refused_in_a_shared_checkout_but_not_in_ones_own(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    plain(state, ["config", "alias.yy", "!git checkout -- ."], repo)
    dirty(repo)
    assert run(state, ["yy"], repo, who="B").returncode == 77
    assert untouched(repo)
    claim(repo, "B", branch="b")
    assert run(state, ["-c", "alias.hi=!echo hi", "hi"], repo, who="B").returncode == 0


def test_alias_to_push_or_stash_hits_the_push_and_linked_rules(tmp_path, state):
    bare = tmp_path / "origin.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(bare)], tmp_path)
    owner = mk_repo(tmp_path, state, "owner")
    plain(state, ["remote", "add", "origin", str(bare)], owner)
    plain(state, ["checkout", "-q", "-b", "feat"], owner)
    claim(owner, "A", branch="feat", origin=str(bare))
    primary = mk_repo(tmp_path, state, "primary")
    plain(state, ["remote", "add", "origin", str(bare)], primary)
    plain(state, ["branch", "feat"], primary)
    r = run(state, ["-c", "alias.pp=push", "pp", "origin", "feat"], primary, who="B")
    assert r.returncode == 77 and "feat" in r.stderr
    repo, wt = setup_linked(tmp_path, state)
    assert run(state, ["-c", "alias.ss=stash", "ss"], wt, who="A").returncode == 77


@pytest.mark.parametrize("cmd", [["rebase", "-x", "true", "main"], ["rebase", "--exec", "true", "main"],
                                 ["rebase", "--exe=true", "main"], ["rebase", "-xtrue", "main"]],
                         ids=lambda c: " ".join(c))
def test_rebase_exec_is_refused_in_shared_and_linked_checkouts(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    assert run(state, cmd, repo, who="B").returncode == 77
    wt = tmp_path / "L"
    plain(state, ["worktree", "add", "-q", "-b", "lb", str(wt)], repo)
    claim(wt, "A", branch="lb")
    assert run(state, cmd, wt, who="A").returncode == 77


def test_header_says_seatbelt_and_names_what_git_spawns():
    text = GUARD.read_text()
    assert "NOT A SANDBOX" in text and "git itself spawns" in text.lower().replace("everything ", "")
    assert "NOT A SANDBOX" in ade_claims.__doc__


# --- MEDIUM-2: push destinations that come from config ---------------------------------------------

def push_setup(tmp_path, state):
    bare = tmp_path / "origin.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(bare)], tmp_path)
    owner = mk_repo(tmp_path, state, "owner")
    plain(state, ["remote", "add", "origin", str(bare)], owner)
    plain(state, ["checkout", "-q", "-b", "feat"], owner)
    claim(owner, "A", branch="feat", origin=str(bare))
    assert run(state, ["push", "-q", "origin", "feat"], owner, who="A").returncode == 0
    primary = tmp_path / "primary"
    plain(state, ["clone", "-q", str(bare), str(primary)], tmp_path)
    plain(state, ["checkout", "-q", "-b", "mine"], primary)
    (primary / "x").write_text("x\n")
    plain(state, ["add", "x"], primary)
    plain(state, ["commit", "-qm", "mine"], primary)
    sha = plain(state, ["--git-dir", str(bare), "rev-parse", "feat"], tmp_path).strip()
    return bare, primary, sha


def test_push_destination_from_remote_push_config_is_checked(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    r = run(state, ["-c", "remote.origin.push=HEAD:refs/heads/feat", "push", "origin"], primary, who="B")
    assert r.returncode == 77 and "feat" in r.stderr
    plain(state, ["config", "remote.origin.push", "HEAD:refs/heads/feat"], primary)
    assert run(state, ["push"], primary, who="B").returncode == 77
    assert plain(state, ["--git-dir", str(bare), "rev-parse", "feat"], tmp_path).strip() == sha


def test_push_destination_from_upstream_and_push_default_is_checked(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    plain(state, ["branch", "-u", "origin/feat"], primary)
    r = run(state, ["-c", "push.default=upstream", "push"], primary, who="B")
    assert r.returncode == 77 and "feat" in r.stderr
    assert plain(state, ["--git-dir", str(bare), "rev-parse", "feat"], tmp_path).strip() == sha


def test_bare_push_to_an_unclaimed_branch_still_works_and_an_unresolvable_one_is_refused(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    assert run(state, ["push", "-q", "-u", "origin", "mine"], primary, who="B").returncode == 0
    (primary / "y").write_text("y\n")
    plain(state, ["add", "y"], primary)
    plain(state, ["commit", "-qm", "y"], primary)
    assert run(state, ["push", "-q"], primary, who="B").returncode == 0           # upstream mine: resolvable
    lone = mk_repo(tmp_path, state, "lone")                                       # no remote at all
    r = run(state, ["push"], lone, who="B")
    assert r.returncode == 77 and "unresolved" in r.stderr and "refspec" in r.stderr


# --- MEDIUM-3: GIT_WORK_TREE ------------------------------------------------------------------

def test_git_work_tree_selects_the_workspace_that_gets_written(tmp_path, state):
    a = mk_repo(tmp_path, state, "a")
    b = mk_repo(tmp_path, state, "b")
    claim(a, "A")
    claim(b, "B", branch="b")
    dirty(a)
    for args, extra in ((["checkout", "-f"], {"GIT_WORK_TREE": str(a)}), (["reset", "--hard"], {"GIT_WORK_TREE": str(a)}),
                        (["--work-tree", str(a), "checkout", "-f"], {}), (["--work-tree=" + str(a), "clean", "-fd"], {}),
                        (["commit", "--allow-empty", "-m", "x"], {"GIT_WORK_TREE": str(a)})):
        r = run(state, args, b, who="B", **extra)
        assert r.returncode == 77, (args, r.stderr)
    assert untouched(a)
    assert run(state, ["checkout", "-f"], b, who="B").returncode == 0           # B's own tree is fine


# --- MEDIUM-4: case-insensitive paths ----------------------------------------------------------

def test_a_differently_cased_path_still_finds_the_claim(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    swapped = Path(str(repo.resolve()).swapcase())
    if not swapped.exists() or not os.path.samefile(swapped, repo):
        pytest.skip("case-sensitive filesystem")
    assert ade_claims._same_path(str(swapped), repo)
    r = run(state, ["-C", str(swapped), "commit", "--allow-empty", "-m", "x"], tmp_path, who="B")
    assert r.returncode == 77, r.stderr
    assert ade_claims.find_claim(ade_claims.find_workspace(swapped))["id"] == "A"


def test_same_path_uses_the_file_not_the_spelling(tmp_path):
    (tmp_path / "d").mkdir()
    os.symlink(tmp_path / "d", tmp_path / "link")
    assert ade_claims._same_path(str(tmp_path / "link"), tmp_path / "d")
    assert not ade_claims._same_path(str(tmp_path / "d"), tmp_path)
    assert ade_claims._same_path(str(tmp_path / "gone"), tmp_path / "gone")      # nonexistent: same spelling
    assert not ade_claims._same_path("", tmp_path)


# --- MEDIUM-5: `new` never overwrites -------------------------------------------------------------

def test_new_refuses_an_existing_id_and_another_owners_path(tmp_path, state):
    a = mk_repo(tmp_path, state, "a")
    b = mk_repo(tmp_path, state, "b")
    cli = [sys.executable, str(ROOT / "bin" / "ade_claims.py")]
    env = base_env(state)

    def new(cid, path, owner):
        return subprocess.run([*cli, "new", "--id", cid, "--path", str(path), "--branch", "x", "--base-sha", "s",
                               "--owner-record", owner], env=env, capture_output=True, text=True, timeout=60)

    assert new("A", a, "A").returncode == 0
    before = (state / "claims" / "A.json").read_text()
    r = new("A", b, "A")
    assert r.returncode == 3 and "already exists" in r.stderr
    assert (state / "claims" / "A.json").read_text() == before
    assert not (b / ".git" / "ade-claim").exists()
    r = new("B", a, "B")
    assert r.returncode == 4 and "already claimed" in r.stderr
    assert not (state / "claims" / "B.json").exists()
    assert (a / ".git" / "ade-claim").read_text().strip() == "A"
    assert new("A2", a, "A").returncode == 0      # the same owner may re-claim its own workspace
    assert new("B", b, "B").returncode == 0


def test_create_claim_is_exclusive_under_concurrency(tmp_path, state):
    from concurrent.futures import ThreadPoolExecutor

    def make(i):
        c = ade_claims.make_claim(id="same", path=tmp_path / f"p{i}", branch="b", base_sha="s", owner_record=f"o{i}")
        try:
            ade_claims.create_claim(c)
            return "ok"
        except ade_claims.ClaimExists:
            return "exists"

    with ThreadPoolExecutor(8) as ex:
        got = list(ex.map(make, range(16)))
    assert got.count("ok") == 1 and got.count("exists") == 15
    assert [p.name for p in (state / "claims").iterdir() if p.name != ".lock"] == ["same.json"]


def test_a_released_claim_does_not_block_a_new_claim_on_the_path(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    ade_claims.set_state("A", "released")
    ade_claims.create_claim(ade_claims.make_claim(id="B", path=repo, branch="b", base_sha="s", owner_record="B"))


# --- MEDIUM-6: "read-only" commands that write ----------------------------------------------------------

@pytest.mark.parametrize("cmd", [
    ["log", "-0", "--output=f"], ["log", "-0", "--output", "f"], ["diff", "--output=f"], ["show", "--output=f", "HEAD"],
    ["log", "-0", "--out=f"], ["log", "-0", "--outp=f"], ["format-patch", "-1", "-o", "f"], ["format-patch", "-1", "-of"],
    ["format-patch", "-1", "--output-directory=f"], ["format-patch", "-1", "--output-d", "f"],
    ["archive", "-o", "f", "HEAD"], ["archive", "--output=f", "HEAD"], ["grep", "-Oless", "base"],
    ["grep", "--open-files-in-pager=less", "base"],
], ids=lambda c: " ".join(c))
def test_output_writing_options_are_not_read_only_in_a_foreign_workspace(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    dirty(repo)
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert untouched(repo)


def test_output_into_another_claims_tree_is_refused_from_ones_own(tmp_path, state):
    a = mk_repo(tmp_path, state, "a")
    b = mk_repo(tmp_path, state, "b")
    claim(a, "A")
    claim(b, "B", branch="b")
    dirty(a)
    r = run(state, ["log", "-0", f"--output={a / 'f'}"], b, who="B")
    assert r.returncode == 77 and untouched(a)
    assert run(state, ["log", "-0", f"--output={b / 'out.txt'}"], b, who="B").returncode == 0
    assert (b / "out.txt").exists()


@pytest.mark.parametrize("cmd", [["ls-files", "-o"], ["grep", "-o", "base"], ["log", "--oneline", "-1"],
                                 ["diff", "--output-indicator-new=+"], ["log", "-1", "--format=%s"], ["ls-files", "--others"]],
                         ids=lambda c: " ".join(c))
def test_look_alike_read_options_stay_allowed_in_a_foreign_workspace(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_plain_reads_still_never_start_python(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    for cmd in (["log", "--oneline", "-1"], ["diff", "--stat"], ["status", "-sb"], ["show", "--format=%s", "HEAD"]):
        r = run(state, cmd, repo, who="B", ADE_PYTHON="/nonexistent/python3")
        assert r.returncode == 0 and r.stderr == "", (cmd, r.stderr)
    r = run(state, ["log", "-0", "--output=f"], repo, who="B", ADE_PYTHON="/nonexistent/python3")
    assert "unguarded" in r.stderr          # it went to the rules (which fail open here), not the fast path


# --- LOW items fixed on the way ---------------------------------------------------------------------------------

def test_guard_log_holds_option_names_never_values(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    r = run(state, ["commit", "-mTOKEN-attached-xyz", "--author=Secret Name <s@x>", "--allow-empty"], repo, who="B")
    assert r.returncode == 77
    r = run(state, ["commit", "-m", "-token abc", "--", "-secretfile"], repo, who="B")
    assert r.returncode == 77
    text = (Path(state) / "guard.log").read_text()
    for leak in ("TOKEN", "Secret", "token abc", "secretfile"):
        assert leak not in text
    assert guard_log(state)[0]["flags"] == ["-m", "--author", "--allow-empty"]


def test_a_hostile_claim_file_does_not_blind_the_guard(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    (state / "claims" / "zz.json").write_text("[" * 200000)
    (state / "claims" / "zy.json").write_text('{"id": "zy", "path": 5, "allow": 3, "owner": []}')
    dirty(repo)
    assert ade_claims.read_claim("zz") is None
    assert run(state, ["reset", "--hard"], repo, who="B").returncode == 77
    assert untouched(repo)


def test_a_poisoned_pythonpath_does_not_switch_the_guard_off(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "json.py").write_text("raise SystemExit(0)\n")
    (evil / "re.py").write_text("raise SystemExit(0)\n")
    dirty(repo)
    r = run(state, ["reset", "--hard"], repo, who="B", PYTHONPATH=str(evil))
    assert r.returncode == 77
    assert untouched(repo)


# ============================================================================================
# repair round 2 (adversary BLOCK at 858cf6d, 2026-10-24): one regression per finding
# ============================================================================================

def remote_sha(state_dir, bare, branch="feat"):
    return plain(state_dir, ["--git-dir", str(bare), "rev-parse", branch], bare.parent).strip()


def two_claimed(tmp_path, state):
    """a (claimed by A, with uncommitted work) and b (claimed by B, the caller)."""
    a = mk_repo(tmp_path, state, "a")
    b = mk_repo(tmp_path, state, "b")
    claim(a, "A")
    claim(b, "B", branch="b")
    dirty(a)
    return a, b


# --- R2-B1: the push preflight can never perform the push -------------------------------------

@pytest.mark.parametrize("args", [
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "--no-dry-run", "origin"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "--no-dry", "origin"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "--no-d", "origin"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "--no-porcelain", "origin"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "--no-por", "origin"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "push", "origin", "--no-dry-run"],
    ["push", "--no-dry-run", "origin", "HEAD:feat"],
], ids=lambda a: " ".join(a[2:] if a[0] == "-c" else a))
def test_push_preflight_can_never_perform_the_push(tmp_path, state, args):
    bare, primary, sha = push_setup(tmp_path, state)
    r = run(state, args, primary, who="B")
    assert r.returncode == 77, r.stderr
    assert remote_sha(state, bare) == sha          # the claimed branch did not move, not even once


def test_check_of_a_push_that_cancels_the_dry_run_pushes_nothing(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    for cmd in ("git -c remote.origin.push=+HEAD:refs/heads/feat push --no-dry-run origin",
                "git -c remote.origin.push=+HEAD:refs/heads/feat push origin"):
        assert check(state, cmd, primary).returncode == 77
        assert remote_sha(state, bare) == sha
    assert check(state, "git push origin HEAD:scratch-b", primary).returncode == 0   # asked, not executed
    assert plain(state, ["--git-dir", str(bare), "branch", "--list", "scratch-b"], tmp_path) == ""


def test_push_preflight_runs_no_pre_push_hook(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    marker = tmp_path / "hook.log"
    hook = primary / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\necho ran >> '{marker}'\nexit 0\n")
    hook.chmod(0o755)
    r = run(state, ["-c", "remote.origin.push=HEAD:refs/heads/feat", "push", "origin"], primary, who="B")
    assert r.returncode == 77 and not marker.exists()
    assert run(state, ["push", "-q", "origin", "HEAD:scratch-b"], primary, who="B").returncode == 0
    assert marker.read_text().count("ran") == 1     # the real push only, never the guard's own dry run


def test_run_git_kills_the_whole_process_group_on_timeout(tmp_path, monkeypatch):
    import time
    fake = tmp_path / "git"
    pidfile = tmp_path / "pid"
    fake.write_text(f"#!/bin/sh\nsleep 300 &\necho $! > '{pidfile}'\nwait\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ADE_REAL_GIT", str(fake))
    rc, _ = ade_claims._run_git(["push"], timeout=1)
    assert rc == 124
    pid = int(pidfile.read_text())
    try:
        for _ in range(60):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            pytest.fail("a grandchild of the timed-out git is still running")
    finally:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def test_an_unresolvable_push_is_refused_only_while_someone_else_holds_a_claim(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    r = run(state, ["push", "nowhere", "HEAD:feat"], primary, who="B")
    assert r.returncode == 77 and "unresolved" in r.stderr
    ade_claims.set_state("A", "released")
    r = run(state, ["push", "nowhere", "HEAD:feat"], primary, who="B")
    assert "REFUSED" not in r.stderr          # nothing is claimed: git's own failure follows


# --- R2-B5: destinations and URLs come from git, under the call's own ordered config -------------------------

@pytest.mark.parametrize("args", [
    ["push", "-f", "origin", "HEAD:heads/feat"],
    ["push", "-f", "origin", "mine:heads/feat"],
    ["-c", "remote.origin.push=+HEAD:refs/heads/feat", "-c", "remote.origin.push=+HEAD:refs/heads/mine", "push", "origin"],
    ["push", "--mirror", "origin"],
    ["push", "origin", "--delete", "feat"],
    ["push", "origin", ":feat"],
], ids=lambda a: " ".join(a)[:60])
def test_push_destinations_come_from_git_not_from_the_command_line(tmp_path, state, args):
    bare, primary, sha = push_setup(tmp_path, state)
    r = run(state, args, primary, who="B")
    assert r.returncode == 77, r.stderr
    assert remote_sha(state, bare) == sha


def test_push_of_at_sign_resolves_to_the_checked_out_claimed_branch(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    plain(state, ["checkout", "-q", "feat"], primary)
    (primary / "z").write_text("z\n")
    plain(state, ["add", "z"], primary)
    plain(state, ["commit", "-qm", "z"], primary)
    assert run(state, ["push", "origin", "@"], primary, who="B").returncode == 77
    assert remote_sha(state, bare) == sha


def test_wildcard_refspec_is_judged_by_the_remote_names_it_maps_to(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    ade_claims.write_claim(ade_claims.make_claim(id="C", path=tmp_path / "cw", branch="foreign/mine", base_sha="s",
                                                 repo_origin=str(bare), owner_record="C"))
    r = run(state, ["push", "origin", "refs/heads/*:refs/heads/foreign/*"], primary, who="B")
    assert r.returncode == 77, r.stderr
    assert plain(state, ["--git-dir", str(bare), "branch", "--list", "foreign/*"], tmp_path) == ""


def test_push_url_comes_from_the_calls_own_config(tmp_path, state):
    bare, primary, sha = push_setup(tmp_path, state)
    other = tmp_path / "other.git"
    plain(state, ["init", "-q", "--bare", "-b", "main", str(other)], tmp_path)
    plain(state, ["remote", "set-url", "origin", str(other)], primary)      # the repo's own url is an unrelated repo
    r = run(state, ["-c", f"remote.origin.pushurl={bare}", "push", "origin", "HEAD:feat"], primary, who="B")
    assert r.returncode == 77 and remote_sha(state, bare) == sha
    plain(state, ["remote", "set-url", "origin", "zz:origin"], primary)
    r = run(state, ["-c", f"url.{bare}.insteadOf=zz:origin", "push", "origin", "HEAD:feat"], primary, who="B")
    assert r.returncode == 77 and remote_sha(state, bare) == sha
    plain(state, ["remote", "set-url", "origin", str(other)], primary)
    assert run(state, ["push", "-q", "origin", "HEAD:feat"], primary, who="B").returncode == 0   # unrelated repo


def test_normalize_origin_knows_verified_aliases_only():
    n = ade_claims.normalize_origin
    assert n("https://github.com:443/a/b.git") == n("git@github.com:a/b.git") == "github.com/a/b"
    assert n("ssh://git@ssh.github.com:443/a/b.git") == "github.com/a/b"
    assert n("https://github.com:8443/a/b") != n("https://github.com/a/b")
    assert n("ssh://git@example.org:2222/a/b") != n("ssh://git@example.org/a/b")


# --- R2-B2: the workspace git really writes ------------------------------------------------------

def test_effective_worktree_follows_git_dir_env_core_worktree_and_c_chains(tmp_path, state):
    a, b = two_claimed(tmp_path, state)
    cases = [
        (["-C", str(a), "reset", "--hard"], b, {"GIT_DIR": ".git"}),                          # .git is relative to a
        (["-C", str(a), "--git-dir", "../b/.git", "checkout", "-f"], b, {}),                  # worktree = cwd = a
        (["-C", str(a), "--git-dir=../b/.git", "reset", "--hard"], b, {}),
        (["-C", str(a), "checkout", "-f"], b, {"GIT_DIR": "../b/.git"}),
        (["-c", f"core.worktree={a}", "checkout", "-f"], b, {}),
        (["-C", str(tmp_path), "--work-tree", "a", "checkout", "-f"], b, {}),
    ]
    for args, cwd, extra in cases:
        r = run(state, args, cwd, who="B", **extra)
        assert r.returncode == 77, (args, extra, r.stderr)
        assert untouched(a)
    plain(state, ["config", "core.worktree", str(a)], b)       # b's own config points at a's files
    r = run(state, ["checkout", "-f"], b, who="B")
    assert r.returncode == 77 and untouched(a), r.stderr


def test_output_file_symlinks_are_resolved_before_their_parent(tmp_path, state):
    a, b = two_claimed(tmp_path, state)
    os.symlink(a / "f", b / "link")
    os.symlink(a / "newfile", b / "dangling")
    os.symlink(a, b / "dirlink")
    for args in (["log", "-0", "--output=link"], ["log", "-0", "--output=dangling"], ["log", "-0", "--output=dirlink/f"],
                 ["log", "-0", "--output=dirlink/newfile"], ["format-patch", "-1", "-o", "dirlink"]):
        r = run(state, args, b, who="B")
        assert r.returncode == 77, (args, r.stderr)
    assert untouched(a) and not (a / "newfile").exists()
    assert run(state, ["log", "-0", "--output=ok.txt"], b, who="B").returncode == 0


def test_output_over_a_dirty_file_of_a_shared_checkout_is_refused(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    for args in (["diff", "--output=f"], ["log", "-0", "--output=u.txt"], ["diff", "--output", "f"]):
        r = run(state, args, repo, who="B")
        assert r.returncode == 77 and "dirty" in r.stderr, (args, r.stderr)
    assert untouched(repo)
    assert run(state, ["diff", "--output=new.patch"], repo, who="B").returncode == 0


def test_absolute_dash_c_is_honored_when_the_cwd_is_gone(tmp_path, state, monkeypatch):
    a, b = two_claimed(tmp_path, state)

    def gone():
        raise FileNotFoundError("cwd removed")

    monkeypatch.setattr(os, "getcwd", gone)
    assert ade_claims.guard_argv(["-C", str(a), "reset", "--hard"], base_env(state, "B")) == 77
    assert untouched(a)


# --- R2-B4: option state in order, pathspec files, aliases ----------------------------------------

@pytest.mark.parametrize("cmd", [
    ["restore", "--staged", "--no-staged", "f"], ["restore", "--staged", "--no-stag", "f"],
    ["restore", "-S", "--no-staged", "f"],
    ["rm", "-f", "--cached", "--no-cached", "f"], ["rm", "--force", "--cached", "--no-cach", "f"],
    ["rm", "-f", "-n", "--no-dry-run", "f"],
    ["clean", "-f", "--dry-run", "--no-dry-run"], ["clean", "-fn", "--no-dry"], ["clean", "-i"], ["clean", "-fi"],
    ["checkout", "--pathspec-from-file=list"], ["checkout", "--pathspec-from-file", "list"],
    ["checkout", "HEAD", "--pathspec-f=list"],
], ids=lambda c: " ".join(c))
def test_option_state_is_evaluated_in_order_in_a_shared_checkout(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    (repo / "list").write_text("f\n")
    r = run(state, cmd, repo, who="B")
    assert r.returncode == 77, r.stderr
    assert untouched(repo)


@pytest.mark.parametrize("cmd", [
    ["restore", "--no-staged", "--staged", "f"], ["rm", "--cached", "--no-cached", "--cached", "g"],
    ["clean", "-n", "--no-dry-run", "-n"], ["clean", "-nfd", "--dry-run"],
], ids=lambda c: " ".join(c))
def test_a_later_safe_option_restores_the_safe_state(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    (repo / "f").write_text("base\nedit\n")
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


def test_alias_resolution_uses_the_calls_config_and_fails_closed(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    for k, v in (("a1", "a2"), ("a2", "a3"), ("a3", "a4"), ("a4", "reset --hard")):      # four links
        plain(state, ["config", f"alias.{k}", v], repo)
    assert run(state, ["a1"], repo, who="B").returncode == 77
    for i in range(12):                                                                   # deeper than the limit
        plain(state, ["config", f"alias.d{i}", f"d{i + 1}" if i < 11 else "status"], repo)
    r = run(state, ["d0"], repo, who="B")
    assert r.returncode == 77 and "alias chain" in r.stderr
    plain(state, ["config", "alias.l1", "l2"], repo)
    plain(state, ["config", "alias.l2", "l1"], repo)
    assert run(state, ["l1"], repo, who="B").returncode == 77
    inc = tmp_path / "inc.cfg"
    inc.write_text("[alias]\n\tzz = reset --hard\n")
    assert run(state, ["-c", f"include.path={inc}", "zz"], repo, who="B").returncode == 77
    r = check(state, "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.zz GIT_CONFIG_VALUE_0='reset --hard' git zz", repo)
    assert r.returncode == 77
    inline_cfg = tmp_path / "evil.cfg"
    inline_cfg.write_text("[alias]\n\tqq = reset --hard\n")
    assert check(state, f"GIT_CONFIG_GLOBAL={inline_cfg} git qq", repo).returncode == 77
    assert untouched(repo)


# --- R2-B3: what --check cannot judge is refused; scope is tracked ---------------------------------

@pytest.mark.parametrize("tpl", [
    "cat <<< x\ngit reset --hard",
    "bash <<'EOF'\ngit reset --hard\nEOF",
    "sh <<EOF\ngit reset --hard\nEOF",
    "cat <<EOF\n$(git reset --hard)\nEOF",
    "bash <<< 'git reset --hard'",
    "echo 'git reset --hard' | bash",
    "printf 'git reset --hard\\n' | sh -s",
    "source /dev/stdin <<'EOF'\ngit reset --hard\nEOF",
    "(cd {b}) && git reset --hard",
    "pushd {b} > /dev/null; popd > /dev/null; git reset --hard",
    "cd {b} | cat; git reset --hard",
    "cd {b} & git reset --hard",
    "G=git; $G reset --hard",
    "$(which git) reset --hard",
    "$'\\x67it' reset --hard",
    "g{{i,}}t reset --hard",
    "/usr/bin/g?t reset --hard",
    "echo reset | xargs -I{{}} git {{}} --hard",
], ids=lambda c: c.replace("\n", "⏎")[:44])
def test_check_refuses_what_the_lexer_cannot_judge_or_would_misscope(tmp_path, state, tpl):
    a, b = two_claimed(tmp_path, state)
    r = check(state, tpl.format(b=b), a)
    assert r.returncode == 77, (tpl, r.stderr)
    assert untouched(a)


@pytest.mark.parametrize("tpl,where", [
    ("echo '$G reset --hard'", "b"),
    ("cat <<'EOF'\ngit reset --hard\nEOF", "b"),
    ("git commit -F- <<EOF\nnote: git reset --hard is only text\nEOF", "b"),
    ("bash <<EOF\necho hi\nEOF", "b"),
    ("cat <<EOF\n$(date)\nEOF", "b"),
    ("$(pwd)/run.sh git", "b"),
    ("ls *.md; echo git", "b"),
    ("{{ cd {b}; }} && git reset --hard", "a"),
    ("( cd {b} && git reset --hard )", "a"),
    ("cd {b} && git reset --hard", "a"),
    ("git commit --allow-empty -m \"$(cat <<'EOF'\nfix: don't break hooks\n\nbody \"quoted\" text\nEOF\n)\"", "b"),
], ids=lambda c: c.replace("\n", "⏎")[:44] if isinstance(c, str) else c)
def test_check_keeps_literal_data_and_correct_scopes_allowed(tmp_path, state, tpl, where):
    a, b = two_claimed(tmp_path, state)
    r = check(state, tpl.format(b=b), {"a": a, "b": b}[where])
    assert r.returncode == 0, (tpl, r.stderr)


def test_check_refuses_when_nesting_exhausts_the_recursion_limit(tmp_path, state):
    a, b = two_claimed(tmp_path, state)
    deep = lambda n, leaf: "echo $(" * n + leaf + ")" * n   # noqa: E731
    assert check(state, deep(12, "git reset --hard"), a).returncode == 77
    assert check(state, deep(3, "git reset --hard"), a).returncode == 77        # still read, and judged
    assert check(state, deep(12, "echo hi"), a).returncode == 0                 # nothing to judge


def test_match_paren_skips_heredoc_bodies():
    s = "$(cat <<'EOF'\ndon't \"break\"\nEOF\n) tail"
    assert ade_claims._match_paren(s, 1) == s.index("\n)") + 1


# --- R2-M1..M4 -------------------------------------------------------------------------------

def test_worktree_selector_is_resolved_against_the_registered_list(tmp_path, state):
    repo, wt = setup_linked(tmp_path, state)
    r = run(state, ["worktree", "move", "W", str(tmp_path / "W2")], repo, who="B")     # `W` is a unique suffix of W
    assert r.returncode == 77 and wt.exists() and not (tmp_path / "W2").exists(), r.stderr
    assert run(state, ["worktree", "remove", "W"], repo, who="B").returncode == 77
    assert untouched(wt)


def test_ref_transactions_and_forced_fetch_cannot_move_a_claimed_branch(tmp_path, state):
    repo, wt = setup_linked(tmp_path, state)
    head = plain(state, ["rev-parse", "wtb"], repo).strip()
    main = plain(state, ["rev-parse", "main"], repo).strip()
    r = subprocess.run([str(SHIM), "update-ref", "--stdin"], cwd=repo, env=base_env(state, "B"), capture_output=True,
                       text=True, input=f"update refs/heads/wtb {main}\n", timeout=60)
    assert r.returncode == 77, r.stderr
    for args in (["fetch", "--update-head-ok", ".", "+main:wtb"], ["fetch", "-u", ".", "+main:refs/heads/wtb"],
                 ["fetch", ".", "+main:wtb"], ["-c", "remote.origin.fetch=+refs/heads/*:refs/heads/*", "fetch", "origin"]):
        r = run(state, args, repo, who="B")
        assert r.returncode == 77, (args, r.stderr)
    assert plain(state, ["rev-parse", "wtb"], repo).strip() == head
    r = run(state, ["fetch", "."], repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr


def test_symbolic_ref_delete_and_updating_fetch_are_not_read_only():
    ro = lambda argv: ade_claims.is_readonly(ade_claims.parse_git_argv(argv, "/tmp", {}))   # noqa: E731
    assert not ro(["symbolic-ref", "--delete", "HEAD"]) and not ro(["symbolic-ref", "--del", "refs/x"])
    assert ro(["symbolic-ref", "HEAD"]) and ro(["symbolic-ref", "--short", "HEAD"])
    assert not ro(["fetch", "-u"]) and not ro(["fetch", "--update-head-ok"]) and not ro(["fetch", "origin", "+a:b"])
    assert not ro(["fetch", "--refm=x", "origin"])
    assert ro(["fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"]) and ro(["fetch", "--all"]) and ro(["fetch", "origin", "main"])


def test_plain_fetch_stays_on_the_fast_path_and_a_refspec_fetch_does_not(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    no_python = {"ADE_PYTHON": "/nonexistent/python3"}
    assert "unguarded" not in run(state, ["fetch"], repo, who="B", **no_python).stderr
    for args in (["fetch", "origin", "+main:wbr"], ["fetch", "--update-head-ok"], ["fetch", "-qu"]):
        assert "unguarded" in run(state, args, repo, who="B", **no_python).stderr, args


def test_a_stale_pointer_does_not_hide_a_newer_active_claim(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    ade_claims.set_state("A", "released")
    ade_claims.create_claim(ade_claims.make_claim(id="A2", path=repo, branch="b", base_sha="s", owner_record="X"))
    ws = ade_claims.find_workspace(repo)
    assert ade_claims.read_pointer(ws) == "A"                    # the pointer still names the released record
    assert ade_claims.find_claim(ws)["id"] == "A2"
    dirty(repo)
    assert run(state, ["reset", "--hard"], repo, who="B").returncode == 77 and untouched(repo)


def test_reclaim_releases_the_old_record_and_reactivation_rechecks_the_path(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    mk = lambda cid, owner: ade_claims.make_claim(id=cid, path=repo, branch="b", base_sha="s", owner_record=owner)   # noqa: E731
    ade_claims.create_claim(mk("A", "o"), pointer_for=repo)
    ade_claims.create_claim(mk("A2", "o"), pointer_for=repo)
    assert [c["id"] for c in ade_claims.list_claims("active")] == ["A2"]
    assert [c["id"] for c in ade_claims.list_claims("released")] == ["A"]
    assert ade_claims.read_pointer(ade_claims.find_workspace(repo)) == "A2"
    ade_claims.set_state("A", "active")                          # same owner: the newer record is released instead
    assert [c["id"] for c in ade_claims.list_claims("active")] == ["A"]
    ade_claims.set_state("A", "released")
    ade_claims.create_claim(mk("B", "other"))
    with pytest.raises(ade_claims.PathClaimed):
        ade_claims.set_state("A", "active")
    cli = [sys.executable, str(ROOT / "bin" / "ade_claims.py")]
    r = subprocess.run([*cli, "set-state", "A", "active"], env=base_env(state), capture_output=True, text=True, timeout=60)
    assert r.returncode == 4


@pytest.mark.parametrize("cmd", [
    ["-c", "merge.autoStash=true", "merge", "--no-autostash", "main"], ["-c", "rebase.autoStash=true", "merge", "main"],
    ["-c", "merge.autoStash=true", "rebase", "main"], ["-c", "rebase.autoStash=true", "pull", "--no-rebase"],
    ["-c", "merge.autoStash=true", "pull", "--rebase"], ["-c", "rebase.autoStash=true", "pull", "--rebase", "--no-autostash"],
], ids=lambda c: " ".join(c))
def test_autostash_follows_the_final_option_and_the_config_of_what_runs(tmp_path, state, cmd):
    repo = mk_repo(tmp_path, state)
    (repo / "f").write_text("base\nedit\n")
    r = run(state, cmd, repo, who="B")
    assert r.returncode != 77 and "REFUSED" not in r.stderr, r.stderr


# --- R2-L1..L3 ---------------------------------------------------------------------------------

def test_log_flags_never_hold_an_option_value(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A")
    assert run(state, ["commit", "-m", "--secret-FAKE-credential", "--allow-empty"], repo, who="B").returncode == 77
    assert run(state, ["commit", "--message", "--other-secret-xyz", "--author=N <x@y>"], repo, who="B").returncode == 77
    text = (Path(state) / "guard.log").read_text()
    assert "secret" not in text.lower() and "FAKE" not in text
    assert [r["flags"] for r in guard_log(state)] == [["-m", "--allow-empty"], ["--message", "--author"]]


def test_refusal_text_escapes_terminal_control_characters(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    claim(repo, "A", agent="ev\x1b[31mil")
    r = run(state, ["evil\nFORGED-LINE\x1b[2J"], repo, who="B")
    assert r.returncode == 77 and "\x1b" not in r.stderr and "\nFORGED-LINE" not in r.stderr
    r = run(state, ["reset", "--hard"], repo, who="B")
    assert r.returncode == 77 and "\x1b" not in r.stderr and "ev\\x1b[31mil" in r.stderr


def test_hostile_json_types_neither_crash_nor_blind_the_guard(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    dirty(repo)
    (state / "claims").mkdir(parents=True)
    (state / "claims" / "bad.json").write_text(json.dumps(
        {"id": [], "path": str(repo), "state": "active", "owner": {"agent": 7, "model": None, "record": 5},
         "allow": [1, {}], "created_at": 3, "branch": ["x"], "repo_origin": 9}))
    c = ade_claims.read_claim("bad")
    assert c["id"] == "bad" and c["owner"]["agent"] == "" and c["allow"] == [] and c["branch"] == ""
    r = run(state, ["reset", "--hard"], repo, who="B")
    assert r.returncode == 77 and "unguarded" not in r.stderr and untouched(repo)


def test_poisoned_head_and_pointer_bytes_do_not_raise(tmp_path, state):
    repo = mk_repo(tmp_path, state)
    ws = ade_claims.find_workspace(repo)
    (repo / ".git" / "ade-claim").write_bytes(b"\xff\xfe\n")
    assert ade_claims.read_pointer(ws) is None
    (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/\xff\n")
    assert isinstance(ade_claims._head_branch(ws.gitdir), str)
