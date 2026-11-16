### Changed

- Unified routing, gates, model tiers, install catalog and context budgeting in `config/ade.toml`, deleting the five legacy production config files and retaining one frozen repo-shaped fixture for explicit legacy readers and projection-drift tests. Added atomic, outside-byte-preserving `ade-model-tiers promote|set` writes to the unified tier subtree. Updated the active edit-surface documentation. (#766)
