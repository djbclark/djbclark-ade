### Added

- Documented the Claude `sandbox.filesystem.denyRead` operator trial (proposed entries mirroring
  `[claude] static`, apply steps, risks, rollback) in `docs/claude-denyread-trial.md`; queue Carried #1 and
  `docs/secret-deny.md` C3 cite it. No live `~/.claude` apply (order 11). Codex parallel: PR #446. (#451)

### Security

- Required `sandbox.allowUnsandboxedCommands: false` and `sandbox.failIfUnavailable: true` in the
  Claude denyRead trial plan so a `bypassPermissions` unsandboxed retry cannot bypass `denyRead`
  via `dangerouslyDisableSandbox`. (#451)
