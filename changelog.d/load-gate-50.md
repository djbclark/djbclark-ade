### Changed

- `bin/load-watch`: `ADMIT_PER_CORE` rises from 2.0 to 5.0 (now env-overridable via `LW_ADMIT_PER_CORE`) and `ADMIT_BOOST_PER_CORE` from 4.0 to 5.0, per the operator ruling (2026-11-21) that bigmac's 10-core Mac stays usable at load 50. Runaway-process and thrash alerts are unchanged (`LW_MIN_CORES` 1.5, compressor churn 50k pages/s, Chrome 0.9 cores).
