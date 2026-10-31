# changelog.d

One file per pull request, named `<branch>.md` (the branch name with `/` replaced by `-`), instead of an edit to the shared `CHANGELOG.md`.
It holds the PR's entries under `### Added`, `### Changed`, `### Fixed`, `### Removed` or `### Security` headings, one `- ` line per user-visible change.
Same wording as before: past tense, every entry ends with the PR number as `(#N)`; a wrapped entry indents its continuation lines.
Only `bin/changelog-fold` edits `CHANGELOG.md`: whoever cuts a release, or the lead after merges, runs it; it folds every fragment into `## Unreleased` and deletes them.
`bin/changelog-fold --check` validates the fragments without writing; the test suite runs it on this directory, so a malformed fragment fails CI.
