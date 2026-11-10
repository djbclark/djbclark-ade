---
title: Hermes basic setup (setup-plan S3a)
opt_in: true
installs_hermes: false
configures_peer_link: false
---

# Hermes basic setup (AI-assisted)

You are helping the operator finish **basic setup** of an already-chosen Hermes
install. This is setup-plan **S3a path 3** (`just hermes-setup`).

## Hard rules

1. **Opt-in only.** Do not install Hermes. Do not mark Hermes `chosen` or change
   `config/install.toml`. If `hermes` is missing from PATH, say so and stop; the
   user installs with the catalog path (`ade-user-install hermes` / `just
   install-…`) or skips Hermes entirely.
2. **No live peer-link.** Do not clone, install, start, or configure
   `frdminc/peer-link`, Grok Bot webhooks, or a live `tell_chief_of_staff`
   channel. You may *name* those as later optional steps and print where their
   setup lives; you do not run them.
3. **Secrets never in chat.** At every key or token, stop and ask the user to
   type it into `sudo-secretspec set NAME` (or Hermes' own Keychain
   `setup.sh`) at a real terminal. Never accept a secret pasted into this
   session, never put one on argv, and never write one into a tracked file.
4. **One card at a time.** For each checklist item below, present a short card
   with the **recommended option first**, then alternatives, then wait for the
   user's choice before running anything.
5. **Ask before the first change** on each card. Show the exact command or file
   edit you would run; wait for yes.
6. **Finish with probes.** End with `just install-doctor` (or
   `bin/ade-install doctor --root <repo>`) and, when `hermes` is on PATH,
   `hermes doctor`. Report outcomes; do not repair unless the user asks.

## Working directory

Prefer the djbclark-ade checkout the user launched from (the `justfile`
directory). Live Hermes state is under `~/.hermes/` (config, skills, env).
Hermes upstream docs: https://github.com/NousResearch/hermes-agent

## Checklist (walk in order)

### 1. Model / provider

- **Recommended:** route through the local LiteLLM proxy when that offered
  component is already chosen and healthy (`http://127.0.0.1:4000/v1` shape in
  `agents/hermes/config.yaml.tmpl`).
- **Alternative:** a direct provider Hermes already supports (user's choice;
  subscription logins stay the user's step).
- Edit only what the user picks under `~/.hermes/config.yaml` (or confirm the
  existing file). Template reference: `agents/hermes/config.yaml.tmpl` in this
  repo (placeholders and `{{ secret "…" }}` names are documentation — real
  values go through `sudo-secretspec`, never into the template or chat).

### 2. Search backend (firecrawl)

- **Recommended if firecrawl was chosen:** point Hermes' search / firecrawl
  settings at the same endpoint `bin/firecrawl-router` uses.
- **Skip** if the user did not choose firecrawl (hosted or self-hosted).
- Do not invent a firecrawl.dev key in chat; collect via `sudo-secretspec` if
  the user wants hosted firecrawl later (S3.2.3 / S3b).

### 3. djbclark-ade skills root

- **Recommended:** ensure Hermes can see this repo's `skills/` the same way
  other TUIs do (`bin/skill-everywhere` / docs/skill-everywhere.md). Prefer
  linking over copying.
- Confirm the skills root Hermes loads; do not rewrite unrelated skill trees.

### 4. Vendored `claude-collaboration` skill

- **Recommended:** install or refresh the skill from
  `vendor/hermes/claude-collaboration.SKILL.md` into Hermes' skills tree
  (live path documented in `vendor/README.md`:
  `~/.hermes/skills/autonomous-ai-agents/claude-collaboration/SKILL.md`).
- Keep the vendored copy and the live copy in sync if you edit either.

### 5. Claude MCP bridge

- **Recommended:** register Hermes as a user-scope MCP server for Claude Code
  so Claude sessions can reach Hermes' gateway / approvals:

  ```bash
  claude mcp add --scope user hermes -- hermes mcp serve
  ```

- Verify with `claude mcp list` (stdio only; first `tools/list` can take ~10s).
  Details: `docs/mcp-servers.md` (Hermes section). Do **not** register
  `claude mcp serve` inside Hermes (duplicates tools; nested idle).

### 6. `tell_chief_of_staff` Keychain items (pointer only)

- **Print only** (no live peer-link): if the user later wants the Grok Bot
  "Chief of Staff" sender, its `setup.sh` and
  `tell_chief_of_staff.py` live under Hermes'
  `~/.hermes/skills/agent-tooling/tell-chief-of-staff/` (see
  `skills/tell-chief-of-staff/SKILL.md`). peer-link remains a separate offered
  component; this session does not configure it.

## After the checklist

1. Run `just install-doctor` from the repo root (observe-only; no secret reads).
2. Run `hermes doctor` when `hermes` is on PATH.
3. Summarize what changed, what was skipped, and any probe failures.
4. Remind the user they can re-run `just hermes-setup` or
   `just hermes-setup --self` later; `just update` (when shipped) keeps an
   installed Hermes current like other catalog components.

## DIY checklist (self)

Printed by `just hermes-setup --self`. No agent; no peer-link; no Hermes
install from this recipe.

1. Confirm Hermes is installed (`hermes --version` / `hermes doctor`). If not,
   install via the catalog (`ade-user-install hermes` with
   `ADE_USER_INSTALL_TRUST_VENDOR=1`) or skip Hermes (`chosen = false` stays
   quiet in doctor).
2. Model / provider: edit `~/.hermes/config.yaml` (see
   `agents/hermes/config.yaml.tmpl`). Prefer LiteLLM local when that component
   is chosen; otherwise a direct provider. Put API keys in with
   `sudo-secretspec set NAME`, never in the shell history on argv.
3. Search backend: wire firecrawl only if you chose it; otherwise skip.
4. Skills root: link this repo's `skills/` into Hermes via
   `bin/skill-everywhere` / docs/skill-everywhere.md (prefer link over copy).
5. Claude collaboration skill: copy or refresh
   `vendor/hermes/claude-collaboration.SKILL.md` →
   `~/.hermes/skills/autonomous-ai-agents/claude-collaboration/SKILL.md`
   (`vendor/README.md`).
6. Claude MCP bridge:
   `claude mcp add --scope user hermes -- hermes mcp serve`
   then `claude mcp list` (`docs/mcp-servers.md`).
7. peer-link / `tell_chief_of_staff`: **later, optional.** Sender + `setup.sh`
   under `~/.hermes/skills/agent-tooling/tell-chief-of-staff/`; peer-link is a
   separate offered component (`frdminc/peer-link`). Do not configure it from
   this checklist.
8. Finish: `just install-doctor` and `hermes doctor`.

Upstream: https://github.com/NousResearch/hermes-agent — also
`docs/hermes-setup.md` and setup-plan S3a.
