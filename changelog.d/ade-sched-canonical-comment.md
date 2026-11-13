### Fixed

- `bin/ade-sched`'s generated-by comment names the plist canonically (repo-relative POSIX path under the ADE root, resolved
  absolute otherwise), so a relative install, an absolute install, a symlinked path and a worktree all render identical
  artifacts and `reconcile` no longer plans an install/reload of an otherwise identical job. Older installs differ in that
  one comment line; a loaded launchd job still defers untouched, and docs/scheduling.md says how to adopt by a comment-only
  rewrite. (#620)
