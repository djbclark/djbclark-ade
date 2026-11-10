### Added

- `bin/gh-pr-checks` wraps `gh pr checks` and registers its own `deadline run` when `--watch` is set (`--no-deadline` opts out; default budget 20m); closes the `gh pr checks --watch` half of queue Carried #34 (#448).
