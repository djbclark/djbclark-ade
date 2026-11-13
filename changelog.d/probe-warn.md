### Added

- Catalog component rows take optional `probe_warn_exit` (exit codes that mean advisory findings) and `probe_summary_re` (the
  probe output line shown as the detail). A listed exit whose stdout carries the summary line is `warn` (doctor exit 0), not
  `error`; a crash without that line stays `error`. Hermes sets both, so `ade-install doctor` no longer fails on `hermes doctor`'s
  advisory exit 1. (#642)

### Fixed

- `ade-install doctor` probe detail now skips box-drawing and blank lines instead of printing the first output line, which for
  Hermes was a border. `apply` treats a `warn` component as present, not blocked; `update` counts it healthy. (#642)
