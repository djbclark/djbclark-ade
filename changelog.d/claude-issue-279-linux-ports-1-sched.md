### Added

- `bin/ade-sched` and `bin/ade_sched.py`: one scheduler for the repo's system jobs that installs a checked-in launchd plist as a launchd agent (macOS), a systemd user service and timer (Linux; refuses without linger unless `--allow-no-linger`) or a marked crontab block; `backend`, `render`, `install`, `uninstall`, `status`, exit 0/1/2/3/69; [`docs/scheduling.md`](docs/scheduling.md). (#279)
- `deadline install` and `pr-policy install` work on Linux through `bin/ade-sched`, with `--backend` and `--allow-no-linger`; `deadline install --agents auto|on|off` decides whether the sweep runs the Paseo agent scan. (#279)

### Changed

- Exit 69 from `deadline install` and `pr-policy install`/`uninstall` now means "no usable scheduler" (it was "not macOS"). (#279)
