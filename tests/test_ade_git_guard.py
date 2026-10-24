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
    ["rebase", "--autostash", "main"], ["-c", "rebase.autoStash=true", "pull"], ["merge", "--autostash", "main"],
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
