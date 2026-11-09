### Added

- `just doctor`, `just install`, and `just update` as setup-plan S2 names over `ade-install` / `ade-update` (#359).
- `config/launchd/com.djbclark.ade-update-check.plist` for a daily `ade-update --check` via `ade-sched` (operator install) (#359).

### Fixed

- Documented `--set __STATE__=$HOME/.local/state/ade` for installing `com.djbclark.ade-update-check` (unfilled `__STATE__` exits 2) (#359).
