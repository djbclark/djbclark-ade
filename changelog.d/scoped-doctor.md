### Added

- Added `ade-install doctor --id ID` and `just doctor hermes` for component-only
  checks with explicit result scope; unchosen components never probe and full
  doctor behavior stayed intact. (#540)

### Fixed

- Fixed pre-existing split printf format strings that prevented Just from
  parsing the Hermes setup recipe. (#540)
