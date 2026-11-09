### Added

- `bin/ade-backup-stores` gained `--keep N` (retain the newest N complete generations) and `--clean-parts` (remove leftover `<stamp>.part` dirs that may hold unscrubbed credentials), plus a daily `config/launchd/com.djbclark.ade-backup-stores.plist` for `bin/ade-sched` (`--strict-stores --keep 3 --clean-parts`). (#402)

### Changed

- `ade-backup-stores` dry-run resolves `ADE_BACKUP_HERMES` the same way as the real run; `seal_and_hash` opens files `O_NOFOLLOW`; scrub drops triggers before DELETE; CRED_RE covers authorization/cookie/jwt/refresh/session_key/pwd; exclusions add `.ssh`, `.netrc` and AWS credential paths; usage documents exit codes, dry-run schema limits and the schedule. (#402)
