### Changed

- `bin/render-secret-deny` (default path) and `bin/review-launch` (default deny list) now read the `secret_deny` domain through `ade_config.load_effective` (S1 consumer adoption; legacy `secret-deny.toml` / `SECRET_DENY_TOML` when `ade.toml` is absent; the hook still reads the rendered JSON) (#388).
