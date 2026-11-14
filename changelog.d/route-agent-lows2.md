### Fixed

- `ade-config check` now refuses a bad `[dispatch.repo_overrides.REPO] frontier_order` (unknown or repeated service, empty or non-list value, upper-case repo key) the same way the router does, and the router's runtime-load error names the local overlay as well as the base file; both go through one `ade_config.validate_frontier_orders` (parity-tested against `route_agent.py`'s pure file reader). (#720)
- Docs: the `frontier_order` comment in `config/routing.toml` and `skills/model-routing` D5a say the order does not apply model-family independence (pass `plan --exclude codex` for a Codex-authored slice); the queue line says a missing window closes only codex's plenty kinds. (#720)
