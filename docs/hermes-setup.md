# Hermes basic setup (setup-plan S3a)

Opt-in prompt + just recipe for Hermes **basic setup** after the user chose to
install Hermes. Snapshot: 2026-11-10.

This unit does **not** install Hermes, does **not** flip `chosen`, and does
**not** configure peer-link live. Install stays on the catalog row
(`ade-user-install hermes` / #345); peer-link stays its own offered component.

## Entry points

| Piece | Role |
|---|---|
| `prompts/setup/hermes.md` | AI-assisted walkthrough (cards, secrets stop, doctor finish) |
| `just hermes-setup` | Opens Claude Code with a pointer to that prompt |
| `just hermes-setup --self` | Prints the DIY checklist section only (no agent) |

## Paths (from setup-plan S3a)

1. **Skip** — Hermes not chosen; doctor stays quiet.
2. **Install, set up myself** — catalog install, then
   `just hermes-setup --self` (or the same checklist inside the prompt).
3. **Install, set up with AI help** — catalog install, then
   `just hermes-setup` (Claude Code session on the prompt).

Either setup path is re-runnable. `just update` (when that recipe lands) keeps
an installed Hermes current like other components.

## Checklist (summary)

- Model / provider (LiteLLM local recommended when that offered component is
  chosen; else a direct provider).
- Search backend (firecrawl only if chosen).
- djbclark-ade skills root (prefer `skill-everywhere` links).
- Vendored `claude-collaboration` skill (`vendor/hermes/…` → `~/.hermes/skills/…`).
- Claude MCP bridge: `claude mcp add --scope user hermes -- hermes mcp serve`
  (`docs/mcp-servers.md`).
- `tell_chief_of_staff` / peer-link: **pointer only** in this unit.

Secrets: user types into `sudo-secretspec` (or Hermes' own Keychain
`setup.sh`); never into chat or argv. Finish with `just install-doctor` and
`hermes doctor`.

## Related

- setup-plan S3a: `docs/setup-plan.md`
- Install catalog Hermes row: `config/install.toml`, `docs/install-catalog.md`
- MCP bridge facts: `docs/mcp-servers.md`
- peer-link pointer: `skills/tell-chief-of-staff/SKILL.md`
