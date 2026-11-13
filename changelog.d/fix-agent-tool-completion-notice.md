### Fixed

- Agent-tool sub-agents following the delivery footer no longer fail with "Agent not found: main": footer rule 22 tells them to skip the Paseo completion notice (the Agent tool already returns their final message), and `bin/completion-notice --send --requester main|team-lead` sends nothing and exits 0 with a clear message (#648)
