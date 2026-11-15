### Fixed

- `bin/route_agent.py`: `route` and `plan` skip a pool that has no model profile for the kind (naming it under `skipped`), so a bulk slice is no longer routed to `herdr-generic` with a blocked `--provider` placeholder; the placeholder remains only when no capable pool has a profile. The plan and route JSON gain an additive `skipped` key, and a queued slice's reason names the skipped pools. (#756)
