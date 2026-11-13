### Changed

- `bin/ade-auto-permit --all-local` approves tool-permission prompts for every agent the local Paseo daemon lists, the lead included (audit reason `all-local`), so operator-started agents no longer stall; the launchd template passes it. In every mode a question or plan approval for the operator (`AskUserQuestion`, `ExitPlanMode`, Pi/OMP `select|input|editor|confirm`, missing tool names; a name-based fail-closed denylist) is logged `operator-question` and never answered. (#653)
