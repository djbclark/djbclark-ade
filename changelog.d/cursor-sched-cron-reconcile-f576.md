### Added

- Extended `ade-sched reconcile --yes` to the user crontab write path (with systemd) so ADE-owned cron blocks install/remove through the `jobs.json` ledger; launchd remains refuse-backend (#511).

### Fixed

- Cron reconcile hash-match now compares the installed `# BEGIN ade-sched` block instead of a pseudo `Path("crontab")` file, and ledger removes refuse a different recorded backend (#511).
