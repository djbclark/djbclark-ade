### Fixed

- `bin/review-launch --detach` (follow-up to #879): a second `--detach` into a run dir that already holds one is refused, and a detached child writes no failure record into a dir whose launch.json names another live launcher; a SIGTERM before claude starts, and a crash after a tripwire (still 77), now leave `result.json` and `done` with the right exit; a resumed run's `parent_run` in launch.json is pinned by tests (relative path, another cwd). (#906)
