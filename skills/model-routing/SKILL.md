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
`~/orca/projects/djbclark-ade/docs/model-routing.md` (repo
djbclark/djbclark-ade). Read it first; this skill carries the stable
method, not the volatile numbers.

Failure chains (what runs when the chosen model fails) are not here.
Load `fallback-chains` and, if this change touches a chain, update that
skill's snapshot in the same turn.

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
- `codex login status`; `opencode models`; `bl quota list`;
  `curl -s localhost:4000/v1/models` (LiteLLM/ClinePass);
  `agy --version`; `devin --version`; `copilot --version`.
- Orca's agent roster + per-agent launch flags:
  `~/Library/Application Support/orca/profiles/local-default/orca-data.json`
  → `settings.agentDefaultArgs` / `disabledTuiAgents`. Nearly every TUI
  is configured inside Orca; macro-graph dispatch reaches any enabled one.

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
3. **One TUI can hold several independent pools, one per model family.** agy:
   Gemini and Claude/GPT are separate pools (`agy models`); Cursor: Auto vs
   third-party (the `cursor-auto` and `cursor` services in `route_agent.py`).
   Claude is **not** such a case: Fable is a sublimit of the one shared pool
   (next paragraph). A 429 or
   `RESOURCE_EXHAUSTED` describes the pool the chosen model draws on, not the
   vendor. Retry on a model from the vendor's other pool before declaring the
   vendor spent (agy: a `gemini-*` model when a `claude-*`/`gpt-*` one is
   exhausted, and vice versa), and pick the model by which pool is fresh, not
   only by which is strongest. On 2026-10-03 the agy Claude/GPT pool was
   depleted while its Gemini pool had plenty left, and a bigteam slice was
   wrongly moved to another vendor.
   **Fable is an extra gate, not a separate allowance:** a Fable run bills the
   Claude 5-hour window too, and that window binds first (2026-08-15: a
   211k-token `fable-deep` run moved the 5h 56% → 87% used, Fable 5% → 10%).
   Check the 5h and `Fable:` lines of `cswap list` together; an account with no
   `Fable:` line cannot run Fable at all and a launch silently gets another
   model. Check what a sub-agent actually ran from harness records, never by
   asking it.
4. **State moves within a session.** agy's Claude/GPT 5-hour window read 0% used
   at probe time and was exhausted ~35 minutes later (weekly 0% to ~51%), around
   the time one Opus-high review ran on it; other sessions use agy too, so the
   cause is inferred. Re-probe before each batch, not once per session, and
   treat a small pool as one that a single heavy slice may be able to spend.
5. **Preflight** each target with one trivial call through the exact invocation
   and model about to be used (`"Reply with exactly: OK"`); `usage limit`,
   `RESOURCE_EXHAUSTED` or 429 means that pool is spent. Note the reset time the
   error prints, then use the sibling pool or reassign.

This section and *agy has a burst limit* below are the one copy of these rules;
`bigteam` Step 1 points here. bigteam keeps the pool classes, *Reserve pools*
and *Current exclusions*.

### agy has a burst limit that `aiuse` cannot see (incident 2026-10-03)

**`aiuse` headroom does not mean agy can generate, and agy's two clients fail
independently.** From 15:42 local on 2026-10-03 every `agy` **CLI** generation
request (Gemini 3.8/3.7 Flash, 3.1 Pro, Claude Sonnet 5.5) got an instant
`RESOURCE_EXHAUSTED (code 429)`, while `agy -p /usage` and `aiuse --json` showed
Gemini 5h 100% left / weekly 71% left and Claude+GPT 5h 100% left / weekly 49%
left. At 22:54, on the same account, `acp-run agy --model gemini-3.8-flash-medium`
answered in 6.5 s. The CLI login (`~/.gemini/antigravity-cli`) was locked out,
not the account; the ACP server (`agy_acp_server` 1.3.0, shadow GEMINI_HOME
`~/.local/share/agy-acp-home`) is a separate client. A probe at 23:50 still got
`attempt 1..5 failed (RESOURCE_EXHAUSTED` in 60 s, then `--print-timeout` cut it.

