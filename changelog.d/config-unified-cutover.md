### Changed

- Unified routing, gates, model tiers, install catalog and context budgeting in `config/ade.toml`, deleting the five legacy production config files and retaining one frozen repo-shaped fixture for explicit legacy readers and projection-drift tests. Added atomic, outside-byte-preserving `ade-model-tiers promote|set` writes to the unified tier subtree. Updated the active edit-surface documentation. (#766)

### Fixed

- Routed manual ClinePass dispatches through configured Pi with fully namespaced model IDs, kept the pool manual-only, made unified tier span scanning linear and TOML-string-aware, preserved writer reason metadata and exact suffix bytes, and made projection drift check parsed tier equality as well as outside-subtree bytes. (#766)
- Gave `research` a profile on every live pool, including claude and codex, which had none: no vendor here lacks research capability, and the two strongest pools were the ones excluded. Codex's `research` is also `plenty_kinds`-gated like its other everyday kinds. Kept `ade-harden` and `ade-github-setup` usable when `config/ade.toml` exists without their domain, instead of refusing on mere presence. (#766)
- Said why a kind cannot route instead of "no pool has room" when no live pool profiles it (`github`, `realtime-web`, and `api-only` after omp was archived), gave claude a last-resort `bulk`/`mechanical` rank behind every other pool, and documented that frontier order is a cost ordering (astra before Fable) rather than a model-quality claim. (#766)
