---
name: model-routing
description: >-
  Route AI work by vendor × model × effort across every service on this
  machine: map aiuse --json lines to their TUIs, know which pools are
  monthly subscription vs prepaid vs free, spot chronically-unused quota
  worth burning, and pick the right AI for the kind of work. Use when
  choosing which agent/model/service should run a task, before big
  multi-agent runs, when a quota window is tight, or when asked "which AI
  should do X", "what models do we have", or about aiuse output.
---

# Model routing on this machine

Canonical source of this skill: `skills/model-routing/SKILL.md` in the
djbclark-ade repo (github.com/djbclark/djbclark-ade); the copy at
`~/.claude/skills/model-routing/` is the deployed live copy — keep them
identical.

The canonical, dated matrix lives at
`~/orca/projects/djbclark-ade/docs/model-routing.md` (repo
djbclark/djbclark-ade). Read it first; this skill carries the stable
method, not the volatile numbers.

## Probes (always prefer these over any cached snapshot)

- `aiuse --json` — authoritative cross-service usage (operator's own
  tool, github.com/djbclark/aiuse; takes ~1 min; JSON starts after two
  preamble lines; `snapshot.accounts[]` has provider/plan/windows/
  balances). Ignore its `kind:"conserve"` pace alerts for go/no-go calls.
- `cswap list` — Claude accounts + 5h/weekly/Fable windows.
- `codex login status`; `opencode models`; `bl quota list`;
  `curl -s localhost:4000/v1/models` (LiteLLM/ClinePass);
  `agy --version`; `devin --version`; `copilot --version`.
- Orca's agent roster + per-agent launch flags:
  `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
  → `settings.agentDefaultArgs` / `disabledTuiAgents`. Nearly every TUI
  is configured inside Orca; macro-graph dispatch reaches any enabled one.

## Billing classes (2026-08-23 shape; membership drifts)

- **Monthly subscription windows**: claude (5h/weekly/+Fable bucket),
  codex (ChatGPT Plus weekly), antigravity/agy (Google AI Pro — also
  exposes Claude/GPT windows), copilot (premium requests), cursor Pro,
  grok (SuperGrok), zai GLM lite (via the crush TUI), clinepass (Cline windows; feeds
  Hindsight+hermes via LiteLLM :4000), devin (disabled in Orca on
  purpose).
- **Free**: opencode-go bundled models; sipb (MIT-hosted, `opencode`
  provider `sipb`).
- **Prepaid real money, gated**: opencode-zen, openrouter, deepseek —
  only via the `opencode-ralph-tui-*` gate scripts, never by default.

## Routing method

1. Free and chronically-unused subscription pools first for bulk work —
   aiuse's history section names them (historically: antigravity,
   opencode-go, copilot, cursor).
2. Claude/codex for judgment and agentic work; tier inside them (haiku/
   low for mechanical, fable/xhigh for hardest adjudication — Fable has
   its own weekly bucket).
3. Never bulk-route to clinepass (hottest window, infrastructure
   lifeline). Never prepaid without an explicit fresh operator decision.
4. Levers: Claude workflows `agent(..., {model, effort})`; Orca
   `worker-start --agent <any enabled TUI> --model --effort`; codex
   `model_reasoning_effort`.

Standing orders that pair with this: continuous operation over handoff
rituals; flag best-practice deviations to the operator (site-private
memory).
