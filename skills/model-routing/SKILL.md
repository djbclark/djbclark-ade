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

## Headless invocation recipes (learned 2026-09-20, two hangs in one run)

Every one of these must run with **stdin closed** (`< /dev/null`) and its
output redirected to a file. Backgrounding a TUI with `&` inherits the
harness's stdin, and at least codex then blocks forever on it.

| TUI | Working headless form | Failure mode without it |
| --- | --- | --- |
| codex (GPT-6 Astra by default) | `codex exec -s read-only -C <dir> "<prompt>" < /dev/null > out.txt 2>&1` | prints `Reading additional input from stdin...` and hangs; no timeout, no output. Kill it and rerun with stdin closed. |
| agy (Antigravity) | `agy -p --dangerously-skip-permissions "<prompt>" < /dev/null > out.txt 2>&1` | `-p` alone exits 0 with a one-line "tool required the command permission ... auto-denied" note and **no review**. Exit 0 is not success — check the output length. |
| copilot | `copilot -p "<prompt>" --allow-all-tools --allow-all-paths --silent < /dev/null > out.txt 2>&1` | works as-is; `--silent` drops the progress chatter. |

Rules that fall out of this:

- Never `wait` on a batch of TUIs blind. Append `echo "<tool> exit=$?"` to
  each output file and treat a file with only a preamble line as a
  failed run, whatever the exit code.
- For read-only review work prefer the read-only sandbox where the TUI
  has one (codex `-s read-only`). Where it does not (agy), verify
  `git status --porcelain` is clean after the run.
- Run them from a background Bash call with a long timeout, one call per
  batch, never chained `sleep`s.

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
