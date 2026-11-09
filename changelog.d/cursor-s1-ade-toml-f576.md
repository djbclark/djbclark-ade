### Added

- Committed `config/ade.toml` as the schema_version=1 repo base for policy domains (`ade-config fold --write` / `--check`); legacy split TOMLs remain for fallthrough when it is absent, and `ade-install` keeps transitional `config/install.toml` until install/keys are folded (#416).
