"""The graft/Trail hook's Cursor sessionStart route (2026-11-18).

`.cursor/hooks.json` calls the helper with `cursor-session-start`, and Cursor reads a top-level
`additional_context` where Claude Code reads `hookSpecificOutput.additionalContext`. The helper also ships as two
byte-identical copies (`.claude/helpers/` and `.cursor/hooks/`); nothing else checks that they stay in step, so this
does. The hook only offers learnings when the repo has none of trail's state and a `.trail/learnings/` directory exists,
so the test builds that in a temporary project and never touches the real one.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAUDE_HOOK = REPO / ".claude" / "helpers" / "graft-hooks.cjs"
CURSOR_HOOK = REPO / ".cursor" / "hooks" / "graft-hooks.cjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    learnings = project / ".trail" / "learnings"
    learnings.mkdir(parents=True)
    (learnings / "2026-11-01-cursor.md").write_text(
        "---\ntitle: Cursor reads additional_context\nauthor: tester\nstatus: live\n---\nbody text\n")
    return project


def _run(hook: Path, argument: str, project: Path, tmp_path: Path) -> str:
    """Run one hook in the temporary project, cut off from every installed trail/graft.

    `entry()` tries a remembered trail home, the packages above the project and above node, the PATH, then
    `npm root -g`; a PATH holding nothing but a `node` link removes the last three, so the run always takes the
    in-repo path this file tests instead of importing whatever is installed on the machine.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "node").symlink_to(shutil.which("node"))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), TRAIL_HOME=str(tmp_path / "trail-home"),
               PATH=str(bin_dir))
    done = subprocess.run([shutil.which("node"), str(hook), argument], env=env, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _payload(hook: Path, argument: str, tmp_path: Path) -> dict:
    return json.loads(_run(hook, argument, _project(tmp_path), tmp_path))


def test_cursor_session_start_answers_in_cursors_shape(tmp_path: Path) -> None:
    payload = _payload(CURSOR_HOOK, "cursor-session-start", tmp_path)
    assert "hookSpecificOutput" not in payload          # Claude Code's shape would be ignored by Cursor
    context = payload["additional_context"]
    assert "Cursor reads additional_context" in context and "tester" in context


def test_claude_session_start_keeps_its_own_shape(tmp_path: Path) -> None:
    payload = _payload(CLAUDE_HOOK, "session-start", tmp_path)
    assert "additional_context" not in payload
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Cursor reads additional_context" in payload["hookSpecificOutput"]["additionalContext"]


def test_an_unknown_hook_argument_stays_a_no_op(tmp_path: Path) -> None:
    assert _run(CURSOR_HOOK, "bogus", _project(tmp_path), tmp_path) == ""


def test_a_repo_without_learnings_says_nothing(tmp_path: Path) -> None:
    project = tmp_path / "bare"
    project.mkdir()
    assert _run(CURSOR_HOOK, "cursor-session-start", project, tmp_path) == ""


def test_the_two_hook_copies_are_identical() -> None:
    """`.claude/helpers/` and `.cursor/hooks/` ship the same helper; a change has to land in both."""
    assert CLAUDE_HOOK.read_bytes() == CURSOR_HOOK.read_bytes()


def test_both_copies_speak_cursors_shape(tmp_path: Path) -> None:
    payload = _payload(CLAUDE_HOOK, "cursor-session-start", tmp_path / "a")
    assert "Cursor reads additional_context" in payload["additional_context"]


def _fake_upstream(project: Path) -> None:
    """An installed trail/graft beside the project: `entry()` finds this hooks.js, as on a machine with trail."""
    dist = project / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  process.stdout.write(JSON.stringify({ hookSpecificOutput: {\n"
        "    hookEventName: 'SessionStart', additionalContext: 'upstream saw ' + event } }));\n"
        "}\n")


def test_an_installed_trail_is_run_as_session_start_and_reshaped(tmp_path: Path) -> None:
    """Upstream knows only the Claude event: Cursor gets its context, and upstream is asked for session-start."""
    project = _project(tmp_path)
    _fake_upstream(project)
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "upstream saw session-start"}


def test_an_installed_trail_keeps_claudes_own_event_shape(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _fake_upstream(project)
    payload = json.loads(_run(CLAUDE_HOOK, "session-start", project, tmp_path))
    assert payload["hookSpecificOutput"]["additionalContext"] == "upstream saw session-start"
    assert "additional_context" not in payload


def test_upstreams_system_message_is_kept_for_cursor(tmp_path: Path) -> None:
    """Cursor has one field for both, so upstream's notice and its context are joined, never silently dropped."""
    project = _project(tmp_path)
    dist = project / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  process.stdout.write(JSON.stringify({ hookSpecificOutput: {\n"
        "    hookEventName: 'SessionStart', systemMessage: 'NOTICE', additionalContext: 'CONTEXT ' + event } }));\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "NOTICE\n\nCONTEXT session-start"}


def test_a_stdout_callback_upstream_is_not_lost(tmp_path: Path) -> None:
    """An upstream that waits on the write callback must still finish and still be re-shaped."""
    project = _project(tmp_path)
    dist = project / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  return new Promise((resolve) => process.stdout.write(JSON.stringify({ hookSpecificOutput: {\n"
        "    additionalContext: 'CALLBACK ' + event } }), () => resolve()));\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "CALLBACK session-start"}


def test_a_broken_installed_upstream_is_a_no_op(tmp_path: Path) -> None:
    """A partial trail install must not print a stack trace or exit non-zero, exactly as the Claude branch does not."""
    project = _project(tmp_path)
    dist = project / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text("export function main() { throw new Error('broken install'); }\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "node").symlink_to(shutil.which("node"))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), TRAIL_HOME=str(tmp_path / "trail-home"), PATH=str(bin_dir))
    done = subprocess.run([shutil.which("node"), str(CURSOR_HOOK), "cursor-session-start"], env=env,
                          capture_output=True, text=True, timeout=60)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
