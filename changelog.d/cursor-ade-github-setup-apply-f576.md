### Added

- Added `ade-github-setup apply --yes` for the merge-gate environment and
  ruleset via the GitHub API, and `apply --verify` for API-only read-back of
  manifest + environment + ruleset (setup-plan S8) (#462).
- Added Just recipes `github-setup-apply` and `github-setup-verify` (#462).

### Changed

- Made `ade-github-setup apply --yes` refuse browser App create/install confirm
  (setup-plan S7) and refuse private-key / client-id store (operator stdin
  only; never prints PEM) (#462).
- Made environment deployment-branch-policies require exactly the configured
  branch (type=branch): `apply --yes` deletes leftovers; `apply --verify`
  fails when extras remain (#462).
