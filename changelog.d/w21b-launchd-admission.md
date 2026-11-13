### Added

- `ade-sched reconcile --yes` and `ade-install apply` admitted launchd installs and removals through a native adapter (`launchd_admission`): an absent job is admitted, an existing one is excluded with `launchctl disable`, read from `launchctl print` (pid and state), deferred with exit 6 when busy or unknown without being killed, and restored to its prior enabled/disabled state on every exit; systemd, cron and paseo keep the conservative deferral (#PR)
