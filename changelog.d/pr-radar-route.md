### Added

- `bin/pr-radar-route`: the routing adapter for the pr-radar Paseo plugin (JSON context on stdin, launch overrides on stdout). It maps the PR signal to a route kind (review requested or security: judgment; bot author: bulk; else code, operator ruling 2026-11-14), asks the `route_agent.py` beside it, and exits 1 with one stderr line when the router fails so pr-radar falls back to its defaults; documented in `docs/model-routing.md` A2b (#684).
