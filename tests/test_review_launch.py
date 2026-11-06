"""bin/review-launch (the review boundary) and bin/review-pr, against a fake `claude` and a fake `gh` on PATH.

The isolation checks the removed Codex local review had (slim-down E8, 2026-11-06, ported before it was deleted): a clean
detached worktree at the exact head with the base pinned by SHA; a scrubbed environment; the boundary proven
from the run's own init event, never assumed; the untrusted-author refusal; the descendant kill at the end and
at the timeout. The live self-check against a real Claude is an operator step (docs/review-boundary.md).
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "bin" / "review-launch"
REVIEW_PR = ROOT / "bin" / "review-pr"
FAKE_CLAUDE = ROOT / "tests" / "fixtures" / "fake-claude-review"
SCHEMA = ROOT / "config" / "review-schema.json"
sys.path.insert(0, str(ROOT / "bin"))
import adversary_marker  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}


def git(*args: str, cwd: Path) -> str:
    env = {**os.environ, **GIT_ENV, "GIT_CONFIG_GLOBAL": "/dev/null"}
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie is dead for our purpose
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        (self.bin / "claude").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n')
        (self.bin / "claude").chmod(0o755)
        self.home = tmp / "home"
        self.home.mkdir()
        self.state = tmp / "state"
        self.scen = tmp / "scenario.json"
        self.log = tmp / "claude.log"
        self.wt = tmp / "wt"
        self.wt.mkdir()
        git("init", "-q", "-b", "main", cwd=self.wt)
        (self.wt / "a.txt").write_text("alpha\n")
        git("add", "a.txt", cwd=self.wt)
        git("commit", "-q", "-m", "one", cwd=self.wt)
        self.head = git("rev-parse", "HEAD", cwd=self.wt)
        self.schema = tmp / "schema.json"
        self.schema.write_text(json.dumps({"type": "object", "properties": {"ok": {"type": "boolean"}}}))
        self.scenario()

    def scenario(self, **kw) -> None:
        self.scen.write_text(json.dumps(kw))

    def env(self, **extra: str) -> dict:
        tool_dirs = sorted({str(Path(shutil.which(t)).parent) for t in ("git", "ps", "sleep") if shutil.which(t)})
        env = {"PATH": os.pathsep.join([str(self.bin), *tool_dirs, "/usr/bin", "/bin"]), "HOME": str(self.home),
               "REVIEW_LAUNCH_STATE_DIR": str(self.state), "REVIEW_PR_STATE_DIR": str(self.state),
               "FAKE_CLAUDE_SCENARIO": str(self.scen), "FAKE_CLAUDE_LOG": str(self.log), **GIT_ENV,
               "GIT_CONFIG_GLOBAL": "/dev/null"}
        env.update(extra)
        return env

    def run(self, *args: str, env: dict | None = None, timeout: float = 120, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(LAUNCH), *args], capture_output=True, text=True,
                              env=env or self.env(), timeout=timeout, cwd=str(cwd or self.tmp))

    def launch(self, *extra: str, mode: str = "review", prompt: str = "review this", env: dict | None = None,
               timeout: float = 120) -> subprocess.CompletedProcess:
        return self.run("--mode", mode, "-C", str(self.wt), "--schema", str(self.schema), "-p", prompt, *extra,
                        env=env, timeout=timeout)

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text().splitlines() if ln.strip()]

    def launches(self) -> list[dict]:
        return [c for c in self.calls() if not c["check"]]

    def checks(self) -> list[dict]:
        return [c for c in self.calls() if c["check"]]

    def passed_check(self, mode: str = "review") -> None:
        r = self.run("--check", "--mode", mode)
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def argv_val(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


# ---- the launch: argv, settings, environment --------------------------------------------------------------

def test_the_launch_passes_exactly_the_boundary_flags_and_the_prompt_after_a_double_dash(world):
    r = world.launch()
    assert r.returncode == 0, r.stderr
    (call,) = world.launches()
    argv = call["argv"]
    assert argv[0] == "-p" and argv[-2:] == ["--", "review this"]
    assert argv_val(argv, "--tools") == "Read,Grep,Glob"
    assert argv_val(argv, "--permission-mode") == "default"
    assert argv_val(argv, "--setting-sources") == ""
    assert argv_val(argv, "--output-format") == "stream-json"
    for flag in ("--verbose", "--strict-mcp-config", "--no-session-persistence", "--json-schema", "--settings"):
        assert flag in argv, flag
    for flag in ("--add-dir", "--mcp-config", "--dangerously-skip-permissions", "--allowedTools", "--bare"):
        assert flag not in argv, flag
    assert json.loads(argv_val(argv, "--json-schema")) == json.loads(world.schema.read_text())
    assert os.path.realpath(call["cwd"]) == os.path.realpath(world.wt)


def test_read_only_mode_adds_the_two_web_tools_and_nothing_else(world):
    assert world.launch(mode="read-only").returncode == 0
    assert argv_val(world.launches()[0]["argv"], "--tools") == "Read,Grep,Glob,WebFetch,WebSearch"


def test_the_settings_block_reads_outside_disable_hooks_and_bypass_and_deny_the_secret_paths(world):
    world.launch()
    s = json.loads(argv_val(world.launches()[0]["argv"], "--settings"))
    assert s["disableAllHooks"] is True and s["hooks"] == {}
    p = s["permissions"]
    assert p["blockReadsOutsideWorkingDirectories"] is True and p["disableBypassPermissionsMode"] == "disable"
    for path in ("~/.config/gh/**", "~/.ssh/**", "~/.claude.json", "~/.claude/projects/**", "~/.aws/**", "~/.netrc",
                 "~/.config/sudo-secretspec/**"):
        assert f"Read({path})" in p["deny"], path
    assert not any("local/state" in d for d in p["deny"]), "review-pr's worktrees live under ~/.local/state"


def test_the_environment_has_no_token_secret_password_or_gh_variable_but_keeps_home_and_path(world):
    env = world.env(GH_TOKEN="x", GITHUB_TOKEN="x", GITHUB_ACTIONS="true", MY_SECRET="x", DB_PASSWORD="x",
                    ANTHROPIC_API_KEY="x", AWS_CREDENTIALS="x", CLAUDE_CONFIG_DIR=str(world.tmp / "cfg"), KEEP_ME="1")
    assert world.launch(env=env).returncode == 0
    for call in world.calls():
        e = call["env"]
        for k in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACTIONS", "MY_SECRET", "DB_PASSWORD", "ANTHROPIC_API_KEY", "AWS_CREDENTIALS"):
            assert k not in e, k
        assert e["HOME"] == str(world.home) and e["KEEP_ME"] == "1" and e["CLAUDE_CONFIG_DIR"] == str(world.tmp / "cfg")
        assert str(world.bin) in e["PATH"]


def test_a_prompt_file_is_passed_as_argv_and_never_written_into_the_worktree(world):
    pf = world.tmp / "prompt.txt"
    pf.write_text("-starts with a dash and spans\ntwo lines")
    before = sorted(os.listdir(world.wt))
    r = world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "-f", str(pf))
    assert r.returncode == 0, r.stderr
    call = world.launches()[0]
    assert call["argv"][-2:] == ["--", "-starts with a dash and spans\ntwo lines"]
    assert call["listing"] == before and sorted(os.listdir(world.wt)) == before


def test_stdout_carries_only_the_structured_output(world):
    world.scenario(output={"ok": True, "n": 3})
    r = world.launch()
    assert r.returncode == 0 and json.loads(r.stdout) == {"ok": True, "n": 3}
    assert len(r.stdout.strip().splitlines()) == 1


def test_json_prints_one_run_record_with_the_init_facts(world):
    r = world.launch("--json")
    rec = json.loads(r.stdout)
    assert rec["exit"] == 0 and rec["structured_output"] == {"ok": True}
    assert rec["init"]["tools"] == ["Glob", "Grep", "Read", "StructuredOutput"] and rec["init"]["permissionMode"] == "default"


# ---- refusals before anything runs (exit 2) -----------------------------------------------------------------

@pytest.mark.parametrize("flag", [["--dangerously-skip-permissions"], ["--permission-mode", "bypassPermissions"],
                                  ["--permission-mode=bypassPermissions"], ["--add-dir", "/"], ["--settings", "{}"],
                                  ["--mcp-config", "x.json"], ["--tools", "Bash"], ["--allowedTools", "Bash"]])
def test_a_bypass_or_widening_flag_is_refused_and_claude_never_runs(world, flag):
    r = world.launch(*flag)
    assert r.returncode == 2 and "refused" in r.stderr
    assert world.calls() == []


@pytest.mark.parametrize("var", ["CLAUDE_PERMISSION_MODE", "CLAUDE_CODE_PERMISSION_MODE", "BYPASS_PERMISSIONS",
                                 "CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS"])
def test_a_permission_mode_or_bypass_variable_is_refused(world, var):
    r = world.launch(env=world.env(**{var: "bypassPermissions"}))
    assert r.returncode == 2 and var in r.stderr
    assert world.calls() == []


def test_usage_errors_exit_2(world):
    assert world.run("--mode", "review", "-C", str(world.tmp / "nope"), "--schema", str(world.schema), "-p", "x").returncode == 2
    world.schema.write_text("{not json")
    assert world.launch().returncode == 2
    world.schema.write_text("[1]")
    assert world.launch().returncode == 2
    world.schema.write_text("{}")
    assert world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema)).returncode == 2
    assert world.run("--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "-p", "x", "-f", "y").returncode == 2
    assert world.run("--mode", "write", "-C", str(world.wt), "--schema", str(world.schema), "-p", "x").returncode == 2
    assert world.run("-C", str(world.wt), "--schema", str(world.schema), "-p", "x").returncode == 2
    assert world.launch(prompt="   ").returncode == 2
    assert world.launches() == []


@pytest.mark.parametrize("which", ["root", "home", "home-parent"])
def test_a_worktree_that_is_root_or_home_or_holds_home_is_refused(world, which):
    target = {"root": "/", "home": str(world.home), "home-parent": str(world.tmp)}[which]
    r = world.run("--mode", "review", "-C", target, "--schema", str(world.schema), "-p", "x")
    assert r.returncode == 2 and "home" in r.stderr
    assert world.calls() == []


# ---- --head: the exact head, a clean tree ------------------------------------------------------------------

def test_head_accepts_a_clean_worktree_at_that_head_and_untracked_inputs_under_review_launch(world):
    (world.wt / ".review-launch").mkdir()
    (world.wt / ".review-launch" / "diff.patch").write_text("diff\n")
    assert world.launch("--head", world.head).returncode == 0


@pytest.mark.parametrize("dirt", ["tracked", "untracked", "staged"])
def test_head_refuses_a_dirty_worktree(world, dirt):
    if dirt == "tracked":
        (world.wt / "a.txt").write_text("changed\n")
    elif dirt == "untracked":
        (world.wt / "stray.txt").write_text("x\n")
    else:
        (world.wt / "b.txt").write_text("x\n")
        git("add", "b.txt", cwd=world.wt)
    r = world.launch("--head", world.head)
    assert r.returncode == 2 and "not clean" in r.stderr and world.launches() == []


def test_head_refuses_another_head_and_a_short_sha(world):
    r = world.launch("--head", "f" * 40)
    assert r.returncode == 2 and "not the requested" in r.stderr
    assert world.launch("--head", world.head[:12]).returncode == 2
    assert world.launches() == []


# ---- the boundary, proven from the stream (exit 77) ---------------------------------------------------------

@pytest.mark.parametrize("init,needle", [
    ({"permissionMode": "acceptEdits"}, "permissionMode"),           # a refused bypass is silently downgraded
    ({"permissionMode": "bypassPermissions"}, "permissionMode"),
    ({"tools": ["Bash", "Glob", "Grep", "Read", "StructuredOutput"]}, "init tools"),
    ({"tools": ["Glob", "Grep", "Read"]}, "init tools"),
    ({"tools": ["Glob", "Grep", "Read", "StructuredOutput", "WebFetch"]}, "init tools"),
    ({"mcp_servers": [{"name": "hermes", "status": "connected"}]}, "mcp_servers"),
    ({"cwd": "/somewhere/else"}, "cwd"),
    ({"additional_directories": ["/"]}, "additional_directories"),
])
def test_an_init_event_outside_the_boundary_trips(world, init, needle):
    world.passed_check()
    world.scenario(init=init)
    r = world.launch()
    assert r.returncode == 77 and needle in r.stderr, r.stderr
    assert r.stdout == ""


def test_builtin_skills_agents_and_plugins_in_init_do_not_trip(world):
    world.passed_check()
    world.scenario(init={"skills": ["a", "b"], "agents": ["Explore"], "plugins": [{"name": "builtin"}], "slash_commands": ["x"]})
    assert world.launch().returncode == 0


@pytest.mark.parametrize("shape", [{"no_init": True}, {"init_after_assistant": True, "tool_uses": [{"name": "Read", "input": {"file_path": "a.txt"}}]}])
def test_a_missing_or_late_init_event_trips(world, shape):
    world.passed_check()
    world.scenario(**shape)
    r = world.launch()
    assert r.returncode == 77 and "init" in r.stderr


def test_a_hook_event_trips(world):
    world.passed_check()
    world.scenario(hook_event=True)
    r = world.launch()
    assert r.returncode == 77 and "hook" in r.stderr


@pytest.mark.parametrize("mode,tool,ok", [("review", "Bash", False), ("review", "WebFetch", False), ("review", "WebSearch", False),
                                          ("review", "Write", False), ("review", "mcp__hermes__send", False), ("review", "Task", False),
                                          ("read-only", "WebFetch", True), ("read-only", "Bash", False), ("review", "Grep", True)])
def test_a_tool_call_outside_the_allowlist_trips(world, mode, tool, ok):
    world.passed_check(mode)
    world.scenario(tool_uses=[{"name": tool, "input": {"pattern": "x"} if tool == "Grep" else {"url": "https://x"}}])
    r = world.launch(mode=mode)
    assert r.returncode == (0 if ok else 77), r.stderr


@pytest.mark.parametrize("tool,inp,ok", [
    ("Read", {"file_path": "a.txt"}, True),
    ("Read", {"file_path": "{wt}/a.txt"}, True),
    ("Read", {"file_path": "/etc/hostname"}, False),
    ("Read", {"file_path": "../outside.txt"}, False),
    ("Read", {"file_path": "~/.ssh/id_rsa"}, False),
    ("Read", {"file_path": "link/secret"}, False),          # a symlink inside the worktree that points outside
    ("Read", {"file_path": 7}, False),
    ("Grep", {"pattern": "x", "path": "/etc"}, False),
    ("Grep", {"pattern": "x", "glob": "../../*"}, False),
    ("Grep", {"pattern": "x"}, True),
    ("Glob", {"pattern": "/etc/*"}, False),
    ("Glob", {"pattern": "~/.aws/*"}, False),
    ("Glob", {"pattern": "**/*.py"}, True),
    ("Glob", {"pattern": "*", "path": ".."}, False),
])
def test_a_read_outside_the_worktree_trips_even_though_the_key_refuses_it(world, tool, inp, ok):
    world.passed_check()
    (world.tmp / "outside").mkdir()
    (world.wt / "link").symlink_to(world.tmp / "outside")
    inp = {k: (v.replace("{wt}", str(world.wt)) if isinstance(v, str) else v) for k, v in inp.items()}
    world.scenario(tool_uses=[{"name": tool, "input": inp}])
    r = world.launch()
    assert r.returncode == (0 if ok else 77), r.stderr


def test_claudes_own_refusals_are_logged(world):
    world.passed_check()
    world.scenario(denials=[{"tool_name": "Read", "tool_use_id": "t1", "tool_input": {"file_path": "a.txt"}}])
    r = world.launch()
    assert r.returncode == 0 and "refused by Claude: Read" in r.stderr


# ---- no output (exit 3), timeout (124), the descendant kill -------------------------------------------------

@pytest.mark.parametrize("shape,needle", [({"is_error": True}, "error"), ({"no_result": True}, "no result"),
                                          ({"no_structured": True}, "structured_output"), ({"no_result": True, "exit": 1}, "exited 1")])
def test_a_run_without_structured_output_is_exit_3(world, shape, needle):
    world.passed_check()
    world.scenario(**shape)
    r = world.launch()
    assert r.returncode == 3 and needle in r.stderr and r.stdout == ""


@pytest.mark.parametrize("spawn", ["group", "session"])
def test_a_hung_run_is_killed_at_the_timeout_with_its_descendants(world, spawn):
    world.passed_check()
    pid_file = world.tmp / "child.pid"
    world.scenario(sleep=60, spawn=spawn, pid_file=str(pid_file))
    t0 = time.monotonic()
    r = world.launch("--timeout", "3")
    assert r.returncode == 124 and time.monotonic() - t0 < 40
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not pid_alive(pid), f"descendant {pid} ({spawn}) survived"


@pytest.mark.parametrize("spawn", ["group", "session"])
def test_a_child_left_behind_by_a_finished_run_is_killed_too(world, spawn):
    world.passed_check()
    pid_file = world.tmp / "child.pid"
    world.scenario(spawn=spawn, pid_file=str(pid_file), sleep=1.5)
    assert world.launch().returncode == 0
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not pid_alive(pid)


def test_the_launchers_own_process_group_is_not_killed(world):
    # The child runs in a session of its own: killing its group must never reach the caller.
    world.passed_check()
    r = world.launch()
    assert r.returncode == 0 and os.getpgrp() == os.getpgid(0)


# ---- the self-check -----------------------------------------------------------------------------------------

def check_doc(world) -> dict:
    (f,) = list(world.state.glob("check-*.json"))
    return json.loads(f.read_text())


def test_a_launch_with_no_cached_check_runs_it_first_and_caches_it(world):
    r = world.launch()
    assert r.returncode == 0, r.stderr
    assert len(world.checks()) == 1 and len(world.launches()) == 1
    world.launch()
    assert len(world.checks()) == 1, "the passing check is cached"
    doc = check_doc(world)
    assert doc["status"] == "passed" and doc["claude_version"] == "9.9.9 (Claude Code)"
    assert (world.state / f"check-{doc['key']}.json").stat().st_mode & 0o777 == 0o600


def test_the_check_runs_with_the_launchs_own_boundary_flags(world):
    world.launch()
    check, launch = world.checks()[0]["argv"], world.launches()[0]["argv"]
    for flag in ("--tools", "--permission-mode", "--setting-sources", "--settings", "--output-format"):
        assert argv_val(check, flag) == argv_val(launch, flag), flag
    assert "--add-dir" not in check


def test_the_check_reads_the_named_paths_and_records_each_outcome(world):
    (world.home / ".claude").mkdir()
    (world.home / ".claude" / "CLAUDE.md").write_text("memory\n")
    (world.home / ".ssh").mkdir()
    world.passed_check()
    doc = check_doc(world)
    t = doc["targets"]
    assert set(t) == {"outside-temp", "gh-hosts", "ssh-dir", "claude-json", "claude-projects", "claude-md", "control"}
    assert t["outside-temp"]["outcome"] == "refused" and t["ssh-dir"]["outcome"] == "refused"
    assert t["control"]["outcome"] == "read"
    assert t["claude-md"]["outcome"] == "refused" and doc["accepted_exposures"] == []


def test_a_readable_claude_md_is_recorded_as_an_accepted_exposure_not_a_failure(world):
    (world.home / ".claude").mkdir()
    (world.home / ".claude" / "CLAUDE.md").write_text("memory\n")
    world.scenario(check="readable_md")
    world.passed_check()
    doc = check_doc(world)
    assert doc["status"] == "passed" and doc["accepted_exposures"] == [str(world.home / ".claude" / "CLAUDE.md")]


@pytest.mark.parametrize("shape,status,rc", [("leak", "failed", 77), ("leak_quiet", "failed", 77), ("trip", "failed", 77),
                                             ("control_fails", "inconclusive", 3), ("skip:outside-temp", "inconclusive", 3)])
def test_a_check_that_does_not_prove_the_key_fails_and_every_launch_is_refused(world, shape, status, rc):
    world.scenario(check=shape)
    r = world.run("--check", "--mode", "review")
    assert r.returncode == rc, r.stdout + r.stderr
    assert check_doc(world)["status"] == status
    world.scenario()                       # even a well-behaved launch is refused while the cached check failed
    r = world.launch()
    assert r.returncode == 2 and "self-check" in r.stderr
    assert world.launches() == []


def test_a_check_that_fails_on_first_use_refuses_that_launch(world):
    world.scenario(check="leak")
    r = world.launch()
    assert r.returncode == 2 and "self-check failed" in r.stderr and world.launches() == []


def test_a_new_claude_version_reruns_the_check(world):
    world.passed_check()
    world.scenario(version="10.0.0 (Claude Code)")
    assert world.launch().returncode == 0
    assert len(world.checks()) == 2 and len(list(world.state.glob("check-*.json"))) == 2


def test_the_two_modes_have_separate_checks(world):
    world.passed_check("review")
    assert world.launch(mode="read-only").returncode == 0
    assert len(world.checks()) == 2


def test_a_claude_whose_version_cannot_be_read_is_refused(world):
    world.scenario(version_rc=1)
    assert world.launch().returncode == 2 and world.calls() == []


def test_the_check_json_output_and_cache_record(world):
    r = world.run("--check", "--mode", "review", "--json")
    doc = json.loads(r.stdout)
    assert r.returncode == 0 and doc["status"] == "passed" and doc["mode"] == "review"
    assert doc["argv"][:2] == ["-p", "--output-format"] and doc["settings"]["permissions"]["blockReadsOutsideWorkingDirectories"]


def test_the_check_temp_dirs_are_removed(world, tmp_path, monkeypatch):
    before = set(Path("/tmp").glob("review-launch-check-*"))
    world.passed_check()
    assert set(Path("/tmp").glob("review-launch-check-*")) <= before


# ---- bin/review-pr -------------------------------------------------------------------------------------------

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_DIR"]
with open(os.path.join(d, "gh.log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
s = json.load(open(os.path.join(d, "gh.json")))
a = sys.argv[1:]
if a[:2] == ["pr", "view"]:
    if s.get("view_rc"):
        sys.stderr.write("no such PR\n"); sys.exit(1)
    print(json.dumps(s["view"])); sys.exit(0)
if a[:2] == ["api", "user"]:
    print(s.get("me", "djbclark")); sys.exit(0)
sys.stderr.write("fake gh: unserved " + " ".join(a) + "\n"); sys.exit(1)
"""


