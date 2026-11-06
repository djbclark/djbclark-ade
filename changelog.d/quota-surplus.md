### Added

- Added `bin/quota-surplus` (`check`, `notify`, `list-work [--pool]`), a no-model "use it or lose it" watchdog that alerts once
  per window episode, and a pool at most once a day, when a reset will throw away 15% or more of a usable pool at the current
  pace, only on pools where running out is fine (agy, omp API credits, codex, zcode, cursor, grok; never the Claude
  subscription, opencode-go or cline); stale, exhausted and just-reset readings give no verdict. It pings Hermes and relays
  the live `LEAD` seats. Also added the per-repo `docs/surplus-work.md` list format, the `quota-surplus` skill,
  `/quota-surplus`, and an unloaded launchd template (#270)
