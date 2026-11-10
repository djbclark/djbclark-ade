### Added

- `just harden-check` / `bin/ade-harden observe` reads transitional
  `config/hardening.toml` back from the GitHub API and exits nonzero on drift
  (setup-plan S6); observe-only — no ruleset writes, no interaction-limit
  auto-reapply (#TBD).
