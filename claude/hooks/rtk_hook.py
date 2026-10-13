#!/usr/bin/env python3
"""PreToolUse Bash wrapper around `rtk hook claude`; failures never block a command.

rtk rewrites commands (`git status` -> `rtk git status`) through `updatedInput`.
Inside a worktree-isolated sub-agent (Agent tool `isolation: "worktree"`, cwd under
`.claude/worktrees/`), Claude Code's isolation guard cannot verify the rewritten
command and refuses it, so plain `git`, `gitleaks git` and `rg` with globs all
failed there (2026-10-12, plektra broker-fix agent). There the command runs as
written; everywhere else rtk rewrites it as before.
"""
import json
import subprocess
import sys

WORKTREE_MARK = "/.claude/worktrees/"


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except ValueError:
        return 0
    cwd = str(event.get("cwd") or "")
    if WORKTREE_MARK in cwd + "/":
        return 0
    try:
        done = subprocess.run(["rtk", "hook", "claude"], input=raw, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return 0
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
