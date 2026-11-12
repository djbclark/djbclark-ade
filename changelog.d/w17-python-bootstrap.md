### Added

- `ade-install python` and the POSIX-sh cold-start bridge `bin/ade-bootstrap`: find or obtain Python 3.11+ with uv
  (never pip/sudo, no system-Python writes, refused as root, preview by default), serialized by the install ledger
  lock with a pending sentinel and an explicit `--recover`; uv itself is never fetched, Just and full setup stay
  separate. (#PR)
