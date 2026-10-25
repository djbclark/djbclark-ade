"""The ref hooks of bin/ade-git-guard (O2, 2026-10-25; PR 59): libexec/git-hooks/reference-transaction and pre-push.

These tests drive the REAL git binary, not the shim: the hooks are the enforcement point for refs, and the claim is that
they hold whatever argv spelling wrote the ref. Everything runs in temp repos with ADE_STATE_DIR pointed at a temp dir.
Agent A/Z/B = `ACP_RUN_AGENT=1 ADE_CLAIM_ID=<id>`; a human shell has neither. Agent Z owns the claim on branch `cb`.
"""
import json
import os
import random
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))  # bin/ is not a package
import ade_claims  # pyright: ignore[reportMissingImports]  # noqa: E402

GUARD = ROOT / "bin" / "ade-git-guard"
SHIM = ROOT / "libexec" / "agent-bin" / "git"


def _real_git():
    """The first `git` on PATH that is not the guard's shim (an agent's PATH starts with libexec/agent-bin)."""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(d or ".") / "git"
        if cand.is_file() and os.access(cand, os.X_OK) and cand.resolve() != GUARD.resolve():
            return str(cand)
    return "/usr/bin/git"


REAL_GIT = _real_git()
HOOK_REF = ROOT / "libexec" / "git-hooks" / "reference-transaction"
HOOK_PUSH = ROOT / "libexec" / "git-hooks" / "pre-push"
REFUSED = ("aborted by the reference-transaction hook", "by the pre-push hook")


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    st = tmp_path / "state"
    monkeypatch.setenv("ADE_STATE_DIR", str(st))
    return st


