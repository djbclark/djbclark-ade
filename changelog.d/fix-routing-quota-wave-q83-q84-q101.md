### Fixed

- Closed multi-account Claude frontier-gate leak (`claude_quota_state` now uses `plenty_remaining` and fails closed with `UNMEASURED_WINDOW` across expired, sublimit-only, windowless, errored, and 3-account stale mixes even under Paseo overlays; Carried #84) (#1024)
- Counted `pi/ade/auto` as an Antigravity user and checked `lastActivityAt`/`updatedAt` (row or `$PASEO_HOME/agents/*/<id>.json`, fail closed when missing on idle agents) in `bin/route_agent.py` stale-reading reuse (Carried #101) (#1024)
- Preserved `resets_at` on refilled exhausted windows for `bin/quota_nudge.py --reset` (plus `available_at` fallback) and applied `_reset_passed` to `shared_pool_family` parent windows, completing Carried #83 (#1024)
