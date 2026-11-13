### Fixed

- `ade-sched`: the two lows left on #626 and three earlier ones. An uninstall of a LOADED canonical-wrapped job now proves under the lock
  that the bytes it would restore match the loaded definition (wrapper head, lock dir, full argv, program, source path; a file edited
  after the load is refused, nothing changed; environment/schedule/KeepAlive keys of the file are not compared); a disk error
  writing the recovery record leaves no half record and refuses before any `bootout`; the KeepAlive `launchctl print` read catches a
  newline-forged `properties` line; a renamed `ade-job-run` inside an `sh -c` string counts as wrapped; `--restart-service` on any
  subcommand but `install`/`uninstall` is a usage error (exit 2). (#PR)
