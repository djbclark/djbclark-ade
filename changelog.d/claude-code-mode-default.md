### Changed

- Claude Code now starts with `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` and no longer sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
  (operator, 2026-11-21: stop using agent teams by default, use code mode by default). Changed in
  `agents/claude/settings.json.tmpl` and in the Codex `[shell_environment_policy.set]` block that Claude children inherit.
