### Fixed

- `ade-sched`: the two lows left on #626 and three earlier ones. An uninstall of a LOADED canonical-wrapped job now proves under the lock
  that the bytes it would restore ARE the loaded definition (a file edited after the load is refused, nothing changed); a disk error
  writing the recovery record leaves no half record and refuses before any `bootout`; the KeepAlive `launchctl print` read ignores a
  newline-forged line; a renamed `ade-job-run` inside an `sh -c` string counts as wrapped; `--restart-service` on any subcommand but
  `install`/`uninstall` is a usage error (exit 2). (#PR)
