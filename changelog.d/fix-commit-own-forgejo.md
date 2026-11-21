### Fixed

- `bin/git-commit-own` publishes to a `forgejo.mit.edu` https remote through `git-forgejo` (ls-remote, fetch and push), so the publish step no longer fails with "could not read Username"; a Forgejo remote with no `git-forgejo` on PATH exits 3 naming it, and other remotes keep plain git (#PR)
