### Added

- `ade-user-install cursor-cli` and `hermes` replace curl|bash install paths;
  catalog `cursor-cli` / `hermes` now have `install_argv`, and `node` is a hard
  catalog row (Mac brew `system_argv_darwin`) for npm runtimes (#345).
- Split hard `npm` from `node` so doctor probes both; Hermes install child stdout/stderr
  is redirected so `ade-user-install hermes --json` stays parseable (#345).
- Non-dry-run Cursor/Hermes installs require `ADE_USER_INSTALL_TRUST_VENDOR=1` (TLS trust gate; no forever digest — order 8) (#345).
