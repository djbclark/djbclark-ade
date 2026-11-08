### Changed

- Reused an existing Paseo workspace on ordinary `acp-dispatch` launches via `--workspace`, verified caller inspect, or `PASEO_WORKSPACE_ID`, validated against `paseo workspace ls --json` and `-C`.
- Required explicit workspace selection when caller inspection omitted workspace identity or failed, instead of silently falling back to an ambient workspace.

### Fixed

- Stopped unconditional `--new-workspace local` on every child dispatch so advisors reuse the task workspace instead of minting one per slice.

### Removed

- Workspace creation from the shim (use native `paseo workspace create` / `paseo run --new-workspace` outside dispatch).
