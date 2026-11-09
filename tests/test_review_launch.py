"""bin/review-launch (the review boundary) and bin/review-pr, against a fake `claude` and a fake `gh` on PATH.

The isolation checks the removed Codex local review had (slim-down E8, 2026-11-06, ported before it was deleted): a clean
detached worktree at the exact head with the base pinned by SHA; a scrubbed environment; the boundary proven
from the run's own init event, never assumed; the untrusted-author refusal; the descendant kill at the end and
at the timeout. The live self-check against a real Claude is an operator step (docs/review-boundary.md).
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
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

    def passed_check(self, mode: str = "review", *extra: str) -> None:
        r = self.run("--check", "--mode", mode, *extra)
        assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def argv_val(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def load_launcher(path: Path = LAUNCH):
    """bin/review-launch as a module (it has no .py suffix)."""
    loader = importlib.machinery.SourceFileLoader(f"review_launch_{abs(hash(str(path)))}", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def secret_deny_toml() -> dict:
    tomllib = pytest.importorskip("tomllib")
    return tomllib.loads((ROOT / "config" / "secret-deny.toml").read_text())


def claude_form(p: str) -> str:
    return "/" + p if p.startswith("/") else ("**/" + p if "/" not in p else p)


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


def test_read_only_mode_has_no_web_tool_by_default(world):
    # 2026-11-07: WebFetch/WebSearch are an exfiltration channel when the input is untrusted.
    assert world.launch(mode="read-only").returncode == 0
    assert argv_val(world.launches()[0]["argv"], "--tools") == "Read,Grep,Glob"


def test_allow_web_adds_the_two_web_tools_in_read_only_mode_and_nothing_else(world):
    r = world.launch("--allow-web", "--json", mode="read-only")
    assert r.returncode == 0, r.stderr
    assert argv_val(world.launches()[0]["argv"], "--tools") == "Read,Grep,Glob,WebFetch,WebSearch"
    rec = json.loads(r.stdout)
    assert rec["mode"] == "read-only" and rec["allow_web"] is True
    assert rec["init"]["tools"] == ["Glob", "Grep", "Read", "StructuredOutput", "WebFetch", "WebSearch"]


@pytest.mark.parametrize("args", [["--mode", "review"], []])
def test_allow_web_outside_read_only_mode_is_refused(world, args):
    r = world.run(*args, "-C", str(world.wt), "--schema", str(world.schema), "-p", "x", "--allow-web")
    assert r.returncode == 2 and "--allow-web" in r.stderr
    r = world.run("--check", *args, "--allow-web")
    assert r.returncode == 2 and "--allow-web" in r.stderr
    assert world.calls() == []


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
    for pat in secret_deny_toml()["deny"]:      # config/secret-deny.toml is the repo's one list (2026-11-07)
        assert f"Read({claude_form(pat)})" in p["deny"], pat
    assert len(p["deny"]) == len(set(p["deny"]))


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
                                  ["--mcp-config", "x.json"], ["--tools", "Bash"], ["--allowedTools", "Bash"],
                                  ["--json", "--settings", "{}"], ["--unknown", "--add-dir", "/"]])
def test_a_bypass_or_widening_flag_is_refused_and_claude_never_runs(world, flag):
    r = world.launch(*flag)
    assert r.returncode == 2 and "refused" in r.stderr
    assert world.calls() == []


@pytest.mark.parametrize("prompt", ["--settings {} is what this PR changes; review it",
                                    "--add-dir=/ is the flag under review here",
                                    "--dangerously-skip-permissions appears in the diff"])
def test_a_prompt_that_starts_with_a_bypass_flag_name_is_a_value_not_a_flag(world, prompt):
    # 2026-11-07: the scan read every argv token, so a prompt (the value after -p) starting with `--settings` was refused.
    r = world.launch(prompt=prompt)
    assert r.returncode == 0, r.stderr
    assert world.launches()[0]["argv"][-2:] == ["--", prompt]


def test_the_bypass_scan_skips_values_by_option_name_and_abbreviation_only():
    rl = load_launcher()
    p = rl.parser()
    assert rl.bypass_flag(["-p", "--settings x"], p) is None
    assert rl.bypass_flag(["-p=--settings"], p) is None
    assert rl.bypass_flag(["--schema", "--add-dir", "-C", "--tools"], p) is None
    assert rl.bypass_flag(["--sch", "--add-dir"], p) is None             # argparse's unique abbreviation of --schema
    assert rl.bypass_flag(["--json", "--add-dir", "/"], p) == "--add-dir"  # --json takes no value
    assert rl.bypass_flag(["-pX", "--settings", "{}"], p) == "--settings"  # -pX carried its value
    assert rl.bypass_flag(["--mo", "--settings"], p) == "--settings"       # ambiguous (--mode/--model): fail closed
    assert rl.bypass_flag(["-p", "x", "--settings=y"], p) == "--settings"


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
                                          ("read-only", "WebFetch", False), ("read-only", "WebSearch", False),
                                          ("read-only+web", "WebFetch", True), ("read-only+web", "WebSearch", True),
                                          ("read-only+web", "Bash", False), ("read-only", "Bash", False), ("review", "Grep", True)])
def test_a_tool_call_outside_the_allowlist_trips(world, mode, tool, ok):
    extra = ("--allow-web",) if mode == "read-only+web" else ()
    mode = "read-only" if extra else mode
    world.passed_check(mode, *extra)
    world.scenario(tool_uses=[{"name": tool, "input": {"pattern": "x"} if tool == "Grep" else {"url": "https://x"}}])
    r = world.launch(*extra, mode=mode)
    assert r.returncode == (0 if ok else 77), r.stderr


@pytest.mark.parametrize("tool,inp,ok", [
    ("Read", {"file_path": "a.txt"}, True),
    ("Read", {"file_path": "{wt}/a.txt"}, True),
    ("Read", {"file_path": "/etc/hostname"}, False),
    ("Read", {"file_path": "../outside.txt"}, False),
    ("Read", {"file_path": "~/.ssh/id_rsa"}, False),
    ("Read", {"file_path": 7}, False),
    ("Grep", {"pattern": "x", "path": "/etc"}, False),
    ("Grep", {"pattern": "x", "glob": "../../*"}, False),
    ("Grep", {"pattern": "x"}, True),
    ("Glob", {"pattern": "/etc/*"}, False),
    ("Glob", {"pattern": "~/.aws/*"}, False),
    ("Glob", {"pattern": "**/*.py"}, True),
    ("Glob", {"pattern": "*", "path": ".."}, False),
    ("Glob", {"pattern": "sub/../*.txt"}, False),            # any `..` in a pattern trips, even one that stays inside
    ("Glob", {"pattern": "..\\*"}, False),
    ("Grep", {"pattern": "x", "glob": "a/../b/*.py"}, False),
    ("Grep", {"pattern": "x", "glob": "*.py"}, True),
    ("Glob", {"pattern": "..foo/*.txt"}, True),               # a name that merely starts with dots is not `..`
])
def test_a_read_outside_the_worktree_trips_even_though_the_key_refuses_it(world, tool, inp, ok):
    # A symlink that leaves the worktree now refuses the launch before it (the tests below); the tripwire's own
    # symlink handling is unit-tested on path_outside/glob_outside.
    world.passed_check()
    inp = {k: (v.replace("{wt}", str(world.wt)) if isinstance(v, str) else v) for k, v in inp.items()}
    world.scenario(tool_uses=[{"name": tool, "input": inp}])
    r = world.launch()
    assert r.returncode == (0 if ok else 77), r.stderr


# ---- a symlink that leaves the worktree (refused before the launch, exit 2) ----------------------------------

def commit_link(world, name: str, target: Path | str) -> None:
    (world.wt / name).symlink_to(target)
    git("add", name, cwd=world.wt)
    git("commit", "-q", "-m", f"link {name}", cwd=world.wt)
    world.head = git("rev-parse", "HEAD", cwd=world.wt)


def test_a_committed_symlink_to_a_directory_outside_is_refused_before_the_launch(world):
    (world.tmp / "outside").mkdir()
    commit_link(world, "evil", world.tmp / "outside")
    r = world.launch("--head", world.head)
    assert r.returncode == 2 and "symlink" in r.stderr and "evil ->" in r.stderr, r.stderr
    assert world.calls() == [], "neither the self-check nor the launch ran"


@pytest.mark.parametrize("shape", ["untracked-dir", "nested-file", "dangling", "home"])
def test_any_symlink_whose_target_leaves_the_worktree_is_refused(world, shape):
    (world.tmp / "outside").mkdir()
    (world.tmp / "outside" / "f").write_text("x\n")
    if shape == "untracked-dir":
        (world.wt / "link").symlink_to(world.tmp / "outside")
    elif shape == "nested-file":
        (world.wt / "sub" / "deeper").mkdir(parents=True)
        (world.wt / "sub" / "deeper" / "f").symlink_to("../../../outside/f")
    elif shape == "dangling":
        (world.wt / "gone").symlink_to(world.tmp / "nothing-here")
    else:
        (world.wt / "dotssh").symlink_to(world.home / ".ssh")
    r = world.launch()
    assert r.returncode == 2 and "symlink" in r.stderr, r.stderr
    assert world.calls() == []


def test_a_symlink_that_stays_inside_the_worktree_is_allowed(world):
    (world.wt / "sub").mkdir()
    (world.wt / "sub" / "b.txt").write_text("b\n")
    git("add", "sub/b.txt", cwd=world.wt)
    commit_link(world, "alias", "a.txt")
    commit_link(world, "subdir", "sub")
    assert world.launch("--head", world.head).returncode == 0


def test_escaping_links_reads_both_git_and_the_disk(tmp_path):
    rl = load_launcher()
    wt = tmp_path / "wt"
    wt.mkdir()
    git("init", "-q", "-b", "main", cwd=wt)
    (tmp_path / "out").mkdir()
    (wt / "tracked").symlink_to(tmp_path / "out")
    git("add", "tracked", cwd=wt)
    git("commit", "-q", "-m", "t", cwd=wt)
    (wt / "untracked").symlink_to("/")
    (wt / "fine").symlink_to("tracked/../untracked")       # resolves through `tracked` to outside too
    found = dict(rl.escaping_links(os.path.realpath(wt)))
    assert set(found) == {"tracked", "untracked", "fine"}
    assert found["untracked"] == "/"


def test_glob_outside_resolves_a_relative_patterns_prefix_through_symlinks(tmp_path):
    rl = load_launcher()
    wt = tmp_path / "wt"
    (wt / "real").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (wt / "link").symlink_to(tmp_path / "outside")
    (wt / "inlink").symlink_to(wt / "real")
    w = os.path.realpath(wt)
    for pat, out in [("link/**", True), ("link/*.txt", True), ("link/sub/**/x", True), ("link", False),
                     ("inlink/**", False), ("real/**", False), ("**/*.py", False), ("*.py", False),
                     ("..foo/*", False), ("/etc/*", True), ("sub/../*", True)]:
        assert rl.glob_outside(pat, w, w) is out, pat
    # a Grep glob is matched under its path: judged against that base
    assert rl.glob_outside("*.txt", os.path.join(w, "link"), w) is True
    assert rl.path_outside("link/secret", w) is True


# ---- the secret-deny policy (config/secret-deny.toml) -------------------------------------------------------

def test_the_deny_rules_carry_every_secret_deny_toml_pattern_plus_the_own_list():
    rl = load_launcher()
    assert rl.POLICY_ERROR is None
    deny = rl.SETTINGS["permissions"]["deny"]
    for pat in secret_deny_toml()["deny"]:
        assert f"Read({claude_form(pat)})" in deny, pat
    for pat in rl.DENY_PATHS:
        assert f"Read({pat})" in deny, pat


def test_default_policy_deny_uses_load_effective(tmp_path, monkeypatch):
    """S1: default policy_deny() matches the effective secret_deny domain."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    rl = load_launcher()
    via_eff = rl.policy_deny(root=ROOT, home=home, environ={})
    assert via_eff == secret_deny_toml()["deny"]


