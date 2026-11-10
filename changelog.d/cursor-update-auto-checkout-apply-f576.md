### Added

- `ade-update --auto --apply-checkout` / `ade-update-auto --apply-checkout` (also
  `ADE_UPDATE_AUTO_APPLY=1`): when `--check` reports behind, runs bare `ade-update` for
  **this checkout only** (S4 option 1). Default without the flag stays observe-only
  exit 5; the `update-auto` schedule plist, mid-turn skip, and failure ping remain
  pending (#0).
