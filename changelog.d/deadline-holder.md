### Added

- `deadline start --holder PID` (notify/relay records only): the process whose heartbeats keep the record. When it is gone (pid and start
  time verified) and `done` was never called, the sweep retires the record silently as the new terminal state `abandoned` (one `abandoned
  (holder N gone)` line in `sweep.log`, no owner notice, no Hermes ping, no recovery); a record without `--holder` behaves as before. The
  holder is never signalled, so the ancestor-pid refusal does not apply to it. (#266)

### Fixed

- `bg` no longer sends false "expired ... Recover: rerun the unfinished part" notices for runs that never started or whose process group was
  killed: its run record is registered only once the run has started, and both its `bg-wait-*` and `bg-run-*` records carry a `--holder`. (#266)
