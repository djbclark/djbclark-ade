### Changed

- Worker placement is now one `workers <middle> <lead agent id>` window per lead, each worker tab named
  `worker <middle> <lead agent id>` (operator ruling 2026-11-13): `docs/workspace-layout.md` (naming, measured name-length
  limits), the `skills/fan-out` launch recipe (first launch mints the window and `paseo workspace rename`s it, later launches
  `--workspace`, `paseo agent update --name`, archive the window at the end) and `docs/orchestration-practices.md` replace
  the 2026-11-07 shared-tab arrangement and the one-window-per-launch "master" pile-up of env-stripped runs; a handoff
  successor stays a new lead with its own placement. (#625)
