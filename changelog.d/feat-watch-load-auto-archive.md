### Changed

- `/watch load` (`skills/watch/SKILL.md`) and `bin/load-watch` (`WATCHER_HOWTO`) now grant the load watcher standing permission to coordinate archiving unneeded Paseo agents under memory/swap pressure: archive verified leadless closed/unneeded agents directly (`paseo agent archive ID`) and delegate archiving of workers/sub-agents to their owning active LEAD via `paseo send`, while preserving the no-kill/no-running-archive boundaries.
