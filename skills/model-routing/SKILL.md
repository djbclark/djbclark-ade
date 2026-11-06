---
name: model-routing
description: >-
  Route AI work by vendor × model × effort × context window across every service on this machine:
  map aiuse --json lines to their TUIs, tell subscription from prepaid from free
  pools, spot unused quota worth burning. Use when choosing which agent/model
  should run a task, before big multi-agent runs, when a quota window is tight,
  or on "which AI should do X", "what models do we have", aiuse output.
---

# Model routing on this machine

Canonical source of this skill: `skills/model-routing/SKILL.md` in the
djbclark-ade repo (`~/src/djbclark-ade`, github.com/djbclark/djbclark-ade).
`~/.claude/skills/model-routing/` and every other TUI's copy are symlinks to it
via a direct skill-everywhere link (`~/src/djbclark-ade/skills/model-routing`),
so there is nothing to keep in sync.

The canonical, dated matrix lives at
`~/src/djbclark-ade/docs/model-routing.md` (repo
djbclark/djbclark-ade). Read it first; this skill carries the stable
method, not the volatile numbers.

Failure chains (what runs when the chosen model fails) are not here.
Load `fallback-chains` and, if this change touches a chain, update that
skill's snapshot in the same turn.

## Retired TUIs (slim-down E9, 2026-11-06)

agy (Antigravity), crush, pi, zcode, venicecode, qwen-code, goose, aider, kiro-cli, devin, muse, dsh, cline and the
Copilot CLI left the router, `acp-run` and the skill-everywhere list. Google's plan is reached through Paseo's antigravity
provider and GitHub Copilot through Paseo's Copilot provider; the pool `pi` (OpenAI API billing) is gone. What they
taught is in `docs/tui-lessons-learned.md`; the rules that were here are in git history.

## Probes (prefer these over a hand-kept snapshot; aiuse's own cache is fine while fresh)

- **`aiuse --available`** (aiuse 3.1.4+, github.com/djbclark/aiuse) — the routing
  shortlist: only usable pools, one line per vendor AND model family, sorted by
  headroom, every window as "X% used / Y% left". Reads the snapshot cache (<1 s,
  age on the first line); `--live` forces a ~30-60 s collect; `--json` is the
  machine form. Exit 0 = pools exist, **3 = nothing usable**, 1 = error. The
  cache (`~/.cache/aiuse/snapshots/latest.json`) stays fresh because the operator
  often runs `aiuse watch` and a launchd job snapshots hourly; treat it as good
  while it says `fresh`; `acp-dispatch` automatically preflights the exact
  agent/model and caches a pass for ten minutes, since no snapshot sees a pool
  drained in the last few minutes. `aiuse serve` defaults to
  port 28787 and is not running here.
  **Agents always run it with `--json`, stderr kept out (`2>/dev/null`)** (djbclark,
  2026-10-17): the human table is not a contract and its format changes. The
  contract is `aiuse schema` (docs/json-contract.md). Read `.available[]`:
  `provider`, `pool_family`, `cli_binary`, `usable_now`, `headroom_percent`,
  `binding_window`, `available_at`, `requires_operator_approval`; top-level
  `fresh`/`age_seconds` for staleness (stale: add `--live`) and `excluded[]`
  for pools the operator ruled out. Per window, decide from `state`
  (`exhausted` | `tight` | `ok` | `unknown`) or `remaining_percent`. In full
  `aiuse --json`, accounts are `.snapshot.accounts[]`; never match rows with a
  recursive `..` jq walk, which also picks up `agent_notes` entries (no numbers).
  `jq -r '.available[] | "\(.provider)/\(.pool_family // "default") via \(.cli_binary): \(.headroom_percent)% left"'`.
- `aiuse --json -q` — everything, including exhausted pools. Schema 1.1 is
  self-describing: per window `state` (`exhausted` <=1% left, `tight` <15%, `ok`,
  `unknown`), `headroom_percent`, and `pool_family` + `models_hint` on split
  vendors; per account `usable_now`, `binding_window`, `available_at`,
  `age_seconds`; top level `summary_lines`, `semantics`, `agent_notes`, `fresh`.
  Ignore its `kind:"conserve"` pace alerts for go/no-go calls.
- `aiuse note-exhausted <provider> [--family F] --resets-in 4h53m [--reason T]` —
  after a 429 you actually saw, record it so the next agent skips that pool until
  its reset (advisory, expires, shown as `source: agent-reported`).
  `~/ops/site-private/bin/aiuse-pools` is a thin wrapper around `--available`.
- `cswap list` — Claude accounts + 5h/weekly/Fable windows.
- **`bin/claude-fleet-governor`** (2026-10-23) — keeps every Claude session on this Mac from exhausting the Claude
  subscription before a reset (2026-10-20 the weekly window ran out 2.6 days early; 2026-10-23 the 5-hour window was
  projected out 55 min before its reset). It reads the newest aiuse snapshots (`~/.cache/aiuse/snapshots/`; older than
  45 min: exit 10, no action), takes each Claude window's burn rate (least-squares slope over the last 90 min of
  snapshots sharing the current `resets_at`) and projects `used + rate × hours_to_reset` and the exhaustion time.
  Levels: `tight` = any window projected ≥ 90% at its reset, or 5-hour left < 25, or weekly left < 30; `critical` =
  exhaustion more than 10 min before the reset and within 45 min, or any window left < 10 (the Fable sublimit window is
  reported, never sets the level). `run` moves live Paseo agents of provider `claude` in place through
  `bin/paseo-set-model` (the daemon's own `set_agent_model_request`; the Paseo CLI has no such command): Fable → Opus at
  any level (lead sessions never run Fable); Opus/Fable → Sonnet 5.5 at tight/critical, the original recorded; at
  critical also one steer per running agent per reset period (`paseo send --no-wait --behavior steer`) to write its
  handoff and `self-slash --finish --successor omp/anthropic/claude-sonnet-5-5` (API credits, off the subscription);
  after the recorded reset, with the level `ok`, an agent still on the governor's model goes back (Fable originals to
  Opus; a manual change wins); one `hermes-ping` per run that changed something. Exit codes 0 ok, 1 tight, 2 critical,
  10 stale or unreadable data, 11 a call failed, 12 internal error. State: `~/.local/state/ade/fleet-governor.json` (`level`, windows,
  `downshifted`, `steered`, `last_ping`); `route_agent.py` reads `level` while under 30 min old and then routes no
  `code`/`bulk`/`research`/`mechanical` slice to claude and prefers omp Opus for `judgment`. launchd job
  `com.djbclark.claude-fleet-governor` (every 300 s): `bin/claude-fleet-governor --install`, then the printed
  `launchctl bootstrap` line. `check` (the default) changes nothing.
  Its thresholds, and the quota guard's, are in `config/gates.toml`; `bin/gate-profile set away --for 72h --reason TEXT`
  loosens them temporarily (expiring, floor-checked, 2026-10-26; `docs/gates.md`).
- `codex login status`; `opencode models`; `bl quota list`;
  `curl -s localhost:4000/v1/models` (LiteLLM/ClinePass);
