---
name: mcp-find
description: >-
  Look up which configured MCP server provides a capability, tool, or integration across Claude Code, Codex, Cursor, and
  Hermes without opening client config files or touching secrets. Use on "which MCP server", "which tool can", "do we
  have a ... server", "which server has ...", or before searching ~/.claude.json, ~/.codex/config.toml, or other client
  configs for an MCP capability.
---

# `mcp-find` — MCP capability lookup

Run `bin/mcp-find` (or `mcp-find` once `ade-update` links it into `~/.local/bin`) before opening any client MCP config file (`~/.claude.json`, `~/.codex/config.toml`, `~/.cursor/mcp.json`, `~/.hermes/config.yaml`). It reads only `config/mcp-registry.toml` — no network calls, no config writes, and no secrets enter the transcript.

## Usage

```sh
bin/mcp-find <capability|text> [--client NAME] [--registry PATH] [--json]
```

1. **Match order** (case-insensitive): exact capability tag, then capability tag prefix (e.g. `photos` matches `photos:app-created-only`), then substring of server `id`, `capabilities`, `notes`, `instead`, `on_demand`, or `risk`.
2. **Client verdict**: `--client` defaults to the TUI detected from session environment variables (`claude`, `codex`, `cursor-agent`, `hermes`, `pi`, `gemini`). Output includes whether the server is `callable`, `callable (lazy: ...)`, `on-demand: ...`, `denied: ask the operator`, or `absent in this client: use ...`.
3. **Exit codes**: `0` at least one match, `1` no match (stop guessing), `2` invalid arguments or registry.

## Examples

```sh
bin/mcp-find photos
bin/mcp-find browser --json
bin/mcp-find imessage --client claude
```

## Related

- Canonical registry: `config/mcp-registry.toml`
- Inventory table generator & check: `bin/mcp-registry --md` / `bin/mcp-registry --check`
- Design & rollout: `docs/mcp-on-demand.md`
