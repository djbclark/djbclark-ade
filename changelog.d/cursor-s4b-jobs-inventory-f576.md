### Added

- `config/install.toml` `[install.jobs]` / `[install.retired_jobs]` ADE jobs inventory (S4b) with schema and validation (#433).
- `ade-sched list` and `ade-sched diff` (and `just sched-list` / `just sched-diff`) compare the inventory to live launchd/systemd/cron/paseo schedules; doctor includes the same drift and never unloads foreign owners (#433).

### Fixed

- `ade-sched` imports the install catalog only for `list`/`diff`, so other subcommands stay usable on Python 3.10 without `tomllib` (#433).
- `ade-sched diff` / doctor treat Paseo probe timeouts/launch errors and failed host-scheduler scans as unknown, not empty or missing (#433).