- Orca's agent roster + per-agent launch flags (Orca is retired from djbclark-ade, 2026-10-31;
  the file stays on the Mac, untouched, and is still the record of these flags):
  `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
  → `settings.agentDefaultArgs` / `disabledTuiAgents`. Nearly every TUI
  is configured inside Orca; macro-graph dispatch reaches any enabled one (Orca retired; dispatch now goes through `acp-run`/`acp-dispatch`).
- **`bin/claude-quota-guard`** (2026-10-23, the incident in *Routing policy* item 12) —
  turns the Claude reading into a level a session acts on, instead of an alert nobody
  reads. `check` (the default; launchd runs it every 15 minutes after
  `claude-quota-guard --install`) reads `aiuse --available --json` plus the newest
  snapshot's Claude `conserve` alerts and writes `~/.local/state/ade/quota-guard.json`
  (`level`, `weekly_left`, `five_hour_left`, `fable_left`, `resets_at`, `pace`, `advice`,
  `checked_at`, `last_pinged_level`). Levels: `ok`; `watch` (weekly < 40% left, Fable cap
  < 15%, or any Claude `conserve` alert); `tight` (weekly < 30%, or a `conserve` alert on a
  weekly window projecting exhaustion before reset; such an alert is ignored while that
  window has `pace_early: true`, and a Fable-cap alert never counts); `critical` (weekly
  < 15%, 5-hour < 10%, an exhausted or `usable_now: false` Claude account, or aiuse exit 3
  with no Claude row). `aiuse --available` drops every pool with `usable_now: false`, so an
  exhausted Claude is an absent row (exit 0): the guard then reads the payload's top-level
  `excluded[]` (an operator exclusion) or the newest snapshot's `accounts[]` (never an
  `excluded` key there); a snapshot-only Claude that is not blocked is still at least `watch`
  (`source: snapshot-only`, a live 429 or a note the snapshot predates), and a Fable pool aiuse
  dropped because the Fable cap is exhausted is read from the snapshot as 0% left (`watch`).
  aiuse exit 3 (nothing usable) is `critical` whatever the snapshot shows, and a live `available`
  row without `windows[]` (a `pool_family: "fable"` row is the Fable cap, never the shared weekly) is judged by its own `headroom_percent` / `binding_window` /
  `usable_now` (never treated as dropped).
  Exit codes 0 / 1 / 2 / 3 for the levels, 10 when Claude appears nowhere, any container
  (`available`, `excluded`, `accounts`, `alerts`, `windows`) is present but not a list of
  objects, the snapshot does not parse, aiuse could not be read, or another check holds the
  lock. Exit 10 never writes a level: the level, advice and number fields stay as they were,
  but a failed read (not a held lock) records `unreadable_since` / `last_unreadable_at` and, on the second failing
  run in a row, sends one ping per episode (`last_unreadable_pinged_at`); the next good read
  clears them. 64 for a bad
  `CLAUDE_QUOTA_GUARD_THRESHOLDS`, 69 for `--install` off macOS (launchd only; use a
  systemd user timer or cron). `status [--json]` prints the state without probing. One
  `hermes-ping` per level per reset period (the mark survives level drops; a new weekly
  reset clears it); data older than 3 hours (the oldest of the payload's age, each judged
  pool's own age and the snapshot's: a dead collector) is `stale: true` / "(stale)", is
  at least `watch` with a "run `aiuse --live --json`" line, suppresses level pings and sends
  one ping per stale episode. The UserPromptSubmit hook
  `claude/hooks/quota_nudge.py` prints the level's `advice` once per session and level,
  from the state file only (silent when it is missing or over 2 hours old); separately it
  prints `[quota-guard unreadable] aiuse unreadable since <when>` once per session while
  the guard has pinged about an unreadable episode and failed again within 2 hours (a
  one-off hiccup or a stopped guard prints nothing); its once-per-session memory is updated
  under a flock. A lead that
  sees `[quota-guard tight]` hands off and continues on Sonnet 5.5; at `critical` it
  starts no new Claude Code subscription work until the reset (Agent-tool sub-agents of a Claude Code
  session included) and hands off, to an omp successor on Paseo or an omp started by hand (on herdr and Orca too, retired from djbclark-ade 2026-10-31; `bin/claude-quota-guard` still prints that advice until D6), while
  `aiuse --available --json` lists omp (omp is off the subscription's dollar pool but shares
  the Claude weekly rate window, so every weekly window exhausted gates it: then a codex or grok successor).
  `critical` never stops a session on codex, grok or opencode, nor one on omp while aiuse lists
  it (2026-10-29: idle omp sessions had read the old "hand off, stop" line as applying to them).

## OpenCode Go cost guard (2026-10-25)

Go Plus is a $40 subscription with shared allowance, not a free model bundle.
Use `config/go-model-policy.json` as the cost classification. Routine routing
uses MiniMax M3 for bulk and GPT-6 Luna for mechanical work. **No code slice goes to
opencode-go** (djbclark 2026-10-30): `route`/`plan` never name it for `code`; DeepSeek V4.1
Flash stays only the main-loop substrate model (`route_agent.py substrate`). Luna stays
routine: a smaller model allowance alone does not establish high per-token cost. Unknown Go
model IDs are refused until classified.

Costly Go models (including Grok 4.7, Kimi K3/K2.7 Code, GLM 5.3 and DeepSeek
V4 Pro) are advisors only. Use `acp-dispatch opencode --model opencode-go/kimi-k3
--kind judgment --role advise --perm read-only --timeout 600 ...` with a short,
self-contained brief. `research` and `frontier` are also eligible kinds; ordinary
code, bulk and mechanical runs are refused. Direct ACP requires `--go-advisory`.
Both entry points enforce a positive deadline no longer than ten minutes and
read-only permissions; no interactive loop, prompt retries or verify loop.
OpenCode has no adjustable ACP context size; keep the brief small rather than
passing an unsupported `--context`. Never use raw `opencode run` to bypass this
guard, or switch a live main loop to a costly model. Native UI choices are not
a server-side spending limit. `route-override` does not bypass the cost gate.

Use the native V2 Go context plugin and `docs/context-hygiene.md` for early
nudges, safe-point compaction, cooldowns and durable boundary handoffs. Automatic
compaction is not permission to clear a parent or abandon running work. Do not
enable Go "Use balance" to evade an exhausted subscription allowance.

## Reading quota numbers (a misreading here already cost a dispatch round)

`aiuse --available` / `--json` now bake these rules into their output; use them for
any raw number from another source.

1. **`used_percent` is the share CONSUMED; 100 means empty.** `remaining_percent`
   is the headroom. Decide from `remaining_percent` and never quote a bare
   percentage: write "100% used / 0% left". On 2026-10-03 `Codex 5-hour quota:
   100` was read as "100% free" and a review was sent to an exhausted codex.
2. **An account is usable only if every one of its windows has headroom.** The
   fullest window binds: codex at 100% used on its 5-hour window is unusable for
   ~5 hours even with its weekly window at 35% used. (Example from the Plus
   plan; since 2026-10-19 codex is on the $100 plan and `aiuse` may show no
   5-hour window at all. The rule itself stands.)
3. **One TUI can hold several independent pools, one per model family.** Cursor: Auto vs
   third-party (the `cursor-auto` and `cursor` services in `route_agent.py`).
   Claude is **not** such a case: Fable is a sublimit of the one shared pool
   (next paragraph). A 429 or
   `RESOURCE_EXHAUSTED` describes the pool the chosen model draws on, not the
   vendor. Retry on a model from the vendor's other pool before declaring the
   vendor spent (Cursor: the third-party pool when Auto is exhausted, and vice
   versa), and pick the model by which pool is fresh, not only by which is
   strongest. (On 2026-10-03 the then agy Claude/GPT pool was depleted while its
   Gemini pool had plenty left, and a bigteam slice was wrongly moved to another vendor.)
   **Fable is an extra gate, not a separate allowance:** a Fable run bills the
   Claude 5-hour window too, and that window binds first (2026-08-15: a
   211k-token `fable-deep` run moved the 5h 56% → 87% used, Fable 5% → 10%).
   Check the 5h and `Fable:` lines of `cswap list` together; an account with no
   `Fable:` line cannot run Fable at all and a launch silently gets another
   model. Check what a sub-agent actually ran from harness records, never by
   asking it.
4. **State moves within a session.** A small pool's 5-hour window can read 0% used
   at probe time and be exhausted ~35 minutes later (agy's did, 2026-10; the cause was inferred).
   Re-probe before each batch, not once per session, and
   treat a small pool as one that a single heavy slice may be able to spend.
5. **Preflight** each target with one trivial call through the exact invocation
   and model about to be used (`"Reply with exactly: OK"`); `usage limit`,
   `RESOURCE_EXHAUSTED` or 429 means that pool is spent. Note the reset time the
   error prints, then use the sibling pool or reassign.

This section is the one copy of these rules;
`bigteam` Step 1 points here. bigteam keeps the pool classes, *Reserve pools*
and *Current exclusions*.

## Billing classes (2026-08-23 shape; membership drifts)

- **Monthly subscription windows**: claude (5h/weekly, with Fable a <=50%
  sublimit of the same weekly, not a separate bucket), codex (ChatGPT Plus
  weekly until 2026-10-18, the $100 plan, aiuse `prolite`, since 2026-10-19;
  `gpt-6-astra` for frontier slices, and `gpt-6.1-sol` / `gpt-6-luna` for everyday kinds while at least
  half of every window is left, item 1b), cursor Pro (Auto and third-party sublimits; GrokBot has its own
  separate Cursor pool since 2026-10-18, never a target), grok (SuperGrok; an
  ordinary pool since 2026-10-18: realtime-web, research, bulk;
  `acp-run grok --model grok-4.7`),
  clinepass (Cline-pass windows; feeds hermes via LiteLLM :4000; never delegated,
  aiuse-disabled). (antigravity, copilot, zai and devin left the router 2026-11-06.)
- **Never a delegation target**: hermes (the operator's assistant; gated in
  acp-run/acp-dispatch since 2026-10-15).
- **OpenCode Go Plus subscription**: one shared monthly allowance, not free fan-out.
  `config/go-model-policy.json` classifies routine models versus bounded advisors.
- **Free**: sipb (MIT-hosted, `opencode` provider `sipb`).
- **Prepaid real money, gated**: opencode-zen, openrouter, deepseek —
  only via the `opencode-ralph-tui-*` gate scripts, never by default.
- **The Claude API credits, omp (operator 2026-10-19; gate lifted)**: the pool
  `aiuse` labels "omp credits" is the Claude Max plan's monthly API credits (an
  expiring dollar grant, resets 2026-11-05). It is a **normal tier, used with
  discernment**: first for work that needs API access and cannot run through a TUI
  or ACP (kind **`api-only`**: SDK paths such as the Claude route in
  `bin/failover.py`, a verdict classifier, batch/API-only jobs; omp ranks first),
  otherwise for ordinary `code` and `bulk`
  slices via `acp-run omp --model anthropic/claude-sonnet-5-5 [--effort L]`, so the
  credits are **fully used before they expire each month, never left unspent**.
  No `ACP_OPERATOR_APPROVED=omp` any more. **burn-before-reset:** `route_agent.py`
  treats the credits as an expiring grant (`grant_days = 30`): while the balance
  sits 30+ points above an even spend over the month it earns the burn-first bonus
  and the route line says "burn before reset". Cautions: omp's own default model is
  `github-copilot/gpt-5.6-luna`, which would spend the Copilot allowance, so
  `acp-run omp` refuses a run without `--model anthropic/claude-...`; and the router
  skips omp for dispatch kinds while omp holds no enabled Anthropic login
  (`omp_anthropic_ready`; 2026-10-19 the OAuth refresh token had expired, `omp login`
  fixes it). Rules: `bigteam`'s *Operator-gated agents*.
  **cline** retired 2026-11-06 (the TUI left acp-run, acp-dispatch and the router).
  Hermes keeps using ClinePass through its own API key; that pool stays.

## Headless invocation (one-shot prompts to other TUIs)

### First choice: `acp-run` for every agent that speaks ACP

For a one-shot or headless call to an agent with an
[Agent Client Protocol](https://agentclientprotocol.com/) mode, use
`~/ops/site-private/bin/acp-run` instead of the per-CLI forms below. It
speaks ACP to the agent over stdio, so permission requests come back to the
caller, tool calls arrive typed, and usage is reported, instead of scraping
text and passing `--yolo`-style flags.

```
acp-run <agent> -C <dir> (-p PROMPT | -f FILE | stdin) --model M \
        [--effort L] [--context SIZE] [--mode M] [--perm all|deny] \
        [--timeout S] [--log PATH] [--json]
