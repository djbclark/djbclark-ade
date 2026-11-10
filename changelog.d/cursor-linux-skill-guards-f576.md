### Changed

- `skill-everywhere` still uses `~/src/djbclark-ade/skills` when that checkout exists, and otherwise finds the skills dir from its own location (a linked worktree resolves to its primary checkout), so it works on hosts whose checkout lives elsewhere (revived from closed #292 / #279). (#0)
- `paseo-set-model` without its Paseo Helper (or `PASEO_SET_MODEL_HELPER`) refuses with explanatory exit 69 instead of a late OSError exit 1 (revived from closed #292 / #279). (#0)
