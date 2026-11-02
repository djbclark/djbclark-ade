### Changed

- Amended the plan of record (paseo-only rearchitecture): B9's outside watchdog enforces declared budgets for every long process or wait, not only the daemon (register, heartbeat, soft then hard stop, recovery once, capped extensions, agent idle alert never kill), and records a job's descendants on every sweep so a child that leaves its group is still stopped; G1 `ade-jobs` got a no-progress timeout and capped, recorded extensions (#222).
- Amended plan F2 and updated the paseo skill: a scheduled run counted as succeeded only when THIS run's declared output exists (a fresh report path per run plus a `.done` naming the run); a scheduled agent never delegates and stops (#222).
