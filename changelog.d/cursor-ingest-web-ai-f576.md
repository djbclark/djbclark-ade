### Added

- Carried #23 design/spike: `docs/ingest-web-ai.md` (sources, S1 sink, trust boundary, operator gates, MVP vs later) and offline stub `skills/ingest-web-ai` (`normalize_export.py` + synthetic fixtures; no network, no credentials, no S1 writes) (#439)

### Fixed

- `normalize_export.py` fallback `conversation_id` includes export ordinal and content fingerprint so multi-conversation exports without ids/titles/timestamps no longer collide at the S1 locator (#439)
- `normalize_export.py` reads at most 32 MiB + 1 byte before refusing oversize input, so the size gate fails closed without allocating the whole file (#439)
