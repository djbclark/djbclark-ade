### Added

- `config/model-tiers.toml` plus `bin/model_tiers.py` / `bin/ade-model-tiers` so frontier/judgment/everyday/bulk roles are data; `promote`/`set` update the file atomically (no secrets); `route_agent` and `ade_config.load_effective` read it (#401).

### Fixed

- Copilot `{id_dotted}` now preserves the model-name prefix and only dots the numeric version suffix (`claude-opus-5.5`, not `claude.opus.5-5`) (#401).
- After `promote` reuses a shared alias, displaced same-family roles resolve to their canonical ids so judgment fallback does not keep returning the new frontier (#401).
