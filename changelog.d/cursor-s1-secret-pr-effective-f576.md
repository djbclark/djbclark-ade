### Changed

- `bin/render-secret-deny`, `bin/review-launch`, and `bin/pr-policy` now read `secret_deny` / `pr_policy` through `ade_config.load_effective` (S1 consumer adoption; legacy `secret-deny.toml` / `SECRET_DENY_TOML` and `pr-policy.toml` / `PR_POLICY_TOML` when `ade.toml` is absent).
