### Added

- `bin/changelog-fold [--check] [--repo DIR]` (2026-10-31) folds the `changelog.d/<branch>.md` fragments into `CHANGELOG.md`'s `## Unreleased` (new entries at the top of each subsection in file-name order, missing subsections created in Keep a Changelog order, an entry already present skipped so a rerun cannot duplicate), writes the file atomically and deletes the folded fragments; `--check` validates headings and the `(#N)` ending without writing; exit 0 folded, nothing to fold or valid, 1 invalid fragment (nothing written or deleted), 2 usage error or no `CHANGELOG.md` (#186).

### Changed

- A pull request now adds its changelog line as a `changelog.d/<branch>.md` fragment instead of editing the shared `## Unreleased` block of `CHANGELOG.md`, so a merge no longer makes every other open PR conflict there; AGENTS.md code review rule 10 says so, and order 9's staged list marks "CHANGELOG fragments" done (#186).
