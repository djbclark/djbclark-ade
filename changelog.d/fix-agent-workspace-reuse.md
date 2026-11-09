### Changed

- Reused an existing Paseo workspace on ordinary `acp-dispatch` launches via `--workspace`, verified caller inspect, or `PASEO_WORKSPACE_ID`, validated against `paseo workspace ls --json` and `-C`. (#309)
- Required explicit workspace selection when caller inspection omitted workspace identity or failed, instead of silently falling back to an ambient workspace. (#309)

### Fixed

- Stopped unconditional `--new-workspace local` on every child dispatch so advisors reuse the task workspace instead of minting one per slice. (#309)

### Removed

- Workspace creation from the shim (use native `paseo workspace create` / `paseo run --new-workspace` outside dispatch). (#309)
