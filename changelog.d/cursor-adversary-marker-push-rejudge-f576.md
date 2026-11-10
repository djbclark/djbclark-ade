### Added

- `adversary-marker` rejudges every open PR when `bin/adversary_marker.py` or its workflow lands on the default branch (`push` paths filter; no APPROVE invented), so owner-trust flips tips green without per-PR `workflow_dispatch` (#490).
