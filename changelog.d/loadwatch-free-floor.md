### Changed

- Lowered the `load-watch admit` free-memory floor from 600 to 150 MB (`--min-free-mb`, `LW_MIN_FREE_MB`; 2026-11-01, operator): macOS free+speculative memory read 80-490 MB on an idle-ish host (`memory_pressure` 49% free, churn 2-4k/s of 20k, pageins under 100/s), so the old floor held a `bg` test run for over an hour; the compressor, pageins and agent-cap limits are unchanged (#232).