acp-run --list              # agents and the command each runs
acp-run <agent> --info      # its models, modes and auth methods
```

**For a slice that must deliver a report, call `acp-dispatch` instead of
`acp-run` directly** (`bin/acp-dispatch` in djbclark-ade, on PATH; 2026-10-08):
`acp-dispatch <agent> --model M --kind K --name N --task T -C <dir> -f <brief> [--perm P]
[--effort L] [--context SIZE] [--timeout S]`. It makes `--model` mandatory
(`--model` was optional for zcode until it retired, 2026-11-06) and `--kind` mandatory on a fresh
dispatch (2026-10-18; exit 2 without it, or when the agent and model are not
eligible for that kind), appends the shared delivery footer
(`docs/dispatch-footer.md`: report file, pointer-only final message, `BLOCKED:`
protocol, no waiting by ending the turn), writes the report, `.done` marker, log
and `jobs/<name>.json` record under `~/.local/state/bigteam/<task>/`. Before
launch it applies the router's snapshot, a 10% headroom gate (stricter than
`route_agent plan`, which defaults to 15%), estimated-fit gate, and cached live
preflight; `--no-preflight` and `--min-headroom 0` are explicit overrides. It
exits 0 done / 1 unfinished / 3 no report / 4 BLOCKED / 5 pool unavailable
before launch / 124 timeout. Exit 5 means re-plan with `--exclude` and does not
count as a slice attempt. `acp-dispatch
check <dir|report>...` classifies later; `acp-dispatch footer --report <path>`
prints the footer for a Claude Code Agent-tool prompt, which no script can
drive. Everything below about acp-run's flags still applies underneath it.
Pass `--est-pct N` when known; near-fit and unmeasured work gets incremental
checkpoint instructions (`--checkpoint` forces them). **A quota stop is
resumed in place, automatically** (2026-10-18): finalize schedules
`acp-dispatch auto-resume` under launchd for the reset time plus 5 min, gated
on the pool's live headroom (`aiuse --available --json --live`, 20% left,
re-checked 6 times), up to 3 attempts; the same session continues with a
prompt saying the stop was the limit, not the agent. The `rearm` waiter waits
through it; `check` reports `resume-scheduled` (exit 1, still running). A quota
stop it cannot schedule (`--no-auto-resume`, no session id, an agent without
load/resume) stays exit 3 and the `check` line ends with the
`acp-dispatch resume <record> --detach --no-wait` to run after the retry time.
A quota death with a checkpoint also prints `acp-dispatch reroute <record>
--agent A --model M`, which continues from the report and diff on another pool
in a linked record instead of restarting; prefer the in-place resume unless
the pool is out for days.

- **Agents** (`--list`): claude (via the `claude-agent-acp` adapter), codex
  (via `codex-acp`), opencode, cursor, hermes, omp,
  grok (`grok agent --always-approve stdio`, dropped under `--perm deny`; `--model grok-4.7`; exclusion lifted 2026-10-09, probe 4 s).
  Which ones currently work end to end, and what the others need, is
  in `site-private/memory/feedback_prefer_acp_for_delegation.md`; check
  there, not here.
- **Output:** final message on stdout; one summary line on stderr (stop
  reason, seconds, tool calls, permissions allowed/denied, tokens, cost, log
  path); full JSONL event log under `~/.local/state/acp-run/` unless
  `--log` names one. Exit 0 = end_turn, 1 = error/other stop reason,
  124 = timeout (it sends `session/cancel` first).
- **Always pass `--model`**. Without it an agent uses its own default; for the claude adapter
  that is the settings model, which cost about 6× a `--model sonnet` run on
  the same task. `--info` lists valid values.
- **Context window is a routing choice next to vendor, model and effort**
  (2026-10-15). Ask for a bigger window when the slice reads a whole corpus
  or a long log, and leave the default for a small edit. A bigger window
  bills more per token on some services (xAI long-context rates from a 200k
  prompt; Cursor input above 256k at 2×, Fast at 3×) and can be slower.
  1. Request it with `acp-run <agent> --model M --effort high --context 500k`
     (also `256k`, `1m`, and the sizes that agent's table lists). The model
     is applied first.
  2. `acp-dispatch --effort` and `--context` are first-class (checked with the
     model before the job is written, stored on the record, kept by `resume`):
     `acp-dispatch <agent> --model M --kind K --effort high --context 500k`.
     `--acp-arg` still forwards other flags except model/credential changers
     (`--model`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`, `--set` but effort keys: refused for omp, codex and claude (docs/agent-guard-contract.md)); a dash-leading value needs `--acp-arg=--tripwire-exempt-kinds`.
  3. Read stderr `acp-run: applied: model=... effort=... ctx=...`.
     `(unverified)` means that value could not be read back. A mismatch is
     failure class `config`, exit 1. A level or size the agent cannot take
     exits 2 and names the valid values. Codex context is fixed by the model:
     gpt-6.1-sol 500000 (475000 effective); every other visible model 272000
     (258400); all have `max_context_window` 872000. `--context 500k` only
     with `--model gpt-6.1-sol`; `--context 272k` only on the others;
     anything else exits 2 (the message names `--model gpt-6.1-sol`). The full table is
     `tools/acp-run/README.md`, section "Per-agent choices: vendor, model,
     effort, context (2026-10-15)".
