### Added

- `bin/ade-job-run LABEL -- COMMAND...`: every ADE launchd job in `config/launchd/com.djbclark.*.plist` now starts through
  it. Each run holds a shared `flock` on a per-label admission lock (`<jobs state dir>/admission/LABEL.lock`) for the whole
  run, and skips (exit 0, one log line) while `ade-sched reconcile` holds the lock exclusively. `reconcile` can now reload
  or remove a LOADED job whose installed plist provably routes through the wrapper, is ledger-owned with a matching hash
  and was loaded from that plist: it takes the lock exclusive without waiting (a run in flight defers the step, nothing is
  killed), keeps it across `bootout`, write, `bootstrap` and read-back, restores the prior bytes if the new ones fail, and
  leaves a durable recovery record that the next `reconcile` acts on after a kill. Jobs not routed through the wrapper,
  including every existing install, keep the exit-6 deferral until migrated once (docs/scheduling.md). (#622)
