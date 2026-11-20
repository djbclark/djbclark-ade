### Fixed

- `route_agent.py` records `age_s` of the account whose reading a multi-account pool keeps, not the last-processed account's, and the oldest age when one account has no usable reading, so the frontier gate cannot open on the fresh account alone in either account order (F39, CodeRabbit on omercnet/paseo-plugins#618; adversary M1) (#831)
- `pr-radar-route` and `docs/model-routing.md` no longer claim pr-radar's example is a byte-identical copy; `docs/dispatch-footer.md` item 16 gives `load-watch` its full path `~/src/djbclark-ade/bin/load-watch` (#831)
