### Changed

- Unified routing, gates, model tiers, install catalog and context budgeting in `config/ade.toml`, deleting the five legacy production config files and retaining one frozen repo-shaped fixture for explicit legacy readers and projection-drift tests. Added atomic, outside-byte-preserving `ade-model-tiers promote|set` writes to the unified tier subtree. Updated the active edit-surface documentation. (#766)

### Fixed

- Routed manual ClinePass dispatches through configured Pi rather than the unconfigured native provider, kept the pool manual-only, made unified tier span scanning linear and TOML-string-aware, and made projection drift compare canonical tier data instead of regenerated formatting. (#766)
