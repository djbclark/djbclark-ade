### Fixed

- `route_agent.py` records `age_s` of the account whose reading a multi-account pool keeps, not the last-processed account's, and the oldest age when one account has no usable reading, so a pool of two accounts, one older than the stale limit, reads as old to the frontier gate in either account order (the wider gate gap is queue Carried 84) (F39, CodeRabbit on omercnet/paseo-plugins#618; adversary M1) (#834)
- `pr-radar-route` and `docs/model-routing.md` no longer claim pr-radar's example is a byte-identical copy; `docs/dispatch-footer.md` item 16 gives `load-watch` its full path `~/src/djbclark-ade/bin/load-watch` (#834)