- **`--perm`:** `all` (the default) is yolo for every agent; `deny` refuses
  every request, with a tripwire (exit 77, no report) for any tool that runs
  without asking, **reads included**: an agent that runs `grep`/`read` unasked
  (crush and agy did, until they retired) also needs
  `--acp-arg=--tripwire-exempt-kinds=read,search`. **cursor cannot deny at
  all**: cursor-agent takes permissions from `~/.cursor/cli-config.json`
  `approvalMode` (`unrestricted`, the yolo default) and never sends a
  permission request, whatever ACP mode is set (2026-10-15: four repro runs),
  so acp-run refuses `cursor --perm deny`; review on cursor under `all` with a
  read-only brief and check `git status` for stray edits after. **`deny` is
  for security-sensitive slices only** (prompt-injection exposure and the
  like); every other sub-agent runs yolo (operator 2026-10-15). Those are the only two policies (operator 2026-10-14): the old
  `scoped:<paths>` and `ask` are accepted but only print a deprecation warning
  and run as `all`. For a work slice, name the owned files in the brief and
  check `git status --short` / `git diff --stat` afterwards.
- **Exit 0 is still not success.** An agent can end its turn normally with a
  provider error as its reply. Verify the outcome (tests, diff, a real
  review in the output) exactly as for the headless forms.
- Generic form for any config option: `--set <config-id>=<value>`, ids from `--info`.
- claude bills the orchestrator's own pool: see *Reserve pools* below before sending it bulk work.

### Knowing when a delegated call finished

Run each delegation (`acp-run ...` or a per-CLI form below) as a **foreground
command in its own Bash call with `run_in_background: true`**, with no trailing
`&`. The harness then re-invokes you when it exits. A shell-`&` job is not
tracked and finishes silently (tested 2026-10-03); a wait loop built on
`pgrep -f '<pattern>'` matches itself and never ends. ACP does not change this:
`acp-run` is an ordinary command, and ACP only makes its exit code (0, 1, 124)
and stop reason reliable. Full recipe: `bigteam` Step 4.

### Per-CLI headless forms (no ACP mode, or fallback)

The rows for ACP-capable CLIs stay as a fallback for when an ACP route is
broken. (muse, zcode, agy and copilot had rows here until they retired, 2026-11-06.)

**Default permission mode: yolo or its equivalent, for every agent however launched** (standing rule 2026-10-03, `home-agents.md`). Gate only a clearly security-sensitive slice (prompt-injection exposure: `--perm read-only` for a slice that reads, `--perm deny` for text-only; `--role advise` refuses `deny`, 2026-10-19), and say so (operator 2026-10-15; a plain review runs yolo with a read-only brief and a diff check); acp-run has no other gate since 2026-10-14 (bigteam checks file ownership from the diff after the run). `-s read-only` on codex likewise only for those calls; work slices use `--dangerously-bypass-approvals-and-sandbox`.

**Security-sensitive PR that Codex will not or cannot review** (no Daybreak access, a business-only Codex program; djbclark 2026-10-24; `memory/feedback_security_prs_codex_refuses_go_open_weight.md`): review the diff with a frontier open-weight model unlikely to refuse, and once its findings are fixed drop the Codex retry (retry only if another agent investigating the failure wants the PR as a test case). First choice `acp-dispatch zcode --kind code --role advise --model GLM-5.3 --effort high`, second opinion `opencode-go/kimi-k3` or `opencode-go/deepseek-v4-pro`. Pass the diff as a file in the brief, review read-only, and quote the verdict in the PR body like an `adversary` verdict. First used on getpaseo/paseo PR 7817 (GLM-5.3 found two real defects Codex never reached).

**Authority for launch flags:** the retired Orca's roster (retired from djbclark-ade 2026-10-31;
the file stays on the Mac),
`~/Library/Application Support/orca/profiles/local-default/orca-data.json`
→ `settings.agentDefaultArgs`. That map is what actually works on this
machine for every enabled TUI (codex `--dangerously-bypass-approvals-and-sandbox`,
cursor `--yolo`,
grok `--permission-mode bypassPermissions`, …). Read it instead of guessing
flags. Standing rule (frontier-ai-review-stack memory): prefer a TUI's
official headless mode, or a maintained orchestrator (`acp-run`/`acp-dispatch`,
Paseo `paseo run`), over a
hand-rolled subprocess wrapper.

When a direct one-shot call is still the right tool (a single review of a
diff), these forms are verified 2026-09-20. Every one runs with **stdin
closed** (`< /dev/null`) and output redirected to a file; backgrounding a
TUI with `&` inherits the harness's stdin and codex blocks on it forever.

