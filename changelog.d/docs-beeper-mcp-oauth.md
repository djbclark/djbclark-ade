### Fixed

- `docs/mcp-servers.md` no longer claims Beeper is always registered or that its OAuth works "from any session": it gives the user-scope `claude mcp add` command and says only the operator can approve the OAuth, by either `/mcp` → beeper → Authenticate in an interactive tab or `claude mcp login beeper` from a shell (`--no-browser` prints the URL), because headless and Paseo-launched Claude sessions get no `authenticate` tool; an agent runs `claude mcp login` only with the operator's yes (Claude Code 2.1.325, 2026-11-15). (#665)
