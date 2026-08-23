# Model and effort routing

Goal: know exactly which models are reachable through which service on this
machine, and route every graph node by vendor × model × effort so tokens
are spent where judgment lives and nowhere else. Facts below are a
**snapshot dated 2026-08-23**; each service lists its refresh probe —
re-probe rather than trusting this file for balances and windows.

## Inventory

### Claude (Anthropic subscription, cswap-managed) — probe: `cswap list`

- Accounts: `djbclark@gmail.com` active; `djbclark@mit.edu` needs re-login
  (`cswap add` after a Claude Code login). `cswap switch <n>` moves *new*
  sessions only.
- Models: Fable 5, Opus 5, Sonnet 5, Haiku 4.5; effort low→max. Every
  Workflow `agent()` call accepts per-node `model`/`effort`.
- Quota shape: 5h window (usually the binding constraint), 7d window, and
  a **separate Fable bucket** — heavy Fable use doesn't drain the shared
  7d the same way (visible as its own line in `cswap list`).
- Do **not** use `aiuse --json` "conserve" alerts for go/no-go decisions —
  they're pace projections that fire on a fast hour even when the window
  is nearly untouched.

### Codex (OpenAI subscription) — probe: `codex --version`, `~/.codex/config.toml`

- codex-cli 0.149.0; configured default `gpt-5.6-sol` at
  `model_reasoning_effort = "high"`. Config is ignored-local state
  (symlinked into site-private), editable in place.
- A separate subscription pool from Claude — the cheapest way to add
  fan-out capacity when the Claude 5h window is tight. Orca tracks codex
  usage/reset credits.

### OpenCode (multi-provider frontend) — probe: `opencode models`

- Configured provider `sipb` in `~/.config/opencode/opencode.json`
  (JSONC; enumerate with the probe, not by parsing the file).
- Gated prepaid launchers exist deliberately:
  `opencode-ralph-tui-{deepseek,zen,openrouter,prepaid}` — these spend
  **real prepaid balances** (DeepSeek models, OpenCode Zen, OpenRouter).

### Grok CLI — grok 1.0.5, authenticated (`~/.grok/auth.json`)

### Cursor CLI — cursor-agent 3.17.8

### LiteLLM local proxy (ClinePass only)

- Serves exactly two models by design: `clinepass-minimax-m3` and
  `clinepass-kimi-k3` — single provider, no fallback chain, specifically
  to prevent accidental vendor routing and prepaid burn. API-shaped
  (Hindsight uses it for structured output); not an interactive agent CLI.

### Bailian / DashScope (`bl` CLI)

- Qwen-family text models plus generation/finetune services; skills
  installed. Probe: `bl usage` / `bl quota`.

## Routing policy

1. **Subscriptions before prepaid.** Burn the Claude and Codex
   subscription windows first; anything prepaid (DeepSeek, Zen,
   OpenRouter, ClinePass balance) requires an explicit per-run decision,
   never a default route. The gated launchers and the one-model LiteLLM
   proxy exist to enforce exactly this.
2. **Tier inside the micro graph.** Workflow nodes default to inheriting
   the session model — correct for judgment nodes. Route bounded,
   repetitive nodes (extract, classify, reformat) down to `haiku` /
   `effort: 'low'` explicitly. Reserve Fable at xhigh for the hardest
   single-shot adjudications (it has its own quota bucket).
3. **Tier across vendors in the macro graph.** Orca
   `worker-start --model <id> --effort <level>` sets both per Task for
   claude/codex/cursor workers. Send breadth work (many bounded Tasks) to
   whichever subscription window currently has room; keep the merge and
   adjudication nodes on the strongest available model.
4. **Check before big runs.** `cswap list` for Claude windows, Orca's
   account switcher/usage tracker for claude+codex+opencode. If the
   Claude 5h window is hot, shift fan-out to Codex or schedule after the
   reset rather than downgrading judgment nodes.
5. **Keep this file honest.** Every service entry carries its probe;
   update the snapshot date when re-verified. Model names and CLI flags
   drift — the probes are the source of truth, this file is the map.
