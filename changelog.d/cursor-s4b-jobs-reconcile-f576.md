### Added

- `ade-sched reconcile` (and `just sched-reconcile`) installs/reloads ADE-owned `ade-sched` jobs on systemd user units, writes the ownership ledger at `~/.local/state/djbclark-ade/jobs.json` (`ADE_JOBS_STATE_DIR`), and removes only ledger-owned labels; default dry-run, `--yes` executes; never unloads foreign/unknown owners or root/`--system` units (#461).

### Fixed

- Reconcile treats matching unit files as healthy only when the timer is active (completed oneshots without a timer may stay inactive); keeps implicit `--ade` so linked worktrees still refuse; preserves the old ledger identity across a label rename until removal completes (#461).
