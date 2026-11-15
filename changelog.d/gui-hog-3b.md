### Added

- GUI-hog dialog PR 3b: the native window. `macos/gui-hog/` (Swift, a thin view over the Python core; `ade-gui-hog --self-test` checks its logic without a window) and
  `bin/ade-gui-build` (compiles it into `~/.local/libexec/djbclark-ade/ADE GUI Hog.app`, ad-hoc signed, stamped with the sources' SHA-256; `ade update` runs it with `--if-stale`
  and fails open without `swiftc`). The window shows the load header and one row per desktop app (Quit, Force Quit… with a confirm sheet whose default is Cancel) and the bottom
  row Wait (leftmost, the default, does nothing; Return and Escape are swallowed), Ignore 1 h and Quit All… (confirm sheet, Cancel default; never Force Quit). Every Quit runs
  `bin/gui-hog vet` (live protected-list, identity and build-subtree checks, exit 0/3/4/5/6) and the dialog's own pid-plus-start-time re-check before it calls
  `NSRunningApplication`. New `gui-hog` subcommands `vet`, `snooze`, `record-exit`, `log`, `show` (manual run on real apps) and `demo` (fixture rows, touches nothing). (#728)

### Changed

- The GUI-hog trigger is live: a `would-show` decision now also starts the dialog detached when the operator owns the console and the bundle is fresh (single instance by flock;
  the build never waits on it). The dry-run log and `LW_GUI_HOG=0` are kept. A missing or stale bundle is one event line a day and no dialog. The sampler rewrites
  `gui-hog/snapshot.json` while a hold is active or the dialog runs. (#728)

### Fixed

- `gui-hog status` no longer raises when a window entry's RSS is a float; `window_means` rows carry `present`, `cpu_now` and an integer `rss_mb`. (#728)
- GUI-hog agent detection skips leading option words, so `node --max-old-space-size=4096 /opt/bin/pi` is recognised as the `pi` agent CLI. (#728)
- A hold file with pid 1 is no longer accepted; stale `.hold-*.tmp` files older than 2 minutes are swept; the start times of all holds come from one `ps -p a,b,c` call. (#728)
