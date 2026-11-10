### Added

- `adversary-marker` rejudges every open PR when `bin/adversary_marker.py` or its workflow lands on the default branch (`push` paths filter; no APPROVE invented), so owner-trust flips tips green without per-PR `workflow_dispatch` (#484).

### Fixed

- Push rejudge emits one `marker` matrix cell per head (concurrency `adversary-marker-<head>`) and scopes unreadable-PR failures to that head, so a sweep no longer races dispatch / Tests completion or poisons other heads (#484).