def env_for(state_dir, who=None, **extra):
    """A clean environment: no inherited GIT_*/ADE_*/ACP_*/harness variable (this suite runs inside agents too)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "ADE_", "ACP_", "CLAUDE", "PASEO", "PRE_COMMIT", "CODEX_", "OMPCODE"))}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                "ADE_STATE_DIR": str(state_dir), "ADE_REAL_GIT": REAL_GIT})
    if who:
        env["ADE_CLAIM_ID"] = who
        env["ACP_RUN_AGENT"] = "1"
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}      # an extra of None unsets the variable


def git(state_dir, args, cwd, who=None, stdin=None, **extra):
    """The real git binary (no shim), as `who` (None = a human shell)."""
    return subprocess.run([REAL_GIT, *args], cwd=cwd, env=env_for(state_dir, who, **extra), input=stdin,
                          capture_output=True, text=True, timeout=120)


def ok(state_dir, args, cwd, **kw):
    r = git(state_dir, args, cwd, **kw)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def refused(r):
    return r.returncode != 0 and any(m in r.stderr for m in REFUSED)


def log_lines(state_dir):
    p = Path(state_dir) / "guard.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def install(repo, state_dir=None):
    rc, notes = ade_claims.install_hooks(str(repo))
    assert rc == 0, notes
    return notes


def claim_cb(state_dir, origin, cid="Z", branch="cb", path=None, allow=()):
    c = ade_claims.make_claim(id=cid, path=path or "/nonexistent/zpasture", branch=branch, base_sha="deadbeef",
                              repo_origin=origin, owner_record=cid, owner_agent="codex", owner_model="gpt-x", allow=allow)
    ade_claims.write_claim(c)
    return c


@pytest.fixture
def world(tmp_path, state):
    """upstream.git (the origin; holds main=B and cb=A), repo `r` cloned from it with the hooks installed and claim Z on
    `cb`; main is one commit ahead of cb, so every write of cb is a real change. cb is not checked out anywhere."""
    up = tmp_path / "upstream.git"
    seed = tmp_path / "seed"
    ok(state, ["init", "-q", "-b", "main", str(seed)], tmp_path)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "A"], seed)
    ok(state, ["branch", "cb"], seed)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "B"], seed)
    ok(state, ["clone", "-q", "--bare", str(seed), str(up)], tmp_path)
    repo = tmp_path / "r"
    ok(state, ["clone", "-q", str(up), str(repo)], tmp_path)
    ok(state, ["remote", "add", "up", str(up)], repo)
    ok(state, ["config", "remote.up.fetch", "+refs/heads/main:refs/heads/cb"], repo)
    ok(state, ["branch", "cb", "origin/cb"], repo)
    install(repo)
    claim_cb(state, str(up))
    return type("World", (), {"up": up, "repo": repo, "state": state, "tmp": tmp_path,
                              "cb": lambda self: ok(state, ["rev-parse", "cb"], repo),
                              "main": lambda self: ok(state, ["rev-parse", "main"], repo),
                              "up_cb": lambda self: ok(state, ["--git-dir", str(up), "rev-parse", "cb"], repo)})()


# --------------------------------------------------------------------------------------------
# the proof test (design report section 4): refs are guarded whatever the argv spelling
# --------------------------------------------------------------------------------------------

def _mix(rng, repo):
    """A random mix of global options that change nothing about which ref gets written."""
    pool = [["--no-pager"], ["--no-replace-objects"], ["--no-optional-locks"], ["--literal-pathspecs"],
            ["-c", "advice.detachedHead=false"], ["-c", "core.abbrev=12"], ["-c", "fetch.parallel=4"],
            ["--attr-source", "HEAD"], ["-C", str(repo)], ["--no-lazy-fetch"], ["-c", "gc.auto=0"]]
    return [x for opt in rng.sample(pool, rng.randint(0, 4)) for x in opt]


# every way r7-r9 (and the obvious plumbing) found to write `cb`; each MUST move cb when no hook is installed
FORMS = [
    ("fetch . main:heads/cb", ["fetch", ".", "main:heads/cb"], None),
    ("fetch . main:cb", ["fetch", ".", "main:cb"], None),
    ("fetch --multiple --no-multiple . main:cb", ["fetch", "--multiple", "--no-multiple", ".", "main:cb"], None),
    ("pull --no-rebase . main:cb", ["pull", "--no-rebase", "--no-edit", ".", "main:cb"], None),
    ("remote -v update up", ["remote", "-v", "update", "up"], None),
    ("-c fetch.parallel=4 fetch --all", ["-c", "fetch.parallel=4", "fetch", "--all"], None),
    ("--attr-source HEAD branch -f cb main", ["--attr-source", "HEAD", "branch", "-f", "cb", "main"], None),
    ("--shallow-file /dev/null fetch origin +main:cb", ["--shallow-file", "/dev/null", "fetch", "origin", "+main:cb"], None),
    ("update-ref refs/heads/cb main", ["update-ref", "refs/heads/cb", "main"], None),
    ("update-ref -d refs/heads/cb", ["update-ref", "-d", "refs/heads/cb"], None),
    ("update-ref --stdin", ["update-ref", "--stdin"], "update refs/heads/cb main\n"),
    ("branch -D cb", ["branch", "-D", "cb"], None),
    ("branch -f cb main", ["branch", "-f", "cb", "main"], None),
    ("branch -m cb cb9", ["branch", "-m", "cb", "cb9"], None),
    ("branch -M cb cb9", ["branch", "-M", "cb", "cb9"], None),
    ("symbolic-ref refs/heads/cb refs/heads/main", ["symbolic-ref", "refs/heads/cb", "refs/heads/main"], None),
    ("push . main:cb", ["push", ".", "main:cb"], None),
    ("push origin main:cb", ["push", "origin", "main:cb"], None),
    ("push origin :cb", ["push", "origin", ":cb"], None),
    ("push --force origin main:refs/heads/cb", ["push", "--force", "origin", "main:refs/heads/cb"], None),
    ("checkout -B cb main", ["checkout", "-q", "-B", "cb", "main"], None),
    ("switch -C cb main", ["switch", "-q", "-C", "cb", "main"], None),
    ("worktree add -B cb ../wtx main", ["worktree", "add", "-q", "-B", "cb", "WTX", "main"], None),
]


@pytest.mark.parametrize("name,args,stdin", FORMS, ids=[f[0] for f in FORMS])
def test_ref_guard_is_argv_independent(world, name, args, stdin):
    """Agent B, through the real git with a random mix of global options in front, cannot move or delete Z's `cb`: git's own
    reference-transaction (or pre-push) hook refuses, whatever the argv. Mutation: with the stubs removed from `.git/hooks`
    every form succeeds and moves `cb`, so this test is red (recorded in the build report)."""
    rng = random.Random(f"o2-{name}")
    wtx = str(world.tmp / "wtx")
    before = (world.cb(), world.up_cb())
    for attempt in range(3):
        args2 = [wtx if a == "WTX" else a for a in args]
        r = git(world.state, [*_mix(rng, world.repo), *args2], world.repo, who="B", stdin=stdin)
        assert refused(r), (attempt, r.returncode, r.stderr)
        assert (world.cb(), world.up_cb()) == before
    assert any(x["outcome"] == "refused" and x["claim"] == "Z" for x in log_lines(world.state))


def test_the_same_forms_succeed_without_the_hook(world):
    """The control of the proof test: a form that is refused above really would have moved the ref."""
    for f in ("reference-transaction", "pre-push"):
        (world.repo / ".git" / "hooks" / f).unlink()
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")
    assert r.returncode == 0 and world.cb() == world.main()


def test_namespace_never_writes_the_claimed_ref(world):
    """--namespace moves refs under refs/namespaces/<ns>/, not into refs/heads/cb: nothing claimed is touched."""
    before = world.cb()
    git(world.state, ["--namespace=x", "branch", "-f", "cb", "main"], world.repo, who="B")
    git(world.state, ["--namespace=x", "fetch", ".", "main:cb"], world.repo, who="B")
    assert world.cb() == before


def test_refusal_names_owner_claim_and_alternative_and_is_logged(world):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")
    assert refused(r)
    assert "claim Z" in r.stderr and "codex" in r.stderr and "you are B" in r.stderr
    assert "Safe alternative" in r.stderr and "exit 77" in r.stderr and "relay.py" in r.stderr
    last = log_lines(world.state)[-1]
    assert last["outcome"] == "refused" and last["via"] == "reference-transaction" and last["ref"] == "refs/heads/cb"
    assert last["ident"] == "B" and last["claim"] == "Z" and last["rule"] == "ref-claimed-branch"


def test_the_owner_may_write_its_branch_and_the_change_is_logged(world):
    ok(world.state, ["branch", "-f", "cb", "main"], world.repo, who="Z")
    assert world.cb() == world.main()
    ev = [x for x in log_lines(world.state) if x["outcome"] == "ref-change"]
    assert ev and ev[-1]["ref"] == "refs/heads/cb" and ev[-1]["ident"] == "Z" and ev[-1]["claim"] == "Z"
    assert ev[-1]["new"] == world.main()


def test_allow_list_member_may_write(world):
    claim_cb(world.state, str(world.up), cid="Z", allow=("B",))
    ok(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")
    assert world.cb() == world.main()


def test_other_branches_are_untouched_by_the_guard(world):
    ok(world.state, ["branch", "-f", "mine", "main"], world.repo, who="B")
    ok(world.state, ["branch", "-D", "mine"], world.repo, who="B")
    ok(world.state, ["fetch", "origin"], world.repo, who="B")
    ok(world.state, ["commit", "-q", "--allow-empty", "-m", "own"], world.repo, who="B")


def test_a_claim_of_another_repository_is_not_enforced(world):
    claim_cb(world.state, "https://example.invalid/other/repo.git", cid="Q", branch="elsewhere")
    ok(world.state, ["branch", "elsewhere", "main"], world.repo, who="B")


# --------------------------------------------------------------------------------------------
# who is exempt, the override, and fail-open
# --------------------------------------------------------------------------------------------

def test_a_human_shell_is_never_refused(world):
    ok(world.state, ["branch", "-f", "cb", "main"], world.repo)
    assert world.cb() == world.main()
    ok(world.state, ["push", "origin", "main:cb"], world.repo)


def test_git_internal_hook_and_pre_commit_context_are_exempt(world):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", GIT_INDEX_FILE=str(world.tmp / "idx"))
    assert r.returncode == 0, r.stderr
    ok(world.state, ["branch", "-f", "cb", "HEAD~1"], world.repo, who="B", PRE_COMMIT="1")


@pytest.mark.parametrize("marker", [{"CLAUDECODE": "1"}, {"OMPCODE": "1"}, {"CODEX_SANDBOX": "x"}])
def test_a_harness_marker_without_a_claim_may_write_nothing_claimed(world, marker):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, **marker)
    assert refused(r), r.stderr
    assert "no claim id" in r.stderr
    ok(world.state, ["branch", "-f", "free", "main"], world.repo, **marker)


def test_acp_run_agent_zero_is_not_an_agent(world):
    ok(world.state, ["branch", "-f", "cb", "main"], world.repo, ACP_RUN_AGENT="0")


def test_operator_override_allows_and_logs(world):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", ACP_OPERATOR_APPROVED="git-guard")
    assert r.returncode == 0, r.stderr
    assert "ACP_OPERATOR_APPROVED=git-guard" in r.stderr
    assert world.cb() == world.main()
    assert any(x["outcome"] == "override" and x["ref"] == "refs/heads/cb" for x in log_lines(world.state))


def _py(tmp_path, body):
    p = tmp_path / "fakepy"
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return str(p)


@pytest.mark.parametrize("body", ["exit 1", "echo 'Traceback (most recent call last)' >&2; exit 1", "exit 3", "exit 126", "kill -9 $$"],
                         ids=["rc1", "traceback", "alarm-rc3", "rc126", "killed"])
def test_a_crashing_hook_lets_the_transaction_proceed(world, body):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", ADE_PYTHON=_py(world.tmp, body))
    assert r.returncode == 0, r.stderr
    assert world.cb() == world.main()


def test_a_missing_python_lets_the_transaction_proceed(world):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", ADE_PYTHON="/nonexistent/python3")
    assert r.returncode == 0, r.stderr


def test_python_exit_77_is_the_only_refusal(world):
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", ADE_PYTHON=_py(world.tmp, "exit 77"))
    assert r.returncode != 0 and "aborted by the reference-transaction hook" in r.stderr
    assert world.cb() != world.main()


def test_a_missing_ade_checkout_lets_git_proceed(world):
    stub = world.repo / ".git" / "hooks" / "reference-transaction"
    stub.write_text(stub.read_text().replace(str(HOOK_REF), "/nonexistent/libexec/reference-transaction"))
    ok(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")


# --------------------------------------------------------------------------------------------
# per-worktree rules
# --------------------------------------------------------------------------------------------

def _zworktree(w, branch="zb"):
    wt = w.tmp / "zwt"
    ok(w.state, ["worktree", "add", "-q", "-b", branch, str(wt)], w.repo)
    c = ade_claims.make_claim(id="W", path=wt, branch=branch, base_sha="deadbeef", repo_origin=str(w.up), owner_record="W",
                              owner_agent="codex", owner_model="gpt-x")
    ade_claims.write_claim(c)
    ade_claims.write_pointer(wt, "W")
    return wt


def test_head_and_branch_moves_in_a_foreign_claimed_worktree_are_refused(world):
    wt = _zworktree(world)
    head = ok(world.state, ["rev-parse", "HEAD"], wt)
    for args in (["commit", "--allow-empty", "-m", "x"], ["switch", "-c", "other"], ["checkout", "--detach", "main"],
                 ["reset", "--soft", "HEAD~1"], ["update-ref", "refs/heads/zb", "main"]):
        r = git(world.state, args, wt, who="B")
        assert refused(r), (args, r.stderr)
    r = git(world.state, ["-C", str(wt), "commit", "--allow-empty", "-m", "x"], world.repo, who="B")
    assert refused(r), r.stderr
    assert ok(world.state, ["rev-parse", "HEAD"], wt) == head
    ok(world.state, ["commit", "--allow-empty", "-m", "mine"], wt, who="W")      # the owner


def test_stash_in_a_linked_worktree_is_refused_even_for_its_owner_but_not_in_the_primary(world):
    wt = _zworktree(world)
    (wt / "n.txt").write_text("x\n")
    ok(world.state, ["add", "n.txt"], wt)
    r = git(world.state, ["stash"], wt, who="W")
    assert refused(r) and "refs/stash" in r.stderr
    assert ok(world.state, ["stash", "list"], wt) == ""
    (world.repo / "f.txt").write_text("y\n")
    ok(world.state, ["add", "f.txt"], world.repo)
    ok(world.state, ["stash"], world.repo, who="B")
    assert "stash@{0}" in ok(world.state, ["stash", "list"], world.repo)


def test_a_branch_checked_out_in_a_claimed_workspace_is_refused_by_name(world):
    wt = _zworktree(world)
    claim_cb(world.state, str(world.up), cid="W", branch="elsewhere", path=wt)       # the claim names another branch
    r = git(world.state, ["update-ref", "refs/heads/zb", "main"], world.repo, who="B")      # git itself guards `branch -f` here
    assert refused(r) and "checked out" in r.stderr


# --------------------------------------------------------------------------------------------
# pack-refs, gc, reftable, performance
# --------------------------------------------------------------------------------------------

def test_pack_refs_and_gc_beside_someone_elses_claim_are_not_refused(world):
    """pack-refs reports each ref it packs as `0 sha` and each loose ref it prunes as `sha 0`; the hook exempts a transaction
    whose git process is `pack-refs` (measured on git 2.56), so maintenance works and refs keep their values."""
    before = {r: ok(world.state, ["rev-parse", r], world.repo) for r in ("cb", "main")}
    r = git(world.state, ["pack-refs", "--all"], world.repo, who="B")
    assert r.returncode == 0, r.stderr
    r = git(world.state, ["gc", "--quiet"], world.repo, who="B")
    assert r.returncode == 0, r.stderr
    assert {r: ok(world.state, ["rev-parse", r], world.repo) for r in ("cb", "main")} == before
    assert not any(x["outcome"] == "refused" for x in log_lines(world.state))
    # ... and a real deletion of the (now packed) claimed ref is still refused
    assert refused(git(world.state, ["branch", "-D", "cb"], world.repo, who="B"))
    assert ok(world.state, ["rev-parse", "cb"], world.repo) == before["cb"]


def test_reftable_backend_is_guarded_too(tmp_path, state):
    repo = tmp_path / "rt"
    r = git(state, ["init", "-q", "-b", "main", "--ref-format=reftable", str(repo)], tmp_path)
    if r.returncode != 0:
        pytest.skip(f"this git cannot build a reftable repository: {r.stderr.strip()[:80]}")
    ok(state, ["commit", "-q", "--allow-empty", "-m", "A"], repo)
    ok(state, ["branch", "cb"], repo)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "B"], repo)
    install(repo)
    claim_cb(state, "")
    before = ok(state, ["rev-parse", "cb"], repo)
    assert refused(git(state, ["branch", "-f", "cb", "main"], repo, who="B"))
    assert refused(git(state, ["update-ref", "-d", "refs/heads/cb"], repo, who="B"))
    assert ok(state, ["rev-parse", "cb"], repo) == before


def test_a_500_ref_fetch_starts_no_python_and_costs_little_beside_a_hookless_fetch(tmp_path, state):
    """Measured 2026-10-25 (git 2.56): a fetch of N changed refs opens N reference transactions. The stub matches stdin with
    bash's own regex, so none of the 500 starts Python (a fork-free path), and the fetch costs about what a hookless one does
    (same machine, same moment: a loose bound, since the suite runs on a loaded Mac). `gc.auto=0` keeps the auto-gc's
    `pack-refs` (which does name refs/heads/main) out of the count."""
    up = tmp_path / "big.git"
    ok(state, ["init", "-q", "-b", "main", "--bare", str(up)], tmp_path)
    tree = ok(state, ["--git-dir", str(up), "hash-object", "-t", "tree", "-w", "--stdin"], tmp_path, stdin="")
    c1 = ok(state, ["--git-dir", str(up), "commit-tree", tree, "-m", "1"], tmp_path)
    c2 = ok(state, ["--git-dir", str(up), "commit-tree", tree, "-m", "2", "-p", c1], tmp_path)
    c3 = ok(state, ["--git-dir", str(up), "commit-tree", tree, "-m", "3", "-p", c2], tmp_path)
    ok(state, ["--git-dir", str(up), "update-ref", "refs/heads/main", c1], tmp_path)
    ok(state, ["--git-dir", str(up), "update-ref", "--stdin"], tmp_path,
       stdin="".join(f"create refs/heads/b{i} {c1}\n" for i in range(500)))
    plain_repo, hooked = tmp_path / "plain", tmp_path / "hooked"
    ok(state, ["clone", "-q", str(up), str(plain_repo)], tmp_path)
    ok(state, ["clone", "-q", str(up), str(hooked)], tmp_path)
    install(hooked)
    counter = tmp_path / "py-starts"
    py = _py(tmp_path, f'echo x >> {counter}; exec {sys.executable} "$@"')

    def timed(repo, new, **kw):
        ok(state, ["--git-dir", str(up), "update-ref", "--stdin"], tmp_path,
           stdin="".join(f"update refs/heads/b{i} {new}\n" for i in range(500)))
        t0 = time.time()
        r = git(state, ["-c", "gc.auto=0", "fetch", "-q", "origin"], repo, **kw)
        took = time.time() - t0
        assert r.returncode == 0, r.stderr
        assert ok(state, ["rev-parse", "refs/remotes/origin/b499"], repo) == new
        return took

    base = timed(plain_repo, c2, who="B")
    with_hook = timed(hooked, c3, who="B", ADE_PYTHON=py)
    assert not counter.exists(), counter.read_text()
    assert with_hook < base * 6 + 30, (with_hook, base)


def test_a_human_fetch_never_starts_python_either(tmp_path, state):
    repo = tmp_path / "h"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    install(repo)
    counter = tmp_path / "py-starts"
    py = _py(tmp_path, f'echo x >> {counter}; exec {sys.executable} "$@"')
    ok(state, ["commit", "-q", "--allow-empty", "-m", "x"], repo, ADE_PYTHON=py)
    assert not counter.exists()


# --------------------------------------------------------------------------------------------
# pre-push
# --------------------------------------------------------------------------------------------

def test_pre_push_refuses_a_claimed_branch_and_a_deletion_and_lets_the_owner_and_other_branches_through(world):
    up_before = world.up_cb()
    r = git(world.state, ["push", "origin", "main:cb"], world.repo, who="B")
    assert refused(r) and "pre-push" in r.stderr
    assert refused(git(world.state, ["push", "origin", ":cb"], world.repo, who="B"))
    assert world.up_cb() == up_before
    ok(world.state, ["push", "origin", "main:other"], world.repo, who="B")
    ok(world.state, ["push", "origin", "main:cb"], world.repo, who="Z")
    assert world.up_cb() == world.main()


def test_pre_push_matches_by_the_remotes_url_not_by_the_branch_name_alone(world, tmp_path):
    other = tmp_path / "other.git"
    ok(world.state, ["clone", "-q", "--bare", str(world.up), str(other)], tmp_path)
    ok(world.state, ["remote", "add", "fork", str(other)], world.repo)
    ok(world.state, ["push", "fork", "main:cb"], world.repo, who="B")      # a different repository: claims are per repository


# --------------------------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------------------------

def test_install_is_idempotent_and_writes_executable_stubs_that_name_the_checkout_by_absolute_path(tmp_path, state):
    repo = tmp_path / "i"
    ok(state, ["init", "-q", str(repo)], tmp_path)
    assert all("installed" in n for n in install(repo))
    assert all("already installed" in n for n in install(repo))
    for name in ("reference-transaction", "pre-push"):
        stub = repo / ".git" / "hooks" / name
        assert stub.stat().st_mode & stat.S_IXUSR
        assert str(ROOT / "libexec" / "git-hooks" / name) in stub.read_text()
        assert not (repo / ".git" / "hooks" / f"{name}.pre-ade").exists()


def test_install_keeps_an_existing_hook_as_pre_ade_and_runs_it_after_ours(world):
    hooks = world.repo / ".git" / "hooks"
    for n in ("reference-transaction", "pre-push"):
        (hooks / n).unlink()
    seen = world.tmp / "seen"
    (hooks / "pre-push").write_text(f"#!/bin/sh\ncat >> {seen}\nexit 0\n")
    (hooks / "reference-transaction").write_text(f"#!/bin/sh\necho \"$1\" >> {seen}.rt\ncat >/dev/null\nexit 0\n")
    for n in ("reference-transaction", "pre-push"):
        (hooks / n).chmod(0o755)
    notes = install(world.repo)
    assert any("kept as pre-push.pre-ade" in n for n in notes)
    assert (hooks / "pre-push.pre-ade").exists() and (hooks / "reference-transaction.pre-ade").exists()
    ok(world.state, ["push", "origin", "main:other"], world.repo, who="B")       # ours allows, then the old hook sees stdin
    assert "refs/heads/other" in seen.read_text()
    assert "prepared" in Path(str(seen) + ".rt").read_text()
    # ours still refuses first, and the old hook does not run for a refused update
    Path(str(seen) + ".rt").unlink()
    assert refused(git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B"))
    assert not Path(str(seen) + ".rt").exists() or "prepared" not in Path(str(seen) + ".rt").read_text()
    # the old hook's own failure still aborts, for a human too
    (hooks / "pre-push.pre-ade").write_text("#!/bin/sh\ncat >/dev/null\nexit 1\n")
    assert git(world.state, ["push", "origin", "main:other2"], world.repo).returncode != 0


def test_install_refuses_while_core_hooks_path_is_set_and_says_why(tmp_path, state):
    repo = tmp_path / "hp"
    ok(state, ["init", "-q", str(repo)], tmp_path)
    ok(state, ["config", "core.hooksPath", str(tmp_path / "elsewhere")], repo)
    rc, notes = ade_claims.install_hooks(str(repo))
    assert rc == ade_claims.EXIT_HOOKSPATH and "core.hooksPath" in notes[0]
    assert not (repo / ".git" / "hooks" / "pre-push").exists()


def test_install_outside_a_repository_fails_with_usage_code(tmp_path, state):
    rc, notes = ade_claims.install_hooks(str(tmp_path))
    assert rc == 2 and "not inside a git repository" in notes[0]


def test_install_covers_every_linked_worktree_through_the_common_dir(tmp_path, state):
    repo = tmp_path / "m"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "x"], repo)
    wt = tmp_path / "lw"
    ok(state, ["worktree", "add", "-q", "-b", "lwb", str(wt)], repo)
    install(wt)
    assert (repo / ".git" / "hooks" / "pre-push").exists()


def test_cli_install_through_the_guard_front_door(tmp_path, state):
    repo = tmp_path / "cli"
    ok(state, ["init", "-q", str(repo)], tmp_path)
    r = subprocess.run([str(GUARD), "install", str(repo)], env=env_for(state), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (repo / ".git" / "hooks" / "reference-transaction").exists()
    r = subprocess.run([str(GUARD), "install", str(tmp_path)], env=env_for(state), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2


def test_the_shim_installs_the_hooks_lazily_in_a_repo_without_them_and_never_elsewhere(tmp_path, state):
    repo = tmp_path / "lazy"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "x"], repo)
    assert not (repo / ".git" / "hooks" / "pre-push").exists()
    r = subprocess.run([str(SHIM), "branch", "newb"], cwd=repo, env=env_for(state, "B"), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert (repo / ".git" / "hooks" / "reference-transaction").exists() and (repo / ".git" / "hooks" / "pre-push").exists()
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    r = subprocess.run([str(SHIM), "branch", "x"], cwd=nowhere, env=env_for(state, "B"), capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and not (nowhere / ".git").exists() and not list(nowhere.iterdir())


def test_the_shim_does_not_install_while_core_hooks_path_is_set(tmp_path, state):
    repo = tmp_path / "lazyhp"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    ok(state, ["config", "core.hooksPath", str(tmp_path / "custom")], repo)
    r = subprocess.run([str(SHIM), "branch", "newb"], cwd=repo, env=env_for(state, "B"), capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 128)       # git's own answer; never the guard's
    assert not (repo / ".git" / "hooks" / "pre-push").exists()


def test_a_failed_lazy_install_never_fails_the_command(tmp_path, state):
    repo = tmp_path / "ro"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "x"], repo)
    hooks = repo / ".git" / "hooks"
    shutil.rmtree(hooks)
    hooks.write_text("a file where the hooks directory should be\n")
    r = subprocess.run([str(SHIM), "branch", "newb"], cwd=repo, env=env_for(state, "B"), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_hooks_and_stubs_parse_under_bash_3_2(tmp_path):
    for p in (HOOK_REF, HOOK_PUSH):
        assert subprocess.run(["/bin/bash", "-n", str(p)], capture_output=True).returncode == 0
        assert p.stat().st_mode & stat.S_IXUSR
        assert "declare -A" not in p.read_text()
    for name in ("reference-transaction", "pre-push"):
        stub = tmp_path / f"stub-{name}"
        stub.write_text(ade_claims._stub_text(name))
        assert subprocess.run(["/bin/bash", "-n", str(stub)], capture_output=True).returncode == 0


# --------------------------------------------------------------------------------------------
# round 10 (2026-10-25): git answers config questions; the stub fails open at the bash layer; exact parent identity
# --------------------------------------------------------------------------------------------

def shim(state_dir, args, cwd, who=None, **extra):
    """`git ARGS` through the guard's shim (the real git underneath, found through ADE_REAL_GIT)."""
    return subprocess.run([str(SHIM), *args], cwd=cwd, env=env_for(state_dir, who, **extra), capture_output=True, text=True,
                          timeout=120)