def test_without_tomllib_the_rendered_policy_json_is_read(tmp_path, monkeypatch):
    rl = load_launcher()
    monkeypatch.setattr(rl, "tomllib", None)
    toml = tmp_path / "secret-deny.toml"
    toml.write_text("not toml at all [[[")
    js = tmp_path / "policy.json"
    js.write_text(json.dumps({"version": 1, "deny": ["~/.x/**", "*.key"]}))
    assert rl.policy_deny(toml, js) == ["~/.x/**", "*.key"]
    js.write_text("{broken")
    with pytest.raises(rl.PolicyError):
        rl.policy_deny(toml, js)
    js.unlink()
    with pytest.raises(rl.PolicyError):
        rl.policy_deny(toml, js)
    toml.unlink()
    assert rl.policy_deny(toml, js) == []


@pytest.mark.parametrize("body", ["deny = [", "version = 2\ndeny = ['x']", "version = 1\ndeny = []",
                                  "version = 1\ndeny = [3]", "version = 1"])
def test_a_secret_deny_toml_that_does_not_parse_refuses_every_launch_and_check(world, body):
    pytest.importorskip("tomllib")
    repo = world.tmp / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "config").mkdir()
    shutil.copy2(LAUNCH, repo / "bin" / "review-launch")
    (repo / "config" / "secret-deny.toml").write_text(body + "\n")
    launcher = repo / "bin" / "review-launch"
    for args in (["--check"], ["--mode", "review", "-C", str(world.wt), "--schema", str(world.schema), "-p", "x"]):
        r = subprocess.run([sys.executable, "-I", str(launcher), *args], capture_output=True, text=True,
                           env=world.env(), timeout=120)
        assert r.returncode == 2 and "secret-deny" in r.stderr, r.stderr
    assert world.calls() == []


