### Added

- `bin/pr-radar-route`: the routing adapter for the pr-radar Paseo plugin (JSON context on stdin, launch overrides on stdout). It maps the PR signal to a route kind (review requested or security: judgment; bot author: bulk; else code, operator ruling 2026-11-14), asks the `route_agent.py` beside it, and, when the router or the adapter fails, exits non-zero (the router's own exit code when it had one, else 1) with one stderr reason and nothing on stdout so pr-radar falls back to its defaults; documented in `docs/model-routing.md` A2b (#685).
