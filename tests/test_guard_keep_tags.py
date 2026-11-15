"""The "keep this directory" rule tags of `bin/review-pr` and `bin/ade-merge-ready` match what ade-git-guard prints (ec-01 E2a).

Both tools leave a temporary worktree in place (instead of `shutil.rmtree`) only when the guard refuses `git worktree remove`
with exit 77 AND the refusal carries one of two rule tags: a live process uses the directory, or another agent claims it.
They match the tags as text in the guard's stderr (`GUARD_KEEP_RULES`), so a rename in `bin/ade_claims.py` would silently turn the
keep into an rmtree (PR 701 lead review: a mutant of the strings survived). Their own tests feed hand-written refusal texts, so
nothing tied the strings to the guard: this test runs the real guard for both refusals and compares what it prints.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ade_git_guard import run, setup_linked, state  # noqa: E402,F401  (state: autouse fixture)
from test_git_guard_live_use import rig  # noqa: E402,F401  (a repo, a linked worktree, a fake lsof)

BIN = Path(__file__).resolve().parent.parent / "bin"
TOOLS = ("review-pr", "ade-merge-ready")
REFUSAL_TAG = re.compile(r"REFUSED `.*?` \[([^\]]+)\]")   # `REFUSED `<command>` [rule]`: a `[` in the command cannot be taken for the rule


def keep_rules(tool: str) -> tuple[str, ...]:
    """`GUARD_KEEP_RULES` read from the tool's source as a literal (no import: the tools run their CLI on load paths)."""
    tree = ast.parse((BIN / tool).read_text(), filename=tool)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "GUARD_KEEP_RULES" for t in node.targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple) and value and all(isinstance(v, str) for v in value), (tool, value)
            return value
    raise AssertionError(f"bin/{tool} has no GUARD_KEEP_RULES assignment")


def printed_tag(stderr: str) -> str:
    m = REFUSAL_TAG.search(stderr)
    assert m, f"no `REFUSED ... [rule]` line in the guard's stderr: {stderr!r}"
    return f"[{m.group(1)}]"


def test_the_guard_prints_one_tag_for_a_live_process_and_one_for_a_claim(tmp_path, state, rig):
    live = rig.remove(cwd_users=[[10129, "claude", "cwd", str(rig.wt)]])
    assert live.returncode == 77, live.stderr
    (tmp_path / "claimed").mkdir()   # own dir: the rig's `w` and setup_linked's `W` are one name on a case-insensitive Mac
    claimed_repo, claimed_wt = setup_linked(tmp_path / "claimed", state)
    claimed = run(state, ["worktree", "remove", str(claimed_wt)], claimed_repo, who="B")
    assert claimed.returncode == 77, claimed.stderr
    tags = {printed_tag(live.stderr), printed_tag(claimed.stderr)}
    assert len(tags) == 2, tags
    for tool in TOOLS:
        assert set(keep_rules(tool)) == tags, (
            f"bin/{tool} GUARD_KEEP_RULES {keep_rules(tool)!r} drifted from the tags bin/ade_claims.py prints {sorted(tags)!r}")


@pytest.mark.parametrize("tool", TOOLS)
def test_the_routine_force_refusal_is_not_a_keep_tag(tmp_path, state, tool):
    """The guard's `--force`-on-an-unclaimed-tree refusal (also 77) hits these tools' own never-claimed worktree every run."""
    repo, _ = setup_linked(tmp_path, state)
    other = tmp_path / "W2"
    run(state, ["worktree", "add", "-q", "-b", "w2", str(other)], repo)
    (other / "f").write_text("dirty\n")
    # ADE_LSOF=false: the live-process check runs before the --force rule; keep it off the host's real process table
    p = run(state, ["worktree", "remove", "--force", str(other)], repo, who="B", ADE_LSOF="/usr/bin/false")
    assert p.returncode == 77, p.stderr
    assert printed_tag(p.stderr) not in keep_rules(tool)


def test_the_tag_is_the_bracket_after_the_displayed_command_not_one_inside_it():
    err = "ade-git-guard: REFUSED `git worktree remove /x[1]/w` [worktree remove: live process] in /y\n"
    assert printed_tag(err) == "[worktree remove: live process]"
