### Added

- `bin/ade-merge-ready` classifies open ADE PRs against pytest-linux, adversary-marker, and live owner APPROVE (read-only; prints paste-ready marker templates, never invents a verdict) (#371).

### Fixed

- `ade-merge-ready` takes `live_approve` / `merge_now` only from the `adversary-marker` check (attribution-aware `decide`), not from an unfiltered body or comment marker scan (#371).
