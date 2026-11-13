### Changed

- Documented worker placement as one `workers <middle> <lead agent id>` window per lead, each worker tab named
  `worker <middle> <lead agent id>` (operator ruling 2026-11-13): `docs/workspace-layout.md` (naming, measured name-length
  limits), the `skills/fan-out` launch recipe (the first launch minted the window, whose id is read from the launch itself,
  then `paseo workspace rename`; later launches `--workspace`; `paseo agent update --name`; archive the window only when no
  live labelled agent remains) and `docs/orchestration-practices.md` replaced the 2026-11-07 shared-tab arrangement and the
  one-window-per-launch "master" pile-up of env-stripped runs; a handoff successor stayed a new lead with its own
  placement. (#625)
