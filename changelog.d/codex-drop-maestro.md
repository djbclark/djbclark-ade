### Removed

- `agents/codex/config.toml.tmpl` no longer registers the Maestro MCP server (`maestro mcp`, a Java mobile-UI tester): every Codex session, headless `codex review` and Codex slices included, started it (about 1 core while starting) during agent start-up storms on a memory-starved Mac (djbclark, 2026-11-01: "drop it from everywhere for now"). The live `~/.codex/config.toml` was changed the same way (#PRNUM).