**Update 2026-10-04: the CLI lockout persisted 18+ hours and re-login cannot
clear it.** The throttle keys on persistent client state
(`~/.gemini/antigravity-cli/installation_id` survives logout/login), and it held
while a working quota probe showed Gemini 5h **1% used**. `acp-run agy` answered
in 15.8 s the same minute the CLI 429'd a flash model. So the CLI surface can be
dead for a day with a full quota and nothing an agent does locally will revive
it — route around it, don't retry it.

**Likely cause (inferred, not published by Google): a per-client burst limit.**
Between 12:00 and 14:59 the agy CLI made about **304 generation requests**; the
busiest earlier hour had 68. One bigteam `claude-opus-5-5-high` review alone was
47 requests, and two sessions looped skill-detection `agy -p` probes. Count
**requests, not calls**: a tool-using agy turn is many requests. Treat roughly
**60 requests/hour per CLI login** as the budget, i.e. about one review an hour.
`aiuse`/CodexBar launching `agy -p /usage` every few minutes adds CLI launches
but no generation requests.

Rules for any agent that dispatches to agy:

1. **Cap the calls.** No probe loops, no per-skill or per-TUI "do you see X"
   loops. One probe, then reuse the answer. Sequential `agy -p` calls count the
   same as concurrent ones against the hourly budget.
2. **Always pass `--print-timeout`** (for example `--print-timeout 120s`). agy
   retries a 429 in-process 8 times with backoff (~2m20s), so an exhausted CLI
   looks like a hang. A log line `Run: attempt N failed (RESOURCE_EXHAUSTED` in
   `~/.gemini/antigravity-cli/log/cli-*.log` is a **fast fail**: stop, do not
   wait out the retries or retry the call.
3. **Delegate only via `acp-run agy` — never `agy -p`** (standing rule
   2026-10-04). The CLI surface throttles independently of quota and of the ACP
   client, and its lockouts are client-keyed and survive re-login, so a CLI
   dispatch can silently hit a dead client for hours. `agy -p` is not a
   fallback; the interactive TUI is for the operator. If a CLI call is truly
   unavoidable (e.g. probing CLI-local state the ACP shadow home cannot see),
   run exactly one with `--print-timeout`. When one client returns 429 while
   `aiuse` shows headroom, **try the other client** before moving the slice to
   another vendor. Preflight the exact client you will use.

   **`acp-run claude` handshake flake:** `session/new` can hang after a successful
   `initialize` (claude-agent-acp `newSession` awaits `providerUpdate` with no
   timeout). `acp-run` retries handshake twice (40s each) then falls back to
   `claude -p --model … --dangerously-skip-permissions` unless `--no-fallback`.
   Do not wait out a hung ACP process.
