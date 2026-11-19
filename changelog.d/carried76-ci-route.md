### Fixed

- `scripts/github-ci-run` now prefers the remote-tracking `ci/base` ref over a local branch, so a stale local `ci/base` no longer shadows the fixed remote workflow; it warns to stderr when a local branch is strictly behind. (#800)
