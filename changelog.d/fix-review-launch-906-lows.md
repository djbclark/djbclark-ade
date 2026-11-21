### Fixed

- `bin/review-launch` (follow-up to #906): a tripwire followed by a failed write while the run is cleaned up (a full disk) still ends exit 77, not 2; a SIGTERM that lands right after claude starts kills claude instead of leaving it running while the record says "finished"; the detached-child ownership guard (never skip your own record) is pinned by a test; and the detached-survival test waits for the child's exit instead of racing it. (#PR)
