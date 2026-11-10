### Added

- `load-watch` mds probe ported from #231 onto Wave 6 master (2026-11-10): when root's Spotlight `mds` has used 0.5+ cores over consecutive samples spanning 2 minutes (`LW_MDS_CORES`, `LW_MDS_SUSTAIN_S`; a gap over `LW_MDS_MAX_GAP_S`, 90 s, restarts the span), one line per 30 minutes (`LW_MDS_COOLDOWN_S`) goes to the load-watch log with mds, Finder and the six busiest other processes by program name only. No root required, no pings, no signals. Master's Paseo agent-counting path is unchanged. Test: `tests/test_load_watch_mds_probe.py`. After this lands, close #231.
