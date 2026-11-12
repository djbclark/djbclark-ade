### Added

- `ade-harden` S6 coverage: Forgejo read-back through `forgejo-api`
  (`[hardening.forgejo]`), an operator drift notice printed by `observe`,
  `ade-harden renew` for the expiring interaction limit (dry-run unless
  `--apply`; the only mutation a check authorizes, the read-back must show the
  expiry moved, and a failed PUT exits nonzero), and the S5a gate canary
  (`[hardening.canaries]`, corpus outside the repo with `~` expanded; a
  configured but missing corpus fails the check). A malformed Forgejo
  `base_url` is a validation error, not a traceback. `observe` stays
  read-only and CI runs the local check (#592).
