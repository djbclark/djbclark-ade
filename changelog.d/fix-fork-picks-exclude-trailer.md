### Fixed

- `bin/ade-fork-picks`: a branch or PR entry can carry an `exclude` list of commits apply must not pick (named in the output, an unmatched id reported as `exclude_unused`), and a commit whose `cherry-pick -x` trailer is already on HEAD counts as present when a rebase changed its patch-id, so a re-run on a new base is idempotent; the two v0.17.1 release commits (changelog and cut) are excluded from both Pi stack entries (#PR)
