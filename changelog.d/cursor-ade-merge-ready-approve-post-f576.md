### Added

- `ade-merge-ready approve-post` posts owner `adversary-verdict:v1` APPROVE markers for selected green `needs_approve` tips after `--i-reviewed --yes` (dry-run by default; refuses non-owner `gh`; optional `--trigger-marker`); `--via auto|body|comment` (default auto: body for owner-authored tips, comment for outside); documented in `docs/review-boundary.md`.

### Changed

- `ade-merge-ready approve-paste` and `docs/review-boundary.md` warn that herdr mangles HTML-comment markers; prefer `approve-post` (GitHub API, not herdr).
