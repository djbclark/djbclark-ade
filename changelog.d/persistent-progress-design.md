### Added

- `docs/persistent-progress-reminder-design.md` (design only, 2026-11-12): a zero-token `ade-progress` scanner run by `ade-sched` that, for an enrolled idle agent with declared open work, writes a local inbox record, raises a Paseo Progress-panel item, sends one `hermes-ping` and wakes the agent with `paseo send --json --no-wait`; a closed, errored or archived owner gets an operator notice and no wake; the Paseo built-in survey (heartbeat, schedule, wait, plugin hooks, Progress, Herald) is recorded, and `docs/scheduling.md` points to it (#565)
