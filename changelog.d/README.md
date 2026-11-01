# changelog.d

One file per pull request, named `<branch>.md` (the branch name with `/` replaced by `-`), instead of an edit to the shared `CHANGELOG.md`.
It holds the PR's entries under `### Added`, `### Changed`, `### Fixed`, `### Removed` or `### Security` headings, one `- ` line per user-visible change.
Same wording as before: past tense, every entry ends with the PR number as `(#N)`; a wrapped entry indents its continuation lines.
ONE writer folds: the lead, at release time or when it chooses, runs `bin/changelog-fold` in a fresh worktree from master and lands the result through a normal PR (it moves validated lines, deletes the fragments).
`bin/ade-update` lists unfolded fragments (so none is invisible) and warns about one older than 14 days on the revision it updates to (master's, on the canonical checkout); `bin/changelog-fold --check` validates without writing, and the test suite runs it on this directory.
An open PR that still edits `CHANGELOG.md` moves that hunk into its fragment at its next master merge.
