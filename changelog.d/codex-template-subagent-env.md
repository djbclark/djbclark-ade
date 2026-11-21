### Changed

- The Codex template's `[shell_environment_policy.set]` now carries `CLAUDE_CODE_SUBAGENT_MODEL = "sonnet"` and
  `CLAUDE_CODE_FORK_SUBAGENT = "0"`, as the Claude template and the live config already did (operator, 2026-11-21), so
  `codex-env-policy-apply` no longer sees them as drift and would not drop them.