| TUI | Verified headless form | Failure mode seen |
| --- | --- | --- |
| codex (GPT-6 Astra default) | `codex exec -s read-only -C <dir> "<prompt>" < /dev/null > out 2>&1` | without `< /dev/null`: prints `Reading additional input from stdin...` and hangs with no timeout. |
| opencode (Go subscription) | Use `acp-dispatch opencode` with an explicitly qualified routine model such as `opencode-go/minimax-m3` (bulk) or `opencode-go/gpt-6-luna` (mechanical); never a code slice (djbclark 2026-10-30). Expensive models require the bounded advisory form below; direct `opencode run` bypasses the ACP cost gate. | **`opencode/<model>` is the prepaid Zen catalogue, not Go**: every `opencode/*` model except `big-pickle` fails with `Upstream request failed: Insufficient account funds`. `big-pickle` answers but on a review prompt spent its run trying to install pytest and returned nothing — steer it with "do not run tests or install anything". **Side effect:** every `opencode run` rewrites `./opencode.json` in the cwd (adds a `$schema` key) — `git checkout -- opencode.json` afterwards in repos that track it. |
| cursor-agent | `cursor-agent -p --yolo --output-format text "<prompt>" < /dev/null > out 2>&1` | without `--trust` (or `--yolo`/`-f`) in a directory Cursor hasn't trusted: exits 1 with a "Workspace Trust Required" prompt and no review. |

Where DeepSeek lives on this machine (updated 2026-10-25): Go subscription —
`opencode-go/deepseek-v4-pro` (advisory only) / `-v4-flash` / `-v4.1-flash`; free —
`sipb/deepseek-r1:{8b,14b,32b}` (MIT-hosted); prepaid —
`opencode/deepseek-*` (Zen prepaid), `clinepass-deepseek`
via LiteLLM :4000 (ClinePass, a reserve pool), and the `deepseek`
prepaid account. Check `aiuse` for what is left in each. z.ai serves GLM, not DeepSeek.

For the **main loop** (the agent's own substrate, not a dispatched slice), run
`bin/route_agent.py substrate` at session start: it prints the Flash-primary chain
(opencode-go ↔ cline-pass, same model, provider failover) with the binding headroom (monthly budget
included; a stale, errored or expired reading counts as unmeasured), and
`--apply <agent>` does a within-provider switch. A pool in aiuse's `[disabled_services]` (or
`operator_disabled()`) is never named, except the lifeline listed in `config/routing.toml`
`[substrate].lifeline` (`clinepass`, operator 2026-10-23); with nothing usable left it prints
`no usable substrate` and exits 6, also when every pool is exhausted. A cross-provider move is
refused (exit 5) — a live cross-provider model switch is what broke the ◈ Dann tab on 2026-10-23;
failover is a session-start choice, never a live switch. Exit codes: 0 ok; 1 `paseo-set-model`
failed; 2 `--apply` agent empty or ambiguous (an exact id, else a unique id prefix); 3 no such
agent; 4 model not applied; 5 cross-provider; 6 no usable substrate; 7 cannot list agents.

Rules that fall out of this:

- Exit 0 is not success. Append `echo "<tool> exit=$?"` to each output
  file and treat a file holding only a preamble line as a failed run.
- Prefer the read-only sandbox where one exists (codex `-s read-only`).
  Where it does not, check `git status --porcelain` afterwards.
- One background Bash call per batch with a long timeout, never chained
  `sleep`s; read each output file when the batch notification arrives.
- A reviewer that returns exit 0 with no findings is a failed run, not a
  clean bill: check the file has an actual review before counting it.
- Run reviewers against a stable tree: don't edit the file under review
  while they read it. For a second round after fixes, tell them what the
  first round found and fixed, so they verify rather than repeat.

Herdr-hosted TUIs (retired from djbclark-ade, 2026-10-31; history only, verified 2026-09-26; do not start herdr for new work, use Paseo):

- `herdr workspace create` returns before the pane's shell is up;
  `herdr agent start` a moment later fails `agent_pane_busy: … is not an
  available shell`. Poll `herdr pane read <pane>` for a shell prompt (`$`)
  first — ~2 s.
- Key names are `ctrl+c`, `enter`, `esc` (`ctrl-c` → `invalid_key`).
- `herdr pane read` prints plain text; every other command prints one JSON
  envelope, `{"error":…}` **with exit 0** on failure — parse the envelope.
- `herdr agent prompt <target> "/exit"` cleanly ends a Claude session and
  returns the pane to its shell; the `herdr-sleeper` plugin in djbclark-ade
  builds on this (see docs/agent-sleep.md). Never `/exit` a pane whose
  composer holds unsent text: the draft dies with the process.
- A prompt can land unsubmitted (`agent_prompt_stalled`, or the text sits on
  the prompt line, maybe as `[Pasted text #1]`; herdr #1878/#2063, a
  text-vs-Enter race). Check `herdr agent read <t> --source visible`, then
  `herdr agent send-keys <t> enter`. It can recur on every prompt.
- Keys sent before a prompt is on screen land in the input box as type-ahead
  (2026-10-06). Read the screen first, send when the prompt is there.
- A finished turn nobody has looked at is `done`, not `idle`: wait with
  `--until idle --until done` (or no `--until`).
- A `timeout` from `agent prompt --wait` on a long task is normal. Stalled
  means `state_change_seq` from `herdr agent get` stays flat across checks
  minutes apart while still `working`: read the screen, then nudge, restart
  or reassign.
- Backticks inside a double-quoted `herdr agent prompt "…"` run in your own
  shell first (command substitution) and the agent gets their output.
  Single-quote the prompt or escape each backtick.

## Routing policy (operator, 2026-10-15; the one copy, every TUI, any directory)

Goal: **minimise cost while maximising code quality.** Not "minimise tokens":
tokens on different pools cost different money, and a weak model's cheap
tokens are paid for again in review and rework. Every choice is **vendor ×
model × effort × context window**, made per slice, always through ACP
(`acp-dispatch` / `acp-run`), and never by fanning one prompt out to every
vendor ("use all agents" is not a routing plan). `bin/route_agent.py plan
--kinds ...` applies the rules below from the aiuse snapshot and prints the
`acp-dispatch <agent> --model M --kind K --effort E` line per slice; `bigteam` is the
method that runs the waves.

