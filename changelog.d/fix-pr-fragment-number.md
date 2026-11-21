### Added

- `bin/ade-pr-open`: opens a PR with `gh pr create` and fills the `(#PR)` placeholder in the branch's own changelog fragment with the new PR number, checks it with `changelog-fold --check`, then commits and pushes that file, so a fragment written before the PR exists no longer turns CI red; `docs/dispatch-footer.md` item 25, `skills/fan-out/SKILL.md` and `changelog.d/README.md` now say to write `(#PR)` first (#PR)