def _pairs(n, last=("core.hooksPath", "/dev/null")):
    """GIT_CONFIG_COUNT=n with n-1 harmless pairs and `last` as pair n-1 (the 257th for n=257)."""
    env = {"GIT_CONFIG_COUNT": str(n)}
    for i in range(n - 1):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = f"ade.k{i}", "1"
    env[f"GIT_CONFIG_KEY_{n - 1}"], env[f"GIT_CONFIG_VALUE_{n - 1}"] = last
    return env


def _held(w, r):
    assert r.returncode == 77 and "hook-config" in r.stderr, (r.returncode, r.stderr)
    assert w.cb() != w.main()


def test_r10_f1_hook_disabling_config_past_257_env_pairs_is_refused_not_truncated(world):
    _held(world, shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", **_pairs(257)))
    r = shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", **_pairs(257, ("ade.last", "1")))
    assert r.returncode != 77, r.stderr              # the same 257 pairs without hooksPath: the shim has no quarrel (the hook does)


def test_r10_f1_hooks_path_beyond_one_mib_of_global_config_is_refused_not_truncated(world, tmp_path):
    cfg = tmp_path / "big.cfg"
    cfg.write_text("# " + "x" * ((1 << 20) + 10) + "\n[core]\n\thooksPath = /dev/null\n")
    _held(world, shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", GIT_CONFIG_GLOBAL=str(cfg)))


def test_r10_f1_a_config_git_cannot_read_is_refused_with_the_reason(world, tmp_path):
    cfg = tmp_path / "broken.cfg"
    cfg.write_text("[core\n\thooksPath = /dev/null\n")
    r = shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", GIT_CONFIG_GLOBAL=str(cfg))
    assert r.returncode == 77 and "hook-config-unknown" in r.stderr and "did not say" in r.stderr, r.stderr
    assert world.cb() != world.main()


@pytest.mark.parametrize("how", ["home", "xdg", "empty-value"])
def test_r10_f2_f5_a_global_config_git_finds_through_home_or_xdg_that_sets_hooks_path_is_refused(world, tmp_path, how):
    home = tmp_path / "home"
    (home / ".config" / "git").mkdir(parents=True)
    body = "[core]\n\thooksPath = /dev/null\n" if how != "empty-value" else "[core]\n\thooksPath =\n"
    extra = {"GIT_CONFIG_GLOBAL": None, "HOME": str(home)}
    if how == "xdg":
        (tmp_path / "xdg" / "git").mkdir(parents=True)
        (tmp_path / "xdg" / "git" / "config").write_text(body)
        extra["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")
    else:
        (home / ".gitconfig").write_text(body)
    _held(world, shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", **extra))


def test_r10_f2_an_included_file_that_sets_hooks_path_is_refused_because_git_follows_it(world, tmp_path):
    inc = tmp_path / "inc.cfg"
    inc.write_text("[core]\n\thooksPath = /dev/null\n")
    cfg = tmp_path / "g.cfg"
    cfg.write_text(f"[include]\n\tpath = {inc}\n")
    _held(world, shim(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B", GIT_CONFIG_GLOBAL=str(cfg)))


def _stub_with_hook(w, name, body):
    """Point the INSTALLED stub of `name` at a scratch hook with `body` (the stub still does everything else)."""
    fake = w.tmp / f"fake-{name}"
    fake.write_text("#!/bin/bash\n" + body + "\n")
    fake.chmod(0o755)
    stub = w.repo / ".git" / "hooks" / name
    text = stub.read_text()
    stub.write_text(re.sub(r"(?m)^hook=.*$", lambda m: "hook=" + shlex.quote(str(fake)), text))
    assert f"hook={shlex.quote(str(fake))}" in stub.read_text()


CRASHES = ["cat >/dev/null; exit 1", "cat >/dev/null; exit 3", "cat >/dev/null; exit 126", "cat >/dev/null; kill -9 $$",
           "exit 1", "echo boom >&2; exit 2"]


@pytest.mark.parametrize("who", ["B", None], ids=["agent", "human"])
@pytest.mark.parametrize("body", CRASHES)
def test_r10_f4_a_crashing_checkout_hook_lets_a_ref_write_through_the_installed_stub(world, body, who):
    _stub_with_hook(world, "reference-transaction", body)
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who=who)
    assert r.returncode == 0, r.stderr
    assert world.cb() == world.main()


@pytest.mark.parametrize("body", CRASHES)
def test_r10_f4_a_crashing_pre_push_hook_lets_a_push_through_the_installed_stub(world, body):
    _stub_with_hook(world, "pre-push", body)
    ok(world.state, ["push", "origin", "main:fresh"], world.repo, who="B")


def test_r10_f4_only_exit_77_refuses_and_the_pre_ade_chain_survives_a_crash(world):
    _stub_with_hook(world, "reference-transaction", "cat >/dev/null; exit 77")
    assert refused(git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B"))
    assert world.cb() != world.main()
    hooks = world.repo / ".git" / "hooks"
    (hooks / "reference-transaction.pre-ade").write_text("#!/bin/sh\ncat >/dev/null\nexit 1\n")
    (hooks / "reference-transaction.pre-ade").chmod(0o755)
    _stub_with_hook(world, "reference-transaction", "kill -9 $$")
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")
    assert refused(r) and world.cb() != world.main()     # our hook crashed (fail open); the kept old hook still said no


def test_r10_f3_a_forged_argv0_does_not_pass_for_pack_refs(world):
    r = subprocess.run(["git pack-refs", "branch", "-f", "cb", "main"], executable=REAL_GIT, cwd=world.repo,
                       env=env_for(world.state, "B"), capture_output=True, text=True, timeout=120)
    assert refused(r), r.stderr
    assert world.cb() != world.main()


def test_r10_f5_an_empty_core_hooks_path_counts_as_set_for_install_and_lazy_install(tmp_path, state):
    repo = tmp_path / "ehp"
    ok(state, ["init", "-q", "-b", "main", str(repo)], tmp_path)
    ok(state, ["commit", "-q", "--allow-empty", "-m", "x"], repo)
    ok(state, ["config", "core.hooksPath", ""], repo)
    rc, notes = ade_claims.install_hooks(str(repo))
    assert rc == ade_claims.EXIT_HOOKSPATH and "core.hooksPath is set" in notes[0]
    r = shim(state, ["branch", "newb"], repo, who="B")
    assert r.returncode == 0, r.stderr
    assert not (repo / ".git" / "hooks" / "pre-push").exists()


def _origin_text(w, new_lines):
    cfg = w.repo / ".git" / "config"
    text = cfg.read_text()
    text, n = re.subn(r'(\[remote "origin"\]\n)\turl = [^\n]*\n', lambda m: m.group(1) + new_lines, text)
    assert n == 1
    cfg.write_text(text)


@pytest.mark.parametrize("form", ["comment", "quoted", "quoted-comment", "included"])
def test_r10_f6_origin_is_what_git_says_whatever_its_spelling_in_the_config(world, form):
    up = str(world.up)
    if form == "included":
        (world.repo / ".git" / "origin.cfg").write_text(f'[remote "origin"]\n\turl = {up}\n')
        _origin_text(world, "")
        with open(world.repo / ".git" / "config", "a") as f:
            f.write("[include]\n\tpath = origin.cfg\n")
    else:
        url = {"comment": f"{up} # normal comment", "quoted": f'"{up}"', "quoted-comment": f'"{up}" ; note'}[form]
        _origin_text(world, f"\turl = {url}\n")
    assert ok(world.state, ["config", "--get", "remote.origin.url"], world.repo) == up
    r = git(world.state, ["branch", "-f", "cb", "main"], world.repo, who="B")
    assert refused(r), r.stderr
    assert world.cb() != world.main()


# --------------------------------------------------------------------------------------------
# round 11 (2026-10-25): the origin question reads the repository's own config and nothing the caller controls
# --------------------------------------------------------------------------------------------

def _count_env(pairs):
    env = {"GIT_CONFIG_COUNT": str(len(pairs))}
    for i, (k, v) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    return env


def _move_refused(w, args, **extra):
    r = shim(w.state, args, w.repo, who="B", **extra)
    assert refused(r), (r.returncode, r.stderr)
    assert r.returncode == 128
    assert w.cb() != w.main()


@pytest.mark.parametrize("how", ["dash-c", "count-env", "parameters-env", "global-file"])
def test_r11_f1_a_callers_config_never_rewrites_the_origin_the_claim_is_matched_against(world, tmp_path, how):
    if how == "dash-c":
        _move_refused(world, ["-c", "remote.origin.url=/x", "branch", "-f", "cb", "main"])
    elif how == "count-env":
        _move_refused(world, ["branch", "-f", "cb", "main"], **_count_env([("remote.origin.url", "/x")]))
    elif how == "parameters-env":
        _move_refused(world, ["branch", "-f", "cb", "main"], GIT_CONFIG_PARAMETERS="'remote.origin.url=/x'")
    else:
        g = tmp_path / "g.cfg"
        g.write_text('[remote "origin"]\n\turl = /x\n')
        _move_refused(world, ["branch", "-f", "cb", "main"], GIT_CONFIG_GLOBAL=str(g))


def _wt_cb(w, wt):
    return ok(w.state, ["rev-parse", "cb"], wt)


def test_r11_f2_an_origin_question_that_fails_only_for_the_hook_does_not_switch_the_claim_rule_off(world, tmp_path):
    """The repository's own config includes a broken file only when the git dir is the COMMON dir: the main git, running in
    the linked worktree (git dir .git/worktrees/wt), never reads it; the hook's question (`--git-dir <common>`) does and
    fails. An unanswered question must not read as `no claim`."""
    common = (world.repo / ".git").resolve()
    wt = tmp_path / "wt"
    ok(world.state, ["worktree", "add", "-q", "--detach", str(wt)], world.repo)
    (tmp_path / "bad.cfg").write_text("[broken\n")
    with open(common / "config", "a") as f:
        f.write(f'[includeIf "gitdir:{common}"]\n\tpath = {tmp_path / "bad.cfg"}\n')
    assert git(world.state, ["config", "--get", "remote.origin.url"], wt).returncode == 0     # git itself is fine in wt
    r = shim(world.state, ["branch", "-f", "cb", "main"], wt, who="B")
    assert refused(r), (r.returncode, r.stderr)
    assert _wt_cb(world, wt) != ok(world.state, ["rev-parse", "main"], wt)
    r = shim(world.state, ["branch", "-f", "cb", "main"], wt, who="Z")              # the owner may still write its own branch
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("n", range(1, 9))                  # the exec path's length mod 8 decides the kernel's padding
@pytest.mark.parametrize("argv0", ["", "x"])
def test_r11_f3_proc_args_returns_the_exact_argv_whatever_the_first_word_is_and_the_exec_paths_length(tmp_path, argv0, n):
    link = tmp_path / ("s" * n)
    link.symlink_to(shutil.which("sleep"))
    p = subprocess.Popen([argv0, "30"], executable=str(link))
    try:
        got = None
        for _ in range(100):
            got = ade_claims._proc_args(p.pid)
            if got is not None and got[1] == [argv0, "30"]:
                break
            time.sleep(0.05)
        assert got is not None and got[1] == [argv0, "30"], got
    finally:
        p.kill()
        p.wait()


def _forged_pack_refs(w, argv_tail, **extra):
    (w.repo / "pack-refs").mkdir(exist_ok=True)
    return subprocess.run(argv_tail, executable=REAL_GIT, cwd=w.repo, env=env_for(w.state, "B", **extra), capture_output=True,
                          text=True, timeout=120)


def test_r11_f3_an_empty_argv0_does_not_shift_the_parse_into_a_pack_refs_exemption(world):
    r = _forged_pack_refs(world, ["", "-C", "pack-refs", "branch", "-f", "cb", "main"])
    assert refused(r), (r.returncode, r.stderr)
    assert world.cb() != world.main()
