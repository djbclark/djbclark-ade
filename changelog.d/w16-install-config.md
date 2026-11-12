### Added

- `ade-config set` now writes string arrays and choices: `keys.NAME.verify_argv|components`, `context_budget.dirs`,
  and existing install rows by identity (`install.component.ID.chosen` and its argv/platform arrays,
  `install.jobs.NAME.chosen|set|platforms`, repo target only), plus `--create-key` for new key identities. Every edit
  is proved against the whole reparsed tree, the catalog schema and semantics (docs/config-migration.md C4). (#602)
- `ade-config export-unified [--write|--check]` generates `config/ade.toml` from the legacy domain files with their
  comments and proves the effective tree is identical; the tracked file waits for in-flight catalog edits (section F
  of docs/config-migration.md). (#602)

### Changed

- Pathless `model_tiers` readers, `ade-model-tiers` and the `context_size_nudge` hook accept `config/ade.toml` before
  anything writes it; the legacy tier writer refuses while `ade.toml` carries `[model_tiers]`. (#602)
