### Added

- Scheduled the daily S3b `keys-check` job (`config/launchd/com.djbclark.keys-check.plist`, `just keys-check-install`) so `ade-install keys` can run observe-only on a timer without waiting on `update --auto` (#508).
