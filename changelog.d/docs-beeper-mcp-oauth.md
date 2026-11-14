### Fixed

- `docs/mcp-servers.md` no longer claims Beeper is always registered or that its OAuth works "from any session": it gives the user-scope `claude mcp add` command and says only the operator can authenticate, interactively (`/mcp` → beeper → Authenticate), because headless and Paseo-launched Claude sessions get no `authenticate` tool (2026-11-14). (#665)
