### Fixed

- `bin/ade-install doctor` no longer fails on a slow healthy sub-doctor: a `[[component]]` row in `config/install.toml` may set an optional
  `probe_timeout_s` (positive number of seconds, at most 3600, range-checked by the catalog loader (both schemas only type-check it); documented in `docs/install-catalog.md`)
  that replaces the global 15 s probe timeout for that row only. The `hermes` row sets it (`hermes doctor` runs ~44 connectivity checks and
  took more than 15 s). A probe that still times out stays `error`. (#646)
