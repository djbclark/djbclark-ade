### Added

- `bin/ade-settings-apply` (run by `bin/ade-update`; `--check` is a dry-run) applies the ADE-owned parts of `agents/claude/settings.json.tmpl` to the live `~/.claude/settings.json`: ADE hooks whose script exists in the djbclark-ade tree, matched by script path (live form wins), a `permissions.deny` union, and template keys absent from live (such as `sandbox`); it backs up first, writes atomically, never removes or overwrites a live value, and refuses if a live key path would vanish. The template was re-refreshed from the merged result (docs/claude-settings-apply.md). (#759)
