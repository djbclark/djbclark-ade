### Changed

- `load-watch install|uninstall` routes through `ade_sched` with `__ADE__`/`__HOME__` plist templates (Linux systemd + Mac launchd; cron refused for the 20 s interval), closing the leftover from #293 without restoring retired monitors (#NNN).
