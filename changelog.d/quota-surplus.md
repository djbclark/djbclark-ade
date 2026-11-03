### Added

- Added `bin/quota-surplus` (`check`, `notify`, `list-work`), a no-model "use it or lose it" watchdog that alerts once per window
  episode when a reset will throw away 15% or more of a usable pool at the current pace (frontier pools weighted higher; never
  prepaid credits or gated pools; stale readings give no verdict), pings Hermes and relays the live leads, plus the per-repo
  `docs/surplus-work.md` list format, the `quota-surplus` skill, `/quota-surplus`, and an unloaded launchd template (#270)
