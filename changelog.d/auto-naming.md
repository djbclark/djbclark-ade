### Added

- `ade-window-name` Paseo plugin and `bin/ade_ws_autoname.py`: a new window gets a `<KIND> <repo> (<work>)` name when its first agent is
  created (WORKERS for an agent with a parent or `ade.lead` label, else MAIN), but only while the window has no title; a window named
  on purpose is never renamed. Operator-installed (`paseo plugin install`), dry run with `ADE_WINDOW_NAME_DRY_RUN=1`. (#666)
