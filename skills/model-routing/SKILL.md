---
name: model-routing
description: >-
  Route AI work by vendor × model × effort × context window on this machine: the Claude tier for a role, the effort
  level, which pool takes a slice (`route_agent.py plan`), how to read quota (aiuse, `paseo usage ls`), the frontier
  allowance, and what runs when a chosen model fails (fallback chains). Use when choosing which agent/model/effort
  should run a task, before a multi-agent run, when a quota window is tight, when a high-effort session does rote work,
  or on "which AI should do X", "what models do we have", "should we drop the thinking level", aiuse output, or a
  fallback-chain question.
---

# Model routing on this machine

Canonical source: `skills/model-routing/` in djbclark-ade (`~/src/djbclark-ade`); every TUI's copy is a
skill-everywhere link to it. Rewritten 2026-11-07 (slim-down E7); the effort skill and the model-chain half of the
fallback-chain skill are folded in below (sections B and F; git history has both). The dated matrix and the
reasons behind the rules are in `docs/model-routing.md`; this skill is the method.

**The policy numbers live in one place: `config/routing.toml` and `config/gates.toml [frontier]`, printed by
`bin/route_agent.py policy --md`** (services × kinds with each rank and suggested `--model [--effort]`, the pools
with their Paseo provider and billing, the gates and caps, the lead's model). Run it; copy no rank, model id or
threshold from this file or any other.

## A. Claude tiers by role (PLAN section G, 2026-11-06)

| Tier | Roles | Effort |
|---|---|---|
| A1. **Fable 5.1** | the lead of a planned multi-slice project, architects, adversaries | `high` (its default); `xhigh` only for a synthesis the operator asked for; never `max` |
| A2. **Opus 5.5** | rewrites, reviewers, judgment slices, the next rung after a failed Sonnet check | `high` |
| A3. **Sonnet 5.5** | audits, deletions, inventories, everyday code from a clear brief, a pipeline-only lead | `medium` (`high` where verification matters) |
| A4. **Haiku 5.5** | mechanical work: lookups, classification, extraction, reformatting | `low` |

A5. Fable is a frontier model: a dispatched Fable slice is `--kind frontier` (and a `--frontier-reason` for judged
use, section D), an advisor unless `ACP_OPERATOR_APPROVED=frontier-exec`, and Fable at `xhigh`/`max` through
`acp-dispatch` needs `ACP_OPERATOR_APPROVED=fable-xhigh`. Fable is a **sublimit** (at most 50%) of the shared Claude
weekly window, not a separate allowance: every Fable run bills the 5-hour and weekly windows too.
A6. **Deviation flagged (2026-11-07):** `[lead]` in `config/routing.toml` still carries the operator's 2026-10-23 rule
(a judgment lead on Opus 5.5 high, a pipeline lead on Sonnet 5.5 medium, never a Fable lead; `policy --md` prints it).
PLAN section G runs this slim-down's lead on Fable. Until the operator rules which is general, a lead outside a planned
project follows `[lead]`.
A7. Agent-tool sub-agents: the model alias only (`haiku`, `sonnet`, `opus`, `fable`); `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`
makes an unpinned one Sonnet (`bin/claude-settings-env`); pass `model: "opus"` for a judgment sub-agent.

## B. Effort

B1. Levels `low`, `medium`, `high`, `xhigh`, `max`. Precedence: `CLAUDE_CODE_EFFORT_LEVEL` > `/effort` > `--effort` >
settings `effortLevel` > the model default (`high` on Fable 5.1, `medium` on Opus, Sonnet and Haiku 5.5). **Set a
sub-agent's effort explicitly**; `CLAUDE_CODE_SUBAGENT_EFFORT` pins it for every sub-agent, and a sub-agent on another
model uses that model's effort.
B2. Classify the next several actions, not the last one: applying a decision already made (edits, commits, docs, known
commands) is `low`/Haiku; normal implementation with a clear shape is `medium`/Sonnet; an unclear shape (architecture,
adjudication, a bug that defeated one attempt) is `high`/Opus, Fable only when that really needs it.
B3. A running session cannot re-tier itself mid-turn. The levers: dispatch the stretch (a sub-agent or `acp-dispatch`
with its own `--model`/`--effort`), or say in one line that the next stretch is mechanical and `/effort low` or
`/model sonnet` would cost less, and keep working. Name every switch and why. One hard call inside ordinary work is a
dispatched judgment question, not a raised session.
B4. What dominates cost is the conversation re-sent on every request (prompt caching makes the re-read cheap, not
free; the cache lives an hour on a subscription, five minutes on credits or API keys). The cheapest move is usually a
shorter conversation: clear between unrelated tasks; let auto-compaction and the `handoff` skill handle a long one;
send verbose work (test runs, logs, fetches) to a sub-agent that returns a summary. An effort change keeps the cache.
B5. The context window is a choice next to model and effort: the agent's default unless the slice reads a whole corpus
or a long log. Bigger windows bill more per token on some services (Cursor 2× above 256k) and can be slower.

## C. Pools (J2 pool audit, 2026-11-06; grok retired 2026-11-07)

One row per surviving pool; its kinds, ranks and models are in `route_agent.py policy --md`.

| Pool | Paseo provider | Use it for | Never |
|---|---|---|---|
| C1. `claude` | claude | judgment (Opus), code (Sonnet), frontier (Fable, section D); the lead's own pool | Fable for everyday work |
| C2. `omp` (Claude API credits) | omp | `api-only` first, adversary rounds and judgment (Opus), then code and bulk, so the monthly grant is spent before it expires | omp's own default model (it bills Copilot): always `--model anthropic/claude-...` |
| C3. `codex` | codex | frontier (astra, one per wave); its everyday models for judgment, code, bulk and mechanical only while every codex window has `plenty_min` left | astra for an everyday kind |
| C4. `cursor-auto`, `cursor` | cursor | Cursor's Auto pool (burn-first, monthly) and its third-party pool, separately metered | the GrokBot pool (`grok-bot`, Cursor-billed): never a slice target |
| C5. `cursor-cloud` | none: `cursor-cloud launch` | a slice that leaves the Mac and pushes a branch the lead reviews | `autoCreatePR` |
| C6. `opencode-go`, `opencode-zen-free` | opencode | bulk and mechanical on routine Go models (`config/go-model-policy.json`); costly Go models as bounded read-only advisors only | code on opencode-go; Go "Use balance" |
| C7. `antigravity-argon` (Google AI Pro) | antigravity | Gemini 4 Argon as the frontier FALLBACK, only while codex or claude is short (`plan` names it then; tendcf/nix2cf review route 3) | the provider's other pools (not routed); an API key path (bills separately) |
| C8. `hermes`, `clinepass` | hermes; none | Hermes is the operator's assistant; ClinePass is the Hermes/Dann lifeline (`route_agent.py substrate`, `hermes-chain`) | a delegation target, ever |

C9. Prepaid opencode-zen stays retired until an operator top-up; credits-backed models (Claude usage credits, Codex
credits, Go "Use balance") are never reached for by re-enabling a toggle; there is no all-vendor fan-out.
C10. `github` and `realtime-web` are kinds with no pool since copilot (2026-11-06) and the grok CLI (2026-11-07)
retired: `plan` leaves them queued.

## D. Routing, the frontier allowance and quota

D1. **Plan a wave with the router, re-plan at every slice boundary:** `bin/route_agent.py plan --kinds code,code,bulk
[--repo NAME]` prints one `acp-dispatch <agent> --model M --kind K` line per slice (or `cursor-cloud launch …`), spreads
the wave over pools by `max_parallel`, and keeps a slice queued rather than buy a much weaker pool into code or judgment
(`quality_max_rank_gap`). `route --kind K [--json]` picks one; `show` prints each pool's headroom, pace, expected waste
and source; `services [--check-models]` lists the roster with each provider's `paseo provider ls` status and checks
every suggested model against `paseo provider models <provider>`.
D2. **Start cheap, climb on a verified failure** (operator 2026-10-18): mechanical → bulk → code → judgment → frontier,
one rung at a time, never straight to frontier; `research` climbs to judgment. Re-dispatch the failed slice on the
next rung with its report and diff.
D3. **Frontier allowance** (`docs/gates.md`; standing since 2026-10-27): you MAY use Fable or `gpt-6-astra` where you
judge it significantly better than Opus 5.5, with a one-line reason (`acp-dispatch … --kind frontier --frontier-reason
"10-200 chars"`; Agent tool: a `frontier-reason: …` line in the prompt), within the per-wave caps and the Agent-tool
daily cap. For claude it needs a fresh, known Claude reading (aiuse or `paseo usage ls`) with the tightest window and
the Fable cap above their floors; stale, unknown or short means the closed rules (one frontier slice per pool per wave,
an Agent-tool Fable call asks).
D4. **Quota limits are the session-guard and usage-auto-resume plugins' job** (D4, 2026-11-07): they pause a session at
a quota limit and continue it after the reset. The fleet governor and the quota guard were deleted. When the Claude
windows are short (`route_agent.py show`), a lead hands judgment to omp and Agent-tool sub-agents run with
`model: "sonnet"`.
D5. **In-flight slices reserve quota per service** (`[dispatch.estimate_floor]`, the repo overrides for tendcf and
nix2cf): `acp-dispatch` refuses a slice that does not fit (exit 5, class `inflight`).

## E. Reading quota (a misreading here already cost a dispatch round)

E1. Probes, in this order, per batch: `aiuse --available --json 2>/dev/null` (exit 3 = nothing usable; read
`.available[]`: `provider`, `pool_family`, `usable_now`, `headroom_percent`, `binding_window`; top-level `fresh` and
`age_seconds`; add `--live` when stale), `paseo usage ls --json` (a report whose `report.status` is not `available` is
unknown, never a pass), then `route_agent.py plan`. The contract is `aiuse schema`; never the human table.
E2. `used_percent` is the share consumed: 100 means empty. Quote "X% used / Y% left".
E3. An account is usable only if every window has headroom: the fullest binds.
E4. One provider can hold several pools (Cursor Auto vs third-party): a 429 describes the pool the model draws on.
Claude's Fable is not such a pool: it is a sublimit that also bills the shared windows.
E5. State moves within a session: re-probe before each batch. After a 429 you saw, `aiuse note-exhausted <provider>
--resets-in 4h53m` so the next agent skips that pool until its reset.

## F. Fallback chains: what runs when a chosen model fails

F1. A dispatched slice has no automatic model chain: `paseo run` runs one provider/model, and the lead re-dispatches a
failed slice (D2). `route_agent.py` scores which agent runs; it is not a failure chain.
F2. The live chains are Hermes's and LiteLLM's. Re-read their sources before answering, never a snapshot alone:
`~/.hermes/config.yaml` (`model`, `fallback_providers`, `agent.reasoning_effort`, `auxiliary`, `cron`, `moa`),
`~/.hermes/cron/jobs.json` (a pinned job does not walk `fallback_providers`), `~/.litellm/config.yaml`
(`router_settings.fallbacks`), and whether `ai-model-switch` is loaded (`launchctl list | rg 'ai-model-switch|litellm'`).
Extract provider, model, effort and thinking only; never a key or a URL that embeds one.
F3. `python3 ~/src/djbclark-ade/skills/model-routing/scripts/chains-check.py` prints the live layers and exits 1 on a
cycle, a same-vendor pair, MoA on with a missing preset, or a second writer. The dated snapshot is
`references/fallback-chains-inventory.md`, the not-started single-system backlog `references/fallback-chains-integration.md`:
update the snapshot in the same turn when a live source differs.

## G. Multiple-choice decisions are not reasoning (2026-10-11)

Which pool, which kind, retry or stop: answer from code first (`route_agent.py`, exit codes, `aiuse --available`), then
a cheap text model at low effort with a closed option list and a parser that rejects anything off it, and only then the
judgment tier. Retry caps are counters in code, not sentences in a prompt (`docs/orchestration-practices.md`).
