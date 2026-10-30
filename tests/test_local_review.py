"""bin/local-review: Codex's review run locally on the exact head of a PR, against a fake `codex` and `gh` on PATH and a real git repository."""

import fcntl
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
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
if [ "$1" = api ] && [ "$2" = user ]; then echo '{"login": "operator"}'; exit 0; fi
echo "fake gh: unexpected $*" >&2; exit 1
"""

# FAKE_CODEX_MODE picks what `codex review ...` does in its working directory. `say MSG` prints MSG on stdout and, as the real codex does, the same
# message after a `codex` line on stderr (after some transcript noise).
FAKE_CODEX = r"""#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.0-test"; exit 0; fi
{ echo "$PWD"; echo "$@"; git -C "$PWD" status --porcelain; } > "$FAKE_CODEX_LOG"
env | cut -d= -f1 | sort > "$FAKE_CODEX_ENV"
# the header the real codex prints (checked on real runs, 2026-10-29): workdir, sandbox, then the review request
base="${@: -1}"; sandbox=danger-full-access; case "$*" in *'sandbox_mode="read-only"'*) sandbox=read-only ;; esac
[ "$FAKE_CODEX_MODE" = wrong_sandbox ] && sandbox=danger-full-access
[ "$FAKE_CODEX_MODE" = wrong_base ] && base=0000000000000000000000000000000000000000
[ "$FAKE_CODEX_MODE" = wrong_workdir ] && PWD_SHOWN=/somewhere/else || PWD_SHOWN=$(pwd -P)
{ echo "workdir: $PWD_SHOWN"; echo "sandbox: $sandbox"; echo user; echo "changes against '$base'"; } >&2
say() { echo "transcript noise" >&2; echo exec >&2; { echo codex; printf '%s\n' "$1"; } >&2; printf '%s\n' "$1"; }
case "$FAKE_CODEX_MODE" in
  clean) say "The patch looks correct." ;;
  findings) say "The change has two problems.

Full review comments:

- [P1] Fail open on a missing marker — $PWD/bin/x.py:10-12
  detail text

- [P2] Wrong exit code — $PWD/bin/y.py:3-3
- [Positive observations]" ;;
  duplicates) say "$(printf -- '- [P2] Same thing — %s/a.py:1-1\n- [P2] Same thing — %s/a.py:1-1' "$PWD" "$PWD")" ;;
  generated)
    echo '{"changed": true}' > "$PWD/.cursor/hooks.json"
    say "- [P2] Hooks point at the worktree — $PWD/.cursor/hooks.json:7-7" ;;
  generated_and_real)
    echo '{"changed": true}' > "$PWD/.cursor/hooks.json"
    say "$(printf -- '- [P2] Hooks point at the worktree — %s/.cursor/hooks.json:7-7\n- [P3] Real nit — %s/bin/x.py:1-1' "$PWD" "$PWD")" ;;
  hook_clean) say "- [P2] Hook content is wrong — $PWD/.cursor/hooks.json:1-1" ;;
  exit1) echo "boom" >&2; exit 1 ;;
  nomessage) echo "only a transcript" >&2 ;;
  stdout_only) echo "All good." ;;
  mismatch) echo "transcript noise" >&2; { echo codex; echo "the real review"; } >&2; echo "All good." ;;
  refusal) say "Unable to review the diff because the repository could not be read." ;;
  wrong_sandbox|wrong_base|wrong_workdir) say "The patch looks correct." ;;
  aborted) say "Review aborted: the context window was exhausted before I could finish." ;;
  asks) say "Which files should I focus on?" ;;
  no_issues) say "I did not find any actionable issues in the patch. Nothing in the diff needs changing." ;;
  aborted_with_hook) echo '{"changed": true}' > "$PWD/.cursor/hooks.json"; say "$(printf -- 'Review aborted: the context window was exhausted.\n- [P2] Hooks point at the worktree — %s/.cursor/hooks.json:7-7' "$PWD")" ;;
  tests_unrunnable) say "I found no actionable issues in this patch. I could not run tests in the read-only sandbox. The patch also fixes the failed command." ;;
  wasnt_able) say "I wasn't able to review the patch because the repository is unavailable." ;;
  incomplete_records) say "The patch correctly handles incomplete records and rejects inaccessible paths, and I found no actionable issues." ;;
  late_child) { (cd /tmp && sleep 300 & echo $! > "$FAKE_PID_FILE"); }; say "The patch looks correct." ;;
  aborted_requests) say "The patch cleanly handles aborted requests and I found no actionable issues." ;;
  could_not_find) say "I could not find any bugs in this change." ;;
  cant_review) say "I couldn't review this patch because the repository is inaccessible." ;;
  noexec) { echo "transcript noise"; echo codex; echo "Looks fine."; } >&2; echo "Looks fine." ;;
  detached_tmp) python3 -c "import subprocess,os,time;p=subprocess.Popen(['sleep','300'],start_new_session=True,cwd='/tmp');open(os.environ['FAKE_PID_FILE'],'w').write(str(p.pid));time.sleep(4)" & sleep 3; say "The patch looks correct." ;;
  detached) python3 -c "import os,subprocess;p=subprocess.Popen(['sleep','300'],start_new_session=True,cwd=os.getcwd());open(os.environ['FAKE_PID_FILE'],'w').write(str(p.pid))"; say "The patch looks correct." ;;
  shaped) say "- **[P1]** A bold priority — $PWD/a.py:1-1" ;;
  shaped_bare) say "[P1] A bare priority" ;;
  unparseable) say "- [P7] An invented priority" ;;
  hang) echo $$ > "$FAKE_PID_FILE"; sleep 300 & echo $! >> "$FAKE_PID_FILE"; trap '' TERM; wait ;;
  orphan) sleep 300 & echo $! > "$FAKE_PID_FILE"; say "The patch looks correct." ;;
  moves) git -C "$PWD" -c user.name=t -c user.email=t@t commit -q --allow-empty -m moved; say "fine" ;;
  base_moves) git -C "$PWD" update-ref refs/remotes/origin/master "$(git -C "$PWD" rev-parse HEAD)"; say "fine" ;;
