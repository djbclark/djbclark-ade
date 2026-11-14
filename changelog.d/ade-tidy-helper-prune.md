### Added

- `bin/ade-tidy prune [--apply] [--json] [--min-idle S]`: a machine-wide, observe-by-default prune that archives idle, finished Baton `[Handoff writer]` helpers (title and `baton-writer=1` label; parent archived/closed/gone or handoff provably written; no pending permission; never a lead, MAIN or the caller), one JSON log line per archive in `~/.local/state/ade/helper-prune.log`; `config/launchd/com.djbclark.ade-helper-prune.plist` (every 30 minutes, not installed by merging) and the `ade-helper-prune` inventory row (#690)
