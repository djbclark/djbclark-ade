### Added

- `ade-sched reconcile --yes` and `ade-install apply` admitted launchd installs and removals through a native adapter (`launchd_admission`): an absent job is admitted, a busy or unknown one defers with exit 6 and is never touched, an idle loaded one is unloaded (a probe on macOS 27.2 showed `launchctl disable` does not stop a loaded job's StartInterval, so the adapter never uses it) and reloaded if the mutation did not reload it; systemd, cron and paseo keep the conservative deferral (#619)

### Fixed

- `ade-sched reconcile` refused a job whose catalog `label` differs from its plist `Label` at plan time and again before `install`, so an install cannot boot out a label that was never admitted (#619)
