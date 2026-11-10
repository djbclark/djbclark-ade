### Added

- Folded `config/install.toml` (component/key/login) under `config/ade.toml` `[install]` via `ade-config fold`; `ade-install` prefers the folded catalog and falls through to transitional `install.toml` when `ade.toml` is absent or lacks `[install]` (#431).

### Fixed

- `ade-install` loads folded `[install]` through `ade_config.load_effective` so `local.toml` overlays apply to plan/doctor/apply, and a present but empty or invalid `[install]` fails validation instead of falling through to `install.toml` (#431).
