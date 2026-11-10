### Added

- `ade-install linux-e2e` / `just linux-e2e`: Linux one-step prove path chaining `doctor` (hard-dep probes + linger), `keys` (`sudo-secretspec check`, no values), and hard-id apply `--dry-run` with Linux `system_argv` preview (no Mac; never sudo; never enable-linger) (#PR).
- `ade-install keys` / `just keys`: observe-only bulk key presence via `sudo-secretspec check` (no values; missing binary → unknown) (#PR).
