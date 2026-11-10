### Added

- `ade-merge-ready approve-post` posts owner `adversary-verdict:v1` APPROVE comments for selected green `needs_approve` tips after `--i-reviewed --yes` (dry-run by default; refuses non-owner `gh`; optional `--trigger-marker`); documented in `docs/review-boundary.md`.

### Changed

- `ade-merge-ready approve-paste` and `docs/review-boundary.md` warn that herdr mangles HTML-comment markers; prefer `approve-post` (`gh pr comment` / GitHub API) or a non-herdr body edit until #484.
