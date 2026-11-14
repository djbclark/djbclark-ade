### Fixed

- `agent_footer_gate` denies launching an Agent-tool sub-agent whose report path already exists without its `.done` (an interrupted earlier sub-agent) and says to resume it with SendMessage; a deliberate fresh start adds a `Relaunch-reason: <why>` prompt line (allowed, logged). docs/orchestration-practices.md section 5 rule 10. (#691)
