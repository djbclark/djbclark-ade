"""bin/ade-update pulls, relinks, checks symlinks and prints the changelog delta (2026-10-20).

Every test builds a real git repo pair in tmp_path: a bare `origin`, a `seed` clone that publishes
commits, and the `machine` clone ade-update runs on. skill-everywhere is a fake on PATH that records
its argv and answers from a JSON file, so no real TUI directory is touched. HOME is tmp_path/home, and
SKILL_EVERYWHERE_ADE names the `machine` clone's skills/ so that clone is the canonical skills home (the
only checkout whose skill links ade-update may change).
"""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-update"

CHANGELOG_V1 = """# Changelog

## Unreleased

### Added

- First thing (#1).
"""

CHANGELOG_V2 = """# Changelog

## Unreleased

### Added

- Second thing, which wraps
  onto a continuation line (#2).
- First thing (#1).
"""

# A fake skill-everywhere: logs argv, answers --check from a JSON map {skill: [[tui, state], ...]},
# and a link call rewrites every named skill's fixable states to "linked".
FAKE_SKILL_EVERYWHERE = """#!{python}
import json, os, sys
state = os.environ["FAKE_SE_STATE"]
with open(os.environ["FAKE_SE_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
table = json.load(open(state))
args = sys.argv[1:]
check = bool(args) and args[0] == "--check"
names = args[1:] if check else args
if check:
    for n in names:
        print("== " + n)
        for tui, st in table.get(n, [["claude", "linked"]]):
            print("  %-13s %s" % (tui, st))
else:
    for n in names:
        table[n] = [[t, "linked" if s in ("missing",) or s.startswith(("dangling", "chained")) else s]
                    for t, s in table.get(n, [])]
        print("== " + n)
    json.dump(table, open(state, "w"))
sys.exit(0)
"""


def sh(*argv, cwd=None):
    r = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{argv}: {r.stderr}"
    return r.stdout.strip()


def commit(repo, message, files):
    for rel, text in files.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        sh("git", "add", str(p), cwd=repo)
    sh("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message, cwd=repo)


class Env:
    def __init__(self, tmp):
        self.tmp = tmp
        self.origin, self.seed, self.machine = tmp / "origin.git", tmp / "seed", tmp / "machine"
        self.home, self.state = tmp / "home", tmp / "state" / "applied"
        self.bin, self.se_state, self.se_log = tmp / "fakebin", tmp / "se-state.json", tmp / "se.log"
        self.home.mkdir()
        self.bin.mkdir()
        self.se_log.write_text("")
        self.se_state.write_text("{}")
        fake = self.bin / "skill-everywhere"
        fake.write_text(FAKE_SKILL_EVERYWHERE.format(python=sys.executable))
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        sh("git", "init", "-q", "--bare", "-b", "master", str(self.origin))
        sh("git", "clone", "-q", str(self.origin), str(self.seed))
        sh("git", "checkout", "-q", "-b", "master", cwd=self.seed)
        commit(self.seed, "initial", {"AGENTS.md": "# agents\n", "CHANGELOG.md": CHANGELOG_V1,
                                      "skills/alpha/SKILL.md": "---\nname: alpha\n---\n", "notes.txt": "one\n"})
        os.symlink("AGENTS.md", self.seed / "CLAUDE.md")
        sh("git", "add", "CLAUDE.md", cwd=self.seed)
        sh("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "link", cwd=self.seed)
        sh("git", "push", "-q", "origin", "master", cwd=self.seed)
        sh("git", "clone", "-q", str(self.origin), str(self.machine))
        self.first = self.head(self.machine)

    @staticmethod
    def head(repo):
        return sh("git", "rev-parse", "HEAD", cwd=repo)

    def publish(self, files=None, message="second"):
        files = {"CHANGELOG.md": CHANGELOG_V2, **(files or {})}
        commit(self.seed, message, files)
        sh("git", "push", "-q", "origin", "master", cwd=self.seed)
        return self.head(self.seed)

    def skills(self, table):
        self.se_state.write_text(json.dumps(table))

    def calls(self):
        return [json.loads(line) for line in self.se_log.read_text().splitlines()]

    def run(self, *flags, repo=None, state=None, extra_env=None):
        env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                   FAKE_SE_STATE=str(self.se_state), FAKE_SE_LOG=str(self.se_log),
                   SKILL_EVERYWHERE_ADE=str(self.machine / "skills"))
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo or self.machine),
                            "--state", str(state or self.state), *flags], capture_output=True, text=True, env=env)
        return r


