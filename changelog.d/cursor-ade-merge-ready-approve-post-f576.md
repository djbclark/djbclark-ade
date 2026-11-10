### Added

- `ade-merge-ready approve-post` posts owner `adversary-verdict:v1` APPROVE markers for selected green `needs_approve` tips after `--i-reviewed --yes` (dry-run by default; refuses non-owner `gh`; optional `--trigger-marker`); `--via auto|body|comment` (default auto: body for owner-authored tips, comment for outside); `--yes` requires `--expect-head N=40hex` matching the live tip so a substituted head cannot be approved (#482).
- `ade-merge-ready merge-now --prs …` squash-merges only tips classified `merge_now` (pytest-linux pass + adversary-marker success); refuses otherwise so a raw `gh pr merge` cannot bypass the gate (#481 incident, 2026-11-10) (#482).

### Changed

- `ade-merge-ready approve-paste` and `docs/review-boundary.md` warn that herdr mangles HTML-comment markers; prefer `approve-post` (GitHub API, not herdr) (#482).
