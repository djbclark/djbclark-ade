### Added

- `bin/ade-release-ready`: dry-run first-release readiness gate (CI, rule 10, `ade-update`, empty tag slot); never creates or pushes a tag (`docs/release.md`) (#445).

### Fixed

- `bin/ade-release-ready`: require Unreleased entries after a prospective in-memory fold (same dedup as `changelog-fold`), so leftover fragments that only duplicate older CHANGELOG sections are not READY (#445).

### Security

- `bin/ade-release-ready`: run `changelog-fold` and `ade-roster` from the trusted script directory, never from `--repo` (#445).
- `bin/ade-roster` `tracked()`: disable `core.fsmonitor` / `core.fsmonitorHook` when inspecting `--root`, so an untrusted tree's hook cannot run via `git ls-files` (#445).