4. **Burn the agy Claude/GPT pool while it has headroom** (operator,
   2026-10-10: "via agy acp as much as possible ... at the moment it has a lot of
   headroom"; this replaces the old "send Opus-high to agy sparingly"). It is
   Claude Opus/Sonnet 5.5 and GPT on the Google AI Pro plan, a separate window
   from Gemini that resets and is lost: on 2026-10-10 `aiuse` raised a
   *critical* burn alert (5h 100% left, weekly 49% left, weekly resets in ~5 h).
   Gate on `aiuse --available`, not on a standing rule: **at >= 40% left on both
   Claude/GPT windows, prefer it** over claude's own window and codex for code,
   review and research (judgment goes to the frontier pools; agy only as an
   independent reviewer of a frontier decision), via `acp-run agy --model
   claude-opus-5-5 --effort high` (hard calls) or `--model claude-sonnet-5-5 --effort high` (volume; agy 1.4.1, 2026-10-18, dropped the effort-suffixed ids);
   `gpt-oss-120b-medium` is offered too. Over ACP these ids exist only because
   agy_acp_server 1.3.0 offers non-Gemini models only to clients whose ACP `clientInfo.name` is `zed`, `xcode` or `JetBrains.*` (`supports_third_party_models()` in its `model_selection.py`), so `acp-run` identifies itself to agy as `zed` (0b56897); the gate is deliberate in Google's code, so this is a
   client-name workaround that a later `.par` could close. Check with
   `acp-run agy --info` (`acp-dispatch` checks `--model` itself before it
   detaches). Between 15% and 40% give it one
   slice at a time; under 15% (or a 429) it is spent, use the Gemini pool or
   another vendor. **Cap concurrency at 2-3 agy slices at once** (the ACP
   client's own limit is not published, and the pool drained in ~35 minutes
   under a heavy Opus-high run on 2026-10-03) and re-probe before each batch.
   It is not judgment-tier: final calls on contract decisions stay with claude
   or codex, but agy-Claude is a good independent reviewer of them.
   `bin/route_agent.py` encodes this as the `antigravity-claude` service
   (`burn_first`, `pool=("antigravity", "claude_gpt")`): `route_agent.py route
   --kind code` picks it while it holds >= 40% headroom. The same `pool=`
   field splits **any** provider that reports several independent model-family
   pools (aiuse `pool_family`; copilot and cursor when re-enabled in aiuse): add
   one `Service` row per extra pool and burn the one with idle headroom first.
   **For a multi-slice run use `route_agent.py plan --kinds ...`** (a wave spread
   over pools by each service's `max_parallel`, `--exclude` for a pool that just
   failed) and re-run it at every slice boundary; bigteam's *Dynamic routing*
   section says when.
   A model sublimit of a shared pool (Claude's `fable`) is not a pool.
5. A `--print-timeout` cut prints `[agy] print timeout ... returning partial
   output` and **exits 0**; exit 0 is not success, read the output and the log.

## Billing classes (2026-08-23 shape; membership drifts)

- **Monthly subscription windows**: claude (5h/weekly, with Fable a <=50%
  sublimit of the same weekly, not a separate bucket), codex (ChatGPT Plus
  weekly until 2026-10-18, the $100 plan, aiuse `prolite`, since 2026-10-19;
  spend it on `gpt-6-astra`), antigravity/agy (Google AI Pro — also
  exposes Claude/GPT windows), copilot (premium requests; **reserve, floor
  60%**), cursor Pro (Auto and third-party sublimits; GrokBot has its own
  separate Cursor pool since 2026-10-18, never a target), grok (SuperGrok; an
  ordinary pool since 2026-10-18: realtime-web, research, bulk;
  `acp-run grok --model grok-4.7`),
  zai GLM coding plan (via the zcode TUI; an everyday pool), clinepass (Cline
  windows; feeds hermes via LiteLLM :4000; never delegated, aiuse-disabled),
  devin (disabled in Orca on purpose).
- **Never a delegation target**: hermes (the operator's assistant; gated in
  acp-run/acp-dispatch since 2026-10-15).
- **Free**: opencode-go bundled models; sipb (MIT-hosted, `opencode`
  provider `sipb`).
- **Prepaid real money, gated**: opencode-zen, openrouter, deepseek —
  only via the `opencode-ralph-tui-*` gate scripts, never by default.
- **Operator-gated (2026-10-15)**: omp (oh-my-pi), every route (`omp`,
  `omp -p`, `omp acp`, acp-run/acp-dispatch, Orca, herdr): never without the
  operator's specific, explicit approval for that run; `aiuse` flags it
  `requires_operator_approval`. Rules: `bigteam`'s *Operator-gated agents*.
  **cline (2026-10-17)**: the TUI and Cline.app are uninstalled; acp-run,
  acp-dispatch and `route_agent.py` gate it like omp so nothing calls it until
  the operator re-enables it on purpose. Hermes keeps using Cline through its
  own ClinePass API key; that pool stays.

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
except for zcode (accepted, still optional) and `--kind` mandatory on a fresh
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
  (via `codex-acp`), copilot, opencode, cursor, qwen, devin, cline,
  hermes, grok (`grok agent --always-approve stdio`, dropped under `--perm deny`; `--model grok-4.7`; exclusion lifted 2026-10-09, probe 4 s), agy
  (Google's signed `agy_acp_server.par`; verified 2026-10-03 22:54, 6.5 s; fails
  independently of the `agy` CLI, see "agy has a burst limit" above).
  Which ones currently work end to end, and what the others need, is
  in `site-private/memory/feedback_prefer_acp_for_delegation.md`; check
  there, not here.
- **Output:** final message on stdout; one summary line on stderr (stop
  reason, seconds, tool calls, permissions allowed/denied, tokens, cost, log
  path); full JSONL event log under `~/.local/state/acp-run/` unless
  `--log` names one. Exit 0 = end_turn, 1 = error/other stop reason,
  124 = timeout (it sends `session/cancel` first).
- **Always pass `--model`**, except zcode, where it works (acp-run sets
  `ZCODE_BIN`, fixed 2026-10-15) and `acp-dispatch` still does not require it.
  Without it every other agent uses its own default; for the claude adapter
  that is the settings model, which cost about 6× a `--model sonnet` run on
  the same task. `--info` lists valid values.
- **Context window is a routing choice next to vendor, model and effort**
  (2026-10-15). Ask for a bigger window when the slice reads a whole corpus
  or a long log, and leave the default for a small edit. A bigger window
  bills more per token on some services (xAI long-context rates from a 200k
  prompt; Cursor input above 256k at 2×, Fast at 3×; Copilot's long tier
  costs more AI credits) and can be slower.
  1. Request it with `acp-run <agent> --model M --effort high --context 500k`
     (also `256k`, `1m`, and the sizes that agent's table lists). The model
     is applied first.
  2. `acp-dispatch --effort` and `--context` are first-class (checked with the
     model before the job is written, stored on the record, kept by `resume`):
     `acp-dispatch <agent> --model M --kind K --effort high --context 500k`.
     `--acp-arg` still forwards other flags; a dash-leading value needs
     `--acp-arg=--meta`.
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
  without asking, **reads included**: crush and agy run `grep`/`read` unasked,
  so a read-only review on them also needs
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
- cline's ACP mode defaults to its paid `cline` provider and ignores the
  TUI's ClinePass setting, so acp-run always sets `provider=cline-pass`
  (generic form: `--set <config-id>=<value>`, ids from `--info`).
- cline bills ClinePass and claude bills the orchestrator's own pool: see
  *Reserve pools* below before sending either bulk work.

### Knowing when a delegated call finished

Run each delegation (`acp-run ...` or a per-CLI form below) as a **foreground
command in its own Bash call with `run_in_background: true`**, with no trailing
`&`. The harness then re-invokes you when it exits. A shell-`&` job is not
tracked and finishes silently (tested 2026-10-03); a wait loop built on
`pgrep -f '<pattern>'` matches itself and never ends. ACP does not change this:
`acp-run` is an ordinary command, and ACP only makes its exit code (0, 1, 124)
and stop reason reliable. Full recipe: `bigteam` Step 4.

### Per-CLI headless forms (no ACP mode, or fallback)

muse has no usable ACP route yet, so it keeps its form. zcode gained one on
2026-10-08 (`acp-run zcode`, via the third-party `zcode-acp-server`). acp-run
sets `ZCODE_BIN` to `vendor/zcode.cjs` (fixed 2026-10-15). The earlier
"refuses every switch" error (`unsupported config option or switch failed:
model`) was that missing variable: the server followed `which zcode`, a
symlink, and never injected `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE`. The
2026-10-11 weekly-limit note was a different failure. `--model` works and
`acp-dispatch zcode` still does not require it. Pass it when you want
GLM-5.3-Flash. Effort is option `thought` (`low` / `high` / `max` on GLM-5.3,
default max; `medium` and `xhigh` exit 2, no neighbor map). `--context N` is
only `ZCODE_ACP_AUTO_COMPACT_THRESHOLD`, a compact cap; GLM-5.3's window is
fixed at 1,000,000. A 2026-10-15 prompt died `project_token_login_failed` at
the z.ai login, unrelated to acp-run. Table: `tools/acp-run/README.md`.
Its row below is the fallback.
The rows for ACP-capable CLIs stay as a fallback for when an ACP route is
broken. **agy:** prefer `acp-run agy`; the `agy -p` form below is the fallback and
is subject to the burst budget in "agy has a burst limit" above.

**Default permission mode: yolo or its equivalent, for every agent however launched** (standing rule 2026-10-03, `home-agents.md`). Gate only a clearly security-sensitive slice (prompt-injection exposure: `--perm read-only` for a slice that reads, `--perm deny` for text-only; `--role advise` refuses `deny`, 2026-10-19), and say so (operator 2026-10-15; a plain review runs yolo with a read-only brief and a diff check); acp-run has no other gate since 2026-10-14 (bigteam checks file ownership from the diff after the run). `-s read-only` on codex likewise only for those calls; work slices use `--dangerously-bypass-approvals-and-sandbox`.

**Authority for launch flags:** Orca's roster,
`~/Library/Application Support/orca/profiles/local-default/orca-data.json`
→ `settings.agentDefaultArgs`. That map is what actually works on this
machine for every enabled TUI (codex `--dangerously-bypass-approvals-and-sandbox`,
antigravity `--dangerously-skip-permissions`, copilot/cursor `--yolo`,
grok `--permission-mode bypassPermissions`, …). Read it instead of guessing
flags. Standing rule (frontier-ai-review-stack memory): prefer a TUI's
official headless mode, or a maintained orchestrator (Orca
`worker-start --agent <name>`, see the `orchestration` skill), over a
hand-rolled subprocess wrapper.

When a direct one-shot call is still the right tool (a single review of a
diff), these forms are verified 2026-09-20. Every one runs with **stdin
closed** (`< /dev/null`) and output redirected to a file; backgrounding a
TUI with `&` inherits the harness's stdin and codex blocks on it forever.

| TUI | Verified headless form | Failure mode seen |
| --- | --- | --- |
| codex (GPT-6 Astra default) | `codex exec -s read-only -C <dir> "<prompt>" < /dev/null > out 2>&1` | without `< /dev/null`: prints `Reading additional input from stdin...` and hangs with no timeout. |
| agy (Antigravity) | `agy --dangerously-skip-permissions --print-timeout 120s -p='<prompt>' < /dev/null > out 2>&1` — **attach the prompt with `-p=`**, which is order-independent and cannot be confused with a flag. `-p`/`--print`/`--prompt` is a *required-value string flag*, not a boolean. | `agy -p` with no value: exits 2, `flag needs an argument: -p`. `agy -p --effort high` (value-less `-p` before another flag): **since 1.1.18 this is a clean exit 2** naming the mistake — *"-p took \"--effort\" as its prompt…"* — and before 1.1.18 it silently ran with `--effort` as the prompt. Verified on 1.2.16, 2026-10-03. Headless still needs `--dangerously-skip-permissions` or tool permissions auto-deny (by design, hardened in 1.2.15). **`RESOURCE_EXHAUSTED (code 429)` with `aiuse` showing headroom** (2026-10-03: every CLI model, 15:42 to 23:50+, while ACP worked): a CLI burst lockout, not an empty pool; the CLI retries 8 times (~2m20s) so it looks like a hang, and `--print-timeout` cuts it with exit 0 and partial output. Check `grep 'attempt [0-9]* failed' ~/.gemini/antigravity-cli/log/cli-*.log` and switch to `acp-run agy`. |
| copilot | `copilot -p "<prompt>" --model auto --allow-all-tools --allow-all-paths --silent < /dev/null > out 2>&1` | fine as-is. **Do not add `--reasoning-effort` with `--model auto`**: exits 1, `Model "auto" does not support reasoning effort configuration` (2026-09-26). Name a concrete model if you want an effort level. |
| opencode (free Go bundle) | `opencode run -m opencode-go/<model> "<prompt>" < /dev/null > out 2>&1` — e.g. `opencode-go/deepseek-v4-pro`, `opencode-go/gpt-6-luna`, `opencode-go/kimi-k3` (all answered 2026-09-26; `opencode models \| ggrep ^opencode-go/` lists 33). | **`opencode/<model>` is the prepaid Zen catalogue, not Go**: every `opencode/*` model except `big-pickle` fails with `Upstream request failed: Insufficient account funds`. `big-pickle` answers but on a review prompt spent its run trying to install pytest and returned nothing — steer it with "do not run tests or install anything". **Side effect:** every `opencode run` rewrites `./opencode.json` in the cwd (adds a `$schema` key) — `git checkout -- opencode.json` afterwards in repos that track it. |
| cursor-agent | `cursor-agent -p --yolo --output-format text "<prompt>" < /dev/null > out 2>&1` | without `--trust` (or `--yolo`/`-f`) in a directory Cursor hasn't trusted: exits 1 with a "Workspace Trust Required" prompt and no review. |
| zai (zcode) | `zcode -p "<prompt>" < /dev/null > out 2>&1` — `-p` already defaults to `--mode yolo`; `--attach <file>` works (verified 2026-09-30). Inlining the file into the prompt is equally fine. | **Never pass `--mode build` (or `--mode edit`) headless**: it gates every tool behind an approval no one can give, so the run hangs indefinitely — process alive, ~0 CPU, no `zcode-cli` worker doing work, zero output — until it's killed (seen 2026-09-30, `--mode build --attach`). The default yolo mode auto-approves. The `ZCode Built-in skipped (not-due)` lines on stderr are a benign memory-heartbeat, not an error. |

Where DeepSeek lives on this machine (probed 2026-09-26): free —
`opencode-go/deepseek-v4-pro` / `-v4-flash` / `-v4.1-flash` (Go bundle)
and `sipb/deepseek-r1:{8b,14b,32b}` (MIT-hosted); paid —
`opencode/deepseek-*` (Zen prepaid), `clinepass-deepseek`
via LiteLLM :4000 (ClinePass, a reserve pool), and the `deepseek`
prepaid account. Check `aiuse` for what is left in each. z.ai serves GLM, not DeepSeek.

Rules that fall out of this:

- Exit 0 is not success. Append `echo "<tool> exit=$?"` to each output
  file and treat a file holding only a preamble line as a failed run.
- Prefer the read-only sandbox where one exists (codex `-s read-only`).
  Where it does not (agy), check `git status --porcelain` afterwards;
  agy left an empty `graft/` directory in the repo on one run.
- One background Bash call per batch with a long timeout, never chained
  `sleep`s; read each output file when the batch notification arrives.
- A reviewer that returns exit 0 with no findings is a failed run, not a
  clean bill: check the file has an actual review before counting it.
- Run reviewers against a stable tree: don't edit the file under review
  while they read it. For a second round after fixes, tell them what the
  first round found and fixed, so they verify rather than repeat.

Herdr-hosted TUIs (driving agents in Herdr panes; verified 2026-09-26):

- `herdr workspace create` returns before the pane's shell is up;
  `herdr agent start` a moment later fails `agent_pane_busy: … is not an
  available shell`. Poll `herdr pane read <pane>` for a shell prompt (`$`)
  first — ~2 s.
- Key names are `ctrl+c`, `enter`, `esc` (`ctrl-c` → `invalid_key`).
- `herdr pane read` prints plain text; every other command prints one JSON
  envelope, `{"error":…}` **with exit 0** on failure — parse the envelope.
- `herdr agent prompt <target> "/exit"` cleanly ends a Claude session and
  returns the pane to its shell; `bin/herdr-sleeper` in djbclark-ade
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
   1a. **Judgment** (review, design, adjudication) is `acp-dispatch claude
       --model opus --kind judgment --effort high`. It is not Fable and not
       codex.
   1b. **`frontier`** is the only route to codex `gpt-6-astra` (`--kind
       frontier --effort high`) or Fable 5.1 (`--kind frontier --effort high`):
       one slice per pool per wave, for
       work that really needs a frontier model to look it over. Examples: a
       security-relevant or concurrency fix's final review, debugging that has
       defeated real attempts, an adjudication no cheaper model settles, a
       whole-corpus read that needs Fable's 1M window. "Upstream-bound", "small
       issues" and "a second opinion would be nice" are not reasons.
   1c. **In-flight slices reserve quota, per service** (2026-10-18; it replaced
       the codex-only "one slice in flight" cap). Each running slice reserves
       its estimated quota on its service, and a fresh dispatch must fit what
       is left: `acp-dispatch` refuses one that does not (exit 5, class
       `inflight`); resumes are exempt. `ACP_DISPATCH_INFLIGHT=codex=2`
       still sets a hard cap for a run. codex is only for astra; never spend
       its window on `gpt-6-luna` everyday slices.
   1d. **Fable at `xhigh`/`max` almost never runs**: `acp-dispatch` refuses it
       without `ACP_OPERATOR_APPROVED=fable-xhigh`. Ask djbclark first; the
       `fable-deep` agent runs at `high`.
2. **Fable and "claude" are one pool.** `aiuse --available` lists two routing
   entries, but Fable is a model sublimit: **at most 50% of the shared Claude
   weekly**, and every Fable run bills the shared 5-hour and weekly windows too
   (`cswap list`: read the 5h, 7d and Fable lines together; the fullest
   binds). Under 10% of the Fable cap, judgment falls back to Opus 5.5 at the
   same effort (`route_agent.py` does this; `FABLE_MIN_LEFT`).
3. **Everyday work goes to the other pools**, so the frontier windows stay for
   item 1: implementation with a clear shape, tests, refactors, doc writing,
   research summaries, bulk reads, mechanical edits. Order by fitness, then
   headroom, as `plan` computes it: agy's Claude/GPT pool while it has >= 40%
   left (Opus/Sonnet 5.5 quality that is otherwise lost at reset), Cursor's
   Auto pool (`--model default`; its third-party pool is separate and often
   tight), zai GLM-5.3 (`GLM-5.3 --effort high` for code, `GLM-5.3-Flash
   --effort low` for bulk), opencode-go, agy Gemini for bulk and big-context
   reads, crush/SIPB (free, 30B-class) for light bulk. Claude's own pool
   codes on Sonnet 5.5 (`claude --model sonnet --effort high`, rank 12, right
   after agy's Claude pool; operator 2026-10-18: only Fable stays out of
   code); Haiku only as Agent-tool sub-agents for small lookups. Gemini Flash
   is not a code pool (2026-10-18: GLM-5.3 tier on hard agentic coding), and
   **quota never buys a much weaker pool into code or judgment**: `plan`
   only picks pools within `[routing].quality_max_rank_gap` (10) rank steps
   of the best eligible one, and otherwise keeps the slice queued.
4. **Minimum needed spec, proactively.** Pick the smallest model, effort and
   context that will do the slice *well*, and delegate even when nobody asked:
   `/bigteam` for separable work; an Agent sub-agent only at `model: "haiku"`,
   `effort: "low"` for a lookup or a classification (item 3: it bills the
   shared pool), so the session's own context stays small. Implementation,
   whether its shape is clear or not, goes through `acp-dispatch` to the
   everyday pools (agy `claude-opus-5-5 --effort high`, claude `sonnet --effort high`,
   zcode `GLM-5.3 --effort high`, cursor `default`); Fable/astra only for `frontier` (item 1b). **Start on the cheap eligible tier and escalate
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
          (`claude --model opus --kind code --effort high`, or agy's Claude
          pool, whose code row is already Opus). That means root cause without
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
   prompt), Cursor (2× above 256k, Fast 3×) and Copilot (long tier), and can be
   slower. Read `acp-run: applied: model=... effort=... ctx=...`; the per-agent
   table is `tools/acp-run/README.md` (2026-10-15).
6. **The reserve, never depleted:** **copilot** (GitHub-side Copilot
   review of commits draws on its premium requests; it read 100% used on
   2026-10-15, so this has already gone wrong once). Hard floor **60% left**
   (`reserve_floor` in `route_agent.py`), one small slice at a time, and only
   for `github` slices, GitHub-context work that `gh` from any other agent cannot
   do. A missing or stale copilot reading means do not use (`route_agent.py`
   fails closed). **Grok is no longer a reserve (2026-10-18):** GrokBot (the
   cloud Chief of Staff) moved to its own separate Cursor pool when djbclark
   upgraded to the $60 Cursor plan, so the `grok` TUI is an ordinary
   subscription pool (`realtime-web`, `research`, `bulk`; no floor), ranked
   behind the burn-first pools; never route into the GrokBot pool (aiuse
   provider `grok-bot`). Grok *models* reached through another TUI (cursor,
   copilot, opencode) bill that TUI and are fine. **clinepass**: never a bigteam target
   (`NEVER_ROUTE` in `route_agent.py`; it stays in Hermes's chain as its
   lifeline; aiuse `[disabled_services]`). Claude itself: keep enough 5h headroom to finish
   integrating what is in flight, because orchestration runs from it.
7. **Never:** **hermes** as a delegation target (the operator's own assistant;
   `acp-run` and `acp-dispatch` refuse it the way they refuse omp); **omp**
   without the operator's specific, explicit yes for that run
   (`ACP_OPERATOR_APPROVED=omp`; `bigteam`'s *Operator-gated agents*); **cline**,
   uninstalled 2026-10-17 and gated the same way (Hermes's ClinePass pool is
   separate and stays); the
   prepaid pools (opencode-zen paid, openrouter, deepseek) without a fresh
   operator decision; a credits-backed model (Claude usage credits, Codex
   credits, OpenCode Go "Use balance") or re-enabling a disabled toggle to reach
   a better model; `devin` (dormant by choice); an all-vendor fan-out.
8. **Probes over memory, per batch:** `aiuse --available` (exit 3 = nothing
   usable), `cswap list`, then `route_agent.py plan --kinds ...`; re-plan at
   every slice boundary (`bigteam`, *Dynamic routing*). Exhausted vendors come
   back by themselves when their window resets; keep no private skip list.
9. **Levers:** `acp-run <agent> --model M [--effort L] [--context SIZE] [--mode M]`
   (`--info` lists the ids); `acp-dispatch` takes the same three flags; Claude
   workflows `agent(..., {model, effort})`; Orca `worker-start --agent <TUI>
   --model --effort`; the per-CLI headless forms only where no ACP route exists
   (muse) or as a fallback.
10. Model names get renamed and retired: a name from an old plan or roster is a
    hint. Check `acp-run <agent> --info` before committing to an id.
11. **Context hygiene is part of cost.** Claude Code compacts a session by
    itself at 400k tokens (`autoCompactWindow` in `~/.claude/settings.json`,
    2026-10-15; the PreCompact hook writes the Tier 1 checkpoint). In a herdr
    pane or Orca terminal compact earlier, at a natural boundary, with
    `self-slash "/compact <focus>"`; on a topic change run the `handoff` skill,
    then `/new`. Never ask the operator to do either unless `self-slash`
    refuses (`effort-routing`, *What actually dominates cost*).

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
