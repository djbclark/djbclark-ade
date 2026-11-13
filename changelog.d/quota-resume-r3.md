### Fixed

- Changed `bin/ade-net-resume --quota` to skip a malformed `quota-wait` ledger row (missing or mistyped field, or an unparseable `resets_at`/`updated_at`) with one keyed `quota-ledger-invalid` warning instead of ending the whole run with exit 2; a wholly unreadable `events.jsonl` still exits 2. (#614)
- Corrected `docs/net-resume.md` and the `--quota-per-pool` help: the flag only changes dry-run counting because the 600 s pool gap limits `--apply`; ledger rows are keyed per error event or per clock-aligned ten-minute bucket as listed. (#614)
- Added tests for `updated_at` validation, the skip-and-warn behaviour (the network pass still ran) and the future-`UpdatedAt` `stale` note carrying no `stage`. (#614)
