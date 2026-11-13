### Added

- `ade-sched install` and `ade-sched uninstall` take `--restart-service` (low-level `install(..., restart_service=True)` /
  `uninstall(..., restart_service=True)`): the one way to replace or remove a LOADED launchd job that is not wrapped in
  `bin/ade-job-run`, and only for a KeepAlive service that does not run through `ade-job-run` (the `launchctl print` of the
  LOADED job must itself show KeepAlive and its path must be the installed plist; the installed file must provably be the
  loaded definition and have a truthy KeepAlive; an install also needs the new definition's KeepAlive; any loaded argv that
  contains an `ade-job-run` under any name is refused, use `migrate-wrapper`). The flag is accepted before or after the
  subcommand, and acts on any loaded KeepAlive user agent the operator names. It is a deliberate service restart: the
  `bootout` stops the running service. The label's canonical lock is still taken exclusive without waiting (a busy lock
  refuses), the recovery record and the prior bytes are saved before the `bootout`, the unload is proven, and the prior
  definition is restored if the new one fails (the record stays if the restore fails). Without the flag, and for a non-KeepAlive
  unwrapped job, the refusal is unchanged. (#626)

### Changed

- `launchd/com.djbclark.load-watch.plist` now starts `bin/load-watch sample` through `bin/ade-job-run` (canonical `--lock-dir`),
  so once an existing install is migrated with `ade-sched migrate-wrapper`, `load-watch install` and `load-watch uninstall`
  work on the LOADED job through the locked record-first path. (#626)
- `ade-sched migrate-wrapper` also takes the OLD loaded definition's `LABEL.lock` exclusive and non-blocking, for the whole
  migration, when that definition is a wrapped job locking in a directory other than the canonical one: a run of the old wrapper
  makes it refuse with nothing changed. A pre-wrapper old definition keeps the documented idle-only race. (#626)
- `docs/scheduling.md` documents load-watch's emergency stop (`guard_stop`: `bootout`, `kill -TERM/-KILL`, `disable`, and
  the bootstrap/reset without admission) as the one deliberate exception to the admission lock and the no-kill contract, and how
  it interacts with reconcile and a locked reload. (#626)
