### Added

- `[[service]] allow_repos` / `allow_seats` in `config/routing.toml` scope a routing pool to named repos and seats; `opencode-go` is scoped to the `techno-euphora` repo and the `hermes` seat (allow-lists kept while the transport stays retired). Elsewhere `route_agent.py route|plan` skip it as repo-scoped and `acp-dispatch` exits 2 even with `ACP_OPERATOR_APPROVED=route-override`. New `--seat` flag and `ROUTE_SEAT` variable name the calling seat; `policy --md` shows the scope. (#260)

### Fixed

- `ade_config` / the legacy routing shape accepts `allow_repos` and `allow_seats` on `[[service]]` (same contract as `route_agent.load_policy`), so `ade-config check` and effective-config tests no longer reject the shipped `opencode-go` scope. (#260)