esac
"""


def sh(*argv: str, cwd: Path | None = None, env: dict | None = None) -> str:
    r = subprocess.run(argv, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return r.stdout.strip()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


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
        self.pr_json.write_text(json.dumps({"head": {"sha": self.head}, "base": {"ref": "master"}, "user": {"login": "owner"}}))
        bindir = tmp / "bin"
        bindir.mkdir()
        for name, body in (("gh", FAKE_GH), ("codex", FAKE_CODEX)):
            p = bindir / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IXUSR)
        self.state = tmp / "state"
        self.codex_log, self.codex_env, self.pid_file = tmp / "codex.log", tmp / "codex.env", tmp / "codex.pid"
        self.env = {**git_env, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "LOCAL_REVIEW_STATE_DIR": str(self.state),
                    "FAKE_PR_JSON": str(self.pr_json), "FAKE_CODEX_LOG": str(self.codex_log), "FAKE_CODEX_ENV": str(self.codex_env),
                    "FAKE_PID_FILE": str(self.pid_file), "FAKE_CODEX_MODE": "clean"}

    def argv(self, *extra: str) -> list[str]:
        return [sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", REPO, *extra]

    def run(self, *extra: str, mode: str | None = None, timeout: int = 60, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        e = {**self.env, **(env or {}), **({"FAKE_CODEX_MODE": mode} if mode else {})}
        return subprocess.run(self.argv(*extra), cwd=self.work, env=e, check=False, capture_output=True, text=True, timeout=timeout)

    def stem(self, head: str | None = None) -> Path:
        return self.state / f"owner__name-pr{PR}-{head or self.head}"

    def doc(self, head: str | None = None) -> dict:
        return json.loads(self.stem(head).with_suffix(".json").read_text())

    def worktrees(self) -> list[str]:
        return [ln for ln in sh("git", "worktree", "list", cwd=self.work, env=self.env).splitlines() if ln]

    def push_pr_commit(self, **files: str) -> str:
        for name, text in files.items():
            (self.work / name.replace("__", "/")).write_text(text)
        sh("git", "commit", "-q", "-am", "pr change", cwd=self.work, env=self.env)
        head = sh("git", "rev-parse", "HEAD", cwd=self.work, env=self.env)
        sh("git", "push", "-q", "origin", f"{head}:refs/pull/{PR}/head", cwd=self.work, env=self.env)
        self.pr_json.write_text(json.dumps({"head": {"sha": head}, "base": {"ref": "master"}, "user": {"login": "owner"}}))
        return head


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
    assert len(d["out_sha256"]) == 64 and len(d["err_sha256"]) == 64
    assert f"at {world.head[:12]}: clean" in r.stdout
    assert len(world.worktrees()) == 1, world.worktrees()    # the review worktree is gone
    assert (world.state.stat().st_mode & 0o777, world.stem().with_suffix(".json").stat().st_mode & 0o777) == (0o700, 0o600)
    log = world.codex_log.read_text().splitlines()
    assert log[1] == f'review -c sandbox_mode="read-only" --base {d["base_sha"]}'    # pinned by SHA, not by a branch that can move
    assert log[0] != str(world.work) and "wt" in log[0]    # reviewed in its own clean worktree, never in the caller's
    assert len(log) == 2    # `git status --porcelain` printed nothing: the worktree was clean when codex started


def test_the_reviewed_tree_is_exactly_the_head_not_what_the_caller_has_checked_out(world: World) -> None:
    (world.work / "scratch.txt").write_text("uncommitted\n")
    sh("git", "checkout", "-q", "master", cwd=world.work, env=world.env)    # the caller sits on another branch with an untracked file
    r = world.run()
    assert r.returncode == 0 and world.doc()["head"] == world.head
    assert len(world.codex_log.read_text().splitlines()) == 2    # clean: the caller's dirt never reached the review


def test_codex_runs_read_only_with_no_token_secret_or_gh_variable_but_keeps_its_own(world: World) -> None:
    secrets = {"GH_TOKEN": "x", "GITHUB_TOKEN": "x", "GH_ENTERPRISE_FOO": "x", "MY_SECRET": "x", "DB_PASSWORD": "x", "SOME_API_KEY": "x", "AWS_SECRET_ACCESS_KEY": "x"}
    keep = {"OPENAI_API_KEY": "x", "CODEX_HOME": "/tmp/h", "HOME": os.environ["HOME"], "PATH": world.env["PATH"]}
    assert world.run(env={**secrets, **keep}).returncode == 0
    names = set(world.codex_env.read_text().split())
    assert not names & set(secrets), names & set(secrets)
    assert {"OPENAI_API_KEY", "CODEX_HOME", "HOME", "PATH"} <= names


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
    r = world.run(mode="hook_clean")
    assert r.returncode == 1, r.stderr
    d = world.doc()
    assert d["dirty_after"] == [] and d["ignored_generated"] == [] and d["counts"]["P2"] == 1


def test_a_finding_on_a_hook_file_the_pr_itself_edits_is_never_ignored(world: World) -> None:
    """Codex P1 and the adversary's P2 on PR 130: dirtying the file must not be a way to hide a finding about the PR's own change to it."""
    head = world.push_pr_commit(**{".cursor__hooks.json": '{"a": 2}\n'})
    r = world.run(mode="generated")
    assert r.returncode == 1, r.stderr
    d = world.doc(head)
    assert d["dirty_after"] == [".cursor/hooks.json"] and d["ignored_generated"] == [] and d["counts"]["P2"] == 1


@pytest.mark.parametrize("mode,reason", [
    ("exit1", "codex exited 1"),
    ("nomessage", "no final message"),
    ("stdout_only", "no `codex` message block"),    # a banner on stdout with a transcript that holds no review
    ("mismatch", "not the transcript's final message"),
    ("refusal", "reads as a refusal"),
    ("cant_review", "not a verdict"),    # a wording the refusal list does not know
    ("noexec", "not a verdict"),
    ("aborted", "not a verdict"),    # the wording the adversary found filing clean when an exec block existed
    ("asks", "not a verdict"),
    ("wasnt_able", "not a verdict"),    # Codex P1 on PR 130 (round 9)
    ("aborted_with_hook", "not a verdict"),    # one ignored generated-file finding must not turn an incomplete review into clean    # a question is not a verdict
    ("wrong_sandbox", "does not show the review this run asked for"),    # a config that overrode the read-only sandbox
    ("wrong_base", "does not show the review this run asked for"),
    ("wrong_workdir", "does not show the review this run asked for"),    # a message with no sign in the transcript that the repository was looked at
    ("shaped", "cannot read"),    # **[P1]** is a finding in a shape the parser does not know: never "no findings"
    ("shaped_bare", "cannot read"),
    ("unparseable", "cannot read"),
    ("moves", "head moved"),
])
def test_every_way_a_run_can_fail_is_failed_never_clean(world: World, mode: str, reason: str) -> None:
    r = world.run(mode=mode)
    assert r.returncode == 3, (r.stdout, r.stderr)
    d = world.doc()
    assert d["result"] == "failed" and reason in d["reason"] and d["counts"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert len(world.worktrees()) == 1    # cleaned up even when it failed


def test_a_base_branch_that_moves_during_the_review_does_not_change_what_was_reviewed(world: World) -> None:
    r = world.run(mode="base_moves")
    assert r.returncode == 0, r.stderr
    d = world.doc()
    assert d["result"] == "clean" and f"--base {d['base_sha']}" in world.codex_log.read_text()


def test_an_ordinary_no_issues_summary_is_a_clean_review_not_a_refusal(world: World) -> None:
    """Codex P2 on PR 130 (round 6): "I did not find any actionable issues in the patch" matched the refusal wording."""
    assert world.run(mode="no_issues").returncode == 0


def test_a_differently_cased_repo_names_one_identity_for_the_file_the_lock_and_the_reader(world: World) -> None:
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", "Owner/Name"], cwd=world.work, env=world.env,
                       check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert world.doc()["repo"] == "owner/name" and not list(world.state.glob("*Owner*"))


def test_a_finished_review_that_mentions_tests_it_could_not_run_or_a_failed_command_is_clean(world: World) -> None:
    """Codex P2 on PR 130 (round 8): test limitations and failures the patch fixes are ordinary summaries, not refusals."""
    assert world.run(mode="tests_unrunnable").returncode == 0


def test_a_preflight_timeout_is_failed_not_the_findings_exit(world: World) -> None:
    (world.tmp / "bin" / "gh").write_text("#!/bin/bash\nsleep 30\n")
    r = world.run(env={"LOCAL_REVIEW_GH_TIMEOUT": "1"}, timeout=60)
    assert r.returncode == 3 and "timed out before the review started" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stderr)


def test_a_summary_that_merely_discusses_incomplete_records_or_inaccessible_paths_is_clean(world: World) -> None:
    """Codex P2 on PR 130 (round 9): the refusal vocabulary is scoped to the review itself, not matched anywhere in the message."""
    assert world.run(mode="incomplete_records").returncode == 0


@pytest.mark.parametrize("login,ok", [("owner", True), ("Owner", True), ("operator", True), ("mallory", False), ("", False)])
def test_only_the_owner_or_the_authenticated_user_may_have_their_pr_reviewed_by_default(world: World, login: str, ok: bool) -> None:
    """Codex Security Review on PR 130: the PR's own AGENTS.md and diff can steer the reviewing model, so a stranger's PR needs --allow-untrusted."""
    world.pr_json.write_text(json.dumps({"head": {"sha": world.head}, "base": {"ref": "master"}, "user": {"login": login}}))
    r = world.run()
    assert (r.returncode == 0) is ok, r.stderr
    if not ok:
        assert r.returncode == 2 and "author" in r.stderr and not world.stem().with_suffix(".json").exists()
        assert world.run("--allow-untrusted").returncode == 0 and world.doc()["author"] == login


def test_a_child_started_just_before_codex_exits_is_killed_without_lsof_or_a_snapshot(world: World) -> None:
    """Codex P1 (GitHub review of PR 130): the leader must not be reaped before the group kill, or a late child survives where lsof is missing."""
    safe = world.tmp / "nolsof"
    safe.mkdir()
    for tool in ("git", "gh", "python3", "codex", "bash", "sleep", "ps", "cat", "env", "cut", "sort", "pwd", "echo"):    # everything but lsof
        src = world.tmp / "bin" / tool if tool in ("gh", "codex") else Path(shutil.which(tool) or "")
        if src.exists() and not (safe / tool).exists():
            (safe / tool).symlink_to(src)
    env = {"PATH": f"{safe}{os.pathsep}/usr/bin{os.pathsep}/bin"}    # no lsof on this PATH (/usr/sbin is not on it); the child works in /tmp, outside the worktree
    assert shutil.which("lsof", path=env["PATH"]) is None
    assert world.run(mode="late_child", env=env).returncode == 0
    time.sleep(0.5)
    assert not alive(int(world.pid_file.read_text())), "a child started right before codex exited survived"


def test_cleanup_masks_termination_signals_so_nothing_cuts_it_short(world: World) -> None:
    """Codex P2 on PR 130 (round 12): a SIGTERM during the group kill or the worktree removal left tool processes behind."""
    ld = SourceFileLoader("local_review_mod", str(LOCAL_REVIEW))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("local_review_mod", ld))
    ld.exec_module(mod)
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    try:
        proc = subprocess.Popen(["sleep", "300"], start_new_session=True)
        mod.kill_group(proc, world.tmp, {})
        assert proc.poll() is not None
        assert all(signal.getsignal(s) == signal.SIG_IGN for s in saved)
    finally:
        for s, h in saved.items():
            signal.signal(s, h)


def test_a_summary_about_aborted_requests_is_clean_but_an_aborted_review_is_not(world: World) -> None:
    """Codex P2 on PR 130 (round 13): a bare `aborted` anywhere in the message is not a refusal; "Review aborted" still is (parametrized above)."""
    assert world.run(mode="aborted_requests").returncode == 0


def test_a_clean_message_that_merely_says_could_not_find_is_not_a_refusal(world: World) -> None:
    assert world.run(mode="could_not_find").returncode == 0


def test_a_hung_codex_is_killed_with_its_group_and_the_run_is_failed(world: World) -> None:
    r = world.run("--timeout", "1", mode="hang", timeout=40)
    assert r.returncode == 3 and "did not finish in 1 s" in world.doc()["reason"]
    pids = [int(p) for p in world.pid_file.read_text().split()]
    time.sleep(0.3)
    assert not any(alive(p) for p in pids), pids    # the TERM-ignoring parent AND its sleeping child are gone
    assert len(world.worktrees()) == 1


def test_a_child_that_outlives_a_codex_that_exited_is_killed_too(world: World) -> None:
    assert world.run(mode="orphan").returncode == 0
    time.sleep(0.3)
    assert not alive(int(world.pid_file.read_text())), "codex's background child survived the run"


def test_a_tool_command_in_a_session_of_its_own_is_killed_too(world: World) -> None:
    """Codex P2 on PR 130: real tool commands run in their own sessions and process groups, so killing codex's group alone leaves them."""
    assert world.run(mode="detached").returncode == 0
    time.sleep(0.5)
    assert not alive(int(world.pid_file.read_text())), "a detached tool process of codex survived the run"


