### Added

- `config/install.toml` `[install.jobs]` / `[install.retired_jobs]` ADE jobs inventory (S4b) with schema and validation (#433).
- `ade-sched list` and `ade-sched diff` (and `just sched-list` / `just sched-diff`) compare the inventory to live launchd/systemd/cron/paseo schedules; doctor includes the same drift and never unloads foreign owners (#433).
