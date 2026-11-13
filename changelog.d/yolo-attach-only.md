### Fixed

- `plugins/ade-yolo`: attach-only Herdr providers (`herdr-generic`, `herdr-omp`) no longer refuse every chat open and session import; a separate exact-id `ATTACH_ONLY` allowlist skips the mode checks (Paseo launches nothing there), keeps the snapshot identity check where a snapshot is readable, and logs one line per exemption (#654)
