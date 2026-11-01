### Fixed

- Fixed the sibling `RecursionError` readers of #98 (2026-11-01): `guard_level`, `read_state`, `read_snapshot` and the `paseo-set-model list` read in `bin/claude-fleet-governor`, and `load_state`, `read_snapshot` and the aiuse output read in `bin/claude-quota-guard`, treat a deeply nested JSON file as unreadable (the usual fail-safe: level `ok`, empty state, no reading, or the existing unreadable exit 10) instead of crashing (#214).
