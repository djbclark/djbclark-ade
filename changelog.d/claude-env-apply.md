### Added

- `bin/ade_settings_apply.py`: `--allow-env-key NAME` (repeatable) lets a single named `env` key be added when absent from live or removed when absent from the template. Empty by default: the `env` block is still never auto-added, so this is a narrow opt-in (mirrors `codex-env-policy-apply --allow-set-keys`), used when a template must set or clear a feature flag. (#846)
