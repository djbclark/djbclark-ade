### Added

- Committed `config/ade.toml` as the schema_version=1 repo base for policy domains (`ade-config fold --write` / `--check`); legacy split TOMLs remain for fallthrough when it is absent, and `ade-install` keeps transitional `config/install.toml` until install/keys are folded (#416).

### Fixed

- Fold emitter writes nested section tables for gates/pr_policy/context_budget/secret_deny (matching the prior split TOML shape) so `ade-config set` can edit scalar leaves; floor records and `budget."~"` stay inline (#416).
