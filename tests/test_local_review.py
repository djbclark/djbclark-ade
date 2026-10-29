"""bin/local-review: Codex's review run locally on the exact head of a PR, against a fake `codex` and `gh` on PATH and a real git repository."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCAL_REVIEW = ROOT / "bin" / "local-review"
PR_WAIT = ROOT / "bin" / "pr-wait"
REPO = "owner/name"
PR = 7

FAKE_GH = """#!/bin/bash
# only `gh api repos/owner/name/pulls/7` is served; FAKE_PR_JSON holds the document
if [ "$1" = api ] && [ "$2" = "repos/owner/name/pulls/7" ]; then cat "$FAKE_PR_JSON"; exit 0; fi
echo "fake gh: unexpected $*" >&2; exit 1
"""

# FAKE_CODEX_MODE picks what `codex review --base X` does in its working directory
FAKE_CODEX = r"""#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.0-test"; exit 0; fi
echo "$PWD" > "$FAKE_CODEX_LOG"
echo "$@" >> "$FAKE_CODEX_LOG"
git -C "$PWD" status --porcelain >> "$FAKE_CODEX_LOG"
case "$FAKE_CODEX_MODE" in
  clean) echo "The patch looks correct."; echo "codex" >&2; echo "transcript noise" >&2 ;;
  findings)
    echo "The change has two problems."; echo; echo "Full review comments:"; echo
    echo "- [P1] Fail open on a missing marker — $PWD/bin/x.py:10-12"; echo "  detail text"; echo
    echo "- [P2] Wrong exit code — $PWD/bin/y.py:3-3"; echo "- [Positive observations]" ;;
  duplicates) printf -- '- [P2] Same thing — %s/a.py:1-1\n- [P2] Same thing — %s/a.py:1-1\n' "$PWD" "$PWD" ;;
  generated)
    echo '{"changed": true}' > "$PWD/.cursor/hooks.json"
    printf -- '- [P2] Hooks point at the worktree — %s/.cursor/hooks.json:7-7\n' "$PWD" ;;
  generated_and_real)
    echo '{"changed": true}' > "$PWD/.cursor/hooks.json"
    printf -- '- [P2] Hooks point at the worktree — %s/.cursor/hooks.json:7-7\n- [P3] Real nit — %s/bin/x.py:1-1\n' "$PWD" "$PWD" ;;
  hook_clean) printf -- '- [P2] Hook content is wrong — %s/.cursor/hooks.json:1-1\n' "$PWD" ;;
  exit1) echo "boom" >&2; exit 1 ;;
  nomessage) echo "only a transcript" >&2 ;;
  stderr_final) echo "noise"; echo "codex" >&2; echo "All good." >&2 ;;
  unparseable) echo "- [P7] An invented priority"; echo "* [P1] star bullet" ;;
  hang) trap '' TERM; sleep 30 ;;
  moves) git -C "$PWD" -c user.name=t -c user.email=t@t commit -q --allow-empty -m moved; echo "fine" ;;
