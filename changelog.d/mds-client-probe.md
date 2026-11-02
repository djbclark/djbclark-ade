### Added

- `load-watch` mds probe (2026-11-01, approved by the lead): when Spotlight's `mds` has used 0.5+ cores for 2 minutes (`LW_MDS_CORES`, `LW_MDS_SUSTAIN_S`), one line per 30 minutes (`LW_MDS_COOLDOWN_S`) goes to the load-watch log with mds, Finder and the six busiest other processes. It needs no root, pings nobody and signals nothing; Finder's share is the cheap tell (the cause on 2026-11-01 was Finder re-listing `/private/tmp`, found by hand with root-only `sample` and `fs_usage`; XPC client pids from `lsmp` also need root). Test: `tests/test_load_watch_mds_probe.py`.
