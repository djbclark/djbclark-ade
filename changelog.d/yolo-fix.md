### Fixed

- `plugins/ade-yolo`: a ready, modeless Pi catalog is admitted as unattended by construction (Pi never raises permission requests), so ordinary Pi creates no longer refuse; the allowlist is Pi only (#605)
- `plugins/ade-yolo`: resuming an agent created before the plugin (no `ade-yolo.applied` stamp, Hermes included) with no saved mode evidence is now allowed and logged; drift and stamped-agent missing evidence still refuse (#605)

### Added

- `plugins/ade-yolo/README.md` canary and rollback procedure; `tests/test_ade_yolo_plugin.py` runs the plugin's offline node suite under pytest (#605)
