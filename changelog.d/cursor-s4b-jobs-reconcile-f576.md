### Added

- `ade-sched reconcile` (and `just sched-reconcile`) installs/reloads ADE-owned `ade-sched` jobs on systemd user units, writes the ownership ledger at `~/.local/state/djbclark-ade/jobs.json` (`ADE_JOBS_STATE_DIR`), and removes only ledger-owned labels; default dry-run, `--yes` executes; never unloads foreign/unknown owners or root/`--system` units (#TBD).
