### Changed

- Unified routing, gates, model tiers, install catalog and context budgeting in `config/ade.toml`, deleting the five legacy production config files and retaining one frozen repo-shaped fixture for explicit legacy readers and projection-drift tests. Added atomic, outside-byte-preserving `ade-model-tiers promote|set` writes to the unified tier subtree. Updated the active edit-surface documentation. (#766)

### Fixed

- Routed manual ClinePass dispatches through configured Pi with fully namespaced model IDs, kept the pool manual-only, made unified tier span scanning linear and TOML-string-aware, preserved writer reason metadata and exact suffix bytes, and made projection drift check parsed tier equality as well as outside-subtree bytes. (#766)
- Gave `research` a profile on every live pool, including claude and codex, which had none: no vendor here lacks research capability, and the two strongest pools were the ones excluded. Codex's `research` is also `plenty_kinds`-gated like its other everyday kinds. Kept `ade-harden` and `ade-github-setup` usable when `config/ade.toml` exists without their domain, instead of refusing on mere presence. (#766)
- Said why a kind cannot route instead of "no pool has room" when no live pool profiles it (`github`, `realtime-web`, and `api-only` after omp was archived), gave claude a last-resort `bulk`/`mechanical` rank behind every other pool, and documented that frontier order is a cost ordering (astra before Fable) rather than a model-quality claim. (#766)
- Made claude's `bulk`/`mechanical` a structural last resort (`fallback_kinds`), because a weak rank alone let it win against a usable pool that was merely headroom- or pace-penalised; the unprofiled-kind diagnostic now ignores retired pools; and the Argon/Claude research policy comments and the frontier cost-ordering prose now match what the code does. (#766)
- Corrected Argon's research rank to 24 so it sits behind cursor/zai and cursor-cloud rather than ahead of them, and documented that `fallback_after` gates every requested kind, not only `frontier`. (#766)
