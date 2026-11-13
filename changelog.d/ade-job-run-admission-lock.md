### Added

- `bin/ade-job-run --lock-dir DIR LABEL -- COMMAND...`: every ADE launchd job in `config/launchd/com.djbclark.*.plist` now starts through
  it. Each run holds a shared `flock` on a per-label admission lock (`DIR/LABEL.lock`, DIR an absolute argv value) for the whole
  run, and skips (exit 0, one log line) while `ade-sched reconcile` holds the lock exclusively. `reconcile` can now reload
  or remove a LOADED job whose installed plist provably routes through the wrapper, is ledger-owned with a matching hash
  and was loaded from that plist with that lock directory in its LOADED argv and a wrapper that is this checkout's own `ade-job-run` (path, bytes, `--admission-protocol v1`): it takes the lock exclusive without waiting (a run in flight defers the step, nothing is
  killed), keeps it across `bootout`, write, `bootstrap` and read-back, restores the prior bytes if the new ones fail, and
  leaves a durable recovery record that the next `reconcile` acts on after a kill. Jobs not routed through the wrapper,
  including every existing install, keep the exit-6 deferral until migrated once (docs/scheduling.md). Every other ADE plist writer (`ade-sched install`/`uninstall`, native install, recovery) takes the same lock without waiting and refuses while a run holds it, and every locked replace, unlink and restore re-checks the plist's inode and bytes right before the syscall. (#622)
