### Fixed

- `route_agent.py` read every pool as stale whenever aiuse's top-level `fresh` was false, so one rate-limited pool
  (antigravity, queried at most every 15 minutes) made `plan --kinds code` find no slice for minutes at a time.
  When the payload's `stale_pools` names the stale entries and the snapshot itself is young, only those
  (provider, pool_family) rows read as stale; `fresh: false` with no usable list, a malformed entry, or an unknown
  or old snapshot age still reads the whole payload as stale (fail closed) (#650)
