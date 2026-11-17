### Added

- `chrome-devtools` MCP server (user scope, Claude Code) for introspecting and driving the operator's running Chrome, with setup, verification and security notes in `docs/mcp-servers.md`. (#768)
- `ade-install doctor` checks stdio MCP servers (a `command` and `args` row in `config/mcp-clients.toml`, Claude Code only), starting with `chrome-devtools`; `docs/threat-model.md` gains entry 4.12 for the logged-in browser. (#768)
