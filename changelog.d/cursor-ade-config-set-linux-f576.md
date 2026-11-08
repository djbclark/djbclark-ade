### Added

- `ade-config set PATH VALUE [--target local|repo] [--string] [--dry-run]` comment-preserving
  atomic scalar writer (`bin/ade_config_edit.py`): default local records per-machine choices;
  repo edits `config/ade.toml` when present otherwise the legacy domain file; reports
  `adoption=recorded-only` until `route_agent` / `ade_gates` adopt the effective-config reader (#318).