def test_a_detached_tool_working_outside_the_worktree_is_found_while_codex_is_alive_and_killed(world: World) -> None:
    """Codex P2 on PR 130 (second run): once codex exits its tool is reparented and, working in /tmp, invisible to a worktree scan."""
    assert world.run(mode="detached_tmp").returncode == 0
    time.sleep(0.5)
    assert not alive(int(world.pid_file.read_text())), "a detached tool working in /tmp survived the run"


def test_the_base_is_resolved_from_its_own_fetch_not_from_a_tracking_ref(world: World) -> None:
    """Codex P2 on PR 130: a single-branch clone has no origin/<base> to read, or a stale one."""
    sh("git", "update-ref", "-d", "refs/remotes/origin/master", cwd=world.work, env=world.env)
    sh("git", "config", "--unset-all", "remote.origin.fetch", cwd=world.work, env=world.env)
    r = world.run()
    assert r.returncode == 0, r.stderr
    assert world.doc()["base_sha"] == sh("git", "rev-parse", "master", cwd=world.work, env=world.env)    # the remote's master tip


def test_a_run_that_is_terminated_files_failed_removes_its_worktree_and_kills_codex(world: World) -> None:
    """The result is `failed: in progress` from the moment the lock is taken, and an older clean for this head cannot outlive a dying run."""
    old = world.run()    # a clean result for this very head first
    assert old.returncode == 0 and world.doc()["result"] == "clean"
    env = {**world.env, "FAKE_CODEX_MODE": "hang"}
    p = subprocess.Popen(world.argv("--timeout", "100"), cwd=world.work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if world.pid_file.exists() and len(world.pid_file.read_text().split()) == 2:
                break
            time.sleep(0.1)
        d = world.doc()
        assert d["result"] == "failed" and "in progress" in d["reason"], d    # the clean from the first run is already gone
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 3, (out, err)
    assert "interrupted by signal" in world.doc()["reason"] and len(world.worktrees()) == 1
    time.sleep(0.3)
    assert not any(alive(int(x)) for x in world.pid_file.read_text().split())


def test_no_codex_on_path_is_failed_and_never_runs_a_real_one(world: World) -> None:
    safe = world.tmp / "safe"
    safe.mkdir()
    for tool in ("git", "gh", "python3"):    # gh is the fake
        src = world.tmp / "bin" / tool if tool == "gh" else Path(shutil.which(tool) or "")
        (safe / tool).symlink_to(src)
    env = {**world.env, "PATH": f"{safe}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    assert shutil.which("codex", path=env["PATH"]) is None    # the precondition: no codex of any kind is reachable
    r = subprocess.run(world.argv(), cwd=world.work, env=env, check=False, capture_output=True, text=True, timeout=60)
    assert r.returncode == 3 and "not installed" in world.doc()["reason"], r.stderr


def test_a_second_run_for_the_same_head_is_refused_while_the_lock_is_held_and_never_stale_after(world: World) -> None:
    world.state.mkdir(mode=0o700)
    lock = world.state / f"lock-owner__name-pr{PR}-{world.head}"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        r = world.run()
        assert r.returncode == 4 and "is running" in r.stderr
        assert not world.stem().with_suffix(".json").exists()    # the refused run touched no result
    finally:
        os.close(fd)
    lock.write_text("2147483646")    # a leftover file naming a dead pid: only the flock counts, so it is no obstacle
    assert world.run().returncode == 0


def test_the_result_names_the_head_that_was_asked_for_not_the_prs_newer_one(world: World) -> None:
    old = world.head
    new = world.push_pr_commit(**{"bin__x.py": "print(3)\n"})
    r = world.run("--head", old)
    assert r.returncode == 0 and "is not the PR's current head" in r.stderr
    assert world.doc(old)["head"] == old and not world.stem(new).with_suffix(".json").exists()
    assert world.run().returncode == 0 and world.doc(new)["head"] == new    # the default is the PR's current head


def test_a_head_that_is_not_the_prs_head_or_an_ancestor_of_it_is_refused(world: World) -> None:
    empty = sh("git", "hash-object", "-t", "tree", "/dev/null", cwd=world.work, env=world.env)
    stray = sh("git", "commit-tree", empty, "-m", "unrelated", cwd=world.work, env=world.env)
    r = world.run("--head", stray)
    assert r.returncode == 2 and "neither the PR's head" in r.stderr
    assert not world.stem(stray).with_suffix(".json").exists()    # no result for a head that was never in scope


def test_a_head_the_repository_does_not_have_is_failed(world: World) -> None:
    r = world.run("--head", "1" * 40)
    assert r.returncode == 3 and "is not in the repository" in world.doc("1" * 40)["reason"]


@pytest.mark.parametrize("argv,needle", [
    (["--head", "abc"], "full lowercase 40-hex"),
    (["--timeout", "0"], "must be positive"),
    (["--repo", "nonsense"], "OWNER/NAME"),
])
def test_bad_usage_exits_2(world: World, argv: list[str], needle: str) -> None:
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), *(["--repo", REPO] if "--repo" not in argv else []), *argv],
                       cwd=world.work, env=world.env, check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and needle in r.stderr, r.stderr