def test_a_missing_secret_deny_toml_leaves_the_own_list(world):
    repo = world.tmp / "repo"
    (repo / "bin").mkdir(parents=True)
    shutil.copy2(LAUNCH, repo / "bin" / "review-launch")
    rl = load_launcher(repo / "bin" / "review-launch")
    assert rl.POLICY_ERROR is None
    assert rl.SETTINGS["permissions"]["deny"] == [f"Read({p})" for p in rl.DENY_PATHS]


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


def test_the_web_tool_set_has_its_own_check(world):
    # review and read-only launch with the same fixed flags (2026-11-07), so one check proves both; --allow-web's
    # tool set is a different launch and has its own.
    world.passed_check("review")
    assert world.launch(mode="read-only").returncode == 0
    assert len(world.checks()) == 1
    assert world.launch("--allow-web", mode="read-only").returncode == 0
    assert len(world.checks()) == 2
    assert argv_val(world.checks()[1]["argv"], "--tools") == "Read,Grep,Glob,WebFetch,WebSearch"


def test_the_check_runs_on_the_launchs_model_and_each_model_has_its_own_check(world):
    # 2026-11-07: with the default model out of credits, a check on the default model got a 'fallback' content item
    # and tripped, refusing every launch on a model that would have worked; the check now proves the launch's model.
    assert world.launch("--model", "opus").returncode == 0
    check = world.checks()[0]["argv"]
    assert argv_val(check, "--model") == "opus"
    assert world.launch("--model", "sonnet").returncode == 0
    assert len(world.checks()) == 2 and len(list(world.state.glob("check-*.json"))) == 2
    assert world.launch("--model", "opus").returncode == 0
    assert len(world.checks()) == 2, "the opus check is cached"


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


