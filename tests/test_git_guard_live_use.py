"""ade-git-guard: `git worktree remove` is refused while another live process uses the directory (gg-01, 2026-11-14).

Incident: `git worktree remove` removed site-public-djbclark-orchard-wt while an orphaned claude (PID 10129) still had its
cwd there. The guard asks lsof (cwd of every process, then open files under the target); most tests use a fake lsof
($ADE_LSOF) and one uses the real one with a real child process.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ade_git_guard import claim, guard_log, mk_repo, plain, run, state  # noqa: E402,F401  (state: autouse fixture)

FAKE = '''#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get("FAKE_LSOF_MODE", "ok")
files = "+D" in sys.argv
if mode == "fail" or (mode == "fail-files" and files):
    sys.exit(2)
if mode == "hang" or (mode == "hang-files" and files):
    time.sleep(120)
key = "FAKE_LSOF_CWD" if "cwd" in sys.argv else "FAKE_LSOF_FILES"
root = sys.argv[sys.argv.index("+D") + 1] if files else ""
for pid, cmd, fd, name in json.loads(os.environ.get(key, "[]")):
    # real lsof scopes +D to the directory itself (and spells odd bytes its own way, so the caller must not re-filter)
    if files and not os.environ.get("FAKE_LSOF_UNSCOPED") and not (name == root or name.startswith(root + "/")):
        continue
    print(f"p{pid}\\nc{cmd}\\nf{fd}\\nn{name}")
'''


@pytest.fixture
def rig(tmp_path, state):
    """A repo r with a linked worktree w (human-made), a fake lsof, and `remove(...)` run as agent B."""
    repo = mk_repo(tmp_path, state, "r")
    wt = tmp_path / "w"
    plain(state, ["worktree", "add", "-q", "-b", "wbranch", str(wt)], repo)
    fake = tmp_path / "lsof"
    fake.write_text(FAKE)
    fake.chmod(0o755)

    class Rig:
        pass
    r = Rig()
    r.repo, r.wt, r.fake, r.state = repo, wt, fake, state

    def remove(*extra_args, cwd_users=(), file_users=(), **env):
        e = {"ADE_LSOF": str(fake), "FAKE_LSOF_CWD": json.dumps(cwd_users), "FAKE_LSOF_FILES": json.dumps(file_users)}
        e.update(env)
        return run(state, ["worktree", "remove", *extra_args, str(wt)], repo, who="B", **e)
    r.remove = remove
    return r


def test_a_process_with_its_cwd_inside_blocks_the_removal(rig):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt / "sub")]])
    assert p.returncode == 77, p.stderr
    assert "live process" in p.stderr and "pid 10129" in p.stderr and "claude" in p.stderr
    assert "ADE_ALLOW_LIVE_WORKTREE_REMOVE" in p.stderr
    assert rig.wt.is_dir()
    assert [r["rule"] for r in guard_log(rig.state)] == ["worktree remove: live process"]


def test_an_open_file_inside_blocks_the_removal(rig):
    p = rig.remove(file_users=[[777, "vim", "3r", str(rig.wt / "f")]])
    assert p.returncode == 77, p.stderr
    assert "pid 777" in p.stderr and "vim" in p.stderr and str(rig.wt / "f") in p.stderr
    assert rig.wt.is_dir()


def test_no_user_means_the_removal_runs(rig):
    p = rig.remove()
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_a_process_beside_the_worktree_is_not_a_user(rig):
    """`/x/w-other` shares the prefix `/x/w` and is not inside it."""
    other = str(rig.wt) + "-other"
    p = rig.remove(cwd_users=[[5, "zsh", "cwd", other]], file_users=[[6, "vim", "3r", other + "/f"]])
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_the_callers_own_process_chain_is_not_a_user(rig):
    """The shell or agent that runs the removal (this test process is an ancestor of the guard) is not "another user"."""
    p = rig.remove(cwd_users=[[os.getpid(), "pytest", "cwd", str(rig.wt)]])
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_force_does_not_bypass_it(rig):
    p = rig.remove("--force", cwd_users=[[10129, "claude", "cwd", str(rig.wt)]])
    assert p.returncode == 77 and "live process" in p.stderr
    assert rig.wt.is_dir()


def test_the_env_override_allows_it(rig):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ADE_ALLOW_LIVE_WORKTREE_REMOVE="1")
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_the_env_override_does_not_open_the_force_rule(rig):
    """Adversary r2 BLOCK: the override allows the live-process rule only; `--force` on an unclaimed tree is still refused."""
    p = rig.remove("--force", cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ADE_ALLOW_LIVE_WORKTREE_REMOVE="1")
    assert p.returncode == 77, p.stderr
    assert "worktree remove --force" in p.stderr
    assert rig.wt.is_dir()


def test_the_env_override_does_not_hide_a_broken_config_refusal(rig, tmp_path):
    """Adversary r3: a pending `hook-config-unknown` refusal wins over an allowed (overridden) live-process decision."""
    bad = tmp_path / "badconfig"
    bad.write_text("[core\nbroken = \n")
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ADE_ALLOW_LIVE_WORKTREE_REMOVE="1",
                   GIT_CONFIG_GLOBAL=str(bad))
    assert p.returncode == 77, p.stderr
    assert "hook-config-unknown" in p.stderr
    assert rig.wt.is_dir()


def test_the_env_override_with_a_claim_of_mine_still_removes_with_force(rig):
    """A claimed-by-me tree has no --force refusal, so the override plus --force goes through (the owner chose both)."""
    claim(rig.wt, cid="B", branch="wbranch")
    p = rig.remove("--force", cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ADE_ALLOW_LIVE_WORKTREE_REMOVE="1")
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_the_operator_override_allows_it_and_logs(rig):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ACP_OPERATOR_APPROVED="git-guard")
    assert p.returncode == 0 and "allowed" in p.stderr
    assert [(r["outcome"], r["rule"]) for r in guard_log(rig.state)] == [("override", "worktree remove: live process")]


@pytest.mark.parametrize("env", [{"ADE_LSOF": "/nonexistent/lsof"}, {"FAKE_LSOF_MODE": "fail"}])
def test_an_lsof_that_is_missing_or_fails_fails_open(rig, env):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], **env)
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_an_lsof_that_hangs_fails_open_after_the_timeout(rig):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], FAKE_LSOF_MODE="hang", ADE_LSOF_TIMEOUT="1")
    assert p.returncode == 0, p.stderr
    assert not rig.wt.exists()


def test_a_claimed_worktree_of_mine_is_checked_too(rig):
    claim(rig.wt, cid="B", branch="wbranch")
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]])
    assert p.returncode == 77 and "live process" in p.stderr
    assert "claim B" in p.stderr


def test_a_long_list_is_cut_and_counted(rig):
    users = [[100 + i, "node", "cwd", str(rig.wt)] for i in range(11)]
    p = rig.remove(cwd_users=users)
    assert p.returncode == 77
    assert "pid 100 " in p.stderr and "pid 107 " in p.stderr and "pid 108 " not in p.stderr
    assert "and 3 more" in p.stderr


def test_a_human_shell_is_not_guarded(rig):
    e = {"ADE_LSOF": str(rig.fake), "FAKE_LSOF_CWD": json.dumps([[1, "x", "cwd", str(rig.wt)]])}
    p = run(rig.state, ["worktree", "remove", str(rig.wt)], rig.repo, **e)
    assert p.returncode == 0, p.stderr


def test_a_command_with_control_characters_is_escaped(rig):
    p = rig.remove(cwd_users=[[9, "evil\x1b[2Jname", "cwd", str(rig.wt)]])
    assert p.returncode == 77 and "\x1b" not in p.stderr and "\\x1b" in p.stderr


@pytest.mark.skipif(shutil.which("lsof") is None and not os.path.exists("/usr/sbin/lsof"), reason="no lsof")
def test_real_lsof_sees_a_real_process_cwd(tmp_path, state):
    repo = mk_repo(tmp_path, state, "r")
    wt = tmp_path / "w"
    plain(state, ["worktree", "add", "-q", "-b", "wbranch", str(wt)], repo)
    child = subprocess.Popen(["sleep", "120"], cwd=wt, stdin=subprocess.DEVNULL)
    try:
        p = run(state, ["worktree", "remove", str(wt)], repo, who="B")
        assert p.returncode == 77, p.stderr
        assert f"pid {child.pid} " in p.stderr and "sleep" in p.stderr
        assert wt.is_dir()
    finally:
        child.kill()
        child.wait()
    p = run(state, ["worktree", "remove", str(wt)], repo, who="B")
    assert p.returncode == 0, p.stderr
    assert not wt.exists()


@pytest.mark.parametrize("env", [{"FAKE_LSOF_MODE": "fail-files"}, {"FAKE_LSOF_MODE": "hang-files", "ADE_LSOF_TIMEOUT": "1"}])
def test_a_failed_open_file_walk_leaves_the_cwd_answer_standing(rig, env):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], **env)
    assert p.returncode == 77 and "pid 10129" in p.stderr
    assert rig.wt.is_dir()


def test_move_is_not_checked(rig, tmp_path):
    e = {"ADE_LSOF": str(rig.fake), "FAKE_LSOF_CWD": json.dumps([[10129, "claude", "cwd", str(rig.wt)]])}
    p = run(rig.state, ["worktree", "move", str(rig.wt), str(tmp_path / "moved")], rig.repo, who="B", **e)
    assert p.returncode == 0, p.stderr
    assert (tmp_path / "moved").is_dir()


def test_the_env_override_is_logged_and_named(rig):
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]], ADE_ALLOW_LIVE_WORKTREE_REMOVE="1")
    assert p.returncode == 0 and "ADE_ALLOW_LIVE_WORKTREE_REMOVE=1: allowed" in p.stderr
    assert [(r["outcome"], r["rule"]) for r in guard_log(rig.state)] == [("override", "worktree remove: live process")]


def test_the_override_with_nobody_inside_is_silent(rig):
    p = rig.remove(ADE_ALLOW_LIVE_WORKTREE_REMOVE="1")
    assert p.returncode == 0 and "allowed" not in p.stderr and guard_log(rig.state) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS case-insensitivity")
def test_a_case_different_path_is_still_a_user_on_macos(rig):
    other_case = str(rig.wt).swapcase()
    p = rig.remove(cwd_users=[[10129, "claude", "cwd", other_case]])
    assert p.returncode == 77 and "pid 10129" in p.stderr


def test_an_open_file_row_whose_path_lsof_spelled_differently_still_counts(rig):
    """The +D rows are scoped by lsof itself: an escaped spelling of an odd byte in the path must not drop the user."""
    p = rig.remove(file_users=[[88, "vim", "3r", "/escaped/spelling/f"]], FAKE_LSOF_UNSCOPED="1")
    assert p.returncode == 77 and "pid 88" in p.stderr


def test_a_ps_that_cannot_answer_fails_open(rig, monkeypatch):
    """Without a process table the caller cannot be told from an orphan: the check allows rather than refuse its own caller."""
    import ade_claims
    monkeypatch.setattr(ade_claims, "_own_pids", lambda: None)
    monkeypatch.setenv("ADE_LSOF", str(rig.fake))
    monkeypatch.setenv("FAKE_LSOF_CWD", json.dumps([[10129, "claude", "cwd", str(rig.wt)]]))
    assert ade_claims.live_users_of(rig.wt) == []
