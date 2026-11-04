### Added

- `bin/ade-sched` and `bin/ade_sched.py`: one scheduler for the repo's system jobs that installs a checked-in launchd plist as a launchd agent (macOS), a systemd user service and timer (Linux; refuses without linger unless `--allow-no-linger`) or a marked crontab block; `backend`, `render`, `install`, `uninstall`, `status`, exit 0/1/2/3/69; [`docs/scheduling.md`](docs/scheduling.md). (#279)
- `deadline install`, `pr-policy install`, `load-watch install`, `proc-cpu-watch install`, `context-budget-check install` and `claude-quota-guard --install` work on Linux through `bin/ade-sched`, with `--backend`, `--allow-no-linger` and `--dry-run`; `deadline install --agents auto|on|off` decides whether the sweep runs the Paseo agent scan. (#279)
- `coding-bot` falls back to the platform clipboard: pbcopy/pbpaste, wl-copy/wl-paste with `$WAYLAND_DISPLAY`, xclip then xsel with `$DISPLAY`. (#279)

### Changed

- `skill-everywhere` finds the skills dir from its own location (a linked worktree resolves to its primary checkout); `~/src/djbclark-ade/skills` is only the fallback. (#279)
- Exit 69 now means "no usable scheduler" for those installers (it was "not macOS"); `proc-cpu-watch install` returns 69 instead of 2 without one. `load-watch` reads swap from `/proc/meminfo` off macOS. (#279)
- macOS-only tools refuse with an explanatory exit 69 instead of failing late: `codium-ai`, `app-tamer-ab`, `paseo-set-model` without its Paseo Helper (was exit 1), `load-watch guard reset` without launchctl, `proc-cpu-watch install --target codexbar` off macOS, and `acp-dispatch --detach`/`reap --install` without launchctl (they point to `paseo run`; acp-dispatch is replaced in D5). (#279)
