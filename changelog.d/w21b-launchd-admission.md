### Added

- `ade-sched reconcile --yes` and `ade-install apply` admit launchd installs and removals through a read-only native adapter (`launchd_admission`): a job that is absent, or not loaded with a plist provably ADE's (render match, or ledger-owned with a matching artifact hash), is admitted; a loaded job in any state defers with exit 6 and is never touched, because no launch exclusion exists from outside the job (a probe on macOS 27.2 showed `launchctl disable` does not stop a loaded StartInterval job, and idle-read-then-`bootout` is not atomic); systemd, cron and paseo keep the conservative deferral (#619)

### Fixed

- `ade-sched reconcile` refused a job whose catalog `label` differs from its plist `Label` at plan time and again before `install`, so an install cannot touch a label that was never admitted (#619)
