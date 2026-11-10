### Added

- `bin/render-secret-deny` now writes `sandbox.filesystem.denyRead` into `agents/claude/settings.json.tmpl` from
  `[claude] static` (home-anchored `~/**/…` for bare names; exact `~/…` credential paths kept). Render owns that array
  and does not set `sandbox.enabled`; applying denyRead / enabling the sandbox in live `~/.claude/settings.json` stays
  an operator order-11 step. Docs: `docs/secret-deny.md` C3/D2–D4; queue Carried #1. (#405)
