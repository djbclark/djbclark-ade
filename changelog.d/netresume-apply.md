### Changed

- `ade-net-resume`'s launchd template now runs the quota pass with `--apply`, so a provider-window stop is actually resumed instead of only logged as `would-resume-quota` (operator decision 2026-11-16: quota depletion must not stop the project). The per-pool gap, reservation, re-reads and lineage scoping are unchanged. (#766)
