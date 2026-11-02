### Changed

- `load-watch`'s compressor-churn alert got its own threshold, `LW_CHURN_ALERT_PAGES_S` (default 50000), instead of sharing the `admit` gate's 20000 limit, which paged the watcher every hour for standing memory pressure that was never an incident; the gate itself is unchanged (#TBD).
- `load-watch admit` refused on compressor churn above 20000 only when load (over 1.5 per core) or pageins corroborate thrash, or above 60000 on its own (`LW_CHURN_THRASH_PER_CORE`, `LW_MAX_COMPRESSOR_HARD_S`); standing churn with idle CPU had refused nearly every agent launch, review and test run for hours (#TBD).
