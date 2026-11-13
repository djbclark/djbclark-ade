### Added

- `ade-install doctor` / `just install-doctor` reports, per current TUI (the `bin/skill-everywhere` targets table), whether the shared MCP servers in `config/mcp-clients.toml` are registered in its config file and whether every skill is linked (`bin/ade_client_wiring.py`): ok, or a warning with the exact fix command; observe-only, TUIs without readable MCP config report unknown (#633)
