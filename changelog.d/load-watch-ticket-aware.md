### Changed

- `load-watch ci decide DIR local "why"` no longer opens the `sudo-ask` Allow dialog when a live any-command `bgrun approve-local` ticket covers DIR (`bgrun approve-local check DIR` exits 0): it records the row, logs `lw-local-ticket` in `~/.local/state/bg/approvals.log` and names the ticket on stderr, so one Touch ID good for N hours also covers the CI-first decision. `pending` and `ci` never use a ticket, and a missing bgrun, a command-narrowed ticket, exit 1 or 2 or a timeout keep the old dialog path (#PR)
