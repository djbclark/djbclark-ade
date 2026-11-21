### Changed

- Claude Code now starts with `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` and no longer sets `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`
  (operator, 2026-11-21: stop using agent teams by default, use code mode by default), in `agents/claude/settings.json.tmpl` and in the
  Codex `[shell_environment_policy.set]` block that Claude children inherit. (#844)
- The Codex template's `[shell_environment_policy.set]` now also carries `CLAUDE_CODE_SUBAGENT_MODEL = "sonnet"` and
  `CLAUDE_CODE_FORK_SUBAGENT = "0"`, as the Claude template and the live config already did, so `codex-env-policy-apply` no longer
  sees them as drift. (#844)

### Added

- `bin/codex-env-policy-apply --allow-set-keys KEY[,KEY...]` (operator, 2026-11-21): a deliberate template change to the explicit
  `[shell_environment_policy.set]` keys can reach the live Codex config. The default is unchanged: any add, drop or change of a set key
  is refused; the flag permits exactly the keys it names and still refuses the rest, and the machine's browser digest key can never be
  allowed. (#844)