class PrWorld(World):
    """A bare `origin` named like the real repository, a PR head under refs/pull/7/head, a clone to run from."""

    def __init__(self, tmp: Path) -> None:
        super().__init__(tmp)
        (self.bin / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{tmp / "fake_gh.py"}" "$@"\n')
        (self.bin / "gh").chmod(0o755)
        (tmp / "fake_gh.py").write_text(FAKE_GH)
        self.origin = tmp / "djbclark" / "djbclark-ade.git"
        self.origin.parent.mkdir()
        git("init", "-q", "--bare", "-b", "master", str(self.origin), cwd=tmp)
        seed = tmp / "seed"
        git("clone", "-q", str(self.origin), str(seed), cwd=tmp)
        (seed / "base.txt").write_text("base\n")
        git("add", "base.txt", cwd=seed)
        git("commit", "-q", "-m", "base", cwd=seed)
        git("push", "-q", "origin", "HEAD:master", cwd=seed)
        self.base = git("rev-parse", "HEAD", cwd=seed)
        git("checkout", "-q", "-b", "feature", cwd=seed)
        (seed / "feature.txt").write_text("the PR's change\n")
        git("add", "feature.txt", cwd=seed)
        git("commit", "-q", "-m", "feature", cwd=seed)
        self.pr_head = git("rev-parse", "HEAD", cwd=seed)
        git("push", "-q", "origin", "HEAD:refs/pull/7/head", cwd=seed)
        self.clone = tmp / "clone"
        git("clone", "-q", str(self.origin), str(self.clone), cwd=tmp)
        (self.clone / "callers-own-dirty-file.txt").write_text("not the PR\n")
        self.gh(view={"headRefOid": self.pr_head, "baseRefOid": self.base, "baseRefName": "master",
                      "author": {"login": "djbclark"}, "state": "OPEN"})

    def gh(self, **kw) -> None:
        (self.tmp / "gh.json").write_text(json.dumps(kw))

    def env(self, **extra: str) -> dict:
        return super().env(FAKE_GH_DIR=str(self.tmp), **extra)

    def review(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(REVIEW_PR), "7", "--repo", "djbclark/djbclark-ade", *args],
                              capture_output=True, text=True, env=env or self.env(), timeout=180, cwd=str(self.clone))

    def filed(self) -> dict:
        return json.loads((self.state / f"djbclark__djbclark-ade-pr7-{self.pr_head}.json").read_text())


