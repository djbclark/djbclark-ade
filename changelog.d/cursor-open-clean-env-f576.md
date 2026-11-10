### Added

- `bin/open-clean`, a drop-in for macOS `open` that runs `/usr/bin/open` with only HOME, USER, LOGNAME, a fixed PATH, LANG/LC_* and TMPDIR, so an app an agent launches no longer inherits the agent's session variables (`CLAUDE_CODE_CHILD_SESSION` had reached Ghostty and its shells through Quicksilver); `claude/hooks/bash_habits_gate.py` (Claude Code, Codex, Cursor) denies a bare `open` and names it, and `env -i ... open` passes; dispatch-footer rule 23 and the apply-toolchain roster list it (#256)