def test_review_pr_of_a_pr_that_commits_a_symlink_outside_is_refused_and_the_worktree_removed(prw):
    seed = prw.tmp / "seed"
    (seed / "evil").symlink_to(prw.home / ".ssh")
    git("add", "evil", cwd=seed)
    git("commit", "-q", "-m", "evil", cwd=seed)
    head = git("rev-parse", "HEAD", cwd=seed)
    git("push", "-q", "-f", "origin", "HEAD:refs/pull/7/head", cwd=seed)
    prw.pr_head = head
    prw.gh(view={"headRefOid": head, "baseRefOid": prw.base, "baseRefName": "master",
                 "author": {"login": "djbclark"}, "state": "OPEN"})
    r = prw.review()
    assert r.returncode == 2 and "symlink" in r.stderr and "evil" in r.stderr, r.stderr
    assert prw.calls() == [] and prw.filed()["result"] == "failed"
    assert len(git("worktree", "list", cwd=prw.clone).splitlines()) == 1, "the review worktree is removed"


def test_review_pr_never_calls_gh_to_post(prw):
    prw.review()
    for line in (prw.tmp / "gh.log").read_text().splitlines():
        argv = json.loads(line)
        assert argv[:2] in (["pr", "view"], ["api", "user"]), argv


# ---- E8 review repairs (2026-11-07) -------------------------------------------------------------------------