@pytest.fixture(autouse=True)
def _allow_fixture_identity(monkeypatch):
    # The reference-transaction guard refuses a ref update whose committer is not the operator
    # (inside an acp-run session); the fixture repos commit as "t". The override is per test.
    monkeypatch.setenv("ACP_RUN_ALLOW_GIT_IDENTITY", "1")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def load_module():
    loader = importlib.machinery.SourceFileLoader("ade_update", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ade_update", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_current_exits_zero_and_records_head(env):
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "repo: current" in r.stdout
    assert env.state.read_text().strip() == env.first
    assert "First thing (#1)." in r.stdout  # no record yet: every Unreleased entry
    assert env.calls() == [["--check", "alpha"]]  # nothing to link, so only the check


def test_current_check_writes_nothing(env):
    r = env.run("--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not env.state.exists()
    assert "would record" in r.stdout


def test_behind_check_reports_and_changes_nothing(env):
    env.publish()
    r = env.run("--check")
    assert r.returncode == 10, r.stdout + r.stderr
    assert env.head(env.machine) == env.first
    assert not env.state.exists()
    assert "behind" in r.stdout and "would run: git" in r.stdout
    assert "Second thing, which wraps onto a continuation line (#2)." in r.stdout


def test_behind_apply_pulls_records_head_and_prints_only_new_entries(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    new = env.publish()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.head(env.machine) == new
    assert env.state.read_text().strip() == new
    assert "Second thing, which wraps onto a continuation line (#2)." in r.stdout
    assert "First thing" not in r.stdout  # already recorded at the old revision
    assert list(env.state.parent.glob(".applied.*")) == []  # no temp file left beside


def test_dirty_tracked_file_the_pull_changes_stops_with_exit_2(env):
    (env.machine / "notes.txt").write_text("local edit\n")
    env.publish({"notes.txt": "two\n"})
    r = env.run()
    assert r.returncode == 2, r.stdout + r.stderr
    assert "notes.txt" in r.stdout
    assert env.head(env.machine) == env.first
    assert (env.machine / "notes.txt").read_text() == "local edit\n"
    assert not env.state.exists()


def test_dirty_file_the_pull_does_not_touch_does_not_block(env):
    (env.machine / "notes.txt").write_text("local edit\n")
    new = env.publish()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.head(env.machine) == new
    assert (env.machine / "notes.txt").read_text() == "local edit\n"


def test_diverged_branch_is_exit_3_and_never_merged(env):
    commit(env.machine, "local", {"local.txt": "mine\n"})
    local = env.head(env.machine)
    env.publish()
    for flags in ((), ("--check",)):
        r = env.run(*flags)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "diverged" in r.stdout
        assert env.head(env.machine) == local
    assert not env.state.exists()


def test_no_upstream_is_exit_4(env):
    sh("git", "branch", "--unset-upstream", cwd=env.machine)
    r = env.run("--check")
    assert r.returncode == 4
    assert "no upstream" in r.stdout


def test_claude_md_not_a_symlink_is_reported(env):
    (env.machine / "CLAUDE.md").unlink()
    (env.machine / "CLAUDE.md").write_text("a plain file\n")
    r = env.run("--check", "--json")
    assert r.returncode == 10, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["claude_md"]["ok"] is False
    assert "not a symlink" in out["claude_md"]["detail"]
    assert "CLAUDE.md" in out["problems"]


def test_missing_claude_link_is_reported_with_the_fix(env):
    env.publish({"claude/commands/demo.md": "demo\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 10
    (problem,) = out["claude_links"]["problems"]
    assert problem["path"] == str(env.home / ".claude" / "commands" / "demo.md")
    assert problem["fix"].startswith("ln -sfn ")
    # linking it makes the check pass
    dest = env.home / ".claude" / "commands" / "demo.md"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(env.machine / "claude" / "commands" / "demo.md")
    r = env.run("--check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_missing_skill_link_is_linked_on_apply_and_only_reported_on_check(env):
    env.skills({"alpha": [["claude", "missing"], ["codex", "linked"]]})
    r = env.run("--check")
    assert r.returncode == 10, r.stdout + r.stderr
    assert "alpha: claude missing" in r.stdout and "would run:" in r.stdout
    assert env.calls() == [["--check", "alpha"]]
    assert not env.state.exists()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.calls()[2:] == [["alpha"], ["--check", "alpha"]]
    assert "linked now: alpha" in r.stdout
    assert env.state.read_text().strip() == env.first


def test_unfixable_skill_link_is_reported_and_blocks_the_state_record(env):
    env.skills({"alpha": [["claude", "real dir/file (not ours)"]]})
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert "leaves it alone" in r.stdout
    assert ["alpha"] not in env.calls()  # nothing the link form could repair
    assert not env.state.exists()


def test_state_write_is_atomic_and_leaves_the_old_record_on_failure(tmp_path, monkeypatch):
    mod = load_module()
    state = tmp_path / "deep" / "applied"
    mod.write_state(state, "a" * 40)
    assert state.read_text() == "a" * 40 + "\n"
    seen = {}
    real_replace = os.replace

    def failing_replace(src, dst):
        seen["tmp_beside"] = Path(src).parent == Path(dst).parent and Path(src).exists()
        raise OSError("boom")

    monkeypatch.setattr(mod.os, "replace", failing_replace)
    with pytest.raises(OSError):
        mod.write_state(state, "b" * 40)
    monkeypatch.setattr(mod.os, "replace", real_replace)
    assert seen["tmp_beside"] is True
    assert state.read_text() == "a" * 40 + "\n"  # the old record survives
    assert sorted(p.name for p in state.parent.iterdir()) == ["applied"]  # temp file cleaned up


def test_read_state_tolerates_absent_empty_garbage_and_unknown(env, tmp_path):
    mod = load_module()
    assert mod.read_state(tmp_path / "nope", env.machine) is None
    for text in ("", "\n", "not a sha\n", "f" * 40 + "\n"):
        p = tmp_path / "s"
        p.write_text(text)
        assert mod.read_state(p, env.machine) is None, text
    p.write_text(env.first.upper() + "  extra words\n")
    assert mod.read_state(p, env.machine) == env.first
    for raw in (b"\xff\xfe\x00garbage", b"\xff" * 40, env.first.encode() + b"\n\xff\xfe"):
        p.write_bytes(raw)
        assert mod.read_state(p, env.machine) in (None, env.first), raw  # never raises
    p.write_bytes(b"\xff\xfe\x00garbage")
    assert mod.read_state(p, env.machine) is None
    r = env.run("--check", state=p)
    assert r.returncode == 0, r.stdout + r.stderr  # a non-UTF-8 record is read as none, not a traceback


def test_changelog_delta_ignores_entries_moved_under_a_release():
    mod = load_module()
    before = CHANGELOG_V2
    after = """# Changelog

## Unreleased

### Added

- Third thing (#3).

## 0.1.0 - 2026-10-21

### Added

- Second thing, which wraps
  onto a continuation line (#2).
- First thing (#1).
"""
    delta = mod.changelog_delta(before, after)
    assert delta == [("Unreleased / Added", "Third thing (#3).")]
    assert mod.changelog_delta(None, after) == [("Unreleased / Added", "Third thing (#3).")]
    assert mod.changelog_delta(before, None or "") == []


def test_json_output_is_one_object(env):
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert out["mode"] == "check" and out["repo_state"] == "current" and out["exit"] == 0
    assert out["head_before"] == env.first and out["changelog"]["since"] is None


# --- adversary review of 231712f (2026-10-20) ---------------------------------------------------

def clone(env, name):
    dest = env.tmp / name
    sh("git", "clone", "-q", str(env.origin), str(dest))
    return dest


def test_non_canonical_repo_reports_skills_but_never_links(env):
    other = clone(env, "other")
    env.skills({"alpha": [["claude", "missing"], ["codex", "linked"]]})
    for flags in (("--check",), ()):
        r = env.run(*flags, repo=other)
        assert r.returncode == 0, r.stdout + r.stderr  # nothing this run could fix counts as a problem
        assert "report-only" in r.stdout and "not the canonical skills home" in r.stdout
        assert "missing x1" in r.stdout and "alpha:" not in r.stdout  # counted, no per-row hint to copy
        assert "would run:" not in r.stdout and "ran:" not in r.stdout
    assert env.calls() == [["--check", "alpha"], ["--check", "alpha"]]  # no link call, in either mode
    assert json.loads(env.run("--check", "--json", repo=other).stdout)["skills"]["link_mode"] == "report-only"
    # the canonical clone, same table, does link
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert ["alpha"] in env.calls() and "report-only" not in r.stdout


def test_canonical_repo_follows_skill_everywhere_ade_then_the_default(tmp_path, monkeypatch):
    mod = load_module()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SKILL_EVERYWHERE_ADE", raising=False)
    assert mod.canonical_repo() == (tmp_path / "src" / "djbclark-ade").resolve()
    monkeypatch.setenv("SKILL_EVERYWHERE_ADE", str(tmp_path / "elsewhere" / "skills"))
    assert mod.canonical_repo() == (tmp_path / "elsewhere").resolve()


def test_skill_directory_named_like_a_flag_is_skipped_and_reported(env):
    mod = load_module()
    hostile = env.machine / "skills" / "--remove"
    hostile.mkdir()
    (hostile / "SKILL.md").write_text("---\nname: x\n---\n")
    for name in ("-dash", ".hidden", "sp ace"):
        (env.machine / "skills" / name).mkdir()
        (env.machine / "skills" / name / "SKILL.md").write_text("x\n")
    names, skipped = mod.skill_names(env.machine)
    assert names == ["alpha"] and skipped == ["--remove", "-dash", ".hidden", "sp ace"]
    env.skills({"alpha": [["claude", "missing"]]})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipped" in r.stdout and "--remove" in r.stdout
    assert all(call[0] in ("--check", "alpha") for call in env.calls()), env.calls()  # never a flag from a directory
    assert not any("--remove" in call for call in env.calls())


def test_upstream_flag_named_skill_is_skipped_in_check(env):
    env.publish({"skills/--remove/SKILL.md": "x\n", "skills/beta/SKILL.md": "y\n"})
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert out["skills"]["new_upstream"] == ["beta"] and out["skills"]["skipped"] == ["--remove"]


def test_printed_hints_are_shell_quoted_and_a_real_file_is_not_clobbered(env):
    spaced = env.tmp / "machine sp"
    sh("git", "clone", "-q", str(env.origin), str(spaced))
    env.publish({"claude/commands/demo.md": "demo\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=spaced)
    (spaced / "CLAUDE.md").unlink()
    (spaced / "CLAUDE.md").write_text("plain\n")
    mine = env.home / ".claude" / "commands" / "demo.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("my own file\n")
    r = env.run("--check", "--json", repo=spaced, extra_env={"SKILL_EVERYWHERE_ADE": str(spaced / "skills")})
    out = json.loads(r.stdout)
    assert r.returncode == 10, r.stdout + r.stderr
    fix = out["claude_md"]["fix"]
    assert shlex.split(fix.split("then: ")[1]) == ["ln", "-sfn", "AGENTS.md", str(spaced / "CLAUDE.md")]
    (problem,) = out["claude_links"]["problems"]
    assert problem["state"] == "a real file (not ours)"
    assert problem["fix"].startswith("inspect ") and "move it aside" in problem["fix"]
    assert shlex.split(problem["fix"].split("then: ")[1]) == [
        "ln", "-sfn", str(spaced / "claude" / "commands" / "demo.md"), str(mine)]
    assert mine.read_text() == "my own file\n"


def test_a_pull_hint_with_a_space_in_the_path_is_quoted(env):
    spaced = env.tmp / "machine sp"
    sh("git", "clone", "-q", str(env.origin), str(spaced))
    env.publish()
    r = env.run("--check", repo=spaced)
    line = next(l for l in r.stdout.splitlines() if "would run: git" in l)
    assert shlex.split(line.split("would run: ")[1]) == ["git", "-C", str(spaced), "pull", "--ff-only"]


def test_repo_inside_a_subdirectory_is_refused_with_exit_4(env):
    r = env.run("--check", repo=env.machine / "skills" / "alpha")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "not the top of a git work tree" in r.stdout
    assert not env.state.exists()


def test_inherited_git_location_variables_are_not_passed_to_git(env):
    decoy = env.tmp / "decoy"
    sh("git", "init", "-q", str(decoy))
    env.publish()
    r = env.run("--check", "--json", extra_env={"GIT_DIR": str(decoy / ".git"), "GIT_WORK_TREE": str(decoy),
                                                "GIT_INDEX_FILE": str(decoy / "idx")})
    out = json.loads(r.stdout)
    assert r.returncode == 10, r.stdout + r.stderr
    assert out["head_before"] == env.first and out["behind"] == 1  # the machine clone, not the decoy


def test_untracked_file_the_pull_would_create_is_exit_2_not_3(env):
    (env.machine / "added.txt").write_text("mine\n")
    env.publish({"added.txt": "theirs\n"})
    r = env.run()
    assert r.returncode == 2, r.stdout + r.stderr
    assert "added.txt" in r.stdout
    assert env.head(env.machine) == env.first
    assert (env.machine / "added.txt").read_text() == "mine\n"
    assert not env.state.exists()
    r = env.run("--check")
    assert r.returncode == 10 and "would refuse (exit 2)" in r.stdout


def test_pull_failure_code_maps_an_overwrite_refusal_to_dirty():
    mod = load_module()
    assert mod.pull_failure_code("error: The following untracked working tree files would be overwritten by merge:") == 2
    assert mod.pull_failure_code("error: Your local changes to the following files would be overwritten by merge:") == 2
    assert mod.pull_failure_code("fatal: Not possible to fast-forward, aborting.") == 3


def test_unwritable_state_file_is_exit_4_not_a_traceback(env):
    env.state.mkdir(parents=True)  # --state names a directory
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "cannot write the state file" in r.stdout and "Traceback" not in r.stderr
    assert sorted(p.name for p in env.state.parent.iterdir()) == ["applied"]  # temp file cleaned up
    out = json.loads(env.run("--json", state=env.state).stdout)
    assert out["exit"] == 4 and out["error"].startswith("cannot write the state file")


def test_repo_bin_skill_everywhere_is_preferred_over_path(env):
    own = env.machine / "bin" / "skill-everywhere"
    own.parent.mkdir()
    own.write_text(FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "json.dumps(sys.argv[1:])", 'json.dumps(["repo-copy"] + sys.argv[1:])'))
    own.chmod(own.stat().st_mode | stat.S_IXUSR)
    r = env.run("--check", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["skills"]["script"] == str(own)
    assert env.calls() == [["repo-copy", "--check", "alpha"]]  # the fake on PATH was not used
