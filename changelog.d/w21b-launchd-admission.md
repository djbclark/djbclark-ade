### Added

- `ade-sched reconcile --yes` and `ade-install apply` enable only the launchd writes that cannot kill or overwrite under concurrency: an absent job is created exclusively (`O_EXCL` temp + `os.link`) and bootstrapped, an unloaded job whose plist byte-matches the ADE render is bootstrapped without a write, and a loaded job whose plist matches is adopted ledger-only; no path calls `bootout`. Loaded jobs, any existing non-matching file and every removal defer with exit 6, untouched (a probe on macOS 27.2 showed `launchctl disable` does not stop a loaded StartInterval job, and a check followed by `bootout`, replace or unlink is not atomic); systemd, cron and paseo keep the conservative deferral (#619)

### Fixed

- `ade-sched reconcile` refused a job whose catalog `label` differs from its plist `Label` at plan time and again before `install`, and a blocked logical row (missing or unrenderable source, label mismatch) no longer plans the removal of its current or prior identities, so a broken replacement cannot delete the last valid definition (#619)
