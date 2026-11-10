### Added

- `ade-merge-ready approve-paste` prints paste-ready `adversary-verdict:v1` APPROVE templates (`--base`, `--bottoms-only`) without inventing or posting markers; documented in `docs/review-boundary.md` Operator merge order (#474).

### Fixed

- `ade-merge-ready` lists up to 500 open PRs so stack bottoms are not dropped when more than 100 PRs are open (#474).
