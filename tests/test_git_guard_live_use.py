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
if mode == "fail":
    sys.exit(2)
if mode == "hang":
    time.sleep(120)
key = "FAKE_LSOF_CWD" if "cwd" in sys.argv else "FAKE_LSOF_FILES"
for pid, cmd, fd, name in json.loads(os.environ.get(key, "[]")):
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