@pytest.fixture
def prw(tmp_path: Path) -> PrWorld:
    return PrWorld(tmp_path)


def test_review_pr_reviews_the_exact_head_in_a_clean_worktree_and_prints_the_marker(prw):
    r = prw.review()
    assert r.returncode == 0, r.stderr
    marker = r.stdout.strip()
    assert marker == '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"%s"} -->' % prw.pr_head
    v = adversary_marker.adversary_verdict(marker, prw.pr_head)
    assert adversary_marker.outcome(v) == "approve"
    (call,) = prw.launches()
    assert call["head"] == prw.pr_head, "the reviewed tree is the PR head, not the caller's checkout"
    assert "callers-own-dirty-file.txt" not in call["listing"] and "feature.txt" in call["listing"]
    assert call["inputs"]["files.txt"] == "feature.txt\n"
    assert "+the PR's change" in call["inputs"]["diff.patch"] and "base.txt" not in call["inputs"]["diff.patch"]
    assert f"HEAD_SHA: {prw.pr_head}" in call["argv"][-1] and f"BASE_SHA: {prw.base}" in call["argv"][-1]
    assert not Path(call["cwd"]).exists(), "the review worktree is removed"
    assert git("worktree", "list", cwd=prw.clone).count("\n") == 0
    doc = prw.filed()
    assert doc["verdict"] == "APPROVE" and doc["marker"] == marker and doc["base_sha"] == prw.base
    assert (prw.state / f"djbclark__djbclark-ade-pr7-{prw.pr_head}.json").stat().st_mode & 0o777 == 0o600