esac
"""


def sh(*argv: str, cwd: Path | None = None, env: dict | None = None) -> str:
    r = subprocess.run(argv, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return r.stdout.strip()


class World:
    """A bare `origin` at .../owner/name.git, a clone with a PR branch, and fake gh/codex on PATH."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        git_env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        origin = tmp / "remote" / "owner" / "name.git"
        origin.parent.mkdir(parents=True)
        sh("git", "init", "-q", "--bare", "-b", "master", str(origin), env=git_env)
        self.work = tmp / "work"
        sh("git", "clone", "-q", str(origin), str(self.work), env=git_env)
        (self.work / ".cursor").mkdir()
        (self.work / ".cursor" / "hooks.json").write_text('{"a": 1}\n')
        (self.work / "bin").mkdir()
        (self.work / "bin" / "x.py").write_text("print(1)\n")
        sh("git", "add", "-A", cwd=self.work, env=git_env)
        sh("git", "commit", "-q", "-m", "base", cwd=self.work, env=git_env)
        sh("git", "push", "-q", "origin", "HEAD:master", cwd=self.work, env=git_env)
        sh("git", "checkout", "-q", "-b", "feature", cwd=self.work, env=git_env)
        (self.work / "bin" / "x.py").write_text("print(2)\n")
        sh("git", "commit", "-q", "-am", "feature", cwd=self.work, env=git_env)
        self.head = sh("git", "rev-parse", "HEAD", cwd=self.work, env=git_env)
        sh("git", "push", "-q", "origin", f"{self.head}:refs/pull/{PR}/head", cwd=self.work, env=git_env)
        self.pr_json = tmp / "pr.json"
        self.pr_json.write_text(json.dumps({"head": {"sha": self.head}, "base": {"ref": "master"}}))
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in (("gh", FAKE_GH), ("codex", FAKE_CODEX)):
            p = bindir / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.state = tmp / "state"
        self.codex_log = tmp / "codex.log"
        self.env = {**git_env, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "LOCAL_REVIEW_STATE_DIR": str(self.state),
                    "FAKE_PR_JSON": str(self.pr_json), "FAKE_CODEX_LOG": str(self.codex_log), "FAKE_CODEX_MODE": "clean"}

    def run(self, *extra: str, mode: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        env = {**self.env, **({"FAKE_CODEX_MODE": mode} if mode else {})}
        return subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", REPO, *extra],
                              cwd=self.work, env=env, check=False, capture_output=True, text=True, timeout=timeout)

    def stem(self, head: str | None = None) -> Path:
        return self.state / f"owner__name-pr{PR}-{head or self.head}"

    def doc(self, head: str | None = None) -> dict:
        return json.loads(self.stem(head).with_suffix(".json").read_text())

    def worktrees(self) -> list[str]:
        return [ln for ln in sh("git", "worktree", "list", cwd=self.work, env=self.env).splitlines() if ln]


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_clean_review_files_a_head_named_result_and_leaves_nothing_behind(world: World) -> None:
    r = world.run()
    assert r.returncode == 0, r.stderr
    d = world.doc()
    assert (d["result"], d["head"], d["pr"], d["repo"], d["exit_code"], d["final_message"]) == ("clean", world.head, PR, REPO, 0, True)
    assert d["counts"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0} and d["findings"] == [] and d["reason"] == ""
    assert d["base_ref"] == "master" and len(d["base_sha"]) == 40 and d["codex_version"] == "codex-cli 0.0-test"
    assert f"at {world.head[:12]}: clean" in r.stdout
    assert len(world.worktrees()) == 1, world.worktrees()    # the review worktree is gone
    assert not list(world.state.glob("lock-*"))
    assert (world.state.stat().st_mode & 0o777, world.stem().with_suffix(".json").stat().st_mode & 0o777) == (0o700, 0o600)
    log = world.codex_log.read_text().splitlines()
    assert log[1] == "review --base origin/master"
    assert log[0] != str(world.work) and "wt" in log[0]    # reviewed in its own clean worktree, never in the caller's
    assert len(log) == 2    # `git status --porcelain` printed nothing: the worktree was clean when codex started


def test_the_reviewed_tree_is_exactly_the_head_not_what_the_caller_has_checked_out(world: World) -> None:
    (world.work / "scratch.txt").write_text("uncommitted\n")
    sh("git", "checkout", "-q", "master", cwd=world.work, env=world.env)    # the caller sits on another branch with an untracked file
    r = world.run()
    assert r.returncode == 0 and world.doc()["head"] == world.head
    assert len(world.codex_log.read_text().splitlines()) == 2    # clean: the caller's dirt never reached the review


def test_findings_are_listed_by_priority_and_exit_1(world: World) -> None:
    r = world.run(mode="findings")
    assert r.returncode == 1, r.stderr
    d = world.doc()
    assert d["result"] == "findings" and d["counts"] == {"P0": 0, "P1": 1, "P2": 1, "P3": 0}
    assert [(f["priority"], f["title"]) for f in d["findings"]] == [("P1", "Fail open on a missing marker"), ("P2", "Wrong exit code")]
    assert d["findings"][0]["path"].endswith("bin/x.py:10-12")
    assert "findings (P1 1, P2 1)" in r.stdout and "P1 Fail open on a missing marker" in r.stdout


def test_a_finding_repeated_in_the_output_counts_once(world: World) -> None:
    assert world.run(mode="duplicates").returncode == 1
    assert world.doc()["counts"]["P2"] == 1


def test_a_finding_in_a_file_the_review_worktree_dirtied_is_generated_not_the_pr(world: World) -> None:
    r = world.run(mode="generated")
    assert r.returncode == 0, r.stderr
    d = world.doc()
    assert d["result"] == "clean" and d["findings"] == [] and len(d["ignored_generated"]) == 1
    assert d["dirty_after"] == [".cursor/hooks.json"] and "ignored 1 finding" in r.stdout
    r = world.run(mode="generated_and_real")
    assert r.returncode == 1 and [f["title"] for f in world.doc()["findings"]] == ["Real nit"]    # only the real one counts


def test_a_hook_file_finding_is_real_when_the_review_did_not_dirty_the_file(world: World) -> None:
    """Rule 3 ignores a finding only in a file the review worktree dirtied: one on a hook file that is clean is a finding of the PR."""
    r = world.run(mode="hook_clean")
    assert r.returncode == 1, r.stderr
    d = world.doc()
    assert d["dirty_after"] == [] and d["ignored_generated"] == [] and d["counts"]["P2"] == 1


