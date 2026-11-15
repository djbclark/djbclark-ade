### Fixed

- `bin/route_agent.py`: `route` and `plan` skip a pool that has no model profile for the kind (naming it under `skipped`), so a bulk slice is no longer routed to `herdr-generic` with a blocked `--provider` placeholder; the placeholder remains only when no capable pool has a profile. (#756)
