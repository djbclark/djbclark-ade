### Added

- `[[service]] allow_repos` / `allow_seats` in `config/routing.toml` scope a routing pool to named repos and seats; `opencode-go` is scoped to the `techno-euphora` repo and the `hermes` seat (allow-lists kept while the transport stays retired). Elsewhere `route_agent.py route|plan` skip it as repo-scoped and `acp-dispatch` exits 2 even with `ACP_OPERATOR_APPROVED=route-override`. New `--seat` flag and `ROUTE_SEAT` variable name the calling seat; `policy --md` shows the scope. (#PR)
