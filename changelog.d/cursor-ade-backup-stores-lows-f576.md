### Added

- `bin/ade-backup-stores` gained `--keep N` (retain the newest N successful generations) and `--clean-parts` (remove leftover `<stamp>.part` dirs that may hold unscrubbed credentials), plus a daily `config/launchd/com.djbclark.ade-backup-stores.plist` for `bin/ade-sched` (`--strict-stores --keep 3 --clean-parts`). (#402)

### Changed

- `ade-backup-stores` dry-run resolves `ADE_BACKUP_HERMES` the same way as the real run; `seal_and_hash` opens files `O_NOFOLLOW`; scrub drops triggers before DELETE; CRED_RE covers authorization/cookie/jwt/refresh/session_key/pwd; exclusions add `.ssh`, `.netrc` and AWS credential paths; usage documents exit codes, dry-run schema limits and the schedule. (#402)

### Fixed

- `ade-backup-stores --keep` only prunes after a successful run and only among successful generations (`ok` / empty errors); failed renames and failed runs no longer displace usable retained backups. (#402)
- `ade-backup-stores --clean-parts` validates `--dest` with `refuse_reason` and the cleanup parent with `refuse_cleanup_parent` before any recursive delete, so an invalid dest cannot remove sibling `*.part` under a live store. (#402)
