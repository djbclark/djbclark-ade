### Added

- Added dry-run-default `ade-install bootstrap`; explicit `--yes` acquired only
  missing user-scoped Just, verified it, and continued to `just install --dry-run`,
  stopping on acquisition or verification failure without claiming full setup. (#550)