def test_review_pr_runs_the_launcher_in_review_mode_with_the_review_schema_and_head(prw):
    prw.review()
    argv = prw.launches()[0]["argv"]
    assert argv_val(argv, "--tools") == "Read,Grep,Glob"
    assert json.loads(argv_val(argv, "--json-schema")) == json.loads(SCHEMA.read_text())


def test_a_block_verdict_is_exit_1_with_a_block_marker(prw):
    prw.scenario(output={"verdict": "BLOCK", "head": prw.pr_head, "findings": [
        {"file": "feature.txt", "line": 1, "severity": "high", "summary": "bad"}], "note": "n"})
    r = prw.review()
    assert r.returncode == 1 and '"verdict":"BLOCK"' in r.stdout and "[high] feature.txt:1 bad" in r.stderr
    assert prw.filed()["findings"][0]["summary"] == "bad"


@pytest.mark.parametrize("out", [{"verdict": "APPROVE", "head": "f" * 40, "findings": [], "note": ""},
                                 {"verdict": "LGTM", "head": "HEAD", "findings": [], "note": ""}])
def test_a_verdict_that_does_not_name_this_head_is_no_verdict(prw, out):
    prw.scenario(output=out)
    r = prw.review()
    assert r.returncode == 3 and r.stdout == "" and prw.filed()["result"] == "failed"


