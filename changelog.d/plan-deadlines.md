### Changed

- Plan of record (paseo-only rearchitecture): B9's outside watchdog now enforces declared budgets for every long process or wait, not only the daemon (register, heartbeat, soft then hard stop, recovery once, capped extensions, agent idle alert never kill); G1 `ade-jobs` gains a no-progress timeout and capped, recorded extensions (#222).
