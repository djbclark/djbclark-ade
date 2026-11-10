### Added

- `just harden-check` / `bin/ade-harden observe` reads transitional
  `config/hardening.toml` back from the GitHub API and exits nonzero on drift
  (setup-plan S6); observe-only — no ruleset writes, no interaction-limit
  auto-reapply (#452).

### Fixed

- `ade-harden` inventory lists private repos via authenticated
  `/user/repos?affiliation=owner` and `/orgs/{owner}/repos?type=all` (not
  public-only `/users/{owner}/repos`), and `_gh_json` parses a complete JSON
  document before falling back to NDJSON (#452).

### Security

- `ade-harden` enum-validates `interaction_limits.expiry` at load and renders
  `just harden` remediation hints with `shlex.join`, so an attacker-controlled
  `--root` tree cannot inject shell metacharacters into displayed commands
  (#452).
