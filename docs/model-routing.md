# Model and effort routing

Goal: know exactly which models are reachable through which service on this
machine, which budget each spends, and route every graph node by vendor ×
model × effort so tokens are spent where judgment lives. Facts are a
**snapshot dated 2026-08-23**, verified against `aiuse --json` (the
operator's own tool, github.com/djbclark/aiuse — allow ~1 min) and direct
CLI probes. Percentages drift constantly — re-probe, don't trust this file
for balances.

> **Correction 2026-10-03: "route bulk work to antigravity first" has a limit
> that `aiuse` cannot see.** The agy CLI has a per-login burst limit, roughly
> **60 generation requests an hour** (inferred; Google publishes none). On
> 2026-10-03 about 304 CLI requests in 12:00 to 14:59 (the busiest earlier hour
> was 68; one Opus-high review alone was 47) were followed from 15:42 by an instant
> `RESOURCE_EXHAUSTED (code 429)` on every model, for 8+ hours, while `aiuse`
> showed Gemini 5h 100% left / weekly 71% left and Claude+GPT 5h 100% left /
> weekly 49% left. **The agy CLI and its ACP server fail independently**:
> `acp-run agy --model gemini-3.8-flash-medium` answered in 6.5 s at 22:54 on the
> same account. Headroom in `aiuse` does not guarantee the CLI can generate.
> So for agy: use `acp-run agy` rather than `agy -p`; always pass
> `--print-timeout`, and read a log line `attempt N failed (RESOURCE_EXHAUSTED` as
> a fast fail; no probe loops (one probe, reuse the answer); send Opus-high
> work sparingly (small Claude/GPT pool); and if one client 429s while `aiuse`
> shows headroom, try the other. Detail and the source skill:
> `skills/model-routing/SKILL.md` ("agy has a burst limit").

## The service matrix: aiuse line ↔ TUI/CLI ↔ billing

`aiuse --json` (JSON starts after two preamble lines) reports one
`snapshot.accounts[]` entry per provider; `alerts[]`/`suggestion` rank
where quota is going to waste. Mapping, verified 2026-08-23:

| aiuse provider | CLI / TUI on this machine | Plan | Billing | Windows |
|---|---|---|---|---|
| `claude` (gmail) | `claude` (Claude Code; cswap acct 2; Orca/ralph-tui drive it) | Max-class | monthly sub | 5h + weekly + **separate Fable weekly** |
| `claude` (mit) | **permanently gone** (operator, 2026-08-23) — removed from cswap | — | — | — |
| `codex` | `codex` (v0.149) | ChatGPT Plus | monthly sub | weekly |
| `antigravity` | `agy` (v1.1.18; ralph-tui-antigravity-plugin exists) | Google AI Pro | monthly sub | Gemini 5h/weekly **plus Claude/GPT 5h/weekly** |
| `copilot` | `copilot` (v1.0.77; broke 2026-08-23 on stale pkg cache — fix: `rm -rf ~/Library/Caches/copilot/pkg`) | Individual Pro | monthly sub | premium requests (monthly) |
| `cursor` | `cursor` (v3.17.8) | Cursor Pro | monthly sub | included / Auto / other-models (monthly) |
| `grok` | `grok` (v1.0.5; ralph-tui-grok-plugin exists) | SuperGrok | monthly sub | usage limit |
| `zai` | `zcode` TUI (Z.ai's own, v0.16.9; `zcode -p`; GLM-5.3 / GLM-5.3-Flash × low/high/max; not in Orca's roster or herdr's agent kinds) | lite | monthly sub | 5h + weekly |
| `clinepass` | Cline TUI (Orca agent `cline`) and `crush` TUI (Orca agent `crush`) + LiteLLM proxy `localhost:4000` (`clinepass-deepseek`, `clinepass-minimax-m3`, `clinepass-kimi-k3`) consumed by Hindsight + hermes | Cline API key | subscription windows | 5h + weekly + monthly |
| `opencode-go` | `opencode` bundled free tier (`opencode-go/*`: kimi-k3, minimax-m3, qwen3.x, mimo, ox-alpha-free…); `opencode-ralph-tui` wrapper | go (free) | free | 5h + weekly + monthly |
| `opencode-zen` | `opencode` provider `opencode` (`opencode/*`: claude, gpt, gemini, deepseek, glm catalogs) via gated `opencode-ralph-tui-zen` | prepaid | **prepaid balance** | balance |
| `openrouter` | gated `opencode-ralph-tui-openrouter` | prepaid | **prepaid balance** | balance |
| `deepseek` | gated `opencode-ralph-tui-deepseek` | prepaid | **prepaid balance** | balance |
| `devin` | `devin` (v3000.5.20) — **disabled in Orca's TUI roster**, so its 100%-unused windows are deliberate dormancy | ? | sub (ACUs) | daily + weekly |
| `alibaba` / `alibabatokenplan` / `qwencloud` | `bl` (Bailian, v1.17.1; bailian-* skills) | **ID verification pending, expected live ~2026-08-26** | token plan + PAYG | — until verified |
| `muse` | the Muse service (own account via gmail; `opencode-go/muse-spark-1.2-contributor` surfaces its models) | ? | ? | ? |
| (not in aiuse) | `opencode` provider `sipb` — MIT SIPB-hosted models (ollama-style: qwen3-coder:30b, deepseek-r1:32b, gemma…) | MIT affiliation | free | none |

Monthly-subscription pools: claude, codex, antigravity, copilot, cursor,
grok, zai, clinepass (window-shaped), devin. Free: opencode-go, sipb.
Prepaid real money: opencode-zen, openrouter, deepseek — all three
**effectively empty on 2026-08-23** (Zen -$0.04, DeepSeek $0.00,
OpenRouter $1.13), and gated anyway by the wrapper scripts, which require
an explicit fresh human decision per run (keys come from
`~/.config/codexbar/config.json`). **Operator decision 2026-08-23: the
prepaid tier is retired for now** — revisit only on an explicit top-up.

## Orca is the fleet registry

Nearly every TUI above is configured *inside Orca*
(`~/Library/Application Support/orca/profiles/local-default/orca-data.json`
→ `settings`): `agentDefaultArgs` lists ~25 launchable agents — claude,
claude-agent-teams, openclaude, codex, gemini, antigravity, aider, amp,
kiro, crush, autohand, cline, command-code, continue, cursor, kimi,
mistral-vibe, qwen-code, rovo, hermes, copilot, grok, devin, ante, trae
(+ goose via env) — each preconfigured with its auto-approve/yolo flag for
worktree use. `disabledTuiAgents` = gemini, goose, devin. Orca also holds
the claude and codex managed-account switchers and per-provider usage
tracking. Practical upshot: the macro graph can dispatch to any enabled
agent in this roster via `worker-start --agent <name>`, far beyond the
seven group-address CLIs.

## What's going to waste (aiuse history, 76 snapshots)

Chronically unused, i.e. already paid for — route suitable work here
first: **antigravity** (~96-100% left every cycle; aiuse's own top
suggestion is "burn Gemini weekly"; **qualified 2026-10-03: capped at roughly 60
CLI requests an hour per login, so "burn" means a steady trickle, not a burst**), **devin** (100%), **opencode-go**
(93-100%), **copilot** (~70%). Hottest window: **clinepass weekly** (23%
left, and Hindsight/hermes depend on it — never route bulk work there).
Claude 5h is the binding constraint on the core pool as usual.

### Live re-probe, 2026-08-23T23:30Z (`aiuse --json`)

Confirms the waste pattern above and refines it. Idle or near-idle —
route bulk work here first (antigravity only within its ~60 requests/hour
burst limit, see the 2026-10-03 correction): **antigravity** (Gemini 5h 0%, weekly 3.5%;
Claude/GPT lanes both 0%), **opencode-go** (5h 0%, weekly 7%, monthly
3%), **zai** (5h 0%, weekly 30%), **devin** (daily and weekly both 0%).
Mid-use: copilot 30%, codex weekly 21%, cursor 15-44% across its three
lanes, grok 55%.

Core pool at probe time: **claude** 5h 4%, weekly 33%, and the separate
**Fable weekly lane at 50%** — Fable has its own budget, so spending it
does not eat the Sonnet/Opus weekly. **clinepass** 5h 15% / weekly 3% /
monthly 42% — monthly is the real constraint; still never bulk-route
there (Hindsight + hermes lifeline). **deepseek** prepaid $0.00 (retired,
as policy says); openrouter $1.13 remaining.

Parsing gotcha: `aiuse --json` prints two preamble lines *and* the JSON's
opening `{` is part of what a naive `tail -n +3` strips. Take everything
from the first `{` instead, or the parse fails with "Extra data".

## Effort levers per service

- **claude**: session effort low→max; per-node `model`/`effort` in
  Workflow `agent()`; per-worker `--model`/`--effort` in Orca
  `worker-start`.
- **codex**: `model_reasoning_effort` minimal→xhigh in
  `~/.codex/config.toml` (currently `gpt-5.6-sol` @ high); per-worker via
  Orca launch prefs.
- **grok/cursor/copilot/agy/opencode**: model choice is the lever
  (`-m`/`--model`/per-invocation); no separate effort knob confirmed.
- **bl**: model choice per call; Token Plan vs PAYG routing per
  bailian-web-search skill.

## Which AI for which work (judgment snapshot, 2026-08-23)

- **Claude Fable 5 @ xhigh** — hardest single-shot adjudications,
  architecture, whole-corpus analysis. Has its **own weekly bucket**, so
  it doesn't drain the Sonnet/Opus pool.
- **Claude Sonnet 5** — default agentic-coding workhorse; best harness
  integration (workflows, skills, Orca, this repo).
- **Claude Haiku 4.5 @ low** — mechanical fan-out nodes: extract,
  classify, reformat.
- **Codex (gpt-5.6-sol @ high)** — strong second coding vendor: parallel
  breadth, second opinions, porting; a separate weekly pool, first
  overflow target for real coding.
- **Gemini via agy** — big-context reading, summarization, multimodal,
  bulk research; the most-wasted subscription → default overflow for
  non-critical bulk. Its Claude/GPT windows are unexplored.
- **Copilot** — GitHub-shaped work (PR review, inline suggestions, repo
  Q&A) on the premium-request pool.
- **Cursor Pro** — IDE-centric composer sessions; its "Auto" pool for
  cheap interactive edits.
- **Grok (SuperGrok, 45% left)** — realtime X/news/web angle, quick
  standalone questions.
- **z.ai GLM (lite) via zcode** — budget bulk coding on its own
  5h/weekly windows. zcode headless has no model/effort flag: it runs
  GLM-5.3 at max.
- **opencode-go free models** (kimi-k3, minimax-m3, qwen3.x) — zero-cost
  experimental fan-out and ralph-tui default via the ungated wrapper;
  burn freely.
- **sipb (MIT)** — free, no-cost, non-Big-Tech option for light tasks and
  experiments where a 30B-class local model suffices.
- **ClinePass via LiteLLM** — reserved plumbing for Hindsight/hermes;
  not a general routing target.
- **Devin** — autonomous end-to-end PR-shaped tasks; currently 100%
  unused, activation is an open operator question.

## Routing policy

1. **Free and already-wasted pools first** for suitable bulk work:
   opencode-go and sipb cost nothing; antigravity/devin/copilot/cursor
   are use-it-or-lose-it monthly quota that history shows expiring
   unused.
   **Exception, 2026-10-03:** antigravity's CLI has a burst limit (roughly 60
   generation requests an hour per login) that `aiuse` cannot see, so spread its
   work over hours, prefer `acp-run agy`, and never fan out a batch at it.
2. **Core pools (claude, codex) for judgment and agentic work**; tier
   inside them (Haiku/low for mechanical, Fable/xhigh for adjudication).
   Check `cswap list` before big runs; shift breadth to codex or the
   wasted pools when the Claude 5h window is hot.
3. **Prepaid requires an explicit fresh human decision** — enforced by
   the gated wrappers, currently moot since all three balances are empty.
4. **Never bulk-route to clinepass** (Hindsight/hermes lifeline, hottest
   weekly window).
5. **Probes over memory**: `aiuse --json` (~1 min, authoritative across
   all services; ignore its `kind:"conserve"` pace alerts for go/no-go),
   `cswap list` (Claude), `codex login status`, `opencode models`,
   `bl quota list`, `curl localhost:4000/v1/models` (LiteLLM),
   `agy --version`, `devin --version`, `copilot --version`.
   Probe agy **once** and reuse the answer: every `agy -p` is a generation request
   against its hourly burst budget (see the 2026-10-03 correction).

## Formerly open questions — resolved by operator, 2026-08-23

- zai GLM lite is consumed by the `zcode` TUI. (Corrected 2026-09-26: the 2026-08-23 note said `crush`; the operator says crush runs against clinepass, not z.ai.)
- `muse` is the Muse service itself (own account).
- Devin is dormant deliberately (also disabled in Orca's roster).
- Bailian is awaiting ID verification, expected live ~2026-08-26.
- Prepaid tier retired until an explicit top-up.
- MIT Claude account is gone forever; removed from cswap 2026-08-23.