@pytest.mark.parametrize("repo", ["owner/nam", "wner/name", "owner/name-backup"])
def test_the_whole_origin_identity_is_compared_never_a_substring(world: World, repo: str) -> None:
    """Codex P2 on PR 130 (round 6): `owner/name` once matched an origin of `owner/name-backup`."""
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", repo], cwd=world.work, env=world.env,
                       check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "not" in r.stderr and repo in r.stderr


def test_a_checkout_of_another_repository_is_refused(world: World) -> None:
    r = subprocess.run([sys.executable, "-I", str(LOCAL_REVIEW), str(PR), "--repo", "someone/else"], cwd=world.work, env=world.env,
                       check=False, capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "not someone/else" in r.stderr


def test_an_unusable_state_directory_is_failed_not_a_traceback(world: World) -> None:
    blocker = world.tmp / "afile"
    blocker.write_text("x")
    r = world.run(env={"LOCAL_REVIEW_STATE_DIR": str(blocker / "sub")})
    assert r.returncode == 3 and "cannot use the state directory" in r.stderr and "Traceback" not in r.stderr


def test_a_result_it_files_is_what_pr_wait_reads_as_clean_and_a_findings_one_blocks(world: World) -> None:
    ld = SourceFileLoader("pr_wait_mod", str(PR_WAIT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("pr_wait_mod", ld))
    ld.exec_module(mod)
    saved = os.environ.get("LOCAL_REVIEW_STATE_DIR")
    os.environ["LOCAL_REVIEW_STATE_DIR"] = str(world.state)
    try:
        assert world.run().returncode == 0
        assert mod.local_codex_read(REPO, PR, world.head, "master")["status"] == "clean"
        assert mod.local_codex_read(REPO, PR, world.head, "main")["status"] == "unreadable"    # another base than the PR's own
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
