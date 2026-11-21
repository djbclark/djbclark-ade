### Fixed

- `bin/ade-self-session finish` now repoints the supervisor's lead file (`$ADE_SUPERVISOR_STATE_DIR/lead`, default
  `~/.local/state/djbclark-ade/supervisor/lead`) from the archived predecessor to the successor, atomically, and reports
  `supervisor_lead` (`repointed`, `already-successor`, `unchanged-not-predecessor`, `unchanged-not-regular`, `absent`,
  `error`); a file naming another agent, a symlink or a missing file is never touched (#870)