@pytest.mark.parametrize("mode,reason", [
    ("exit1", "codex exited 1"),
    ("nomessage", "no final message"),
    ("unparseable", "cannot read"),
    ("moves", "head moved"),
])
def test_every_way_a_run_can_fail_is_failed_never_clean(world: World, mode: str, reason: str) -> None:
    r = world.run(mode=mode)
    assert r.returncode == 3, (r.stdout, r.stderr)
    d = world.doc()
    assert d["result"] == "failed" and reason in d["reason"] and d["counts"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert len(world.worktrees()) == 1 and not list(world.state.glob("lock-*"))    # cleaned up even when it failed


def test_a_hung_codex_is_killed_with_its_group_and_the_run_is_failed(world: World) -> None:
    r = world.run("--timeout", "1", mode="hang", timeout=40)
    assert r.returncode == 3 and "did not finish in 1 s" in world.doc()["reason"]
    assert len(world.worktrees()) == 1


def test_the_final_message_may_be_on_stderr_after_the_last_codex_line(world: World) -> None:
    assert world.run(mode="stderr_final").returncode == 0
    assert world.doc()["final_message"] is True


def test_no_codex_on_path_is_failed(world: World) -> None:
    env = {**world.env, "PATH": f"{world.tmp / 'bin'}{os.pathsep}/opt/homebrew/bin{os.pathsep}/usr/bin{os.pathsep}/bin"}    # git yes, the real codex (~/.local/bin) no
    (world.tmp / "bin" / "codex").unlink()
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", REPO], cwd=world.work, env=env,
                       check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 3 and "not installed" in world.doc()["reason"], r.stderr


def test_a_second_run_for_the_same_head_is_refused_and_a_stale_lock_is_taken_over(world: World) -> None:
    world.state.mkdir(mode=0o700)
    lock = world.state / f"lock-owner__name-pr{PR}-{world.head}"
    lock.write_text(str(os.getpid()))    # alive: this very test process
    r = world.run()
    assert r.returncode == 4 and "is running" in r.stderr and lock.read_text() == str(os.getpid())
    lock.write_text("2147483646")    # no such process
    assert world.run().returncode == 0 and not lock.exists()


def test_the_result_names_the_head_that_was_asked_for_not_the_prs_newer_one(world: World) -> None:
    old = world.head
    (world.work / "bin" / "x.py").write_text("print(3)\n")
    sh("git", "commit", "-q", "-am", "newer", cwd=world.work, env=world.env)
    new = sh("git", "rev-parse", "HEAD", cwd=world.work, env=world.env)
    sh("git", "push", "-q", "origin", f"{new}:refs/pull/{PR}/head", cwd=world.work, env=world.env)
    world.pr_json.write_text(json.dumps({"head": {"sha": new}, "base": {"ref": "master"}}))
    r = world.run("--head", old)
    assert r.returncode == 0 and "is not the PR's current head" in r.stderr
    assert world.doc(old)["head"] == old and not world.stem(new).with_suffix(".json").exists()
    assert world.run().returncode == 0 and world.doc(new)["head"] == new    # the default is the PR's current head


def test_a_head_the_repository_does_not_have_is_failed(world: World) -> None:
    r = world.run("--head", "1" * 40)
    assert r.returncode == 3 and "is not in the repository" in world.doc("1" * 40)["reason"]


@pytest.mark.parametrize("argv,needle", [
    (["--head", "abc"], "full lowercase 40-hex"),
    (["--base", "bad branch"], "must be a branch name"),
    (["--timeout", "0"], "must be positive"),
    (["--repo", "nonsense"], "OWNER/NAME"),
])
def test_bad_usage_exits_2(world: World, argv: list[str], needle: str) -> None:
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), *(["--repo", REPO] if "--repo" not in argv else []), *argv],
                       cwd=world.work, env=world.env, check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and needle in r.stderr, r.stderr


def test_a_checkout_of_another_repository_is_refused(world: World) -> None:
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", "someone/else"], cwd=world.work, env=world.env,
                       check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "not someone/else" in r.stderr


def test_a_result_it_files_is_what_pr_wait_reads_as_clean_and_a_findings_one_blocks(world: World) -> None:
    ld = SourceFileLoader("pr_wait_mod", str(PR_WAIT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("pr_wait_mod", ld))
    ld.exec_module(mod)
    saved = os.environ.get("LOCAL_REVIEW_STATE_DIR")
    os.environ["LOCAL_REVIEW_STATE_DIR"] = str(world.state)
    try:
        assert world.run().returncode == 0
        assert mod.local_codex_read(REPO, PR, world.head)["status"] == "clean"
        assert world.run(mode="findings").returncode == 1
        got = mod.local_codex_read(REPO, PR, world.head)
        assert (got["status"], got["counts_text"]) == ("findings", "P1 1, P2 1")
        assert world.run(mode="exit1").returncode == 3
        assert mod.local_codex_read(REPO, PR, world.head)["status"] == "failed"
        assert mod.local_codex_read(REPO, PR, "f" * 40)["status"] == "missing"
    finally:
        if saved is None:
            os.environ.pop("LOCAL_REVIEW_STATE_DIR")
        else:
            os.environ["LOCAL_REVIEW_STATE_DIR"] = saved
