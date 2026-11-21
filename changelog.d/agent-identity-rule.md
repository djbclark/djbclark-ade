### Added

- `bin/agent-id <AGENT_ID> [--json]`: prints the agent id, workspace name, and the window/tab and tab/pane placement fields for the harness the agent runs in, so any agent mentioning another to a human can name it fully (docs/agent-identity.md, operator rule 2026-11-20). Fields that do not apply or resolve print `?`. (#842)
