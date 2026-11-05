### Added

- `load-watch install`, `proc-cpu-watch install`, `context-budget-check install` and `claude-quota-guard --install` work on Linux through `bin/ade-sched`, with `--backend`, `--allow-no-linger` and `--dry-run` (`load-watch` also `--ade`). (#279)

### Changed

- Exit 69 from those installers now means "no usable scheduler" (it was "not macOS"); `proc-cpu-watch install` returns 69 instead of 2 without one, and refuses `--target codexbar` off macOS. `claude-quota-guard --install` maps a bad job or an unwritable file to 64, never 1-3. `load-watch` reads swap from `/proc/meminfo` off macOS, and `load-watch guard reset` exits 69 without launchctl instead of a traceback. (#279)
