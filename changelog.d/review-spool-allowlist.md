### Fixed

- `bin/review-launch`: a review may read a regular `toolu_*.txt` in its own session's oversized-output spool, which lives outside the worktree, instead of being killed for it. Only that exact file is exempt; a symlinked Read trips even when the link resolves inside the worktree, because `realpath` follows it. This stops a frontier review losing paid work for touching the harness's own spool (operator ruling 2026-11-20).
