### Added

- Added `ade-sched linger` / `just linger` as the observe-only Linux systemd linger gate (exit 69 when `Linger=no`; never runs sudo) before `just update-check-install`, and documented the Linux one-step `just install` / linger / update-check path in README and install docs (#NNN).
