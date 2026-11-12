### Added

- `ade-harden` S6 coverage: Forgejo read-back through `forgejo-api`
  (`[hardening.forgejo]`), an operator drift notice printed by `observe`,
  `ade-harden renew` for the expiring interaction limit (dry-run unless
  `--apply`; the only mutation a check authorizes, and the read-back must show
  the expiry moved), and the S5a gate canary (`[hardening.canaries]`, corpus
  outside the repo; a configured but missing corpus fails the check).
  `observe` stays read-only and CI runs the local check (#592).