1. **The two frontier models are scarce: send them only what really needs
   them** (operator 2026-10-18, narrowing 2026-10-15's "use them fully"). That
   night a lead put four plektra "small issues" slices on `gpt-6-astra` at
   high/xhigh together. Codex's 5-hour window ran out and all four stopped
   waiting for the reset, although the weekly still had 82% left. (2026-10-19:
   Codex is now on the $100 plan, `aiuse` plan label `prolite`, weekly window
   resetting 2026-10-26; the 5-hour scarcity above, the in-flight limits and
   the estimate floor predate the upgrade and await re-calibration from
   `route_agent.py calibrate`. The routing policy itself is unchanged.) So:
   1a. **Judgment** (review, design, adjudication; 2026-10-25): Claude Opus at
       high first, `acp-dispatch claude --model opus --kind judgment --effort
       high`; omp Opus on the API credits next (adversary rounds name it first:
       item 13); Codex `gpt-6.1-sol --effort high` as an eligible, lower-ranked
       pool (rank 3) only while every codex window has at least
       `[routing].plenty_min` left (item 1b). It is never Fable, and never
       astra (frontier-only).
   1b. **`frontier`** is the only route to codex `gpt-6-astra` (`--kind
       frontier --effort high`) or Fable 5.1 (`--kind frontier --effort high`):
       one slice per pool per wave (two on claude under the standing allowance of 2026-10-27
       while the quota guard passes, `docs/gates.md`), for
       work that really needs a frontier model to look it over. Examples: a
       security-relevant or concurrency fix's final review, debugging that
       has defeated real attempts, an adjudication no cheaper model settles, a
       whole-corpus read that needs Fable's 1M window. "Upstream-bound", "small
       issues" and "a second opinion would be nice" are not reasons. Codex's
       **everyday** models are not frontier (operator 2026-10-25: "if we have
       lots of codex quota and it is the best of available options we can use
       it for non-frontier"): `judgment` on `gpt-6.1-sol --effort high`, `code` on
       `gpt-6.1-sol --effort medium`, `bulk`
       and `mechanical` on `gpt-6-luna --effort low`, eligible only while the
       tightest codex window (5-hour and weekly) has at least
       `[routing].plenty_min` (50%) left, an unknown window counting as not
       plentiful; below that, or with no fresh reading, codex is frontier-only
       again and `acp-dispatch` refuses the kind (exit 2, naming the headroom;
       it re-checks after the load wait, and the detached runner does too). Inside the gate it competes on the
       router's normal ranking (judgment r3, behind claude and omp; code r15, mechanical r12, bulk r20), one slice
       per wave; astra never takes an everyday kind.
       (Gemini 4 Argon was a frontier FALLBACK through agy, 2026-10-31 to 2026-11-06; it left with agy. Its `fallback_after`
       machinery stays in `route_agent.py`/`acp-dispatch`, unused by any service, until a later slice decides on it. The repo
       override (operator 2026-11-01): in tendcf and nix2cf only, astra runs down to 20% of Codex quota left, `[dispatch.repo_overrides.REPO.estimate_floor] "codex:frontier" = 20.0`,
       resolved from acp-dispatch's `-C DIR` through the `origin` remote; other repos keep 60.)
   1c. **In-flight slices reserve quota, per service** (2026-10-18; it replaced
       the codex-only "one slice in flight" cap). Each running slice reserves
       its estimated quota on its service, and a fresh dispatch must fit what
       is left: `acp-dispatch` refuses one that does not (exit 5, class
       `inflight`); resumes are exempt. `ACP_DISPATCH_INFLIGHT=codex=2`
       still sets a hard cap for a run. The brief-size estimate floor is per
       model class (`[dispatch.estimate_floor]`): 60% for an astra slice
       (`codex:frontier`), 10% for codex's everyday models (`codex`), so an
       everyday slice does not reserve a hard slice's share of the window;
       25% for a codex `--kind judgment` slice (`codex:judgment`, 2026-10-25),
       until three history rows that record that kind and effort exist (a row
       with either unrecorded does not count toward them, and a request with
       no `--effort`, a manual reroute included, counts none: it reserves the
       floor, 2026-10-25). The per-window estimates obey the same floor: a
       window with fewer than three comparable measurements is estimated at
       the floor, never at one row's small measurement, and every window of
       the reading is then checked at it.
   1d. **Fable at `xhigh`/`max` almost never runs**: `acp-dispatch` refuses it
       without `ACP_OPERATOR_APPROVED=fable-xhigh`. Ask djbclark first; the
       `fable-deep` agent runs at `high`.
   1e. **Frontier allowance** (2026-10-27, operator; a standing rule, no profile
       needed: `config/gates.toml` `[frontier]` is the baseline, ruled "Frontier
       model use should still be open when required"): you MAY use Fable or
       `gpt-6-astra` where you judge it significantly better than Opus 5.5 for
       that piece of work, if you say why in one line: `acp-dispatch ... --kind
       frontier --frontier-reason "10-200 chars"`; Agent tool: a
       `frontier-reason: ...` line in the sub-agent prompt. Caps:
       `frontier1_per_wave` (2) / `frontier2_per_wave` (1) slices in flight per
       pool, and (Agent tool, Fable) `frontier1_agent_calls_per_day` (4) calls per
       New York day. It needs a fresh quota-guard state at level `ok` (or `watch`
       for the weekly window alone) with the Fable cap at least
       `frontier1_min_left` (the planner's 2-per-wave claude cap too: at the closed 1 without it); at `tight`/`critical`, stale or missing data or an exhausted
       cap the closed rules stand (frontier only through `acp-dispatch --kind
       frontier`, an Agent-tool call asks). The code default is all-closed: a
       missing or unreadable `gates.toml` closes it. Unchanged: advise-only, 1d's
       approval, no lead session on a frontier model. `gate-profile` cannot
       tighten it; closing it is a PR to `[frontier]`. Detail: `docs/gates.md`
       "Frontier allowance".
2. **Fable and "claude" are one pool.** `aiuse --available` lists two routing
   entries, but Fable is a model sublimit: **at most 50% of the shared Claude
   weekly**, and every Fable run bills the shared 5-hour and weekly windows too
   (`cswap list`: read the 5h, 7d and Fable lines together; the fullest
   binds). Under 10% of the Fable cap, judgment falls back to Opus 5.5 at the
   same effort (`route_agent.py` does this; `frontier1_min_left` in `config/gates.toml` `[frontier]`).
3. **Everyday work goes to the other pools** (and to codex's everyday models
   while its quota is plentiful, item 1b), so the frontier windows stay for
   item 1: implementation with a clear shape, tests, refactors, doc writing,
   research summaries, bulk reads, mechanical edits. Order by fitness, then
   headroom, as `plan` computes it: Cursor's
   Auto pool (`--model default`; its third-party pool is separate and often
   tight), opencode-go (bulk and mechanical only, never code). Claude's own pool
   codes on Sonnet 5.5 (`claude --model sonnet --effort high`, rank 12;
   operator 2026-10-18: only Fable stays out of
   code); Haiku only as Agent-tool sub-agents for small lookups. **The Claude
   API credits (omp, operator 2026-10-19)** are a pool here too, used with
   discernment: kind `api-only` first (SDK paths and batch jobs that cannot run
   through a TUI or ACP), else `code`/`bulk` slices (rank 13, ahead of Cursor)
   so the monthly grant is spent before it expires; never left unspent, and
   no per-run approval (cautions under *Operator-gated agents* above). **Quota never buys a much weaker pool into code or judgment**: `plan`
   only picks pools within `[routing].quality_max_rank_gap` (10) rank steps
   of the best eligible one, and otherwise keeps the slice queued.
4. **Minimum needed spec, proactively.** Pick the smallest model, effort and
   context that will do the slice *well*, and delegate even when nobody asked:
   `/bigteam` for separable work; an Agent sub-agent only at `model: "haiku"`,
   `effort: "low"` for a lookup or a classification (item 3: it bills the
   shared pool), so the session's own context stays small. Implementation,
   whether its shape is clear or not, goes through `acp-dispatch` to the
   everyday pools (claude `sonnet --effort high`, cursor `default`, codex `gpt-6.1-sol --effort medium` while its quota is plentiful, item 1b); Fable/astra only for `frontier` (item 1b). **Start on the cheap eligible tier and escalate
   on a verified failure** (operator, 2026-10-18; it replaced "route up when
   unsure"): when a slice fails its check, `acp-dispatch reroute <record>
   --agent A --model M` continues it on a stronger pool, from the report and
   the diff. Sending a hard slice to a cheap worker first costs one failed step
   and a reroute; guessing high costs a frontier window every time.

   **Which Claude tier** (2026-10-18). Each one has a use. The default executor
   is Sonnet, and a slice climbs on evidence, not on a hunch. Prior art:
   Anthropic's model guides,[^tiers] its advisor strategy,[^advisor] Claude
   Code's `opusplan` and effort docs,[^cc] and the routing literature
   (RouteLLM, FrugalGPT).[^routing]
   4a. **Haiku** is for lookups, classification, extraction and one-file
       summaries, as an Agent-tool sub-agent at `effort: "low"`. Anthropic: "Quick
       answers, summaries, and simple extraction".
   4b. **Sonnet 5.5** (`claude --model sonnet --kind code --effort high`) is the
       everyday executor. It implements from a clear brief or plan, writes
       tests, refactors, debugs with a repro and writes docs. Anthropic calls it
       the "versatile default" for "Coding, writing, analysis, and multi-step
       workflows"; Claude Code calls it the model "for daily coding tasks". Use
       `--effort high` where "verification matters or edge cases are likely,
       such as fixing a bug in an existing codebase", and `medium` for
       "day-to-day engineering work with a clear scope".
   4c. **Opus 5.5** (`--kind judgment --effort high`) is for reasoning that
       "genuinely needs sustained thinking". It has five uses:
       1. **Planning:** the brief or plan a Sonnet slice will execute. This is
          `opusplan`'s split: Opus "for complex reasoning and architecture
          decisions", Sonnet "for code generation and implementation".
       2. **Review and adjudication** of a slice's diff.
       3. **Code that is hard up front**, which may start on Opus directly
          (`claude --model opus --kind code --effort high`). That means root cause without
          a repro; concurrency, clock, cache or cross-path state bugs; and a
          change whose design spans several modules or an unfamiliar
          architecture.
       4. **The next rung** after Sonnet fails a verified check:
          `reroute --escalate` takes code to judgment, never straight to Fable.
       5. **The advisor** to a Sonnet executor. A Sonnet slice that hits a
          design decision it can't settle writes `BLOCKED: <question>` instead
          of guessing. The Opus-tier lead answers in a few hundred tokens and
          resumes it, or steers it with `acp-dispatch tell`. In Anthropic's
          tests, Sonnet with an Opus advisor scored 2.7 points higher on
          SWE-bench Multilingual than Sonnet alone, and cost 11.9% less per
          task.
   4d. **Fable 5.1** (`--kind frontier --effort high`) is an advisor unless
       `frontier-exec` is set, and item 1b gates it. It is for previously
       unsolved problems; long-horizon work from a rough idea "with fewer
       check-ins"; a whole-corpus read that needs its 1M window; and work that
       Opus was tried on and missed ("Problems you've tested with Opus and it
       struggled").
   4e. **Climb on evidence.** Go Sonnet → Opus → Fable only when the lighter
       tier was tried and "the lighter answer misses things that matter"; start
       on Opus only for 4c's third use. Anthropic's API guide says the
       opposite: start on the most intelligent model and turn effort down. That
       is right when each token costs money and nothing else is shared. Here
       the binding limit is the shared Claude windows (item 2), so the cascade
       wins: FrugalGPT and RouteLLM report about 2× lower cost at the same
       quality.

[^tiers]: https://academy.claude.com/tutorials/choosing-the-right-claude-model and https://claude.com/resources/articles/claude-models-explained-choosing-the-best-model-for-your-use-case (read 2026-10-18).
[^advisor]: https://claude.com/resources/articles/the-advisor-strategy and https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool (2026-04-09).
[^cc]: https://code.claude.com/docs/en/model-config (aliases, `opusplan`, effort levels).
[^routing]: https://arxiv.org/abs/2406.18665 (RouteLLM) and FrugalGPT's cascade (cheap model first, escalate when a check fails).

5. **The context window is a choice**, next to model and effort. Default is
   the agent's own window. `--context 500k` / `1m` only for a whole-corpus read
   or a long log: bigger windows bill more per token on xAI (from a 200k
   prompt) and Cursor (2× above 256k, Fast 3×), and can be
   slower. Read `acp-run: applied: model=... effort=... ctx=...`; the per-agent
   table is `tools/acp-run/README.md` (2026-10-15).
6. **The reserve, never depleted:** none now. copilot, the last reserve, left the router 2026-11-06 (Paseo's Copilot
   provider replaces the CLI; its allowance rules are in git history). **Grok is no longer a reserve (2026-10-18):** GrokBot (the
   cloud Chief of Staff) moved to its own separate Cursor pool when djbclark
   upgraded to the $60 Cursor plan, so the `grok` TUI is an ordinary
   subscription pool (`realtime-web`, `research`, `bulk`; no floor), ranked
   behind the burn-first pools; never route into the GrokBot pool (aiuse
   provider `grok-bot`). Grok *models* reached through another TUI (cursor,
   opencode) bill that TUI and are fine. **clinepass**: never a bigteam target
   (`NEVER_ROUTE` in `route_agent.py`; it stays in Hermes's chain as its
   lifeline; aiuse `[disabled_services]`). Claude itself: keep enough 5h headroom to finish
   integrating what is in flight, because orchestration runs from it.
7. **Never:** **hermes** as a delegation target (the operator's own assistant;
   `acp-run` and `acp-dispatch` refuse it by an approval gate); the
   prepaid pools (opencode-zen paid, openrouter, deepseek) without a fresh
   operator decision; a credits-backed model (Claude usage credits, Codex
   credits, OpenCode Go "Use balance"; **not** the Claude Max plan's monthly API
   credits, the omp tier of 2026-10-19) or re-enabling a disabled toggle to reach
   a better model; an all-vendor fan-out.
8. **Probes over memory, per batch:** `aiuse --available` (exit 3 = nothing
   usable), `cswap list`, then `route_agent.py plan --kinds ...`; re-plan at
   every slice boundary (`bigteam`, *Dynamic routing*). Exhausted vendors come
   back by themselves when their window resets; keep no private skip list.
9. **Levers:** `acp-run <agent> --model M [--effort L] [--context SIZE] [--mode M]`
   (`--info` lists the ids); `acp-dispatch` takes the same three flags; Claude
   workflows `agent(..., {model, effort})`; `paseo run` for Paseo agents; the per-CLI headless forms only as a fallback.
   For dispatch report paths use `--out DIR --name NAME` (writes
   `DIR/NAME-report.md`); `--report PATH` belongs only to `acp-dispatch footer`,
   not to the dispatch command.

10. Model names get renamed and retired: a name from an old plan or roster is a
    hint. Check `acp-run <agent> --info` before committing to an id.
11. **Context hygiene is part of cost.** Claude Code compacts a session by
    itself at 400k tokens (`autoCompactWindow` in `~/.claude/settings.json`,
    2026-10-15; the PreCompact hook writes the Tier 1 checkpoint). In a herdr
    pane or Orca terminal (retired from djbclark-ade 2026-10-31; `self-slash` keeps those hosts until D6) or a Paseo agent compact earlier, at a natural boundary, with
    `self-slash "/compact <focus>"`; on a topic change run the `handoff` skill,
    then `self-slash "/new"`, which also sends `/baton` into the fresh session
    (2026-10-19). Never ask the operator to do either unless `self-slash`
    refuses (`effort-routing`, *What actually dominates cost*).
12. **The lead / orchestrator session has a model rule too** (operator 2026-10-23;
    `config/routing.toml` `[lead]`, printed by `route_agent.py policy --md`). The rules
    above route dispatched slices; none covered the session that dispatches them.
    Incident: on 2026-10-20 the Claude Code weekly window hit 100% at 17:07Z, 2.6 days
    before its reset, and every orchestrating session stopped, which stopped every other
    pool too. `aiuse` had carried a `conserve` alert for provider `claude` since 06:02Z
    ("projected to run out ~1 day before reset (34% left)"); nothing read it, nothing
    pinged and no session downshifted. The burn was Opus 5.5 (~53%: the `adversary`
    Agent-tool sub-agent is `model: opus`, judgment slices, Orca workers (Orca since retired from djbclark-ade, 2026-10-31)) and Fable 5.1
    (~30%: the lead session itself ran on Fable), mostly cache re-reads of 150-200k
    contexts. So: **a lead that does judgment work runs on Opus 5.5 at high; a lead that
    only drives a pipeline (PR loops, waiters, merges) runs on Sonnet 5.5 at medium
    (`pipeline_effort` in `[lead]`), and goes to high only for a judgment turn; never on
    Fable** (approved by djbclark 2026-10-23). Raise the effort for the turn with
    `/effort high` (Claude Code) or the Paseo thinking setting, and drop back to medium
    after; an effort change keeps the prompt cache (Anthropic: "tuning effort is often a
    better lever than switching models"). Fable
    is reached only through the `fable-deep` sub-agent or a `frontier` slice. Paseo
    launch, judgment lead: `paseo run --provider claude/claude-opus-5-5 --thinking high
    --mode bypassPermissions ...`; pipeline lead: `paseo run --provider
    claude/claude-sonnet-5-5 --thinking medium --mode bypassPermissions ...`; CLI:
    `claude --model opus` with effort `high` in settings (`claude --model sonnet` with
    `medium` for a pipeline lead).
13. **Adversary rounds go to the omp route first** (operator 2026-10-23):
    `acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high`
    (API credits, a normal tier since 2026-10-19; omp is eligible for `judgment` in
    `config/routing.toml`). The Agent-tool `adversary` stays `model: opus` for when omp
    is unavailable; the caller passes the Agent tool's `model: "sonnet"` override
    whenever `bin/claude-quota-guard` reports `tight` or worse (see *Probes*). Omp
    spends through the same Claude account: while a shared Claude window is exhausted,
    aiuse marks omp rate-gated and `--available` omits it.
    Since 2026-10-23 `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` (settings `env`, set by running
    `bin/claude-settings-env`; `--check` shows drift) makes every unpinned Agent-tool sub-agent and teammate
    Sonnet: pass `model: "opus"` in the call for a judgment sub-agent; pinned
    definitions keep theirs; the built-in Explore and Plan agents ignore it.
14. **Cost tiers by kind of work** (operator, 2026-11-01, after a proposed "cheap model as the daily driver" plan
    was checked against the evidence). Decide the tier from the kind of task, up front; for code, no cheap-first
    cascade from tier 2 to tier 1 ("escalate after the cheap tier fails twice"): a weak model's failures are often
    silent (the code passes and is wrong). Within the Claude ladder (4c.4, 4e: Sonnet, then Opus on a verified
    failed check) the evidence-based climb still applies; this item does not repeal it.
    | Tier | Work | Models, in order of value |
    |---|---|---|
    | 1, most work | code, tests, refactors, glue, configs | Sonnet 5.5 (claude subscription, omp), GPT-6.1 Sol (codex: best score per dollar among the models above 50% on Terminal-Bench, see below) |
    | 2, never new or changed logic, output reviewed by a stronger model | bulk, docs, large reading, mechanical edits only when a check proves them | `gpt-6-luna`, DeepSeek V4.1 Flash (non-code bulk only) |
    | 3 | judgment, architecture; reviews default here | Opus 5.5 at high; frontier models (astra, Fable) only through `--kind frontier` |
    Tier 3 is a default, not a ban elsewhere: item 13 drops the `adversary` to Sonnet when `claude-quota-guard` is
    tight, and `AGENTS.md` "Code review" (adversary marker on the PR body, local Codex review) governs which
    reviews a PR needs. `dispatch.frontier_models` is `gpt-6-astra` and `fable` only.
    **Never code on DeepSeek V4.1 Flash** (djbclark 2026-10-30: no `code` on opencode-go). Evidence: Terminal-Bench 4.0
    (Vals AI, 2026-10-29, pass/fail on long real terminal tasks): Opus 5.5 65.2%, Sonnet 5.5 64.1%, GPT-6.1 Sol 55.1%,
    GPT-6.1 Terra 49.5%, GLM 5.3 38.9%, GLM 5.3 Flash 37.4%, DeepSeek V4.1 Flash 19.7% (its 1017 build 31.8%), Gemini
    3.8 Flash 19.7%, Kimi K3 17.2%, GPT-6 Luna 13.6%. Vals cost per test: Sol $1.72 at 55.1%, Terra $2.16, Kimi K3.1 Pro $4.57, Opus
    $13.20, Sonnet $16.51; DeepSeek V4.1 Flash is cheaper ($0.50) but at 19.7%, so "best per dollar" holds only among
    the models above 50%. The 2026-10-30 review of this repo's code (reports under
    `~/.local/state/bigteam/deepseek-review-2026-10-30/`, PRs 171, 172, 173, 174) found four BLOCKs (a credential leak, a
    `NameError` crash, a disabled pool chosen as primary, and a forged-ack hole in `relay.py` that predates the
    Flash-written code) and a MAJOR duplicate paid send: weak-model code needs strong review. "Cheapest per token"
    matters only once the flat subscriptions run out: inside a subscription's quota a strong model costs nothing
    extra. `config/routing.toml` ranks the tiers this way (`bin/route_agent.py policy --md`); other code routes in it
    (clinepass, the unpinned opencode-zen,
    openrouter and deepseek pools) are overflow behind tier 1 or burn-first, not tier-1 choices. This item is the
    reason, not new numbers.

**Where the numbers live (2026-10-18).** The routing policy is data, and
`config/routing.toml` is the source of truth: the kinds, each service's
`good_at` ranks, the frontier model list, the pace and burn-first knobs. Print
it as a table with `bin/route_agent.py policy --md`; copy no numbers from
this file. A fresh `acp-dispatch <agent> --model M --kind K` requires the
kind (exit 2 without it) and the agent and model must be eligible for it;
`ACP_OPERATOR_APPROVED=route-override` skips only that eligibility check.
A frontier model (`gpt-6-astra`, `fable`) runs only with `--kind frontier`
and, by default, as a read-only advisor (`--role advise`: the report is the
deliverable, and a tree edit is flagged); `--role exec` needs
`ACP_OPERATOR_APPROVED=frontier-exec`. Escalation is cheap-first, through
`acp-dispatch reroute` (item 4). Scoring is pace- and reset-aware: a computed
burn-first bonus goes to a pool that would waste quota at its reset, and a pace
penalty to a pool burning fast. `route_agent.py calibrate` reports done rates
per service and kind, and `bin/routing-recalibrate` (monthly, launchd) has Opus
re-rank `good_at` from them.

## Multiple-choice decisions are not reasoning (2026-10-11)

Many calls inside an agent loop pick from a list the harness already holds:
which pool, which kind, retry or re-route or stop, which notes or tests. Do
not send those to a frontier model at high effort. Cheapest rung first:

1. **Code**: `route_agent.py`, exit codes, `aiuse --available`, a table.
2. **A typed decision model** that returns a probability per option (TypeSafe
   Jev; `typesafe-ai` skill). Shadow mode only since 2026-10-11 (`bin/jev`, `docs/jev.md`). The key is
   in `sudo-secretspec` as `TYPESAFE_API_KEY` (2026-10-11; reach it with
   `sudo-secretspec run`); a shadow-mode trial comes before it decides anything.
3. **A cheap text model** at low effort, with a closed option list and a
   parser that rejects anything off the list.
4. **The judgment tier**, when the question is not really multiple choice.

The harness writes the options, code applies a threshold set by risk (cheap
to undo about 0.6, a failed step about 0.8, irreversible means the operator
decides), and anything below the threshold goes up a rung, never to a guess.
Retry caps are counters in code, not sentences in a prompt. Reasons, sources
and the shadow-mode rollout: `docs/orchestration-practices.md` (djbclark-ade).

Standing orders that pair with this: continuous operation over handoff
rituals; flag best-practice deviations to the operator (site-private
memory).
