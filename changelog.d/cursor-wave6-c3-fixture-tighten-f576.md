### Changed

- Tightened Wave 6 C3/Mac FIXTURE `--dry-run` FAILCLOSED path: require C3 FIXTURE labels + Linux-safe `cmd:`/`verified:` (or `waive:`) shape, report `mac_live_blocked`, and refuse FIXTURE / `--linux-safe` Mac proofs as deletion evidence (`mac_not_live`) (queue Carried item 33) (#470).

### Added

- `bin/wave6-mac-proof-capture --linux-safe` runs Linux-safe pgrep (+ optional paseo) probes with launchctl SKIPPED and `LINUX-SAFE — NOT Mac live-cycle` labels (Mac live cycle stays blocked) (queue Carried item 33) (#470).
