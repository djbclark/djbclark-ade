### Changed

- `skills/fan-out`: a lead's background `wait-file` on a worker's done marker passes `--timeout 7000` (the 1200 s default exits 124 before most code slices finish; a 124 means re-check `STATUS:` and re-arm) (#837)
