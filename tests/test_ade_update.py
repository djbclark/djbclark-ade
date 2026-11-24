"""bin/ade-update pulls, relinks, checks symlinks and prints the changelog delta (2026-10-20).

Every test builds a real git repo pair in tmp_path: a bare `origin`, a `seed` clone that publishes
commits, and the `machine` clone ade-update runs on. skill-everywhere is a fake beside the copy of
ade-update the tests run (the trusted helper) that records its argv and answers from a JSON file, so no
real TUI directory is touched. HOME is tmp_path/home, and
SKILL_EVERYWHERE_ADE names the `machine` clone's skills/ so that clone is the canonical skills home (the
only checkout whose skill links ade-update may change).
"""
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-update"
REAL_SE = SCRIPT.parent / "skill-everywhere"
FOLD = SCRIPT.parent / "changelog-fold"

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
# table["__paseo__"] = [[tui, state], ...]: skill-everywhere's paseo step (2026-11-21): --check prints one
# `error: paseo skill is <state> on <tui> (<path>): <hint>` stderr line per gap and exits 1; any link call makes the
# hermes link (the fixable gap states vanish). `paseo` as a name is the step alone: no `== paseo` header.
gaps = table.get("__paseo__", [])
if check:
    for n in names:
        if n == "paseo":
            continue  # like the real script: no header, no rows for the pseudo-name
        print("== " + n)
        for tui, st in table.get(n, [["claude", "linked"]]):
            print("  %-13s %s" % (tui, st))
    print("== end")
    for tui, st in gaps:
        sys.stderr.write("error: paseo skill is %s on %s (/h/%s/paseo): hint\\n" % (st, tui, tui))
    sys.exit(1 if gaps else 0)
else:
    for n in names:
        if n == "paseo":
            continue
        table[n] = [[t, "linked" if s in ("missing",) or s.startswith(("dangling", "chained")) else s]
                    for t, s in table.get(n, [])]
        print("== " + n)
    table["__paseo__"] = [[t, s] for t, s in gaps if t != "hermes" or not (s == "missing" or s.startswith(("dangling", "chained")))]
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


def seed_paseo_skill(home):
    """A healthy Paseo skill state in a fake HOME: the real skill-everywhere (run by the in-process tests) fails
    `--check` when `paseo` is missing from a live target (2026-11-21)."""
    paseo = home / ".agents" / "skills" / "paseo"
    paseo.mkdir(parents=True)
    (paseo / "SKILL.md").write_text("---\nname: paseo\n---\n")
    for d in (home / ".claude" / "skills", home / ".local" / "share" / "skill-everywhere" / "skills"):
        d.mkdir(parents=True)
        (d / "paseo").symlink_to(paseo, target_is_directory=True)


class Env:
    def __init__(self, tmp):
        self.tmp = tmp
        self.origin, self.seed, self.machine = tmp / "origin.git", tmp / "seed", tmp / "machine"
        self.home, self.state = tmp / "home", tmp / "state" / "applied"
        # ade-update runs from a copy in `trusted/bin`, where the fake skill-everywhere is its sibling (the trusted
        # helper); `lone/bin` holds a copy with no sibling. The real bin/ is never run on these fixture repos.
        self.trusted, self.lone = (tmp / "trusted").resolve(), (tmp / "lone").resolve()
        self.bin, self.se_state, self.se_log = self.trusted / "bin", tmp / "se-state.json", tmp / "se.log"
        self.home.mkdir()
        self.bin.mkdir(parents=True)
        (self.lone / "bin").mkdir(parents=True)
        for d in (self.bin, self.lone / "bin"):
            shutil.copy(SCRIPT, d / "ade-update")
            shutil.copy(FOLD, d / "changelog-fold")  # the sibling that parses changelog.d fragments
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

    def run(self, *flags, repo=None, state=None, extra_env=None, script=None):
        env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                   FAKE_SE_STATE=str(self.se_state), FAKE_SE_LOG=str(self.se_log),
                   SKILL_EVERYWHERE_ADE=str(self.machine / "skills"))
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, str(script or self.bin / "ade-update"), "--repo", str(repo or self.machine),
                            "--state", str(state or self.state), *flags], capture_output=True, text=True, env=env)
        return r


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
    assert env.state.read_text().split()[0] == env.first
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
    assert env.state.read_text().split()[0] == new
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
    assert problem["fix"].startswith("mkdir -p ") and " && ln -sfn " in problem["fix"]  # no ~/.claude/commands yet
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
    assert env.state.read_text().split()[0] == env.first


def test_a_missing_hermes_paseo_link_is_exit_10_on_check_and_linked_on_apply(env):  # PR 871 adversary L1
    env.skills({"alpha": [["claude", "linked"]], "__paseo__": [["hermes", "missing"]]})
    r = env.run("--check")
    assert r.returncode == 10, r.stdout + r.stderr  # a link gap, not exit 4 "helper failed"
    assert "paseo: hermes missing" in r.stdout and "would run:" in r.stdout and "skill-everywhere paseo" in r.stdout
    assert env.calls() == [["--check", "alpha"]] and not env.state.exists()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.calls()[2:] == [["paseo"], ["--check", "paseo"]]
    assert "linked now: paseo" in r.stdout
    assert env.state.read_text().split()[0] == env.first


def test_paseo_missing_from_a_target_paseo_syncs_is_a_stuck_row_exit_10_never_a_helper_failure(env):
    env.skills({"alpha": [["claude", "linked"]], "__paseo__": [["claude", "missing"], ["codex", "missing"]]})
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert "paseo/claude is not synced by Paseo: missing" in r.stdout
    assert "paseo/codex is not synced by Paseo: missing" in r.stdout
    assert "enable Paseo's skill sync" in r.stdout and "docs/skill-everywhere.md section 3a" in r.stdout
    assert ["paseo"] not in env.calls()  # nothing of ours repairs it
    assert "helper failed" not in r.stdout and "--check failed" not in r.stdout
    assert not env.state.exists()


def test_a_paseo_gap_line_does_not_hide_a_real_helper_failure(env):
    plant_helper(env.trusted, FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "sys.exit(1 if gaps else 0)", """sys.stderr.write("bash: boom\\n")
    sys.exit(1)"""))
    env.skills({"alpha": [["claude", "linked"]], "__paseo__": [["hermes", "missing"]]})
    r = env.run("--check")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "bash: boom" in r.stdout


def test_linked_now_names_paseo_when_a_stuck_row_of_it_remains(env):  # PR 874 adversary low
    env.skills({"alpha": [["claude", "linked"]], "__paseo__": [["hermes", "missing"], ["claude", "missing"]]})
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr  # the claude row is Paseo's to sync: still stuck
    assert "linked now: paseo" in r.stdout and "linked now: none" not in r.stdout


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
    out = json.loads(env.run("--check", "--json", repo=other).stdout)
    assert out["skills"]["link_mode"] == "report-only"
    assert out["notes"] and "not verified" in out["notes"][0]  # adversary R2-1: never a bare "current"
    assert "result: current (report-only" in r.stdout
    assert all("fix" not in p for p in out["claude_links"]["problems"])  # adversary R2-3: no repointing hint in JSON
    # the canonical clone, same table, does link
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert ["alpha"] in env.calls() and "report-only" not in r.stdout


