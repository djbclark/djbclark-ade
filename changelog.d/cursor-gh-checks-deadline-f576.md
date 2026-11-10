### Added

- `bin/gh-pr-checks` wraps `gh pr checks` and registers its own `deadline run` when `--watch` is set (`--no-deadline` opts out; default budget 20m); closes the `gh pr checks --watch` half of queue Carried #34 (#448).

### Fixed

- `bin/gh-pr-checks` forwards SIGTERM/SIGINT/SIGHUP to its `deadline run` supervisor and falls back to raw `gh pr checks` when deadline refuses or exits before the watch starts (docs/deadline.md "Never costs the wait") (#448).
