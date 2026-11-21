### Fixed

- `bin/ade-update` reads `skill-everywhere --check`'s `error: paseo skill is <state> on <tui>` lines as rows of a `paseo` pseudo-skill instead of a helper failure (exit 4): a missing Hermes link is a fixable link gap (exit 10 on `--check`, repaired on apply by the new `skill-everywhere paseo`), and `paseo` missing from a claude/codex/pi dir that Paseo's daemon syncs is a stuck row (exit 10, documented for hosts that never sync Paseo's skill). docs/skill-everywhere.md section 3a now says the Hermes link and the check need `paseo` selected. (#PR)
