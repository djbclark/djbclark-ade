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


def _run(hook: Path, argument: str, project: Path, tmp_path: Path,
         extra_env: dict[str, str] | None = None, *, exec_path: Path | None = None) -> str:
    """Isolate every install lookup from the host, including node's own lib dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    if not (bin_dir / "node").exists():
        (bin_dir / "node").symlink_to(shutil.which("node"))
    isolate = tmp_path / "isolate.cjs"
    isolate.write_text("Object.defineProperty(process, 'execPath', {value: "
                       + json.dumps(str(exec_path or tmp_path / "node-install" / "bin" / "node")) + "});")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), TRAIL_HOME=str(tmp_path / "trail-home"),
               PATH=str(bin_dir))
    env.pop("ADE_GRAFT_ALLOW_PROJECT_HOOKS", None)
    env.update(extra_env or {})
    done = subprocess.run([shutil.which("node"), "--require", str(isolate), str(hook), argument],
                          cwd=project, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    return done.stdout


def _trusted_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "installed" / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "trail-home"
    home.mkdir(exist_ok=True)
    record = home / "install.json"
    record.write_text(json.dumps({"claudeDist": str(dist)}))
    record.chmod(0o600)
    return dist


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


def _fake_upstream(tmp_path: Path) -> None:
    """A remembered installed trail/graft: `entry()` finds this hooks.js, as on a machine with trail."""
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  process.stdout.write(JSON.stringify({ hookSpecificOutput: {\n"
        "    hookEventName: 'SessionStart', additionalContext: 'upstream saw ' + event } }));\n"
        "}\n")


def test_an_installed_trail_is_run_as_session_start_and_reshaped(tmp_path: Path) -> None:
    """Upstream knows only the Claude event: Cursor gets its context, and upstream is asked for session-start."""
    project = _project(tmp_path)
    _fake_upstream(tmp_path)
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "upstream saw session-start"}


def test_an_installed_trail_keeps_claudes_own_event_shape(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _fake_upstream(tmp_path)
    payload = json.loads(_run(CLAUDE_HOOK, "session-start", project, tmp_path))
    assert payload["hookSpecificOutput"]["additionalContext"] == "upstream saw session-start"
    assert "additional_context" not in payload


def test_upstreams_top_level_notice_is_kept_for_cursor(tmp_path: Path) -> None:
    """Claude's hook output puts `systemMessage` at the top level; Cursor has one field for both, so they are joined."""
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  process.stdout.write(JSON.stringify({ systemMessage: 'NOTICE', hookSpecificOutput: {\n"
        "    hookEventName: 'SessionStart', additionalContext: 'CONTEXT ' + event } }));\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "NOTICE\n\nCONTEXT session-start"}


def test_a_notice_with_no_context_still_reaches_cursor(tmp_path: Path) -> None:
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main() {\n"
        "  process.stdout.write(JSON.stringify({ systemMessage: 'ONLY A NOTICE' }));\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "ONLY A NOTICE"}


def test_a_stdout_callback_upstream_is_not_lost(tmp_path: Path) -> None:
    """An upstream that waits on the write callback must still finish and still be re-shaped."""
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
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
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text("export function main() { throw new Error('broken install'); }\n")
    assert _run(CURSOR_HOOK, "cursor-session-start", project, tmp_path) == ""


def test_output_written_after_the_promise_settles_is_still_reshaped(tmp_path: Path) -> None:
    """An upstream that answers from a later callback, without returning that promise, is still captured."""
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main(event) {\n"
        "  setTimeout(() => process.stdout.write(JSON.stringify({ hookSpecificOutput: {\n"
        "    additionalContext: 'LATE ' + event } })), 30);\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload == {"additional_context": "LATE session-start"}


def test_a_large_context_survives_the_pipe(tmp_path: Path) -> None:
    """The payload is written when main() settles, not at exit, so a context bigger than a pipe buffer is not cut."""
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main() {\n"
        "  process.stdout.write(JSON.stringify({ hookSpecificOutput: { additionalContext: 'X'.repeat(200000) } }));\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert len(payload["additional_context"]) == 200000


def test_a_split_write_is_reshaped_once_both_halves_arrive(tmp_path: Path) -> None:
    """Half a payload at settle must not flush a parse error: the exit hook reshapes the whole thing."""
    project = _project(tmp_path)
    dist = _trusted_dist(tmp_path)
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "hooks.js").write_text(
        "export function main() {\n"
        "  const body = JSON.stringify({ hookSpecificOutput: { additionalContext: 'SPLIT ' + 'Y'.repeat(50) } });\n"
        "  process.stdout.write(body.slice(0, 20));\n"
        "  setTimeout(() => process.stdout.write(body.slice(20)), 25);\n"
        "}\n")
    payload = json.loads(_run(CURSOR_HOOK, "cursor-session-start", project, tmp_path))
    assert payload["additional_context"].startswith("SPLIT YYYY")


def _marker_package(root: Path, marker: Path, version: str = "1.0.0") -> Path:
    dist = root / "dist" / "claude"
    dist.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({
        "name": "@trailhq/trail-code", "version": version, "type": "module"}))
    source = ("import {writeFileSync} from 'node:fs';\n"
              + "writeFileSync(" + json.dumps(str(marker)) + ", 'imported');\n"
              + "export function main(event) { process.stdout.write(JSON.stringify({"
              + "hookSpecificOutput: {additionalContext: event}})); }\n")
    for name in ("hooks.js", "pre-bash.js"):
        (dist / name).write_text(source)
    return dist


EVENTS = [(CLAUDE_HOOK, "session-start"), (CURSOR_HOOK, "cursor-session-start"),
          (CLAUDE_HOOK, "pre-bash"), (CURSOR_HOOK, "pre-bash")]


@pytest.mark.parametrize("hook,event", EVENTS)
@pytest.mark.parametrize("layout", ["package", "bare"])
@pytest.mark.parametrize("opt_in", [None, "0", "true", "1"])
def test_project_helpers_require_explicit_opt_in(
        tmp_path: Path, hook: Path, event: str, layout: str, opt_in: str | None) -> None:
    project = tmp_path / "project"
    project.mkdir()
    root = project / "node_modules" / "@trailhq" / "trail-code" if layout == "package" else project
    marker = tmp_path / "project-imported"
    _marker_package(root, marker, "99999.0.0")
    env = {} if opt_in is None else {"ADE_GRAFT_ALLOW_PROJECT_HOOKS": opt_in}
    output = _run(hook, event, project, tmp_path, env)
    assert marker.exists() == (opt_in == "1")
    if opt_in != "1":
        assert output == ""


@pytest.mark.parametrize("hook,event", EVENTS)
@pytest.mark.parametrize("source", ["remembered", "path", "node-lib", "global"])
def test_trusted_installs_resolve_without_project_opt_in(
        tmp_path: Path, hook: Path, event: str, source: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    hostile_marker = tmp_path / "project-imported"
    _marker_package(project / "node_modules" / "@trailhq" / "trail-code", hostile_marker, "99999.0.0")
    marker = tmp_path / "trusted-imported"
    root = tmp_path / "installed"
    if source == "node-lib":
        root = tmp_path / "node-install" / "lib" / "node_modules" / "@trailhq" / "trail-code"
    if source == "global":
        root = tmp_path / "global" / "node_modules" / "@trailhq" / "trail-code"
    dist = _marker_package(root, marker)
    if source == "remembered":
        assert _trusted_dist(tmp_path) == dist
    elif source == "path":
        cli = root / "dist" / "cli.js"
        cli.write_text("")
        bins = tmp_path / "bin"
        bins.mkdir()
        (bins / "trail").symlink_to(cli)
    elif source == "global":
        bins = tmp_path / "bin"
        bins.mkdir()
        npm = bins / "npm"
        npm.write_text("#!/bin/sh\nprintf '%s\\n' '" + str(tmp_path / "global" / "node_modules") + "'\n")
        npm.chmod(0o755)
    _run(hook, event, project, tmp_path)
    # pre-bash deliberately never shells out to npm, even when no cheap candidate exists.
    assert marker.exists() == (source != "global" or event != "pre-bash")
    assert not hostile_marker.exists()


@pytest.mark.parametrize("hook,event", EVENTS)
def test_writable_remembered_record_is_rejected(tmp_path: Path, hook: Path, event: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "imported"
    _marker_package(tmp_path / "installed", marker)
    _trusted_dist(tmp_path)
    (tmp_path / "trail-home" / "install.json").chmod(0o666)
    assert _run(hook, event, project, tmp_path) == ""
    assert not marker.exists()


@pytest.mark.parametrize("hook,event", EVENTS)
@pytest.mark.parametrize("opt_in", [False, True])
@pytest.mark.parametrize("route", ["sentinel", "local-bin", "outside-link", "relative-home",
                                    "absolute-home", "node-lib", "module-link", "directory-link"])
def test_project_targets_from_install_sources_require_opt_in(
        tmp_path: Path, hook: Path, event: str, opt_in: bool, route: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    hostile_marker = tmp_path / "hostile-imported"
    trusted_marker = tmp_path / "trusted-imported"
    trusted_root = tmp_path / "installed"
    _marker_package(trusted_root, trusted_marker, "1.0.0")
    _trusted_dist(tmp_path)
    root = project
    if route == "local-bin":
        root = project / "node_modules" / "@trailhq" / "trail-code"
    elif route == "node-lib":
        root = project / "runtime" / "lib" / "node_modules" / "@trailhq" / "trail-code"
    hostile_dist = _marker_package(root, hostile_marker, "99999.0.0")
    bins = tmp_path / "bin"
    bins.mkdir()
    env = {"ADE_GRAFT_ALLOW_PROJECT_HOOKS": "1" if opt_in else "0"}
    exec_path = None
    if route in {"sentinel", "local-bin", "outside-link"}:
        if route == "sentinel":
            path_dir = project / "bin"
            path_dir.mkdir()
            (path_dir / "trail").touch(mode=0o600)  # Empty and deliberately non-executable.
        else:
            path_dir = project / "node_modules" / ".bin" if route == "local-bin" else tmp_path / "outside-bin"
            path_dir.mkdir(parents=True)
            cli = root / "dist" / "cli.js"
            cli.write_text("")
            (path_dir / "trail").symlink_to(cli)
        env["PATH"] = os.pathsep.join([str(path_dir), str(bins)])
    elif route in {"relative-home", "absolute-home"}:
        home = project / ".trail"
        home.mkdir()
        record = home / "install.json"
        record.write_text(json.dumps({"claudeDist": str(hostile_dist)}))
        record.chmod(0o600)
        env["TRAIL_HOME"] = ".trail" if route == "relative-home" else str(home)
        # Replacing TRAIL_HOME must not hide the legitimate lower-version candidate.
        cli = trusted_root / "dist" / "cli.js"
        cli.write_text("")
        (bins / "trail").symlink_to(cli)
    elif route == "node-lib":
        exec_path = project / "runtime" / "bin" / "node"
    else:
        wrapper = tmp_path / "wrapper"
        dist = wrapper / "dist" / "claude"
        dist.mkdir(parents=True)
        (wrapper / "package.json").write_text(json.dumps({"name": "@trailhq/trail-code", "version": "99999.0.0"}))
        if route == "directory-link":
            dist.rmdir()
            dist.symlink_to(hostile_dist, target_is_directory=True)
        else:
            for name in ("hooks.js", "pre-bash.js"):
                (dist / name).symlink_to(hostile_dist / name)
        cli = wrapper / "dist" / "cli.js"
        cli.write_text("")
        (bins / "trail").symlink_to(cli)
    _run(hook, event, project, tmp_path, env, exec_path=exec_path)
    assert hostile_marker.exists() == opt_in
    assert trusted_marker.exists() != opt_in


@pytest.mark.parametrize("hook,event", EVENTS)
@pytest.mark.parametrize("opt_in", [False, True])
def test_global_root_candidates_are_checked_after_realpath(
        tmp_path: Path, hook: Path, event: str, opt_in: bool) -> None:
    project = tmp_path / "project"
    project.mkdir()
    hostile_marker = tmp_path / "hostile-imported"
    trusted_marker = tmp_path / "trusted-imported"
    modules = project / "global" / "node_modules"
    _marker_package(modules / "@trailhq" / "trail-code", hostile_marker, "99999.0.0")
    trusted = tmp_path / "installed"
    _marker_package(trusted, trusted_marker, "1.0.0")
    (modules / "@nanonets").mkdir()
    (modules / "@nanonets" / "graft").symlink_to(trusted, target_is_directory=True)
    bins = tmp_path / "bin"
    bins.mkdir()
    npm = bins / "npm"
    npm.write_text("#!/bin/sh\nprintf '%s\\n' '" + str(modules) + "'\n")
    npm.chmod(0o755)
    _run(hook, event, project, tmp_path, {"ADE_GRAFT_ALLOW_PROJECT_HOOKS": "1" if opt_in else "0"})
    assert hostile_marker.exists() == (opt_in and event != "pre-bash")
    assert trusted_marker.exists() == (not opt_in and event != "pre-bash")
