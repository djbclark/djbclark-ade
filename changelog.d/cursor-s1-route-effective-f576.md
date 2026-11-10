### Changed

- `route_agent` module init and `reload_policy()` (no explicit path) now load the routing domain through `ade_config.load_effective` (S1 consumer adoption; legacy `routing.toml` / `ROUTING_POLICY` when `ade.toml` is absent) (#356).
