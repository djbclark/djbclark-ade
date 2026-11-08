### Added

- Versioned read-only effective config loader (`bin/ade_config.py`), `bin/ade-config
  check|get|diff`, checked-in `config/ade.schema.json`, thin `just config-check`, and
  `docs/config-migration.md` for schema_version=1 legacy routing/gates projection (no
  reader adoption, no live config writes). (#308)
### Fixed

- Rejected malformed new/local config before normalization, preserved legacy routing
  validation/defaults and unusable-input errors, and merged raw gate/floor overlays
  before clamping in all read-only config commands. (#308)
- Rejected raw service duplicates before routing isolation, preserved explicit CLI
  root/home targets in every option position, and disabled local loading for diff baselines. (#308)
