### Added
- Restored archive-only `/session-finder` searches and explicit data-only refreshes for retained omp, OpenCode, Crush and Pi history without requiring their executables. (#310)

### Changed
- Retired automatic routing through uninstalled omp and OpenCode clients while preserving their pool metadata for the Pi migration. (#310)

### Fixed
- Preserved indexed history when a client, adapter or source log was unavailable, instead of pruning a retired client's sessions. (#310)