def test_a_non_canonical_repo_never_writes_the_shared_state_record(env, monkeypatch, capsys):
    """Codex pass 11 on PR 20: `--repo <other clone>` without --state wrote that clone's HEAD into the canonical
    record, so the next canonical run saw base == target and hid (or replayed) changelog entries."""
    seed_paseo_skill(env.home)
    mod = load_module()
    other = clone(env, "other")
    for k, v in dict(HOME=str(env.home), PATH=f"{env.bin}{os.pathsep}{os.environ['PATH']}",
                     FAKE_SE_STATE=str(env.se_state), FAKE_SE_LOG=str(env.se_log),
                     SKILL_EVERYWHERE_ADE=str(env.machine / "skills")).items():
        monkeypatch.setenv(k, v)
    shared = env.home / ".local" / "state" / "ade" / "applied"
    rc = mod.main(["--repo", str(other), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, out
    assert not shared.exists()  # the canonical checkout's record is untouched
    own = Path(out["state_file"])
    assert own.parent == shared.parent and own.name.startswith("applied-") and own != shared
    assert own.read_text().split()[0] == sh("git", "-C", str(other), "rev-parse", "HEAD")
    assert mod.default_state(other) == str(own) and mod.default_state(env.machine) == str(shared)
    # the same clone gets the same record next time; a different clone gets another
    assert mod.default_state(clone(env, "third")) != str(own)


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
    for name in ("-dash", ".hidden", "sp ace", "beta\n"):
        (env.machine / "skills" / name).mkdir()
        (env.machine / "skills" / name / "SKILL.md").write_text("x\n")
    names, skipped = mod.skill_names(env.machine)
    assert names == ["alpha"] and skipped == ["--remove", "-dash", ".hidden", "beta\n", "sp ace"]  # R2-2: fullmatch
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
    assert shlex.split(line.split("would run: ")[1]) == ["git", "-C", str(spaced), "merge", "--ff-only",
                                                         env.head(env.seed)]


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


def _refused_and_untouched(env, path, content, blocked_path):
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 10 and out["blocked_by"] == [blocked_path], r.stdout + r.stderr
    r = env.run()
    assert r.returncode == 2, r.stdout + r.stderr
    assert blocked_path in r.stdout
    assert env.head(env.machine) == env.first
    assert (env.machine / path).read_text() == content
    assert not env.state.exists()


def test_ignored_file_the_pull_would_create_is_exit_2_and_kept(env):  # Codex P1 on d3ece30
    (env.machine / ".git" / "info" / "exclude").write_text("local.txt\n")
    (env.machine / "local.txt").write_text("mine\n")
    env.publish({"local.txt": "theirs\n"})
    _refused_and_untouched(env, "local.txt", "mine\n", "local.txt")


def test_a_file_inside_an_ignored_directory_blocks_paths_under_the_matching_ignored_dir(env):  # Codex P1 on d3ece30; PR 20 LOW b
    # `--ignored=matching` reports one `!! build/` row (not every file under it). Any upstream path under
    # that directory collides with local `build` (ancestor), including a sibling the pull would add.
    (env.machine / ".git" / "info" / "exclude").write_text("build/\n")
    (env.machine / "build").mkdir()
    (env.machine / "build" / "out.bin").write_text("mine\n")
    env.publish({"build/out.bin": "theirs\n", "build/x": "theirs\n"})
    r = env.run("--check", "--json")
    assert json.loads(r.stdout)["blocked_by"] == ["build/out.bin", "build/x"], r.stdout + r.stderr
    r = env.run()
    assert r.returncode == 2 and "build/out.bin" in r.stdout and "build/x" in r.stdout, r.stdout + r.stderr
    assert env.head(env.machine) == env.first
    assert (env.machine / "build" / "out.bin").read_text() == "mine\n"


def test_an_ignored_file_the_pull_does_not_touch_does_not_block(env):
    (env.machine / ".git" / "info" / "exclude").write_text("scratch/\n")
    (env.machine / "scratch").mkdir()
    (env.machine / "scratch" / "a").write_text("mine\n")
    new = env.publish()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.head(env.machine) == new


def test_a_local_file_where_the_pull_needs_a_directory_is_exit_2(env):  # Codex P2 on d3ece30
    (env.machine / "foo").write_text("mine\n")
    env.publish({"foo/bar": "theirs\n"})
    _refused_and_untouched(env, "foo", "mine\n", "foo/bar")
    assert "foo/bar (local foo)" in env.run().stdout


def test_a_local_directory_where_the_pull_needs_a_file_is_exit_2(env):  # Codex P2 on d3ece30
    (env.machine / "foo").mkdir()
    (env.machine / "foo" / "x").write_text("mine\n")
    env.publish({"foo": "theirs\n"})
    _refused_and_untouched(env, "foo/x", "mine\n", "foo")
    assert "foo (local foo/x)" in env.run().stdout


def test_a_changed_path_with_leading_whitespace_still_collides(env):  # Codex P2 on a1f7ffd
    # git_out() stripped the whole -z output, so " victim" lost its space before the NUL split and no longer
    # matched the porcelain path of the ignored local file.
    (env.machine / ".git" / "info" / "exclude").write_text("/ victim\n")
    (env.machine / " victim").write_text("mine\n")
    env.publish({" victim": "theirs\n"})
    r = env.run("--check", "--json")
    assert json.loads(r.stdout)["blocked_by"] == [" victim"], r.stdout + r.stderr
    r = env.run()
    assert r.returncode == 2, r.stdout + r.stderr
    assert env.head(env.machine) == env.first
    assert (env.machine / " victim").read_text() == "mine\n"


def test_a_blocked_check_does_not_print_a_would_run_line(env):  # Codex P2 on a1f7ffd
    (env.machine / "added.txt").write_text("mine\n")
    env.publish({"added.txt": "theirs\n"})
    r = env.run("--check")
    assert r.returncode == 10 and "would refuse (exit 2)" in r.stdout, r.stdout + r.stderr
    assert "would run: git" not in r.stdout


def test_apply_fast_forwards_to_the_commit_it_checked_not_to_a_newer_upstream(env):  # Codex P1 on a1f7ffd
    # A `git` shim first on PATH pushes commit B to origin the moment the apply reaches its merge/pull step,
    # i.e. after the tool's own fetch and collision check at A. The old `git pull --ff-only` fetched B and
    # overwrote the ignored local file B adds; the apply must stay at A and leave the file alone.
    real = shutil.which("git")
    (env.machine / ".git" / "info" / "exclude").write_text("late.txt\n")
    (env.machine / "late.txt").write_text("mine\n")
    a = env.publish()
    commit(env.seed, "third", {"late.txt": "theirs\n"})
    shim = env.bin / "git"
    shim.write_text(f"""#!/bin/sh
for a in "$@"; do
  case "$a" in
    merge|pull)
      if [ ! -e "{env.tmp}/pushed" ]; then
        touch "{env.tmp}/pushed"
        {real} -C "{env.seed}" push -q origin master || exit 99
      fi;;
  esac
done
exec {real} "$@"
""")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    r = env.run()
    assert (env.tmp / "pushed").exists(), "the shim never saw the merge step"
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.head(env.machine) == a
    assert (env.machine / "late.txt").read_text() == "mine\n"
    # the next run fetches B, re-checks it, and refuses
    r = env.run()
    assert r.returncode == 2 and "late.txt" in r.stdout, r.stdout + r.stderr
    assert env.head(env.machine) == a
    assert (env.machine / "late.txt").read_text() == "mine\n"


def test_collides_covers_equal_ancestor_and_descendant_paths():
    mod = load_module()
    assert mod.collides({"a", "b/c", "d/e/f", "g", "h/i"}, {"a", "b", "d/", "g/x", "z"}) == {
        "a": "a", "b/c": "b", "d/e/f": "d", "g": "g/x"}
    assert mod.collides({"a"}, set()) == {}


def test_collides_casefolds_when_ignorecase():  # PR 20 LOW a
    mod = load_module()
    assert mod.collides({"notes.txt"}, {"Notes.txt"}, ignorecase=True) == {"notes.txt": "Notes.txt"}
    assert mod.collides({"notes.txt"}, {"Notes.txt"}, ignorecase=False) == {}
    assert mod.collides({"Foo/Bar"}, {"foo"}, ignorecase=True) == {"Foo/Bar": "foo"}
    assert mod.collides({"readme"}, {"README/x"}, ignorecase=True) == {"readme": "README/x"}


def test_case_only_collision_blocks_check_when_core_ignorecase(env):  # PR 20 LOW a
    # Upstream adds foo.txt while a local untracked Foo.txt exists. With core.ignorecase=true,
    # `--check` must refuse (apply on a case-insensitive volume would too). A same-path edit of an
    # already-tracked name is invisible to `git status` under ignorecase on a case-sensitive FS.
    sh("git", "config", "core.ignorecase", "true", cwd=env.machine)
    (env.machine / "Foo.txt").write_text("mine\n")
    env.publish({"foo.txt": "theirs\n"})
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 10, r.stdout + r.stderr
    assert out["ignorecase"] is True
    assert out["blocked_by"] == ["foo.txt"], r.stdout + r.stderr
    assert "would refuse (exit 2)" in env.run("--check").stdout
    assert "would run: git" not in env.run("--check").stdout
    r = env.run()
    assert r.returncode == 2 and "foo.txt" in r.stdout, r.stdout + r.stderr
    assert env.head(env.machine) == env.first


def test_run_replaces_non_utf8_bytes_instead_of_crashing(tmp_path):  # PR 20 LOW d
    mod = load_module()
    bad = tmp_path / "emit-bad"
    bad.write_bytes(b"#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(bytes([0xff, 0xfe]) + b'-ok\\n')\n")
    bad.chmod(bad.stat().st_mode | stat.S_IXUSR)
    rc, out, err = mod.run([str(bad)])
    assert rc == 0 and err == ""
    assert out == "\ufffd\ufffd-ok\n"
    assert mod.show_path("a\nb\x00c") == "a?b?c"


def test_pull_failure_code_maps_an_overwrite_refusal_to_dirty():
    mod = load_module()
    assert mod.pull_failure_code("error: The following untracked working tree files would be overwritten by merge:") == 2
    assert mod.pull_failure_code("error: Your local changes to the following files would be overwritten by merge:") == 2
    assert mod.pull_failure_code("fatal: Not possible to fast-forward, aborting.") == 3
    assert mod.pull_failure_code("hint: Diverging branches can't be fast-forwarded, you need to either:") == 3
    assert mod.pull_failure_code("fatal: Cannot fast-forward your working tree.") == 3
    # Codex on 5e2ab58: pull has its own fetch phase; a transport failure there is not a diverged branch
    assert mod.pull_failure_code("fatal: unable to access 'https://x/r.git/': Could not resolve host: x") == 4
    assert mod.pull_failure_code("fatal: Authentication failed for 'https://x/r.git/'") == 4
    assert mod.pull_failure_code("timed out after 300s: git -C r pull --ff-only") == 4
    assert mod.pull_failure_code("") == 4


def test_unwritable_state_file_is_exit_4_not_a_traceback(env):
    env.state.mkdir(parents=True)  # --state names a directory
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "cannot write the state file" in r.stdout and "Traceback" not in r.stderr
    assert sorted(p.name for p in env.state.parent.iterdir()) == ["applied"]  # temp file cleaned up
    out = json.loads(env.run("--json", state=env.state).stdout)
    assert out["exit"] == 4 and out["error"].startswith("cannot write the state file")


def test_the_helper_is_the_sibling_of_the_running_ade_update(env):
    own = env.machine / "bin" / "skill-everywhere"
    own.parent.mkdir()
    own.write_text(FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "json.dumps(sys.argv[1:])", 'json.dumps(["repo-copy"] + sys.argv[1:])'))
    own.chmod(own.stat().st_mode | stat.S_IXUSR)
    r = env.run("--check", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["skills"]["script"] == str(env.bin / "skill-everywhere")
    assert env.calls() == [["--check", "alpha"]]  # neither the canonical checkout's copy nor PATH's was used
    # no sibling: the canonical checkout's own bin/ comes next, and it outranks PATH
    r = env.run("--check", "--json", script=env.lone / "bin" / "ade-update")
    assert json.loads(r.stdout)["skills"]["script"] == str(own)
    assert env.calls()[-1] == ["repo-copy", "--check", "alpha"]
    # and PATH after that, canonical only
    own.unlink()
    r = env.run("--check", "--json", script=env.lone / "bin" / "ade-update")
    assert json.loads(r.stdout)["skills"]["script"] == str(env.bin / "skill-everywhere")


# --- Codex review of 5e2ab58 (2026-10-20) -------------------------------------------------------

def plant_helper(repo, body):
    own = Path(repo) / "bin" / "skill-everywhere"
    own.parent.mkdir(exist_ok=True)
    own.write_text(body)
    own.chmod(own.stat().st_mode | stat.S_IXUSR)
    return own


def test_check_never_executes_a_non_canonical_checkouts_own_helper(env):
    other = clone(env, "other")
    marker = env.tmp / "pwned"
    plant_helper(other, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 0\n")
    r = env.run("--check", "--json", repo=other)
    out = json.loads(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists()
    assert out["skills"]["script"] == str(env.bin / "skill-everywhere")  # the sibling of the running ade-update
    assert env.calls() == [["--check", "alpha"]]
    # a copy planted in the canonical checkout does not displace the sibling, and the planted one still never runs
    plant_helper(env.machine, FAKE_SKILL_EVERYWHERE.format(python=sys.executable))
    out = json.loads(env.run("--check", "--json", repo=other).stdout)
    assert out["skills"]["script"] == str(env.bin / "skill-everywhere") and not marker.exists()


def test_skill_everywhere_ade_never_chooses_the_helper_that_runs(env):  # adversary R4-1
    other = clone(env, "other")
    marker = env.tmp / "pwned"
    plant_helper(other, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 0\n")
    # the variable names the untrusted checkout's skills, and --repo is the (otherwise canonical) machine clone
    r = env.run("--check", "--json", extra_env={"SKILL_EVERYWHERE_ADE": str(other / "skills")})
    out = json.loads(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and out["skills"]["link_mode"] == "report-only"
    assert out["skills"]["script"] == str(env.bin / "skill-everywhere")
    assert env.calls() == [["--check", "alpha"]]


def test_a_path_entry_or_sibling_inside_a_non_canonical_checkout_is_never_run(env):  # adversary R4-2
    other = clone(env, "other")
    marker = env.tmp / "pwned"
    plant_helper(other, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 0\n")
    lone = env.lone / "bin" / "ade-update"
    # no sibling, no canonical helper, PATH names the untrusted checkout's bin/
    path = f"{other / 'bin'}{os.pathsep}/usr/bin{os.pathsep}/bin"
    r = env.run("--check", "--json", repo=other, extra_env={"PATH": path}, script=lone)
    out = json.loads(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and env.calls() == []
    assert out["skills"]["script"] is None and out["skills"]["link_mode"] == "skipped"
    assert "no skill-everywhere exists beside this ade-update outside it" in env.run(
        "--check", repo=other, extra_env={"PATH": path}, script=lone).stdout
    # an ade-update run from inside the untrusted checkout has its sibling there: not run either
    shutil.copy(SCRIPT, other / "bin" / "ade-update")
    r = env.run("--check", "--json", repo=other, script=other / "bin" / "ade-update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and json.loads(r.stdout)["skills"]["script"] is None


def test_non_canonical_checkout_with_no_trusted_helper_skips_the_skill_step(env):
    other = clone(env, "other")
    marker = env.tmp / "pwned"
    plant_helper(other, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexit 0\n")
    bare = {"PATH": "/usr/bin:/bin"}
    lone = env.lone / "bin" / "ade-update"  # a copy with no sibling helper
    note = "skill-everywhere: no trusted helper (none beside ade-update outside this checkout)"
    r = env.run("--check", repo=other, extra_env=bare, script=lone)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists() and env.calls() == []
    assert "no skill-everywhere exists beside this ade-update" in r.stdout
    assert note in r.stdout
    out = json.loads(env.run("--check", "--json", repo=other, extra_env=bare, script=lone).stdout)
    assert out["problems"] == [] and out["skills"]["link_mode"] == "skipped" and out["skills"]["script"] is None
    assert note in out["notes"]
    r = env.run(repo=other, extra_env=bare, script=lone)  # apply: nothing unresolved, so the state is still recorded
    assert r.returncode == 0 and env.state.read_text().split()[0] == env.first and not marker.exists()
    # the canonical checkout with no helper anywhere is a dependency failure (exit 4 like every other
    # skill-everywhere failure, never 10 which means link drift; Codex on PR 20), no state
    env.state.unlink()
    r = env.run(extra_env=bare, script=lone)
    assert r.returncode == 4 and "skill-everywhere not found" in r.stdout and not env.state.exists()
    out = json.loads(env.run("--json", extra_env=bare, script=lone).stdout)
    assert out["exit"] == 4 and "skill-everywhere not found" in out["error"] and not env.state.exists()


def test_a_crashing_skill_everywhere_check_is_exit_4_and_records_no_state(env):
    plant_helper(env.trusted, "#!/bin/sh\necho '== alpha'\necho '  claude        linked'\n"
                              "echo 'greadlink: command not found' >&2\nexit 127\n")
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "--check failed (rc=127)" in r.stdout and "greadlink: command not found" in r.stdout
    assert not env.state.exists()
    out = json.loads(env.run("--json").stdout)
    assert out["exit"] == 4 and "rc=127" in out["error"]


def test_a_skill_missing_from_the_check_output_is_exit_4(env):
    env.publish({"skills/beta/SKILL.md": "---\nname: beta\n---\n"})
    plant_helper(env.trusted, "#!/bin/sh\necho '== alpha'\necho '  claude        linked'\necho '== end'\nexit 0\n")
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "returned no result for: beta" in r.stdout
    assert not env.state.exists()


def test_the_scripts_own_warning_exit_is_not_a_crash(env):
    plant_helper(env.trusted, "#!/bin/sh\necho '== alpha'\necho '  claude        linked'\necho '== end'\n"
                              "echo 'warning: codex global instructions dangling: x -> y' >&2\nexit 1\n")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert env.state.read_text().split()[0] == env.first


# --- adversary round 4 and Codex P1 on 67bed7e (2026-10-20) ---------------------------------------

def test_a_header_without_rows_is_exit_4_even_with_the_warning_exit(env):  # adversary R4-3
    warn = "echo 'warning: codex global instructions dangling: x -> y' >&2\n"
    for tail in ("exit 1\n", "exit 0\n"):
        plant_helper(env.trusted, "#!/bin/sh\n" + warn + "echo '== alpha'\necho '== end'\n" + tail)
        r = env.run()
        assert r.returncode == 4, r.stdout + r.stderr
        assert "returned no rows for: alpha" in r.stdout
        assert not env.state.exists()
    out = json.loads(env.run("--json").stdout)
    assert out["exit"] == 4 and "no rows for: alpha" in out["error"]


def test_a_failing_link_call_is_exit_4_and_records_no_state(env):  # Codex P1 on 67bed7e
    env.skills({"alpha": [["claude", "missing"]]})
    made = env.tmp / "made"
    plant_helper(env.trusted, FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "sys.exit(0)", f"""if not check:
    open({str(made)!r}, "w").close()  # the link is made, then the Hermes nudge fails
    sys.stderr.write("ghead: command not found\\n")
    sys.exit(127)
sys.exit(0)"""))
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "failed (rc=127)" in r.stdout and "ghead: command not found" in r.stdout
    assert "links may be partly made; rerun after fixing" in r.stdout
    assert made.exists() and not env.state.exists()
    env.skills({"alpha": [["claude", "missing"]]})  # the fake's link call rewrote its table
    out = json.loads(env.run("--json").stdout)
    assert out["exit"] == 4 and "rc=127" in out["error"]


def test_pull_failure_code_ignores_text_the_remote_sends():  # adversary R4-4
    mod = load_module()
    assert mod.pull_failure_code("remote: fatal: Not possible to fast-forward, aborting.\n"
                                 "fatal: unable to access 'https://x/r.git/': Could not resolve host: x") == 4
    assert mod.pull_failure_code("remote: error: would be overwritten\nfatal: Authentication failed") == 4
    assert mod.pull_failure_code("remote: hello\nfatal: Not possible to fast-forward, aborting.") == 3


# --- adversary round 5 (head 6e707c6) ---------------------------------------------------------------

def test_a_left_alone_link_is_exit_10_naming_the_stuck_row_on_the_first_apply(env):  # adversary R5-1 (probe Q6)
    env.skills({"alpha": [["claude", "real dir/file (not ours)"], ["cline", "missing"]]})
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert "alpha/claude is real dir/file (not ours): skill-everywhere leaves it alone" in r.stdout
    assert "failed (rc" not in r.stdout and not env.state.exists()
    assert env.calls() == [["--check", "alpha"], ["alpha"], ["--check", "alpha"]]
    # the stuck row is what remains; the fixable one was linked
    assert json.loads(env.run("--check", "--json").stdout)["skills"]["missing"] == [
        {"skill": "alpha", "tui": "claude", "state": "real dir/file (not ours)"}]


def test_link_left_alone_accepts_only_the_scripts_own_exit_1_wording():
    mod = load_module()
    ok = ("", "warning: x\n", "error: no SKILL.md under a or b\nwarning: y\n")
    assert all(mod.link_left_alone(1, e) for e in ok)
    assert not mod.link_left_alone(127, "") and not mod.link_left_alone(2, "")
    assert not mod.link_left_alone(1, "Traceback (most recent call last):\n")
    assert not mod.link_left_alone(1, "bash: line 3: ghead: command not found\n")
    assert not mod.link_left_alone(1, "warning: x\nbash: boom\n")


def test_a_failing_link_call_exit_4_names_the_stuck_rows_it_can_list(env):  # adversary R5-1
    env.skills({"alpha": [["claude", "real dir/file (not ours)"], ["cline", "missing"]]})
    plant_helper(env.trusted, FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "sys.exit(0)", """if not check:
    sys.stderr.write("bash: boom\\n")
    sys.exit(1)
sys.exit(0)"""))
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr  # rc 1, but the stderr is not the script's own wording
    assert "bash: boom" in r.stdout and "not in place: alpha/claude real dir/file (not ours);" in r.stdout  # cline was linked before the failure
    assert not env.state.exists()


def test_a_check_without_the_end_sentinel_is_exit_4_even_with_every_row(env):  # adversary R5-2
    plant_helper(env.trusted, "#!/bin/sh\necho '== alpha'\necho '  claude        linked'\nexit 0\n")
    r = env.run()
    assert r.returncode == 4, r.stdout + r.stderr
    assert "skill check incomplete" in r.stdout and "== end" in r.stdout
    assert not env.state.exists()
    # a crash after N rows of a later skill: the warning exit 1 and a good first skill must not hide it
    env.publish({"skills/beta/SKILL.md": "---\nname: beta\n---\n"})
    plant_helper(env.trusted, "#!/bin/sh\necho 'warning: codex global instructions dangling: x -> y' >&2\n"
                              "echo '== alpha'\necho '  claude        linked'\necho '== beta'\n"
                              "echo '  claude        linked'\nexit 1\n")
    r = env.run()
    assert r.returncode == 4 and "skill check incomplete" in r.stdout, r.stdout + r.stderr
    assert not env.state.exists()
    out = json.loads(env.run("--json").stdout)
    assert out["exit"] == 4 and out["error"].startswith("skill check incomplete")


def test_the_real_skill_everywhere_check_ends_with_the_sentinel(tmp_path):  # adversary R5-2
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    home = tmp_path / "home"
    home.mkdir()
    r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path,
                       env=dict(os.environ, HOME=str(home), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"),
                                CODEX_HOME=str(home / ".codex")))
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert r.stdout.splitlines()[0] == "== alpha" and r.stdout.splitlines()[-1] == "== end"


def test_the_real_paseo_gap_line_is_parsed_into_classified_rows(tmp_path):  # PR 871 adversary L1
    """The real script's `error: paseo skill is <state> on <tui> (<path>): <hint>` line, with Hermes installed and no
    Hermes link, must come back from check_skills as a fixable `paseo` row, not as a helper failure."""
    mod = load_module()
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    home, fake = tmp_path / "home", tmp_path / "fakebin"
    (home / ".agents" / "skills" / "paseo").mkdir(parents=True)
    (home / ".agents" / "skills" / "paseo" / "SKILL.md").write_text("---\nname: paseo\n---\n")
    fake.mkdir()
    (fake / "hermes").write_text("#!/bin/sh\nexit 0\n")
    (fake / "hermes").chmod(0o755)
    env = dict(HOME=str(home), CODEX_HOME=str(home / ".codex"), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"),
               SKILL_EVERYWHERE_ONLY="hermes", PATH=f"{fake}{os.pathsep}/usr/bin{os.pathsep}/bin")
    r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path, env=env)
    assert r.returncode == 1 and r.stderr.startswith("error: paseo skill is missing on hermes"), r.stdout + r.stderr
    rows, rest = mod.paseo_gap_rows(r.stderr)
    assert rows == [("paseo", "hermes", "missing")]
    assert all(ln.startswith("warning:") for ln in rest)  # the script's own unrelated Hermes config warning stays a warning
    assert mod.classify("missing") == "fixable"
    assert mod.paseo_gap_rows("error: paseo skill is missing on claude (/h/c/paseo): x\n")[0] == [
        ("paseo", "claude", "not synced by Paseo: missing")]
    assert mod.classify("not synced by Paseo: missing") == "stuck"
    assert mod.paseo_gap_rows("bash: boom\n") == ([], ["bash: boom"])


def test_the_grokbot_copy_target_rows_are_classified_not_stuck(tmp_path):  # adversary R15-1
    """Master's grokbot target prints `not installed (no <dir>)`, `missing (<dest>)`, `copied (<dest>)`,
    `stale copy (<dest>)`; every one used to fall through to stuck, so ade-update exited 10 on every run."""
    mod = load_module()
    assert mod.classify("not installed (no /home/x/agent-data/workflows)") == "ok"
    assert mod.classify("copied (/h/ade-alpha)") == "ok"
    assert mod.classify("missing (/h/ade-alpha)") == "fixable"
    assert mod.classify("stale copy (/h/ade-alpha)") == "fixable"
    assert mod.classify("real dir/file (not ours) (/h/ade-alpha)") == "stuck"
    assert mod.classify("copy of a removed skill (/h/ade-alpha)") == "stuck"
    assert mod.classify("linked") == "ok" and mod.classify("other link -> /x") == "stuck"
    # and the REAL script's rows, with and without the grokbot directory, all classify as ok or fixable
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    home = tmp_path / "home"
    home.mkdir()
    for with_dir in (False, True):
        if with_dir:
            (home / "agent-data" / "workflows").mkdir(parents=True)
        r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path,
                           env=dict(os.environ, HOME=str(home), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"),
                                    CODEX_HOME=str(home / ".codex")))
        rows = [row for row in mod.parse_skill_check(r.stdout) if row[1] == "grokbot"]
        assert rows and all(mod.classify(state) in ("ok", "fixable") for _, _, state in rows), r.stdout


def test_the_gemini_target_rows_are_parsed_and_classified_by_ade_update(tmp_path):
    """Real skill-everywhere --check rows for gemini parse cleanly and never emit spurious paseo gaps."""
    mod = load_module()
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    home, empty_bin = tmp_path / "home", tmp_path / "empty-bin"
    home.mkdir()
    empty_bin.mkdir()
    base_env = dict(os.environ, HOME=str(home), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"),
                    CODEX_HOME=str(home / ".codex"), SKILL_EVERYWHERE_ONLY="gemini",
                    SKILL_EVERYWHERE_BIN_DIR=str(empty_bin))

    # Absent ~/.gemini and no CLI: not installed -> ok.
    r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path, env=base_env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "== end"
    assert mod.parse_skill_check(r.stdout) == [("alpha", "gemini", "not installed")]
    assert mod.classify("not installed") == "ok"

    # Present ~/.gemini without link: missing -> fixable, no paseo stderr gap.
    (home / ".gemini").mkdir()
    r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path, env=base_env)
    assert r.returncode == 0 and r.stderr == "", r.stdout + r.stderr
    assert mod.parse_skill_check(r.stdout) == [("alpha", "gemini", "missing")]
    assert mod.classify("missing") == "fixable"

    # After linking: linked -> ok.
    link = subprocess.run([str(REAL_SE), "alpha"], capture_output=True, text=True, cwd=tmp_path, env=base_env)
    assert link.returncode == 0, link.stdout + link.stderr
    r = subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path, env=base_env)
    assert r.returncode == 0 and r.stderr == "", r.stdout + r.stderr
    assert mod.parse_skill_check(r.stdout) == [("alpha", "gemini", "linked")]
    assert mod.classify("linked") == "ok"


def test_an_inherited_skill_everywhere_only_never_narrows_the_helper_run(tmp_path, monkeypatch):  # adversary R15-2
    mod = load_module()
    monkeypatch.setenv("SKILL_EVERYWHERE_ONLY", "claude")
    env = mod.helper_env(tmp_path)
    assert "SKILL_EVERYWHERE_ONLY" not in env and env["SKILL_EVERYWHERE_ADE"] == str(tmp_path / "skills")
    # PR 20 LOW e: check_skills and link_skills must use helper_env (not a raw os.environ), so an inherited
    # ONLY never reaches the helper even when the R15-2 helper_env assertion alone would pass.
    seen = []

    def fake_run(argv, cwd=None, env=None, timeout=None):
        seen.append(env)
        if argv[1:2] == ["--check"]:
            return 0, "== alpha\n  claude        linked\n== end\n", ""
        return 0, "== alpha\n", ""

    monkeypatch.setattr(mod, "run", fake_run)
    script = str(tmp_path / "skill-everywhere")
    mod.check_skills(script, tmp_path, ["alpha"])
    mod.link_skills(script, tmp_path, ["alpha"])
    assert len(seen) == 2 and all("SKILL_EVERYWHERE_ONLY" not in e for e in seen)
    assert all(e["SKILL_EVERYWHERE_ADE"] == str(tmp_path / "skills") for e in seen)


def test_a_copy_outside_the_canonical_checkout_warns_on_stderr(env):  # adversary R5-3
    for flags in (("--check",), ()):
        r = env.run(*flags, script=env.lone / "bin" / "ade-update")
        assert f"ade-update runs from {env.lone}, not the canonical checkout {env.machine}" in r.stderr, r.stderr
        assert "its sibling skill-everywhere is the one that runs" in r.stderr
    r = env.run("--check", "--json", script=env.lone / "bin" / "ade-update")
    assert json.loads(r.stdout)["mode"] == "check"  # stdout stays one JSON object


def test_check_lists_the_claude_entries_upstream_adds_without_counting_them(env):  # Codex P2 on 68f5ef5
    env.publish({"claude/commands/newcmd.md": "new\n"})
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 10, r.stdout + r.stderr  # behind, nothing else
    assert out["claude_links"]["new_upstream"] == ["claude/commands/newcmd.md"]
    assert out["claude_links"]["problems"] == [] and out["problems"] == ["behind"]
    assert not (env.machine / "claude").exists()  # --check never touches the tree
    text = env.run("--check").stdout
    assert "new upstream ~/.claude links" in text and "claude/commands/newcmd.md" in text
    assert "~/.claude links (commands, agents, hooks): 0 ok, 0 not in place" in text


def test_no_new_upstream_claude_links_when_current(env):
    env.publish({"claude/commands/newcmd.md": "new\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    r = env.run("--check", "--json")
    out = json.loads(r.stdout)
    assert out["claude_links"]["new_upstream"] == []
    assert len(out["claude_links"]["problems"]) == 1  # a local file, so a real problem as before
    assert "new upstream ~/.claude links" not in env.run("--check").stdout


def test_apply_pulls_first_so_the_new_claude_entry_is_a_reported_problem_not_new_upstream(env):
    env.publish({"claude/commands/newcmd.md": "new\n"})
    r = env.run("--json")
    out = json.loads(r.stdout)
    assert out["claude_links"]["new_upstream"] == []
    (problem,) = out["claude_links"]["problems"]  # ade-update never links ~/.claude entries itself
    assert problem["path"] == str(env.home / ".claude" / "commands" / "newcmd.md") and problem["state"] == "missing"
    assert r.returncode == 10 and "~/.claude links" in out["problems"]


def test_symlink_fix_without_a_parent_directory_starts_with_mkdir(env):  # Codex P2 on ffad15a
    env.publish({"claude/commands/demo.md": "demo\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    (env.home / ".claude" / "commands").mkdir(parents=True)
    r = env.run("--check", "--json")
    (problem,) = json.loads(r.stdout)["claude_links"]["problems"]
    assert problem["fix"].startswith("ln -sfn ")  # the parent exists: no mkdir
    shutil.rmtree(env.home / ".claude" / "commands")
    r = env.run("--check", "--json")
    (problem,) = json.loads(r.stdout)["claude_links"]["problems"]
    assert problem["fix"] == shlex.join(["mkdir", "-p", str(env.home / ".claude" / "commands")]) + " && " + shlex.join(
        ["ln", "-sfn", str(env.machine / "claude" / "commands" / "demo.md"), str(env.home / ".claude" / "commands" / "demo.md")])


def test_a_fast_forward_that_landed_before_git_timed_out_still_counts_as_applied(env, monkeypatch, capsys):
    # Codex P2 on ffad15a: a post-merge hook longer than MERGE_TIMEOUT makes run() return 124 AFTER HEAD moved
    # (git ignores the hook's own exit status, so only a timeout can produce this). Run in-process so the merge
    # call can be wrapped: the real merge happens, then the wrapper reports the timeout.
    seed_paseo_skill(env.home)
    mod = load_module()
    real_run = mod.run

    def run_then_time_out(argv, **kw):
        rc, out, err = real_run(argv, **kw)
        if "merge" in argv:
            return 124, out, f"timed out after {kw.get('timeout')}s: {shlex.join(argv)}"
        return rc, out, err

    monkeypatch.setattr(mod, "run", run_then_time_out)
    for k, v in dict(HOME=str(env.home), PATH=f"{env.bin}{os.pathsep}{os.environ['PATH']}",
                     FAKE_SE_STATE=str(env.se_state), FAKE_SE_LOG=str(env.se_log),
                     SKILL_EVERYWHERE_ADE=str(env.machine / "skills")).items():
        monkeypatch.setenv(k, v)
    new = env.publish()
    rc = mod.main(["--repo", str(env.machine), "--state", str(env.state), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert env.head(env.machine) == new
    assert out["pulled"] is True and "timed out" in out["merge_warning"]
    assert "merge warning" in out["problems"]  # adv round 14: a timed-out hook may still run or hold index.lock
    assert out["head_after"] == new
    assert rc in (0, 10)


# --- Codex security review of PR 20, finding 4361214081 (2026-10-23): `cp -rL` of an untrusted skill ----------

def grokbot_home(tmp_path, with_copy):
    """A HOME holding Grok Bot's workflows dir; with_copy adds a managed (`.skill-everywhere`) ade-alpha copy."""
    home = tmp_path / "home"
    wf = home / "agent-data" / "workflows"
    wf.mkdir(parents=True)
    if with_copy:
        (wf / "ade-alpha").mkdir()
        (wf / "ade-alpha" / ".skill-everywhere").write_text("source=x\n")
        (wf / "ade-alpha" / "SKILL.md").write_text("old\n")
    return home


def run_real_se(tmp_path, home, *args, **extra):
    return subprocess.run([str(REAL_SE), *args, "alpha"], capture_output=True, text=True, cwd=tmp_path,
                          env=dict(os.environ, HOME=str(home), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"),
                                   CODEX_HOME=str(home / ".codex"), SKILL_EVERYWHERE_ONLY="grokbot", **extra))


@pytest.mark.parametrize("kind", ["file-outside", "dir-outside", "dangling", "dir-inside", "subdir-inside", "fifo-inside"])
@pytest.mark.parametrize("with_copy", [True, False])
def test_the_grokbot_copy_never_dereferences_a_symlink_that_leaves_the_skill(tmp_path, kind, with_copy):
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n")
    (src / "sub").mkdir()
    (src / "sub" / "f.txt").write_text("f\n")
    if kind == "file-outside":
        os.symlink(outside / "secret.txt", src / "leak")
    elif kind == "dir-outside":
        os.symlink(outside, src / "leak")
    elif kind == "dangling":
        os.symlink(tmp_path / "gone", src / "leak")
    elif kind == "dir-inside":  # a directory link can loop (`leak -> .`) or multiply content: refused even in-tree
        os.symlink(".", src / "leak")
    elif kind == "subdir-inside":  # a link to a real in-tree directory: inside the skill, but `-f` is false (not `.`)
        os.symlink("sub", src / "leak")
    else:
        os.mkfifo(src / "pipe")
        os.symlink("pipe", src / "leak")
    home = grokbot_home(tmp_path, with_copy)
    dest = home / "agent-data" / "workflows" / "ade-alpha"
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    r = run_real_se(tmp_path, home, "--check", TMPDIR=str(tmpdir))
    rows = [row for row in mod_rows(r.stdout) if row[1] == "grokbot"]
    assert rows and rows[0][2].startswith("unsafe source symlink"), r.stdout + r.stderr
    assert load_module().classify(rows[0][2]) == "stuck"
    assert list(tmpdir.iterdir()) == []  # nothing rendered into a temp dir, so nothing was dereferenced into it
    r = run_real_se(tmp_path, home, TMPDIR=str(tmpdir))  # link mode: refuses too, leaves the destination alone
    assert r.returncode == 1 and "unsafe source symlink" in r.stdout + r.stderr, r.stdout + r.stderr
    assert dest.exists() == with_copy
    if with_copy:
        assert (dest / "SKILL.md").read_text() == "old\n"
    assert not (home / "agent-data" / "workflows" / ".ade-alpha.new").exists()


def mod_rows(out):
    return load_module().parse_skill_check(out)


def test_the_grokbot_copy_still_renders_a_symlink_to_a_file_inside_the_skill(tmp_path):
    src = tmp_path / "skills" / "alpha"
    (src / "refs").mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    (src / "refs" / "real.md").write_text("real\n")
    os.symlink("refs/real.md", src / "alias.md")
    home = grokbot_home(tmp_path, with_copy=False)
    assert run_real_se(tmp_path, home).returncode == 0
    alias = home / "agent-data" / "workflows" / "ade-alpha" / "alias.md"
    assert alias.read_text() == "real\n" and not alias.is_symlink()
    assert run_real_se(tmp_path, home, "--check").stdout.count("copied") == 1


def test_a_report_only_ade_update_asks_the_helper_for_link_targets_only(tmp_path, monkeypatch):
    mod = load_module()
    monkeypatch.delenv("SKILL_EVERYWHERE_NO_COPY", raising=False)
    assert "SKILL_EVERYWHERE_NO_COPY" not in mod.helper_env(tmp_path)  # canonical checkout: the copy target stays
    assert mod.helper_env(tmp_path, copies=False)["SKILL_EVERYWHERE_NO_COPY"] == "1"


def test_an_inherited_no_copy_never_hides_the_grokbot_target_from_a_canonical_run(env, monkeypatch):
    """PR 37 landing round, LOW g: `helper_env` pops an inherited SKILL_EVERYWHERE_NO_COPY, so a canonical run (which
    must judge every target) never inherits the report-only setting; the report-only run still sets it itself."""
    mod = load_module()
    monkeypatch.setenv("SKILL_EVERYWHERE_NO_COPY", "1")  # inherited, not deleted first
    assert "SKILL_EVERYWHERE_NO_COPY" not in mod.helper_env(env.machine)
    assert mod.helper_env(env.machine, copies=False)["SKILL_EVERYWHERE_NO_COPY"] == "1"
    fake = env.bin / "skill-everywhere"
    fake.write_text(FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "json.dumps(sys.argv[1:])", 'json.dumps(sys.argv[1:] + [os.environ.get("SKILL_EVERYWHERE_NO_COPY", "")])'))
    env.se_log.write_text("")
    r = env.run("--check", repo=env.machine)
    assert r.returncode in (0, 10), r.stdout + r.stderr
    assert env.calls() == [["--check", "alpha", ""]]  # the helper under the canonical run never saw the inherited value


def test_the_helper_never_renders_a_copy_for_a_non_canonical_checkout(env):
    other = clone(env, "other")
    fake = env.bin / "skill-everywhere"
    fake.write_text(FAKE_SKILL_EVERYWHERE.format(python=sys.executable).replace(
        "json.dumps(sys.argv[1:])", 'json.dumps(sys.argv[1:] + [os.environ.get("SKILL_EVERYWHERE_NO_COPY", "")])'))
    for repo, expect in ((other, "1"), (env.machine, "")):
        env.se_log.write_text("")
        r = env.run("--check", repo=repo)
        assert r.returncode in (0, 10), r.stdout + r.stderr
        assert env.calls() == [["--check", "alpha", expect]]


def test_skill_everywhere_no_copy_skips_the_grokbot_target_only(tmp_path):
    src = tmp_path / "skills" / "alpha"
    src.mkdir(parents=True)
    (src / "SKILL.md").write_text("---\nname: alpha\n---\n")
    os.symlink(tmp_path, src / "leak")  # would be dereferenced by a copy
    home = grokbot_home(tmp_path, with_copy=True)
    env = dict(os.environ, HOME=str(home), SKILL_EVERYWHERE_ADE=str(tmp_path / "skills"), CODEX_HOME=str(home / ".codex"))
    env.pop("SKILL_EVERYWHERE_ONLY", None)
    check = lambda **x: subprocess.run([str(REAL_SE), "--check", "alpha"], capture_output=True, text=True, cwd=tmp_path,
                                       env=dict(env, **x))
    assert any(row[1] == "grokbot" for row in mod_rows(check().stdout))
    r = check(SKILL_EVERYWHERE_NO_COPY="1")
    rows = mod_rows(r.stdout)
    assert rows and not any(row[1] == "grokbot" for row in rows) and r.stdout.splitlines()[-1] == "== end", r.stdout


FRAG_A = "### Added\n\n- Fragment thing A (#10).\n\n### Fixed\n\n- Fragment fix A\n  wrapped (#11).\n"
FRAG_B = "### Changed\n\n- Fragment thing B (#12).\n"


def test_an_unfolded_fragment_is_listed_by_ade_update(env):  # adversary PR190 r1 A1
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-a.md": FRAG_A, "changelog.d/README.md": "readme, not a fragment\n"})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Unreleased (changelog.d) / Added" in r.stdout and "Fragment thing A (#10)." in r.stdout
    assert "Unreleased (changelog.d) / Fixed" in r.stdout and "Fragment fix A wrapped (#11)." in r.stdout
    assert "readme, not a fragment" not in r.stdout
    assert "3 entries" in r.stdout  # CHANGELOG's "Second thing" plus the two fragment entries


def test_a_fragment_already_seen_at_the_base_is_not_listed_again(env):
    env.state.parent.mkdir(parents=True)
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    env.run()  # applies and records a revision that already carries feat-a
    env.publish({"changelog.d/feat-b.md": FRAG_B}, message="third")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing B (#12)." in r.stdout and "Fragment thing A" not in r.stdout


def test_a_fragment_folded_between_base_and_target_shows_once(env):
    env.state.parent.mkdir(parents=True)
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    env.run()  # recorded with the fragment unfolded
    folded = CHANGELOG_V2.replace("- First thing (#1).", "- Fragment thing A (#10).\n- First thing (#1).")
    sh("git", "rm", "-q", "changelog.d/feat-a.md", cwd=env.seed)
    env.publish({"CHANGELOG.md": folded}, message="fold")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing A" not in r.stdout  # run 1 already showed it as a fragment; the fold is not news
    assert "0 entries" in r.stdout


def test_a_fragment_added_and_folded_between_base_and_target_shows_once_through_changelog(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    sh("git", "rm", "-q", "changelog.d/feat-a.md", cwd=env.seed)
    folded = CHANGELOG_V2.replace("- First thing (#1).", "- Fragment thing A (#10).\n- First thing (#1).")
    env.publish({"CHANGELOG.md": folded}, message="fold")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("Fragment thing A (#10).") == 1 and "changelog.d" not in r.stdout


def test_an_entry_in_both_a_fragment_and_changelog_at_the_target_shows_once(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    both = CHANGELOG_V2.replace("- First thing (#1).", "- Fragment thing B (#12).\n- First thing (#1).")
    env.publish({"CHANGELOG.md": both, "changelog.d/feat-b.md": FRAG_B})
    r = env.run()
    assert r.stdout.count("Fragment thing B (#12).") == 1


def test_every_unfolded_fragment_is_listed_when_no_revision_is_recorded(env):
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing A (#10)." in r.stdout


def test_an_invalid_fragment_is_skipped_not_a_crash(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/bad.md": "### Added\n\n- no number\n", "changelog.d/feat-b.md": FRAG_B})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing B (#12)." in r.stdout and "no number" not in r.stdout


def test_a_fragment_older_than_14_days_on_the_target_is_warned_about(env, monkeypatch):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2026-01-01T00:00:00Z")
    env.publish({"changelog.d/old-one.md": FRAG_A})
    monkeypatch.delenv("GIT_COMMITTER_DATE")
    env.publish({"changelog.d/new-one.md": FRAG_B}, message="third")
    r = env.run("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    stale = json.loads(r.stdout)["changelog"]["stale_fragments"]
    assert [s["name"] for s in stale] == ["old-one.md"] and stale[0]["age_days"] > 14
    text = env.run().stdout
    assert "older than 14 days" in text and "old-one.md" in text and "new-one.md (" not in text


def test_no_stale_warning_without_old_fragments(env):
    env.state.parent.mkdir(parents=True)
    env.publish({"changelog.d/new-one.md": FRAG_B})
    r = env.run()
    assert "older than" not in r.stdout


def test_fragments_are_not_listed_when_no_changelog_fold_sits_beside_ade_update(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    (env.bin / "changelog-fold").unlink()
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing B" not in r.stdout and "fragments not listed" in r.stdout


def test_a_changelog_fold_that_does_not_load_is_a_note_not_a_crash(env):  # adversary PR190 r2 A3
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    (env.bin / "changelog-fold").write_text("def broken(:\n")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Traceback" not in r.stderr and "does not load" in r.stdout
    assert "Second thing" in r.stdout and env.state.read_text().split()[0] == env.head(env.machine)  # the rest still ran


def test_fragment_names_with_a_space_a_newline_or_non_ascii_are_read_exactly(env):  # Codex P2 on 05beee8 (ls-tree -z)
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    names = {"feat with space.md": "Spaced", "feat\nnewline.md": "Newlined", "feat-\u00e9.md": "Accented"}
    env.publish({f"changelog.d/{n}": f"### Added\n\n- {w} fragment (#{20 + i}).\n" for i, (n, w) in enumerate(names.items())})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    for w in names.values():
        assert f"{w} fragment" in r.stdout, r.stdout
    assert "4 entries" in r.stdout  # CHANGELOG's "Second thing" plus the three fragments


def test_loading_changelog_fold_writes_no_bytecode_and_ignores_a_stale_cache(env):  # Codex P2 on 450a4ba, bin/ade-update:202-205 [INFERENCE: finding file absent]
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing B (#12)." in r.stdout
    assert not (env.bin / "__pycache__").exists()


def _poisoned_copy(env, where, marker):
    """A copy of ade-update with a changelog-fold beside it whose module body touches `marker`."""
    (where / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, where / "bin" / "ade-update")
    (where / "bin" / "changelog-fold").write_text(f"open({str(marker)!r}, 'w').close()\n" + FOLD.read_text())
    return where / "bin" / "ade-update"


def test_a_modified_changelog_fold_inside_a_non_canonical_checkout_is_never_executed(env):  # Codex P1 on 3bd729f
    other = clone(env, "other")
    marker = env.tmp / "pwned"
    script = _poisoned_copy(env, other, marker)
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    sh("git", "-C", str(other), "pull", "-q")
    r = env.run("--check", repo=other, script=script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not marker.exists()
    assert "not the canonical checkout; not executed" in r.stdout and "Fragment thing B" not in r.stdout


def test_nothing_is_executed_before_the_repository_is_validated(env):
    notrepo = env.tmp / "notrepo"
    marker = env.tmp / "pwned"
    script = _poisoned_copy(env, notrepo, marker)
    r = env.run("--check", repo=notrepo, script=script)
    assert r.returncode == 4 and not marker.exists()


def test_the_canonical_checkouts_own_changelog_fold_still_loads(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    marker = env.tmp / "ran"
    script = _poisoned_copy(env, env.machine, marker)  # inside the canonical checkout: already-running code
    r = env.run(script=script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.exists() and "Fragment thing B (#12)." in r.stdout


def test_an_install_upgraded_by_the_fragment_unaware_updater_still_gets_its_fragments(env):  # Codex P2 on 3bd729f
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    sh("git", "pull", "-q", cwd=env.machine)
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.head(env.machine) + "\n")  # what the old updater records: the new head, no marker
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fragment thing A (#10)." in r.stdout and "already at the recorded" not in r.stdout
    assert env.state.read_text().split()[1:] == ["fragments-v1"]
    r = env.run()  # the marked record is believed from now on
    assert "Fragment thing A" not in r.stdout and "already at the recorded" in r.stdout


def test_an_unmarked_record_does_not_suppress_the_fold_of_a_fragment_it_never_showed(env):
    env.publish({"changelog.d/feat-a.md": FRAG_A})
    sh("git", "pull", "-q", cwd=env.machine)
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.head(env.machine) + "\n")
    sh("git", "rm", "-q", "changelog.d/feat-a.md", cwd=env.seed)
    env.publish({"CHANGELOG.md": CHANGELOG_V2.replace("- First thing (#1).", "- Fragment thing A (#10).\n- First thing (#1).")}, message="fold")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("Fragment thing A (#10).") == 1  # never seen as a fragment, so the fold is its first showing


def test_a_run_that_could_not_list_fragments_records_no_marker(env):
    env.state.parent.mkdir(parents=True)
    env.state.write_text(env.first + "\n")
    env.publish({"changelog.d/feat-b.md": FRAG_B})
    (env.bin / "changelog-fold").unlink()
    assert env.run().returncode == 0
    assert env.state.read_text().split() == [env.head(env.machine)]


FAKE_SETTINGS_APPLY = """#!{python}
import json, os, sys
a = sys.argv[1:]
t = a[a.index("--template") + 1]
open(os.environ["FAKE_SA_LOG"], "a").write(json.dumps({{"argv": [x for x in a if x != t], "template": open(t).read()}}) + "\\n")
print("settings: fake line")
"""


def _settings_env(env):
    fake = env.bin / "ade-settings-apply"
    fake.write_text(FAKE_SETTINGS_APPLY.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    (env.home / ".claude").mkdir()
    (env.home / ".claude" / "settings.json").write_text("{}")
    log = env.tmp / "sa.log"
    log.write_text("")
    return log


def test_settings_step_check_passes_no_apply_and_reads_the_target_commit(env):
    log = _settings_env(env)
    env.publish({"agents/claude/settings.json.tmpl": "COMMITTED\n"})
    r = env.run("--check", extra_env={"FAKE_SA_LOG": str(log)})
    got = [json.loads(x) for x in log.read_text().splitlines()]
    assert r.returncode == 10 and "Claude settings: settings: fake line" in r.stdout, r.stdout + r.stderr
    assert got == [{"argv": ["--template"], "template": "COMMITTED\n"}]  # dry-run, from the upstream commit not yet in the tree


def test_settings_step_apply_uses_the_committed_template_not_the_dirty_working_tree(env):
    log = _settings_env(env)
    env.publish({"agents/claude/settings.json.tmpl": "COMMITTED\n"})
    assert env.run(extra_env={"FAKE_SA_LOG": str(log)}).returncode == 0
    (env.machine / "agents" / "claude" / "settings.json.tmpl").write_text("DIRTY\n")
    env.run(extra_env={"FAKE_SA_LOG": str(log)})
    got = [json.loads(x) for x in log.read_text().splitlines()]
    assert all(g["argv"] == ["--template", "--apply"] and g["template"] == "COMMITTED\n" for g in got) and len(got) == 2


def test_settings_step_skipped_without_the_template_or_live_file(env):
    log = _settings_env(env)
    env.run(extra_env={"FAKE_SA_LOG": str(log)})  # the fixture repo carries no agents/claude/settings.json.tmpl
    assert log.read_text() == ""


@pytest.mark.parametrize("old", [None, "old helper\n"])
def test_graft_helper_check_reports_drift_without_writes(env, old):
    env.publish({".claude/helpers/graft-hooks.cjs": "#!/usr/bin/env node\nconsole.log('new helper');\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    if old is not None:
        live.parent.mkdir(parents=True)
        live.write_text(old)
    before = sorted(str(p.relative_to(env.home)) for p in env.home.rglob("*"))
    r = env.run("--check", "--json")
    row = json.loads(r.stdout)["graft_helper"]
    assert r.returncode == 10, r.stdout + r.stderr
    assert row["state"] == ("missing" if old is None else "differs")
    assert row["fix"] == f"ade-update --repo {env.machine}"
    assert sorted(str(p.relative_to(env.home)) for p in env.home.rglob("*")) == before
    assert (live.read_text() if live.exists() else None) == old
    assert not env.state.exists()


@pytest.mark.parametrize("old", [None, "old helper\n"])
def test_graft_helper_apply_copies_with_backup_and_is_then_silent(env, old):
    env.publish({".claude/helpers/graft-hooks.cjs": "#!/usr/bin/env node\nconsole.log('new helper');\n"})
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    if old is not None:
        live.parent.mkdir(parents=True)
        live.write_text(old)
        live.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    row = json.loads(r.stdout)["graft_helper"]
    assert row["state"] == "installed"
    assert live.read_text() == "#!/usr/bin/env node\nconsole.log('new helper');\n" and not live.is_symlink()
    assert stat.S_IMODE(live.stat().st_mode) == 0o755
    backups = list(live.parent.glob("graft-hooks.cjs.bak-*"))
    assert len(backups) == int(old is not None)
    if old is not None:
        import re
        assert re.fullmatch(r"graft-hooks.cjs.bak-\d{8}T\d{6}Z", backups[0].name)
        assert backups[0].read_text() == old
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o755
    before = live.stat().st_mtime_ns
    for flags in [("--check",), ()]:
        r = env.run(*flags)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "graft helper" not in r.stdout
        assert live.stat().st_mtime_ns == before
    assert list(live.parent.glob("graft-hooks.cjs.bak-*")) == backups


@pytest.mark.parametrize("flags", [("--check",), ()])
def test_graft_helper_noncanonical_repo_is_report_only(env, flags):
    env.publish({".claude/helpers/graft-hooks.cjs": "feature helper\n"})
    other = env.tmp / "other"
    sh("git", "clone", "-q", str(env.origin), str(other))
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    live.write_text("live helper\n")
    r = env.run(*flags, "--json", repo=other)
    assert r.returncode == 0, r.stdout + r.stderr
    row = json.loads(r.stdout)["graft_helper"]
    assert row["state"] == "differs" and row["mode"] == "report-only"
    assert "fix" not in row
    assert live.read_text() == "live helper\n"
    assert list(live.parent.iterdir()) == [live]


@pytest.mark.parametrize("edit", ["local edit\n", "", "#!/usr/bin/env node\nfunction broken("])
def test_graft_helper_local_edit_cannot_deploy(env, edit):
    env.publish({".claude/helpers/graft-hooks.cjs": "#!/usr/bin/env node\nconsole.log('committed');\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    (env.machine / ".claude/helpers/graft-hooks.cjs").write_text(edit)
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    for flags in [("--check",), ()]:
        r = env.run(*flags, "--json")
        assert r.returncode == 10, r.stdout + r.stderr
        row = json.loads(r.stdout)["graft_helper"]
        assert row["state"] == "refused" and "working-tree" in row["detail"]
        assert live.read_text() == "good live helper\n"
        assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("source", ["", "#!/usr/bin/env node\n", "garbage", "#!/usr/bin/env node\nfunction broken("])
def test_graft_helper_invalid_committed_source_cannot_deploy(env, source):
    env.publish({".claude/helpers/graft-hooks.cjs": source})
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    r = env.run("--json")
    assert r.returncode == 10, r.stdout + r.stderr
    assert json.loads(r.stdout)["graft_helper"]["state"] == "refused"
    assert live.read_text() == "good live helper\n"
    assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("branch", ["feature", "ahead-master"])
def test_graft_helper_requires_authorized_branch_and_revision(env, branch):
    env.publish({".claude/helpers/graft-hooks.cjs": "#!/usr/bin/env node\nconsole.log('committed');\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    if branch == "feature":
        sh("git", "checkout", "-q", "-b", "feature", "--track", "origin/master", cwd=env.machine)
    else:
        commit(env.machine, "unpublished", {".claude/helpers/graft-hooks.cjs": "#!/usr/bin/env node\nconsole.log('unpublished');\n"})
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    r = env.run("--json")
    assert r.returncode == 10, r.stdout + r.stderr
    row = json.loads(r.stdout)["graft_helper"]
    assert row["state"] == "refused" and "master" in row["detail"]
    assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("mode", [0o4755, 0o2755, 0o1755])
def test_graft_helper_special_mode_bits_are_drift(env, mode):
    source = "#!/usr/bin/env node\nconsole.log('committed');\n"
    env.publish({".claude/helpers/graft-hooks.cjs": source})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    live.write_text(source)
    live.chmod(mode)
    assert stat.S_IMODE(live.stat().st_mode) == mode
    r = env.run("--check", "--json")
    assert r.returncode == 10 and json.loads(r.stdout)["graft_helper"]["state"] == "differs"
    assert stat.S_IMODE(live.stat().st_mode) == mode
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert stat.S_IMODE(live.stat().st_mode) == 0o755


@pytest.mark.parametrize("dangling", [False, True])
def test_graft_helper_destination_symlink_becomes_copy(env, dangling):
    source = "#!/usr/bin/env node\nconsole.log('committed');\n"
    env.publish({".claude/helpers/graft-hooks.cjs": source})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    live = env.home / ".claude/helpers/graft-hooks.cjs"
    live.parent.mkdir(parents=True)
    target = env.tmp / "symlink-target"
    if not dangling:
        target.write_text(source)
        target.chmod(0o755)
    live.symlink_to(target)
    assert env.run("--check").returncode == 10
    assert live.is_symlink()
    r = env.run("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not live.is_symlink() and live.read_text() == source
    backups = list(live.parent.glob("*.bak-*"))
    assert len(backups) == int(not dangling)  # absent content cannot be backed up
    assert target.exists() == (not dangling)
    if not dangling:
        assert target.read_text() == source and backups[0].read_text() == source


def helper_snapshot(directory):
    return {p.name: (p.read_bytes(), stat.S_IMODE(p.stat().st_mode)) for p in directory.iterdir()}


def seed_helper_backup(live):
    live.chmod(0o755)
    backup = live.with_name(live.name + ".bak-20260101T000000Z")
    backup.write_bytes(b"existing backup\n")
    backup.chmod(0o640)
    return helper_snapshot(live.parent)


def test_graft_helper_replacement_ref_cannot_authorize_other_bytes(env, monkeypatch):
    monkeypatch.delenv("GIT_NO_REPLACE_OBJECTS", raising=False)
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel: "#!/usr/bin/env node\nconsole.log('authorized');\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    authorized = env.head(env.machine)
    # B is a real local commit, but master and origin/master still name A.
    sh("git", "checkout", "-q", "-b", "replacement", cwd=env.machine)
    replacement = "#!/usr/bin/env node\nconsole.log('replacement');\n"
    commit(env.machine, "replacement bytes", {rel: replacement})
    other = env.head(env.machine)
    sh("git", "checkout", "-q", "master", cwd=env.machine)
    sh("git", "replace", authorized, other, cwd=env.machine)
    (env.machine / rel).write_text(replacement)
    assert sh("git", "show", f"{authorized}:{rel}", cwd=env.machine) == replacement.strip()
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    for flags in [("--check",), ()]:
        r = env.run(*flags, "--json")
        assert r.returncode == 10, r.stdout + r.stderr
        assert json.loads(r.stdout)["graft_helper"]["state"] == "refused"
        assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("code", [1, 124, 127, 128, 2])
@pytest.mark.parametrize("working_source", [False, True])
def test_graft_helper_git_probe_failure_is_error(env, code, working_source):
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel: "#!/usr/bin/env node\nconsole.log('authorized');\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    if not working_source:
        (env.machine / rel).unlink()
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    real_git = shutil.which("git")
    fake = env.bin / "git"
    fake.write_text(f"""#!{sys.executable}
import os, sys
if 'cat-file' in sys.argv and any(a.endswith(':{rel}') for a in sys.argv):
    print("injected object read failure: path does not exist in revision", file=sys.stderr)
    sys.exit({code})
os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])
""")
    fake.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "injected object read failure" in json.loads(r.stdout)["error"]
    assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("failure", ["signal", "unexpected", "exit-one", "empty-exit-one"])
def test_graft_helper_node_tool_failure_is_error(env, failure):
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel: "#!/usr/bin/env node\nconsole.log('authorized');\n"})
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    fake = env.bin / "node"
    action = "os.kill(os.getpid(), signal.SIGTERM)" if failure == "signal" else "sys.exit(2)" if failure == "unexpected" else "sys.exit(1)"
    diagnostic = "" if failure == "empty-exit-one" else "injected node failure"
    fake.write_text(f"#!{sys.executable}\nimport os, signal, sys\nif {bool(diagnostic)!r}: print({diagnostic!r}, file=sys.stderr, flush=True)\n{action}\n")
    fake.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "Node validation failed" in json.loads(r.stdout)["error"]
    assert diagnostic in json.loads(r.stdout)["error"]
    assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("canonical", [True, False])
def test_graft_helper_committed_directory_is_error(env, canonical):
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel + "/child": "not a helper\n"})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    repo = env.machine if canonical else clone(env, "other")
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    for flags in [("--check",), ()]:
        r = env.run(*flags, "--json", repo=repo)
        assert r.returncode == 4, r.stdout + r.stderr
        assert "not one regular-file blob" in json.loads(r.stdout)["error"]
        assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("entry", ["160000 commit", "120000 blob", "100644 tree", "100644 blob"])
def test_graft_helper_invalid_object_entry_is_error(env, entry):
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel: "#!/usr/bin/env node\nconsole.log('authorized');\n"})
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    # Even a blob-labelled row must fail its typed object read if that OID is a tree.
    oid = sh("git", "rev-parse", "HEAD^{tree}", cwd=env.seed)
    real_git = shutil.which("git")
    fake = env.bin / "git"
    output = f"{entry} {oid}\t{rel}\0"
    fake.write_text(f"""#!{sys.executable}
import os, sys
if 'ls-tree' in sys.argv and sys.argv[-1] == {rel!r}:
    sys.stdout.write({output!r})
    sys.exit(0)
os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])
""")
    fake.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 4, r.stdout + r.stderr
    assert helper_snapshot(live.parent) == saved


@pytest.mark.parametrize("failure", ["ls-tree", "blob-read", "signal"])
def test_graft_helper_git_listing_and_blob_read_failures(env, failure):
    rel = ".claude/helpers/graft-hooks.cjs"
    env.publish({rel: "#!/usr/bin/env node\nconsole.log('authorized');\n"})
    live = env.home / rel
    live.parent.mkdir(parents=True)
    live.write_text("good live helper\n")
    saved = seed_helper_backup(live)
    real_git = shutil.which("git")
    fake = env.bin / "git"
    conditions = {
        "ls-tree": f"'ls-tree' in sys.argv and sys.argv[-1] == {rel!r}",
        "blob-read": "'cat-file' in sys.argv and 'blob' in sys.argv",
        "signal": f"'cat-file' in sys.argv and any(a.endswith(':{rel}') for a in sys.argv)",
    }
    action = "os.kill(os.getpid(), signal.SIGTERM)" if failure == "signal" else "sys.exit(127)"
    fake.write_text(f"""#!{sys.executable}
import os, sys, signal
if {conditions[failure]}:
    print('injected Git operational failure', file=sys.stderr, flush=True)
    {action}
os.execv({real_git!r}, [{real_git!r}, *sys.argv[1:]])
""")
    fake.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "injected Git operational failure" in json.loads(r.stdout)["error"]
    assert helper_snapshot(live.parent) == saved


# --- ~/.local/bin tool links (step 3d, 2026-11-21) ------------------------------------------------------------

def bin_tools(env, *names):
    """Executable bin/<name> files in the canonical `machine` clone (untracked: no pull happens in these tests)."""
    (env.machine / "bin").mkdir(exist_ok=True)
    for n in names:
        f = env.machine / "bin" / n
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)


def bin_dir(env):
    return env.home / ".local" / "bin"


def test_missing_bin_link_is_created_pointing_at_the_canonical_checkout(env):
    bin_tools(env, "git-commit-own", "load-watch")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    for n in ("git-commit-own", "load-watch"):
        link = bin_dir(env) / n
        assert link.is_symlink() and os.readlink(link) == str(env.machine.resolve() / "bin" / n)
    assert "2 linked" in r.stdout
    assert "agent-id" in r.stdout and "skipped" in r.stdout  # absent tool: an info line, not a problem
    assert env.run().returncode == 0  # idempotent, second run finds them ok
    assert "2 ok" in env.run().stdout


def test_stale_link_into_a_djbclark_ade_worktree_is_repaired(env):
    bin_tools(env, "load-watch")
    gone = env.tmp / "djbclark-ade-old-wt"  # a removed worktree: the link dangles
    live = env.tmp / "src" / "djbclark-ade-other-wt"  # a live one: has bin/ade-update and skills/
    (live / "bin").mkdir(parents=True)
    (live / "skills").mkdir()
    (live / "bin" / "ade-update").write_text("")
    (live / "bin" / "load-watch").write_text("")
    bin_dir(env).mkdir(parents=True)
    for stale, name in ((gone, "load-watch"), (live, "git-commit-own")):
        os.symlink(stale / "bin" / name, bin_dir(env) / name)
    bin_tools(env, "git-commit-own")
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    for n in ("load-watch", "git-commit-own"):
        assert os.readlink(bin_dir(env) / n) == str(env.machine.resolve() / "bin" / n)
    assert "2 repaired" in r.stdout
    assert [p.name for p in bin_dir(env).iterdir() if p.name.startswith(".")] == []  # no temp symlink left


def test_regular_file_and_foreign_symlink_are_untouched_and_reported(env):
    bin_tools(env, "git-commit-own", "load-watch")
    bin_dir(env).mkdir(parents=True)
    (bin_dir(env) / "git-commit-own").write_text("my own script\n")
    elsewhere = env.tmp / "elsewhere" / "bin"
    elsewhere.mkdir(parents=True)
    (elsewhere / "load-watch").write_text("")
    os.symlink(elsewhere / "load-watch", bin_dir(env) / "load-watch")
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert (bin_dir(env) / "git-commit-own").read_text() == "my own script\n"
    assert not (bin_dir(env) / "git-commit-own").is_symlink()
    assert os.readlink(bin_dir(env) / "load-watch") == str(elsewhere / "load-watch")
    assert "a regular file (not ours)" in r.stdout and "not a djbclark-ade checkout" in r.stdout
    assert "2 unresolved" in r.stdout and "bin links" in r.stdout
    out = json.loads(env.run("--json").stdout)
    assert {p["tool"] for p in out["bin_links"]["problems"]} == {"git-commit-own", "load-watch"}


def test_absent_bin_tool_is_skipped_quietly_with_exit_0(env):
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "info: no executable bin/ file in this checkout for: git-commit-own, load-watch, agent-id, lsp-root-guard; skipped" in r.stdout
    assert not bin_dir(env).exists()
    (env.machine / "bin").mkdir()
    (env.machine / "bin" / "load-watch").write_text("not executable\n")  # a non-executable file is not a tool either
    assert env.run().returncode == 0
    assert not bin_dir(env).exists()


def test_check_writes_no_bin_link_and_reports_exit_10(env):
    bin_tools(env, "load-watch")
    gone = env.tmp / "djbclark-ade-old-wt"
    bin_dir(env).mkdir(parents=True)
    os.symlink(gone / "bin" / "git-commit-own", bin_dir(env) / "git-commit-own")
    bin_tools(env, "git-commit-own")
    r = env.run("--check")
    assert r.returncode == 10, r.stdout + r.stderr
    assert "would link: load-watch" in r.stdout and "would repair: git-commit-own" in r.stdout
    assert not (bin_dir(env) / "load-watch").exists() and not (bin_dir(env) / "load-watch").is_symlink()
    assert os.readlink(bin_dir(env) / "git-commit-own") == str(gone / "bin" / "git-commit-own")  # untouched
    assert sorted(p.name for p in bin_dir(env).iterdir()) == ["git-commit-own"]


def test_non_canonical_repo_never_links_bin_tools(env):
    other = clone(env, "other")
    (other / "bin").mkdir()
    (other / "bin" / "load-watch").write_text("")
    (other / "bin" / "load-watch").chmod(0o755)
    for flags in (("--check",), ()):
        r = env.run(*flags, repo=other)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "tool links: report-only" in r.stdout
    assert not bin_dir(env).exists()


def test_new_upstream_bin_tool_is_info_only_under_check(env):
    env.publish({"bin/agent-id": "#!/bin/sh\n"})
    r = env.run("--check")
    assert r.returncode == 10, r.stdout + r.stderr  # behind, nothing else
    assert "new upstream tools, linked after the pull: agent-id" in r.stdout
    assert "bin links" not in json.loads(env.run("--check", "--json").stdout)["problems"]


def test_dangling_link_outside_djbclark_ade_is_foreign_not_repaired(env):
    """Mutation target: the `any(part.startswith("djbclark-ade") ...)` rule for a root that no longer exists."""
    bin_tools(env, "load-watch")
    bin_dir(env).mkdir(parents=True)
    gone = env.tmp / "some-other-project-gone" / "bin" / "load-watch"  # dangles, and no djbclark-ade component
    os.symlink(gone, bin_dir(env) / "load-watch")
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert os.readlink(bin_dir(env) / "load-watch") == str(gone)
    assert "not a djbclark-ade checkout" in r.stdout


@pytest.mark.parametrize("rel", ["bin/other-tool", "tools/load-watch", "load-watch"])
def test_link_to_a_different_name_or_outside_bin_is_foreign(env, rel):
    """Mutation target: the `t.name != dest.name or t.parent.name != "bin"` check, even inside a djbclark-ade tree."""
    bin_tools(env, "load-watch")
    bin_dir(env).mkdir(parents=True)
    wt = env.tmp / "djbclark-ade-x-wt"
    target = wt / rel
    target.parent.mkdir(parents=True)
    target.write_text("")
    (wt / "bin").mkdir(exist_ok=True)
    (wt / "bin" / "ade-update").write_text("")
    (wt / "skills").mkdir(exist_ok=True)
    os.symlink(target, bin_dir(env) / "load-watch")
    r = env.run()
    assert r.returncode == 10, r.stdout + r.stderr
    assert os.readlink(bin_dir(env) / "load-watch") == str(target)
    assert "not a djbclark-ade checkout" in r.stdout


def test_path_warnings_never_change_the_exit_code(env):
    bin_tools(env, "load-watch")
    plain = os.environ["PATH"]
    # bin dir not on PATH (the default test PATH): a warning, exit 0, link still made
    r = env.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"warning: {bin_dir(env)} is not on PATH" in r.stdout
    # on PATH, nothing earlier: no warning
    r = env.run(extra_env={"PATH": f"{bin_dir(env)}{os.pathsep}{plain}"})
    assert r.returncode == 0 and "warning:" not in r.stdout, r.stdout + r.stderr
    # an earlier entry holding an executable of the same name shadows the link
    shadow = env.tmp / "shadow"
    shadow.mkdir()
    (shadow / "load-watch").write_text("#!/bin/sh\n")
    (shadow / "load-watch").chmod(0o755)
    r = env.run("--json", extra_env={"PATH": f"{shadow}{os.pathsep}{bin_dir(env)}{os.pathsep}{plain}"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert any("shadows the load-watch link" in w for w in json.loads(r.stdout)["bin_links"]["warnings"])
    # a shadow AFTER the bin dir is not a shadow
    r = env.run(extra_env={"PATH": f"{bin_dir(env)}{os.pathsep}{shadow}{os.pathsep}{plain}"})
    assert "shadows" not in r.stdout


# --- ~/.local/libexec/ade standalone copies (step 3e, 2026-11-24) -------------------------------------------

VALID_MCP_LAZY = "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n"


@pytest.mark.parametrize("old", [None, "#!/usr/bin/env python3\nprint('old')\n"])
def test_libexec_copy_check_reports_drift_without_writes(env, old):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    live = env.home / ".local" / "libexec" / "ade" / "mcp-lazy"
    if old is not None:
        live.parent.mkdir(parents=True)
        live.write_text(old)
    before = sorted(str(p.relative_to(env.home)) for p in env.home.rglob("*"))
    r = env.run("--check", "--json")
    row = json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]
    assert r.returncode == 10, r.stdout + r.stderr
    assert row["state"] == ("missing" if old is None else "differs")
    assert sorted(str(p.relative_to(env.home)) for p in env.home.rglob("*")) == before
    assert (live.read_text() if live.exists() else None) == old


@pytest.mark.parametrize("old", [None, "#!/usr/bin/env python3\nprint('old')\n"])
def test_libexec_copy_apply_installs_standalone_copy_with_backup_and_is_silent(env, old):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    live = env.home / ".local" / "libexec" / "ade" / "mcp-lazy"
    if old is not None:
        live.parent.mkdir(parents=True)
        live.write_text(old)
        live.chmod(0o755)
    r = env.run("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    row = json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]
    assert row["state"] == "installed"
    assert live.is_file() and not live.is_symlink()
    assert live.read_text() == VALID_MCP_LAZY
    assert stat.S_IMODE(live.stat().st_mode) == 0o755
    backups = list(live.parent.glob("mcp-lazy.bak-*"))
    assert len(backups) == int(old is not None)
    # Second run is silent and idempotent.
    for flags in (("--check",), ()):
        r2 = env.run(*flags)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "libexec copy" not in r2.stdout


def test_libexec_copy_replaces_symlink_with_standalone_file(env):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    live = env.home / ".local" / "libexec" / "ade" / "mcp-lazy"
    live.parent.mkdir(parents=True)
    live.symlink_to(env.machine / "bin" / "mcp-lazy")
    assert env.run("--check").returncode == 10
    assert live.is_symlink()
    r = env.run("--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]["state"] == "installed"
    assert not live.is_symlink() and live.read_text() == VALID_MCP_LAZY
    assert stat.S_IMODE(live.stat().st_mode) == 0o755


def test_libexec_copy_noncanonical_repo_is_report_only(env):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    other = env.tmp / "other-libexec"
    sh("git", "clone", "-q", str(env.origin), str(other))
    live = env.home / ".local" / "libexec" / "ade" / "mcp-lazy"
    for flags in (("--check",), ()):
        r = env.run(*flags, "--json", repo=other)
        assert r.returncode == 0, r.stdout + r.stderr
        row = json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]
        assert row["state"] == "missing" and row["mode"] == "report-only"
    assert not live.exists()


def test_libexec_copy_local_edit_and_syntax_error_refused(env):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    sh("git", "pull", "-q", "--ff-only", cwd=env.machine)
    (env.machine / "bin" / "mcp-lazy").write_text("#!/usr/bin/env python3\n# dirty\n")
    r = env.run("--json")
    assert r.returncode == 10, r.stdout + r.stderr
    assert json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]["state"] == "refused"
    assert not (env.home / ".local" / "libexec" / "ade" / "mcp-lazy").exists()

    # Syntax-error committed version is also refused.
    (env.machine / "bin" / "mcp-lazy").write_text(VALID_MCP_LAZY)
    env.publish({"bin/mcp-lazy": "#!/usr/bin/env python3\ndef broken(\n"})
    r2 = env.run("--json")
    assert r2.returncode == 10, r2.stdout + r2.stderr
    assert json.loads(r2.stdout)["libexec_copies"]["mcp-lazy"]["state"] == "refused"
    assert not (env.home / ".local" / "libexec" / "ade" / "mcp-lazy").exists()


def test_libexec_copy_check_behind_new_upstream_reports_missing(env):
    env.publish({"bin/mcp-lazy": VALID_MCP_LAZY})
    r = env.run("--check", "--json")
    assert r.returncode == 10, r.stdout + r.stderr
    row = json.loads(r.stdout)["libexec_copies"]["mcp-lazy"]
    assert row["state"] == "missing"
    assert not (env.home / ".local" / "libexec" / "ade" / "mcp-lazy").exists()
