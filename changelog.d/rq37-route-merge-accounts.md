### Changed

- `bin/route_agent.py`: `--available` rows and Paseo usage reports of one pool are told apart by the account they read (aiuse `account`, Paseo `id`), not by the pool key. A repeat of one account's quota keeps known-beats-unknown; any other second row folds as another account, fail closed, and an unreadable Paseo report of another account now leaves an `(unmeasured)` window instead of being dropped. `cap_only` is removed. `docs/model-routing.md` D3a and A2c record the rule and the no-`frontier_order` default (PR 708 Lows). (#735)
