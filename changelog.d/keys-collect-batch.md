### Added

- Added `ade-install keys-collect` / `just keys-collect`: one interactive batch of
  `sudo-secretspec set` on inherited terminal stdio for the selected keys that are
  missing, failing or expiring within 14 days, with immediate re-verify, retry/skip,
  a summary table and launch-time delivery through `sudo-secretspec run`; without a
  terminal it lists key names and exits 3. Offline-tested only; no live vault. (#597)
