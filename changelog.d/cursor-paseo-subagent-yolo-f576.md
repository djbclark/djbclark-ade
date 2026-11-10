### Added

- `plugins/ade-yolo`: on `agent.create.before`, set Claude/Codex/OpenCode/omp creates to Bypass / Full Access / build (+ OpenCode `auto_accept`) unless `plan`/`read-only` or metadata `ade-yolo.skip` (operator install; restores YOLO after Always Ask drift).
- `bin/paseo_yolo.py`: shared provider → unattended mode map for launches.

### Changed

- `acp-dispatch --perm all` and dialogue `paseo`/`acp` routes use YOLO modes from `paseo_yolo` instead of the provider's `defaultMode` (Wave 4 E6 plan drift that left seats in Always Ask).
