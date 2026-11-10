### Added

- `just github-setup` / `bin/ade-github-setup` (observe, plan, dry-run) with
  checked-in `.github/app-manifest.json` and transitional `config/github.toml`
  for setup-plan S8 merge-gate App setup; secrets refuse argv; live
  `apply --yes` deferred (#412).

### Changed

- `ade-github-setup observe` probes App installation via
  `GET /user/installations` (operator `gh` creds), not the App-JWT
  `repos/.../installation` endpoint (#412).

### Security

- `ade-github-setup` refuse messages for equals-form secret flags
  (`--token=<value>`) report only the normalized flag name, never the value
  (#412).
