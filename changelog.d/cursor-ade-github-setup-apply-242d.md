### Added

- `ade-github-setup apply --yes` applies the merge-gate environment and
  ruleset via the GitHub API; `apply --verify` is API-only read-back of
  manifest + environment + ruleset (setup-plan S8) (#460).
- Just recipes `github-setup-apply` and `github-setup-verify` (#460).

### Changed

- `ade-github-setup apply --yes` refuses browser App create/install confirm
  (setup-plan S7) and refuses private-key / client-id store (operator stdin
  only; never prints PEM) (#460).
