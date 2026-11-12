# Hermes basic setup (setup-plan S3a)

Opt-in prompt + just recipe for Hermes **basic setup**, plus the install-time
choice. Snapshot: 2026-11-12 (choice flow and checklist probes added; the
2026-11-10 prompt and recipe are unchanged in spirit).

The choice is recorded in local state
(`~/.local/state/djbclark-ade/install/hermes-choice.json`, or
`ADE_INSTALL_STATE_DIR`). It does **not** edit tracked `config/install.toml`
and does **not** flip the catalog `chosen` flag (`ade-config set` still refuses
component-choice writes). It does **not** configure peer-link live. Install
stays on the catalog row (`ade-user-install hermes` / #345); peer-link stays
its own offered component.

## Entry points

| Piece | Role |
|---|---|
| `prompts/setup/hermes.md` | AI-assisted walkthrough (cards, secrets stop, doctor finish) |
| `just hermes-setup` | Opens Claude Code with a pointer to that prompt |
| `just hermes-setup --self` | Prints the DIY checklist section only (no agent) |
| `just doctor hermes` | Catalog probe, then the S3a checklist probes when Hermes is expected |
| `ade-install hermes-choice {skip,self,ai}` | Records the choice; installs nothing |
| `just install` | Asks the three paths on a tty, records the answer, then applies |

The `hermes-setup` recipe carries Just's `[positional-arguments]` so `--self` /
`--help` reach the shebang body's `$@` (without it, `*args` stays empty and the
recipe always takes the AI path).

## Paths (from setup-plan S3a)

`just install` asks when stdin is a terminal. `ADE_HERMES_CHOICE=skip|self|ai`
answers without a prompt (CI and scripts). With neither, install behaves as
before and records nothing.

1. **Skip** — recorded as `skip`. `just doctor hermes` reports `unchosen` and
   runs no probe.
2. **Install, set up myself** — recorded as `self`, then the catalog apply,
   then `just hermes-setup --self` prints the DIY checklist.
3. **Install, set up with AI help** — recorded as `ai`, then the catalog apply,
   then `just hermes-setup` opens Claude Code on the prompt.

Either setup path is re-runnable (`just hermes-setup`, `just hermes-setup
--self`, or `ade-install hermes-choice` again). `just update` keeps an
installed Hermes current like other components once that recipe runs updates.

A recorded `skip` overrides the catalog `chosen` flag for the `hermes` row
only, so doctor stays quiet even where the tracked catalog says `chosen =
true` (this operator's row). No record leaves the catalog flag in force.

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

`just doctor hermes` (or `bin/ade-install doctor --id hermes --json`) runs the
catalog's `hermes doctor` probe when Hermes is expected. A recorded `skip`, or
an unchosen catalog row with no record, reports `unchosen` and runs nothing.
When the catalog probe passes, the same scoped run adds observe-only checklist
probes (never repairs, never reads a secret):

| Item | Probe |
|---|---|
| model/provider config | `~/.hermes/config.yaml` is a file |
| skills root | `~/.local/share/skill-everywhere/skills` is a directory |
| claude-collaboration | `~/.hermes/skills/autonomous-ai-agents/claude-collaboration/SKILL.md` is a file |
| Claude MCP bridge | `claude mcp list` output contains `hermes` |
| tell_chief_of_staff | directory present is `ok`; absent is `ok` too (optional; never configured here) |
| search backend (firecrawl) | not probed: firecrawl is its own component |

A missing required item fails this scoped doctor. Plain `just doctor` keeps the
catalog probe only and does not add the checklist, so installation-wide output
stays as it was. Scoped output still does not claim whole-installation health.

## Related

- setup-plan S3a: `docs/setup-plan.md`
- Install catalog Hermes row: `config/install.toml`, `docs/install-catalog.md`
- MCP bridge facts: `docs/mcp-servers.md`
- peer-link pointer: `skills/tell-chief-of-staff/SKILL.md`
