# vendor/ — sidecar index

Everything this repo references that lives elsewhere on the system,
either vendored here (with its canonical/live location named) or listed
as a pointer when it has its own home. Rule of thumb: the canonical copy
is wherever the thing actually *runs from*; vendored copies here are for
reference, disaster recovery, and so any agent reading this repo can see
the whole system without leaving it.

## Vendored copies

| Here | Canonical / live location | Notes |
|---|---|---|
| `hermes/claude-collaboration.SKILL.md` | `~/.hermes/skills/autonomous-ai-agents/claude-collaboration/SKILL.md` (live, loaded by Hermes) | Teaches Hermes to proactively offer Claude delegation when a task is hard for it, and the 2026-08-23 Claude↔Hermes MCP bridge facts. If you edit, update both places. See docs/mcp-servers.md. |

## Pointers (own homes; not vendored)

The complete component list, with each one's install, update and probe command, is planned as `config/ade.toml`
`[install]` (`../docs/setup-plan.md` S3, 2026-11-07); until it exists, this list is the index.

- **Paseo** — the only harness: github.com/getpaseo/paseo; its skill bundle
  (`npx skills add getpaseo/paseo`) and the Paseo plugins of the J6 set, each in its author's repo
  (`../docs/slim/operator-prompts.md` P2 lists them).
- **sudo-secretspec** — the secret store every key goes through (AGENTS.md review rule 3):
  github.com/frdminc/sudo-secretspec (`brew install frdminc/sudo-secretspec/sudo-secretspec`).
- **peer-link** — Grok Bot's channel code: github.com/frdminc/peer-link; the sender is Hermes'
  `tell_chief_of_staff.py` (`../skills/tell-chief-of-staff/SKILL.md`).
- **herdr4paseo / paseo4herdr** — the last herdr bridges: github.com/djbclark/paseo4herdr.
- **paseo-runner** — the operator's Paseo plugin (script packs as button tabs; `scripts/sync-plugins.mjs` syncs
  plugins across daemons): github.com/djbclark/paseo-runner. Other own Paseo repos: `../docs/setup-plan.md` S3.
- **site-djbclark** — the moved skills, `bin/fleet-watch` and `home-agents.md`; its `skills/` is the third
  `skill-everywhere` root: github.com/djbclark/site-djbclark.

- **fleet-watch** — the launchd fleet change notices to Hermes and the paused upstream watchers' scheduler: site-djbclark
  `bin/fleet-watch` (github.com/djbclark/site-djbclark; it was never in this repo's `bin/`, 2026-11-06).
- **aiuse** — operator's cross-service usage tool: github.com/djbclark/aiuse
  (installed via pipx). `aiuse --json` contract:
  `docs/json-contract.md` in that repo, or `aiuse schema`.
- **cswap** — Claude account switcher: uv tool `claude-swap`
  (`~/.local/bin/cswap`).
- **model-routing skill** — canonical HERE at
  `../skills/model-routing/SKILL.md`; deployed live copy at
  `~/.claude/skills/model-routing/`.
- **graph-audit workflow** — canonical HERE at
  `../.claude/workflows/graph-audit.js`.
- **Session hooks** (`context_size_nudge.py`, `precompact_handoff.py`) —
  tracked HERE in `../claude/hooks/` since 2026-11-01 (c2b66a82; this repo is their
  git home; corrected 2026-11-07), live at `~/.claude/hooks/`.
- **LiteLLM/ClinePass proxy** — fork at `~/src/litellm`; service config in
  site-djbclark `roles/litellm`; serves `localhost:4000`.
- **codexbar config** (`~/.config/codexbar/config.json`) — holds real API
  keys; deliberately never vendored or committed anywhere.
- **Graft** (graft.nanonets.ai, github.com/NanoNets/Graft) — repo context
  graph for coding agents; npm global `@nanonets/graft` (v0.12.0,
  telemetry disabled 2026-08-23). Repo wiring is committed here (fenced
  AGENTS.md section, `.mcp.json`, per-agent configs); machine-global
  wiring landed in `~/.codex/hooks.json` + `~/.gemini/`. The graph cache
  `graft/` is gitignored — regenerate with `graft build`.
- **Standing-orders memory** — canonical in site-private `memory/`
  (`feedback_continuous_operation_over_handoff.md`,
  `feedback_flag_best_practice_deviations.md`,
  `feedback_commit_push_opportune.md`); restated for agents in
  [`../AGENTS.md`](../AGENTS.md).
