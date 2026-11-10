### Added

- `just browser-task` / `bin/ade-browser-task` (list, render, dry-run/send relay)
  with checked-in `prompts/browser/` templates (`github-app-create`, `pr-access`,
  `issue-access`) for setup-plan S7; live browser / completion verification
  deferred (#0).

### Security

- `ade-browser-task` refuses PEM / secret flags on argv and refuses
  `widens_access` templates / known widen task ids (S7 never-through-bot) (#0).
