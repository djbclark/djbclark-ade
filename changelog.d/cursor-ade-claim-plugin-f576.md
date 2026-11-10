### Added

- Scaffolded Paseo plugin `plugins/ade-claim` that registers `worktree.create.after` and runs `ade_claims.py new` (not Mac-installed yet) (#336).

### Security

- `ade-claim` resolves `ade_claims.py` only from `ADE_CLAIMS_PY` or the plugin install tree, never from the new worktree's checkout (#336).
