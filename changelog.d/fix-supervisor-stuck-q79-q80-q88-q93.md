### Fixed

- `bin/ade-pi-stuck`: read aiuse schema-1.8 `unavailable` pools as `usable: False` so exhausted and near-empty `opencode:go` and `clinepass:default` sub-accounts flag as exhausted instead of `unmapped` (Carried 88, 80) (#PR)
- `bin/ade-pi-stuck`: fall back to reading `~/.cache/aiuse/snapshots/latest.json` (overridable via `AIUSE_SNAPSHOT`, fail-closed on symlinks/non-regular/world-writable/oversized/empty files) marked stale when `aiuse --available --json` times out under load, keeping `KNOWN_EMPTY` fail-closed and reporting `quota_source` (Carried 93) (#PR)
- `bin/ade-supervisor-scan`: write `.redirect-noted.*` on first redirect resolution and gate only the `ADE_SUPERVISOR_LEAD` "still names" hint on successful delivery via `.redirect-env-noted.*`, stopping quiet runs from repeating redirect lines every 300 s (Carried 79) (#PR)
