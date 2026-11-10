### Added

- Added `bin/ade-pi-pools probe` observe-only continuation/quota/identity probes for Pi pool acceptance (never writes `accepted=true`; never touches Claude API billing) (#450).

### Fixed

- Treated truthy string `paseo_unknown` (from `_fold_paseo`) as unknown quota in `ade-pi-pools probe`, so a descriptive fold no longer marks the pool ready (#450).
