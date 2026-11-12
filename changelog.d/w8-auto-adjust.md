### Added

- Added `route_agent.py adjust`, a launch-time pool adjustment with restoration (W8, 2026-11-12): a kind's last
  routed pool that falls below its floor is held off and new launches go to the next eligible pool, and it returns
  after recovering `restore_margin` points above its floor and a minimum dwell (hysteresis), with one change-log line
  per switch, restore, expiry or refusal. A `frontier` slice that would be downgraded is refused (exit 3), omp is never
  a target, and running agents are never touched. Config is `[routing.adjust]`; `plan` gained a soft `kind_exclude`. (#598)
