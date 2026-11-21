### Added

- `bin/lsp-root-guard` (stdio proxy that starts a language server with no root when the workspace root is a container such as `~` or `~/src`), `config/lsp-roots.toml`, `bin/ram-census` (read-only per-class process and memory census) and docs/mcp-on-demand.md section 12: the measured MCP/LSP split for queue item 89 (graft and chrome-devtools stay per-session and go on demand; no per-session server qualifies for a shared daemon), saving estimate and operator apply steps. (#882)

### Changed

- `bin/ade-update` step 3d links `lsp-root-guard` into `~/.local/bin` (`BIN_LINKS`). (#882)
