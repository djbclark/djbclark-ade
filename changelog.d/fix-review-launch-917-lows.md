### Fixed

- `bin/review-launch` (follow-up to #917): a SIGTERM, SIGHUP or SIGINT that lands while claude is starting (during the `Popen`, the pgid record, or before the main loop) is recorded and then stops claude, in a plain run as well as a detached one; a second signal during the final `kill_all` is ignored, so it cannot cut the kill short; and the no-init tripwire (exit 77, then a full disk at `result.json`) is pinned by a test. (#920)
