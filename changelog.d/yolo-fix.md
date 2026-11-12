### Fixed

- `plugins/ade-yolo`: a ready, modeless Pi catalog is admitted as unattended by construction (Pi never raises permission requests), so ordinary Pi creates no longer refuse; the allowlist is Pi only (#605)
- `plugins/ade-yolo`: unstamped legacy agents (Hermes included) resume without mode mutation or catalog lookup even with saved mode/control drift or missing evidence; a warning names the agent id, provider and saved mode. Stamped-agent drift and missing evidence still refuse (#605)
- `plugins/ade-yolo`: document and test that Pi with a unique catalog-marked `isUnattended` mode is accepted like any other provider (#605)

### Added

- `plugins/ade-yolo/README.md` canary and rollback procedure; `tests/test_ade_yolo_plugin.py` runs the plugin's offline node suite under pytest (#605)
