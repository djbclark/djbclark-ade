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
| `gate-scripts/opencode-ralph-tui*` | `~/.local/bin/` (executable live copies) | The prepaid-balance gate launchers (deepseek/zen/openrouter + plain free-tier). Previously untracked anywhere. No secrets inside — keys load at runtime from `~/.config/codexbar/config.json`, which is never vendored. If you edit, update both places. |
| `orca/orchestration.stub.md` | Orca repo `skill-stubs/orchestration.md` (fork: `~/src/orca`, github.com/djbclark/orca) | Discovery stub only. |
| `orca/orchestration.guide-orca-1.4.188.md` | **The `orca` binary** — `orca skills get orchestration` serves the version-matched guide | Dated snapshot for offline reading. The binary is always right; if your Orca version differs from the filename, re-run the command and do not trust this file. |

## Pointers (own homes; not vendored)

- **aiuse** — operator's cross-service usage tool: github.com/djbclark/aiuse
  (installed via pipx). `aiuse --json` contract:
  `docs/json-contract.md` in that repo, or `aiuse schema`.
- **cswap** — Claude account switcher: uv tool `claude-swap`
  (`~/.local/bin/cswap`).
- **Orca fork** — `~/src/orca` = github.com/djbclark/orca (upstream
  stablyai/orca). The installed app serves the CLIs and skills.
- **model-routing skill** — canonical HERE at
  `../skills/model-routing/SKILL.md`; deployed live copy at
  `~/.claude/skills/model-routing/`.
- **graph-audit workflow** — canonical HERE at
  `../.claude/workflows/graph-audit.js`.
- **Session hooks** (`context_size_nudge.py`, `precompact_handoff.py`) —
  tracked in site-private `claude/hooks/` (released `ops-v1.4.5`), live
  at `~/.claude/hooks/`. Part of the ops suite, not this repo.
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
