### Added

- `config/mcp-registry.toml`, `bin/mcp-registry` (`--md`, `--check`, `--json`), `bin/mcp-find` (`--client`, `--json`), and `skills/mcp-find/SKILL.md` for Carried #89 Phase 1: canonical secret-free MCP server registry across clients, generated `docs/mcp-on-demand.md` §2.1 inventory table, and read-only capability lookup with reachability verdicts (`mcp-find` and `mcp-registry` added to `bin/ade-update` `BIN_LINKS`). (#PR)

### Changed

- `ade-install doctor` (`bin/ade_client_wiring.py`) now reads `config/mcp-registry.toml` instead of the removed `config/mcp-clients.toml`, validating `expected` states (`user`, `user-lazy` for `mcp-lazy`-wrapped stdio servers such as `chrome-devtools`, `on-demand`, `denied`, `absent` drift warnings such as `graft`, and `project:<path>`) strictly observe-only and without printing secrets. (#PR)
