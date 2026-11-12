### Added

- `ade-install update` (and `just update` with no arguments) now executes each
  catalog candidate's own recorded `update_argv` with evidence: default
  `--dry-run` previews candidates with pre-observation and exact argv; `--yes`
  runs the argv (argv lists, never shell strings; `system_argv` and
  `paseo_plugin` rows are never touched), runs a scoped doctor over the updated
  ids, retries each doctor-failing component once and reports it (never rolls
  back), and writes outcome evidence atomically to
  `~/.local/state/djbclark-ade/updates.json`. Exit 1 when an update command
  fails or an updated component still fails doctor after its retry. (#583)

### Changed

- `ade-update-auto` gained `--apply` (S4 options 2–3, operator ruling
  2026-11-12): the scheduled apply now skips while any machine-wide Paseo agent
  is mid-turn (`paseo ls -g --background --json`; unknown fleet readings defer
  too) and records deferrals and the applying intent durably in
  `~/.local/state/djbclark-ade/update-auto.json` (deferral exits 6), applies
  the checkout fast-forward plus dependency updates, and sends one
  hermes-ping per failed run (`ADE_UPDATE_HERMES_PING` overrides the tool).
  `ade-update --auto --apply` dispatches to it. No launchd/systemd/cron job is
  installed or loaded by the repository; the daily check job stays check-only.
  (#583)
