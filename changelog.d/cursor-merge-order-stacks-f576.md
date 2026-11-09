### Added

- `bin/ade-merge-ready stacks` prints bottom-up APPROVE order for the install, claims (W2–W4), S1, and Wave 6 stacks from live open PR base→head refs, with full tip SHAs for paste-ready `adversary-verdict` templates (never invents or posts a marker) (#404).

### Fixed

- `ade-merge-ready` `link_parents` qualifies stack parents by head repository (`headRepository` / owner+name), not branch name alone, so a fork PR headed at `master` cannot parent every PR targeting the listing repo's `master`; ambiguous same-repo head names leave `parent_number` unset (fail-safe) (#404).
