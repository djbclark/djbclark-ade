### Added

- Push on completion for delegated slices: dispatch footer rule 22 and `skills/fan-out` Collect require a finished slice to tell its requester `done: <title>, <PR URL>` (or status/report) via `paseo send --json --no-wait` with a named ack (never relay); `bin/completion-notice` formats and optionally sends that shape (#397)
