### Added

- `ade-harden` S6 coverage: Forgejo read-back (`[hardening.forgejo]`), an
  operator drift notice, `ade-harden renew` for the expiring interaction limit
  (dry-run unless `--apply`; the only mutation a check authorizes), and the
  S5a gate canary (`[hardening.canaries]`, corpus outside the repo). `observe`
  stays read-only and CI runs the local check (#592).