@pytest.mark.parametrize("login,me,ok", [("djbclark", "someone", True), ("operator", "operator", True),
                                         ("stranger", "djbclark", False)])
def test_only_the_owner_or_the_authenticated_user_is_reviewed_by_default(prw, login, me, ok):
    prw.gh(view={"headRefOid": prw.pr_head, "baseRefOid": prw.base, "baseRefName": "master",
                 "author": {"login": login}, "state": "OPEN"}, me=me)
    r = prw.review()
    assert (r.returncode == 0) == ok, r.stderr
    if not ok:
        assert r.returncode == 2 and "allow-untrusted" in r.stderr and prw.calls() == []
        assert prw.review("--allow-untrusted").returncode == 0


def test_a_tripwire_in_the_review_is_passed_on_and_the_worktree_still_removed(prw):
    prw.passed_check()
    prw.scenario(tool_uses=[{"name": "Read", "input": {"file_path": "/etc/passwd"}}])
    r = prw.review()
    assert r.returncode == 77 and r.stdout == ""
    assert prw.filed()["result"] == "failed"
    assert git("worktree", "list", cwd=prw.clone).count("\n") == 0


def test_review_pr_refuses_another_repository_and_a_missing_pr(prw):
    r = subprocess.run([sys.executable, "-I", str(REVIEW_PR), "7", "--repo", "someone/else"], capture_output=True,
                       text=True, env=prw.env(), timeout=60, cwd=str(prw.clone))
    assert r.returncode == 2 and "origin" in r.stderr
    prw.gh(view_rc=1)
    assert prw.review().returncode == 2 and prw.calls() == []


def test_review_pr_refuses_a_pr_whose_base_or_head_is_not_a_sha(prw):
    prw.gh(view={"headRefOid": "main", "baseRefOid": prw.base, "baseRefName": "master", "author": {"login": "djbclark"}})
    assert prw.review().returncode == 2 and prw.calls() == []


def test_review_pr_never_calls_gh_to_post(prw):
    prw.review()
    for line in (prw.tmp / "gh.log").read_text().splitlines():
        argv = json.loads(line)
        assert argv[:2] in (["pr", "view"], ["api", "user"]), argv
