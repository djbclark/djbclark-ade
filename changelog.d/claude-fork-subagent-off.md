### Changed

- Made `CLAUDE_CODE_FORK_SUBAGENT=0` a provisioned default in `agents/claude/settings.json.tmpl` and `bin/claude-settings-env`, so a new machine or rewritten settings file keeps the fork gate closed for Agent-tool background launches in interactive sessions, which keeps Claude Code's `agent_summary` background-agent label calls off (#PRNUM).
