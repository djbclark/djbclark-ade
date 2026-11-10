### Added

- Folded `config/install.toml` (component/key/login) under `config/ade.toml` `[install]` via `ade-config fold`; `ade-install` prefers the folded catalog and falls through to transitional `install.toml` when `ade.toml` is absent or lacks `[install]` (#431).