@pytest.mark.parametrize("items,ok", [
    ([{"type": "text", "text": "hi"}, {"type": "thinking", "thinking": "hm"}], True),
    ([{"type": "redacted_thinking", "data": "xx"}], True),
    ([{"type": "server_tool_use", "name": "web_search", "input": {"query": "x"}}], False),
    ([{"type": "mcp_tool_use", "name": "send", "server_name": "hermes", "input": {}}], False),
    ([{"type": "image"}], False),
    (["a bare string"], False),
])
def test_an_assistant_content_item_that_is_not_text_thinking_or_tool_use_trips(world, items, ok):
    world.passed_check()
    world.scenario(content_items=items)
    r = world.launch()
    assert r.returncode == (0 if ok else 77), r.stderr
    if not ok:
        assert "content item" in r.stderr


def test_a_signal_to_the_launcher_is_exit_3_and_kills_the_run(world):
    world.passed_check()
    pid_file = world.tmp / "child.pid"
    world.scenario(sleep=60, spawn="session", pid_file=str(pid_file))
    p = subprocess.Popen([sys.executable, "-I", str(LAUNCH), "--mode", "review", "-C", str(world.wt), "--schema",
                          str(world.schema), "-p", "x"], env=world.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, cwd=str(world.tmp))
    deadline = time.monotonic() + 30
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert pid_file.exists(), "the fake never started"
    time.sleep(1.5)        # let the launcher's 1 s ps snapshot see the child
    p.send_signal(signal.SIGTERM)
    out, err = p.communicate(timeout=60)
    assert p.returncode == 3, (p.returncode, err)
    assert out == "" and "interrupted" in err
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not pid_alive(pid)


def test_a_pr_whose_diff_is_not_utf8_is_reviewed_and_the_diff_is_handed_over_byte_for_byte(prw, tmp_path):
    seed = prw.tmp / "seed"
    (seed / "latin1.txt").write_bytes(b"caf\xe9 cr\xe8me\n")
    git("add", "latin1.txt", cwd=seed)
    git("commit", "-q", "-m", "latin-1", cwd=seed)
    head = git("rev-parse", "HEAD", cwd=seed)
    git("push", "-q", "-f", "origin", "HEAD:refs/pull/7/head", cwd=seed)
    prw.pr_head = head
    prw.gh(view={"headRefOid": head, "baseRefOid": prw.base, "baseRefName": "master", "author": {"login": "djbclark"},
                 "state": "OPEN"})
    r = prw.review()
    assert r.returncode == 0, r.stderr      # before the repair: UnicodeDecodeError, exit 1 (read as BLOCK), no result file
    (call,) = prw.launches()
    assert "latin1.txt" in call["inputs"]["files.txt"]
    assert "caf\ufffd cr\ufffdme" in call["inputs"]["diff.patch"], "the fake read it with errors=replace: the bytes were not UTF-8"
    assert prw.filed()["verdict"] == "APPROVE"


def test_a_git_diff_that_fails_with_undecodable_output_is_exit_3_with_a_result_file(prw):
    # git's own error text is not UTF-8 either: still a filed `failed` result and exit 3, never a traceback.
    bad = prw.tmp / "bin" / "git"
    real = shutil.which("git", path=os.pathsep.join(p for p in prw.env()["PATH"].split(os.pathsep) if p != str(prw.bin)))
    bad.write_text(f'#!/bin/sh\nif [ "$1" = diff ]; then printf "\\377\\376" >&2; exit 1; fi\nexec "{real}" "$@"\n')
    bad.chmod(0o755)
    r = prw.review()
    assert r.returncode == 3, r.stderr
    doc = prw.filed()
    assert doc["result"] == "failed" and "git diff failed" in doc["reason"]


def test_the_review_prompt_says_everything_from_the_pr_is_untrusted_and_the_schema_is_the_only_channel(prw):
    prw.review()
    prompt = prw.launches()[0]["argv"][-1]
    for needle in ("UNTRUSTED DATA", "never instructions", "the PR's body", "every file in this checkout",
                   "ONLY through the", "structured output schema", "prompt-injection"):
        assert needle in prompt, needle

