---
name: bigteam
description: >-
  Run the prompt as a multi-vendor fan-out: probe quota pools, slice the work
  into disjoint file-scoped assignments, dispatch them in parallel across the
  non-Claude TUIs, integrate the results. Use for /bigteam, "bigteam",
  "parallelize this", "use the other agents too", any discrete separable task
  that would pull heavy context into the session, and when the context-size hook
  says to delegate.
---

# bigteam — multi-vendor fan-out for one prompt

Turn one prompt into parallel work across every agent CLI on this machine,
spending the *cheapest adequate* pool for each slice and keeping Claude's own
window for what only it should do.

The optimisation target (operator, 2026-10-15): **minimise cost while
maximising code quality.** Not "minimise tokens": tokens on different pools
cost different money, and a weak model's cheap tokens are paid for again in
review and rework. Concretely:

1. **The two frontier models are scarce: only what really needs them**
   (operator 2026-10-18). Claude Fable 5.1 and codex `gpt-6-astra` are reached
   only through the `frontier` kind, one slice per pool per wave (two on claude under the standing allowance of 2026-10-27 while the quota guard passes, `docs/gates.md`). On
   2026-10-18 a wave of four astra slices emptied codex's 5-hour window and
   every one stopped. Judgment is Opus 5.5 at `high` first (2026-10-25: omp Opus next, Codex
   `gpt-6.1-sol` at high only while every codex window has `plenty_min` left). `acp-dispatch` runs a
   frontier model only with `--kind frontier`, as a read-only advisor unless
   `ACP_OPERATOR_APPROVED=frontier-exec` (2026-10-18); it reserves each
   in-flight slice's estimated quota on its service before a new one fits (a
   refusal is class `inflight`, exit 5; this replaced the one-fresh-codex-slice
   cap, 2026-10-18), and refuses Fable at `xhigh` without
   `ACP_OPERATOR_APPROVED=fable-xhigh`. Fable and "claude" are **one pool**
   (Fable is a <=50% sublimit of the shared weekly and bills the 5-hour window
   too).
2. **Everyday work goes to the other pools** so those windows stay free:
   agy's Claude/GPT pool, Cursor Auto, zai GLM-5.3, opencode-go, agy Gemini,
   crush/SIPB. Every slice names its **vendor × model × effort × context**,
   at the minimum spec that does it well; never redo work already paid for.
3. **The reserve is never depleted** (copilot: floor 60% left, one small
   slice, only for `github` slices; grok has been an ordinary pool since
   2026-10-18); **hermes is never a target**;
   **omp (the Claude API credits) is a normal tier since 2026-10-19**: `api-only`
   work first, else `code`/`bulk` slices so the credits are spent before the
   monthly expiry; never an all-vendor fan-out.
4. **Use this skill proactively**, even when not asked: any discrete,
   separable work leaves this session's context.

This skill is the *method*. `model-routing` holds the one copy of the routing
policy (*Routing policy (operator, 2026-10-15)*), the verified invocation
forms and the billing-class map; read it, don't duplicate it here.
The reasons and sources behind the brief shape, run sizing, the 3-attempt cap
and focused-checks-first are in `docs/orchestration-practices.md`
(djbclark-ade, 2026-10-11).

**Decide in code, reason in Claude.** The orchestrator's multiple-choice
calls (which kind, which pool, retry or re-route or stop, which tests first)
come from code: `route_agent.py plan`, `acp-dispatch`'s exit code, `aiuse`'s
exit 3, `git diff --name-only`. Don't spend a frontier turn on them. Spend it on
slicing, briefs, diff review and integration. When code can't decide, route
the slice **up** a tier, not down.

## Step 0 — another bigteam run may already be live

Another session may be running its own fan-out right now (often the Paseo agent
labelled `coord`). The two share every quota pool and possibly the checkout, so
before slicing:

1. **Look.** `paseo ls -g` (a `coord` agent, or any agent
   `running` a fan-out) and `ls -lt ~/.local/state/bigteam/` (task dirs
   touched in the last hour). Read each live dir's `CLAIM`. herdr and Orca
   terminals are retired from djbclark-ade (2026-10-31): do not look there.
2. **Claim.** Use a task name no live run uses, and write
   `~/.local/state/bigteam/<task>/CLAIM` before dispatching: session (Paseo
   agent id or Claude session id), repo, owned files, start time. Append `DONE`
   when you finish.
3. **Never overlap files.** A file another live claim owns is not yours to
   slice, edit, stage or format. In a shared repo, commit only your own paths,
   by path, after `git pull --rebase`; never touch the other run's uncommitted
   files.
4. **Pools are shared.** Re-probe `aiuse --available` right before each batch
   (the other run drains the same windows), leave headroom, and don't put both
   runs on a burst-limited pool at once (agy's ~60 requests/hour is machine-wide).
5. **Hands off its tabs.** Never reuse, close or message the other run's
   Paseo tabs or agents. To coordinate, tell its session (`session-finder`).

## Step 1 — probe, never assume

    aiuse --available --json 2>/dev/null        # usable pools only, per vendor AND model family, cache, <1 s
    aiuse --available --live --json 2>/dev/null # force a live collect (~30-60 s)
    cswap list               # Claude 5h / weekly / Fable

**Always `--json`** and read it by the schema: the field list is in `model-routing`
*Probes* (`aiuse schema` is the contract; the human table changes, 2026-10-17).
`aiuse --available` (aiuse 3.1.4+) prints only pools that can take work, sorted by
headroom, every window as "X% used / Y% left", with the data's age on its first
line. Exit 0 means usable pools exist, **3 means nothing is usable** (the data is
fine, the quota is not), 1 is a real error. It reads the snapshot cache that
`aiuse watch` and an hourly launchd job keep fresh, so you rarely need `--live`.
**Use the cache by default** (operator, 2026-10-06: slightly stale data saves a lot
of time). Take it as good enough when it says `fresh` (under ~25 min); add `--live`
only when it is older than that, or when the choice hinges on a pool that is near
empty or past its reset time since the snapshot. History: every collect is kept in
`~/.cache/aiuse/snapshots/` (and `ledger/`), so trends need no live call either. A pool missing from the list is exhausted or
suppressed: `aiuse --json -q | jq -r '.summary_lines[]'` shows every pool,
including the exhausted ones. Either way, preflight each target (*Reading the numbers* below),
because no snapshot sees a pool drained in the last few minutes.
(`~/ops/site-private/bin/aiuse-pools` is a thin wrapper for the same command.)

### Reading the numbers — a misreading here already cost a dispatch round

Read every number per `model-routing`'s *Reading quota numbers* and *agy has a
burst limit* (the one copy of those rules): used is consumed, the fullest window
binds, one TUI can hold several model-family pools (retry the vendor's other
pool before reassigning), re-probe before each batch, and agy only via
`acp-run agy`, no probe loops. `acp-dispatch` enforces the target preflight
with `"Reply with exactly: OK"`, caches a pass per agent/model for ten minutes,
and refuses measured pools below 10% left. `aiuse --available` already encodes
the first three in its output.

Classify every pool before assigning anything:

| class | meaning | use for |
| --- | --- | --- |
| **fresh subscription** | monthly/weekly window largely unused | bulk, mechanical, writing, research — use heavily |
| **tight** | >40% of the binding window burned | one slice at most, or skip |
| **exhausted** | `remaining_percent` ≈ 0 on ANY window of that pool | skip that pool entirely (the same vendor's other model-family pool may be fine) |
| **frontier** | Claude Fable 5.1 and codex `gpt-6-astra` | only a slice that really needs a frontier model to look it over (a security-relevant or concurrency fix's final review, debugging that defeated real attempts, a whole-corpus read); one per pool per wave, two on claude under the standing allowance while the quota guard passes (2026-10-27, `docs/gates.md`); in-flight slices reserve quota (2026-10-18); see *Pool policy* below |
| **lifeline** | another agent runs on it | use with care and never let it run out; see *Reserve pools* below (clinepass and Claude itself) |
| **reserve** | copilot (GitHub-side review) | hard floor 60% left (`route_agent.py` `reserve_floor`), one small slice at a time, only for kind `github`; a missing or stale reading means do not use. Grok was one until 2026-10-18 (GrokBot moved to its own Cursor pool): now an ordinary subscription pool for `realtime-web`, `research` and `bulk`, behind the burn-first pools |
| **never** | hermes; the prepaid pools; credits-backed models (not the Max plan's API credits: omp, below) | not a target by any route; `acp-run`/`acp-dispatch` refuse hermes behind an approval gate |
| **api credits** | omp: the Claude Max plan's monthly API credits (expiring grant, operator 2026-10-19) | kind `api-only` first (SDK paths, verdict classifiers, batch jobs), else `code`/`bulk` via `acp-run omp --model anthropic/claude-sonnet-5-5` so they are spent before each expiry; `route_agent.py` marks it "burn before reset" when far above an even spend; needs a working omp Anthropic login (`omp login`) |
| **burn-first** | a pool whose window resets and the allowance is lost, with >= 40% left on every window (`aiuse` raises a `kind:"burn"` alert). Today: **agy's Claude/GPT pool** (`acp-run agy --model claude-opus-5-5 --effort high` / `--model claude-sonnet-5-5 --effort high`, agy 1.4.1 (2026-10-18) dropped the effort-suffixed ids), and any provider's idle second pool | assign it first for code, review and research, 2-3 slices at once (judgment goes to Claude and omp first, codex's Sol at high only while plentiful; 2026-10-25); see *agy Claude/GPT pool* below |
| **shared allowance** | a GitHub-side feature draws on the same subscription | usable, but spend modestly and keep a margin; see *Copilot* under *Reserve pools* below |
| **prepaid** | real money | never without a fresh explicit operator decision |
| **excluded** | operator has ruled it out | respect it, with its end condition (below) |
| **operator-gated** | the operator must approve each use (hermes, cline; omp until 2026-10-19) | never plan, probe or dispatch it without the operator's specific, explicit yes for this run; see *Operator-gated agents* below |

### Pool policy — who gets which slice (operator, 2026-10-15)

The one copy of the rules is `model-routing`, *Routing policy (operator,
2026-10-15)*; `bin/route_agent.py plan` applies them and prints the
`acp-dispatch <agent> --model M --kind K --effort E` line per slice (the policy
table is `config/routing.toml`, printed by `route_agent.py policy --md`). What
a fan-out needs from it:

1. **Spec every slice as vendor × model × effort × context, at the minimum
   that does it well.** The brief states all four; the dispatch is
   `acp-dispatch <agent> --model M --kind K --effort E [--context S] ...`
   (`--kind` is required on a fresh dispatch: exit 2 without it, or when the
   agent and model are not eligible for that kind; 2026-10-18); the waiter or
   the lead checks `<name>-stderr.txt` for `acp-run: applied: model=...
   effort=... ctx=...` (exit 1 class `config` = the request did not land).
   Context stays at the agent's default unless the slice reads a whole corpus
   or a long log (`--context 500k` / `1m`; bigger windows bill more on xAI,
   Cursor and Copilot).
2. **`judgment` slices** (architecture, adjudication; 2026-10-25) go to `acp-dispatch claude
   --model opus --kind judgment --effort high` first; omp Opus on the credits is next, and Codex
   `gpt-6.1-sol --effort high` (`--kind judgment`, rank 3) is an eligible, lower-ranked pool only
   while every codex window has at least `[routing].plenty_min` (50%) left (astra stays
   frontier-only; `plan` picks it only when it ranks within the quality gap). **Adversary rounds** (the
   adversarial second opinion of Step 6) go first to the omp route, `acp-dispatch
   omp --model anthropic/claude-opus-5-5 --kind judgment --effort high` (Claude API
   credits; operator 2026-10-23, after the Claude weekly window ran out 2.6 days
   early on 2026-10-20). The Agent-tool `adversary` (`model: opus`) is the fallback
   when omp is unavailable, and the lead passes the Agent tool's `model: "sonnet"`
   override whenever `~/.local/state/ade/quota-guard.json` says `tight` or
   `critical` (`bin/claude-quota-guard`; a `[quota-guard <level>]` line from the
   UserPromptSubmit hook says the same). **Whatever route runs it, the brief says the verdict ends
   with the marker line** `<!-- adversary-verdict:v1 {"verdict":"APPROVE"|"BLOCK","head":"<full
   40-hex sha>"} -->`, raw (not in a fence), for the lead to paste into the PR body. The omp route
   reads only a free-form brief; the Agent-tool `adversary` sub-agent loads
   `claude/agents/adversary.md` (through the `~/.claude/agents/adversary.md` symlink, whose target
   `bin/ade-update` checks and reports a repair command for, never links itself) as its system prompt —
   so the marker line belongs in both that file and the brief, and a marker in one alone reaches only
   one of the two routes (AGENTS.md rule 1, PR 67). The lead session itself runs on Opus 5.5
   high (Sonnet 5.5 at medium when it only drives a pipeline, high only for a judgment turn; `[lead] pipeline_effort`), never Fable
   (`model-routing`, *Routing policy* item 12).
   **`frontier` slices** are the rare few that really need a frontier model
   (debugging that defeated real attempts, a security-relevant or concurrency
   fix's final review, a whole-corpus read): `acp-dispatch codex --model
   gpt-6-astra --kind frontier --effort high` or `acp-dispatch claude --model
   fable --kind frontier --effort high` (an Agent-tool `fable-deep` call is the
   in-session form), one per pool per wave (two on claude under the standing allowance, 2026-10-27, while the quota guard passes: `docs/gates.md`). A frontier slice is a read-only
   advisor by default (`--role advise`: its deliverable is the report, and
   `check` says ADVISOR EDITED THE TREE if it edits); `--role exec` needs
   `ACP_OPERATOR_APPROVED=frontier-exec` (2026-10-18). Fable's cap is 50% of the shared Claude weekly and it bills the
   5-hour window too; under 10% of the cap, `plan` suggests `opus --effort
   high` instead. Fable at `xhigh` needs djbclark's yes for that run. codex is
   for astra, not for luna-class everyday slices, and its in-flight slices
   reserve quota against a new one (class `inflight`, exit 5; replaced the
   one-slice cap, 2026-10-18): a "small issues" wave is not frontier work
   (2026-10-18).
3. **`code`, `research`, `bulk`, `mechanical` slices** go to the everyday
   pools, in `plan`'s order: agy Claude/GPT (>= 40% left; `claude-opus-5-5
   --effort high` for code, `claude-sonnet-5-5` for volume), Cursor Auto
   (`cursor --model default`), zai (`zcode --model GLM-5.3 --effort high`;
   `GLM-5.3-Flash --effort low` for bulk), opencode-go (`opencode --model
   opencode-go/deepseek-v4.1-flash`; MiniMax M3 for bulk, Luna for mechanical work;
   costly Go models are bounded advisors per `model-routing`), agy Gemini (`agy --model gemini-3.8-flash --effort
   medium`) for bulk and big-context reads, crush (`sipb-llms:qwen3.6:35b-a3b-q4_K_M`,
   free) for light bulk. Claude's own Sonnet/Haiku only as small Agent-tool
   sub-agents (they bill the orchestrator's pool).
4. **`github` slices** are the only use of copilot, and only above its 60%
   floor; `gh` from any other agent covers most GitHub work. **Grok** takes
   `realtime-web` slices first and `research`/`bulk` behind the burn-first
   pools; it has no floor (an ordinary subscription pool since 2026-10-18).
5. **Never**: hermes (gated in `acp-run`/`acp-dispatch`), cline, prepaid or
   credits-backed models (the Claude API credits via omp are a pool, item 3), clinepass (never a bigteam target: `NEVER_ROUTE` in
   `route_agent.py`; it stays in Hermes's chain), devin, an all-vendor fan-out.
6. **Start on the cheap eligible tier and escalate on a verified failure**
   (operator, 2026-10-18; it replaces "route up when unsure"): move the slice
   with `acp-dispatch reroute <record> --agent A --model M`, and tell the next
   re-plan what moved (item 6 of *Dynamic routing*).

### agy Claude/GPT pool — assign it first while it has headroom (operator, 2026-10-10)

The operator wants agy's Claude/GPT pool used heavily whenever it has room
(`aiuse` read 5h 100% left, weekly 49% left and a *critical* burn alert on
2026-10-10). It is a **separate pool from agy's Gemini** and from Claude's own
window, so spending it costs nothing that orchestration needs.

1. **Probe it as its own pool.** `aiuse --available` lists it as `antigravity
   claude_gpt`, apart from `antigravity gemini`. Decide from its two windows'
   `remaining_percent`; either one under 15% means skip it this batch.
2. **Assignment order for a Claude-class code, review or research slice**
   (implementation, reviews, research synthesis): the agy Claude/GPT pool
   first, then the other everyday pools in `plan`'s order; judgment follows
   *Pool policy* item 2 above (2026-10-25). `--model claude-opus-5-5 --effort high` for the hard
   slices, `--model claude-sonnet-5-5 --effort high` for volume. Mechanical edits and bulk reading still go to the free and Gemini
   pools first; do not spend Opus on them just because it is idle.
3. **The ACP route reaches it through a client-name workaround (2026-10-10).** agy_acp_server 1.3.0 offers non-Gemini models only to clients whose ACP `clientInfo.name` is `zed`, `xcode` or `JetBrains.*` (`supports_third_party_models()` in its `model_selection.py`), so `acp-run` identifies itself to agy as `zed` (0b56897).
   Before that, the server listed only `gemini-*` models and `claude-opus-5-5-high` failed with
   `no model` (google-antigravity/antigravity-cli#1168, pingdotgg/t3code#16489). The gate is
   deliberate in Google's code, so this is a client-name workaround, not a bug fix, and a later
   `.par` release could close it. `acp-run agy --info` lists the ids (today
   bare `claude-opus-5-5` and `claude-sonnet-5-5` (agy 1.4.1, 2026-10-18; effort is the `thinking_level` option, set with `--effort low|medium|high`, no longer an id suffix),
   `gpt-oss-120b-medium`, plus `gemini-*` and `gemini-pro-agent`, the ACP id of Gemini 3.1 Pro
   High). `acp-dispatch` now checks `--model` against that list before it detaches and exits 2
   with `have:`. If no `claude-*` id is listed, the workaround has stopped working: route to
   codex (`gpt-6-astra`) or claude.
4. **Only through ACP:** `acp-run agy -C <dir> -p '<prompt>' --model <m>` with the
   usual `acp-dispatch` wrapper, never `agy -p`. Run **2-3 agy slices at a time**
   and re-probe between batches; a heavy Opus-high run drained it in ~35 minutes on
   2026-10-03. A 429 or `RESOURCE_EXHAUSTED` on a `claude-*` model means that pool
   is spent; try a `gemini-*` model before leaving agy.
   **agy's file tools see only `-C`** (it ignores `--add-dir`; 2026-10-11).
   `acp-dispatch` relays the report from `<-C>/.acp-dispatch/` by itself. Every
   other file the brief names (an earlier report, a decision note, a log) must be
   copied into `<-C>/.acp-dispatch/` first, and the brief must point there.
5. **Not a replacement for the judgment tier:** use it as the independent reviewer
   of a decision claude or codex makes (Step 6), not as the one deciding.
6. **`bin/route_agent.py route --kind code`** applies the same rule (the
   `antigravity-claude` service, `burn_first` at >= 40% headroom). Any other
   provider that reports an independent second pool (copilot, cursor, once
   re-enabled in `aiuse`) gets the same treatment by adding a `Service` with
   `pool=(provider, pool_family)` there; classify it as burn-first here whenever
   its idle window will reset unused.

### Vendors come back on their own

Nothing here takes a vendor out of rotation for good (operator, 2026-10-06: "make
sure vendors are automatically used again when more tokens become available"):

1. **Exhausted pools** drop out of `aiuse --available` and reappear by themselves
   once the sampler's snapshot sees the reset. Never keep a private "skip X" list
   between batches; probe each batch.
2. **`aiuse note-exhausted`** overrides always carry a reset time and expire then.
3. **An operator exclusion** ("don't use agy for now") is recorded with its end
   condition: a date, or an event such as "until reinstalled" (`acp-run --list`
   shows `ok` again) or "until the burst-limit issue is fixed". Re-check the
   condition each batch; when it has passed, the vendor is back in the pool. If no
   end condition was given, ask for one rather than excluding indefinitely.

**Current exclusions** (keep this list short; delete an entry when it lapses):

1. (none)

Lapsed: **the grok vendor (xAI's SuperGrok subscription)** was excluded
2026-10-06 ("Stop using grok (the vendor) in /bigteams etc. for now") and
**lifted 2026-10-09** by the operator ("grok is working again, so include it
as well as claude and codex", during the `ai-heaven` research run). Route:
`acp-run grok -C <dir> -p '<prompt>' --model grok-4.7` (`grok models` lists
grok-4.7 default, grok-4.7-build-fast, grok-4.6, grok-4.5; the CLI also
takes `--reasoning-effort`, `--prompt-file`, `--permission-mode`); probe
answered in 4 s on 2026-10-09. A missing or stale grok reading in `aiuse`
means do not use it. It is no longer a reserve: GrokBot moved to its own Cursor pool on 2026-10-18 (see *Reserve pools*). Still true: the `grok` entry
in `~/.config/aiuse/config.toml` `[disabled_services]` is commented out, and
Hermes's `fallback_providers` do not name `grok-sub` (operator's call).

### Operator-gated agents: hermes and cline ask first, every time (omp left the list 2026-10-19)

"Not use omp or omp acp without specific explicit operator approval" (operator,
2026-10-15) was a standing gate until **2026-10-19**, when djbclark lifted it
(round 2 of the software-factory `/steps` walk): the pool `aiuse` labels "omp
credits" is the Claude Max plan's monthly API credits, an expiring grant, and
**the Claude API credits are a normal tier, used with discernment: first for work
that needs API access and cannot run through a TUI or ACP (kind `api-only`), and
otherwise for ordinary `code`/`bulk` slices via `acp-run omp`, so the credits are
fully used before they expire each month, never left unspent.** `acp-run` and
`acp-dispatch` no longer ask for `ACP_OPERATOR_APPROVED=omp`; the `aiuse`
`requires_operator_approval` flag on that row is stale (queue item: aiuse). Two
cautions stay: omp's configured default is `github-copilot/gpt-5.6-luna`, so
`acp-run omp` refuses a run without `--model anthropic/claude-...` (a bare omp run
would spend the Copilot reserve), and `route_agent.py` skips omp for dispatch kinds
while omp has no enabled Anthropic login (`omp login`).

1. **hermes**: never a delegation target (operator 2026-10-15), gated in
   `acp-run`/`acp-dispatch`.
1a. **cline (operator 2026-10-17)**: the CLI and Cline.app are uninstalled. The
   machinery (`acp-run cline`, `acp-dispatch cline`, the `route_agent.py` alias)
   stays, gated behind `ACP_OPERATOR_APPROVED=cline`, so it is re-enabled only on
   purpose: reinstall, then the operator names it. Hermes still uses Cline through
   its own ClinePass API key; that is Hermes's pool, not a bigteam target.
2. Approval is specific: the operator names the agent for this run or this slice. A
   general "use every agent", "bigteam this" or a peer's routing plan does not
   count, and one approval does not carry over to the next batch.
3. To ask, put it in the wave plan as its own AskUserQuestion option, with the
   slice and why. After a yes, set `ACP_OPERATOR_APPROVED=<agent>` for that call:
   `acp-run` and `acp-dispatch` refuse a gated slice without it.

### Reserve pools — never run them out

These pools have something else depending on them. Running one dry breaks that
dependant, which costs more than any slice saves:

1. **clinepass** — Hermes runs on it, through the LiteLLM gateway on `:4000`.
   Never a bigteam target (`NEVER_ROUTE` in `route_agent.py`; it stays in
   Hermes's chain).
2. **The grok TUI** (`grok`, the SuperGrok subscription) — **no longer a
   reserve (operator, 2026-10-18).** GrokBot, the cloud "Chief of Staff", moved
   off it onto its own separate Cursor pool when djbclark upgraded to the $60
   Cursor plan (aiuse lists that pool as the non-routable provider `grok-bot`,
   "Grok Bot Weekly"; never route into it). From 2026-10-15 to 2026-10-18 grok
   had a 60% floor and one slice at a time; both are gone. It is an ordinary
   subscription pool: `realtime-web` first, `research` and `bulk` behind the
   burn-first pools. A missing or stale reading in `aiuse --available` still
   means do not use it. Grok *models* reached through another TUI (opencode,
   cursor, copilot, …) bill that TUI's pool instead and are fine.
3. **Copilot** (`copilot`) — the same GitHub Copilot subscription that
   GitHub-side features use, notably automatic Copilot code review of commits
   to `master` (djbclark's note of 2026-07-30), so a drained allowance stops
   those reviews. It read **100% used on 2026-10-15**, so this has already
   gone wrong once. **Floor 60% left**, one small slice,
   only for `github` slices that need GitHub context `gh` cannot give; a
   missing or stale reading means do not use.
4. **Claude** — do use it; it does the judgment, integration and review. But
   orchestration runs from Claude, so if its 5-hour or weekly window runs out,
   nothing else gets dispatched, integrated or committed either. Check
   `cswap list` before every batch, not once per session, and keep enough
   headroom to finish integrating what is already in flight. Fable is a
   sublimit of this same pool (at most 50% of the weekly), not an extra
   allowance: a Fable slice spends the 5-hour window too.

If one of these is the only pool left for a slice, wait or ask; don't spend the
reserve.

Ignore `aiuse`'s `kind:"conserve"` pace alerts for go/no-go; they fire on a fast
hour even when the window is nearly untouched.

### Dynamic routing — plan a wave, re-plan at every boundary (operator, 2026-10-10)

Pools drain and refill while a run is live (agy's Claude/GPT pool went from 0% to
exhausted in ~35 minutes), so **a vendor chosen at the start goes stale.** Don't
bind every slice to a vendor up front:

1. **Queue slices by kind, not vendor.** Step 2 tags each slice `judgment`,
   `code`, `research`, `bulk`, `mechanical` or `github` (the router's kinds).
2. **Plan a wave:** `~/src/djbclark-ade/bin/route_agent.py plan --kinds
   judgment,code,research,bulk` (hardest first; `--json` for scripts; when the
   brief files already exist, add one `--brief FILE` per kind in the same order,
   which only logs what Jev and GLiDE think each kind is, never changes the
   plan: `docs/jev.md` "Dual review"). It reads the
   aiuse snapshot (instant, no tokens), ranks by fitness and headroom, applies
   the burn-first rule, the reserve floors and the judgment rule (Claude first, omp next, codex Sol/high only while plentiful; 2026-10-25),
   and **spreads the wave** with each service's `max_parallel` (agy Claude/GPT
   3, agy Gemini 2, Cursor Auto 2, copilot 1). Each line ends with the
   dispatch to run, `acp-dispatch <agent> --model M --kind K --effort E`
   (the model shell-quoted; `--json`: `agent`, `model`, `dispatch`); add `--name`, `--task`, `-C`, `-f` and, when
   the slice needs it, `--context`. Dispatch only the slices it gives a pool; a
   slice with `none` stays queued. A `WARNING: snapshot empty/old` means run
   `aiuse --available --live` (in the background) first.
3. **Re-plan at every boundary, before dispatching the next queued slice:**
   a. **a slice finishes** (the notification re-invokes you anyway): probe, then
      plan the queue again;
   b. **a slice fails on quota or plan** (acp-run exit 1 `FAILED quota/plan`, a
      429, `RESOURCE_EXHAUSTED`): `acp-dispatch` automatically records the refusal
      via `aiuse note-exhausted` when a reset time is parsed; `route_agent.py` obeys
      exhausted state immediately and treats readings older than `STALE_SOFT` (25m) as
      unmeasured (`None`). Then `plan --exclude <service>` and re-route that slice,
      trying the same vendor's other model-family pool first (item 3 of *Reading the numbers*);
   c. **a quiet stretch:** while a wave runs, keep one background timer going,
      `sleep 1500; echo recheck` as its own `run_in_background: true` call (no
      model tokens until it fires; never CronCreate or `/loop`, per the standing
      rule on periodic updates). When it fires, run `aiuse --available`,
      `cswap list` and `plan` for the queue; start the timer again only if slices
      are still running or queued;
   d. **a pool newly comes back or turns burn-first** (reset passed, a `burn`
      alert): the next re-plan picks it up by itself, no exclusion list to edit.
4. **Re-route only queued or failed slices.** Never kill or move a slice that is
   running and healthy (work already paid for), and never move a slice that
   failed on the work rather than on tooling.
5. **`plan` is advice, not authority.** Still apply *Reserve pools*, *Current
   exclusions*, the judgment-tier rule and the preflight call; `plan` knows
   capability and headroom, not a vendor's burst limit or a file-ownership claim.
6. **Say what moved:** one line per re-route in the batch log and the handoff
   ("slice 3: agy Claude/GPT 12% left, moved to claude"), so the final report
   shows which vendor ran which slice and why.
7. **Log the outcome too:** per slice, `$OUT/batch.log` gets kind, agent,
   model, attempts, the cost or token figure from acp-run's stderr summary,
   and whether the diff passed your review unchanged. That log is the
   evidence for changing a capability profile in `route_agent.py`; don't
   change a profile without it.

## Step 2 — slice by file, not by topic

A fan-out only works if slices cannot collide. The partition rule:

> **Every file has exactly one owner for the duration of the batch.**

Topic slices overlap; file slices don't. Derive the partition from the files the
work actually touches, then name the owned paths explicitly in each prompt. Two
agents in the same file will silently lose each other's edits.

Prefer one shared checkout with strict file ownership over a worktree per agent:
disjoint files in one tree need no merge, and merging five branches costs more
than it saves at this granularity. Reach for `cow-workspaces` or
`git worktree` only when slices genuinely must touch the same file.
When a slice must stay off the live checkout, create the worktree or pasture
yourself and pass *it* as `-C`; never `-C` the live tree with a brief that says
"work in a worktree" (2026-10-23: the slice's first relative-path edit landed in
the live `~/src/djbclark-ade` and had to be moved back by hand).

**Size the run to the work** (Anthropic's research-system heuristic, 2026):
one slice for a lookup or a single-area change, 2-4 for a comparison or a
multi-area change, more only when the parts are truly independent with clear
owners. Overinvesting in a simple task is the common failure. **Cap each wave
at the number of diffs you can review properly** before the next wave lands:
verification, not generation, is the bottleneck.

**Tag each slice with a kind** (`judgment`, `code`, `research`, `bulk`,
`mechanical`, `github`) next to its owned paths, and leave the vendor open: the
vendor, model and effort are chosen at dispatch time by *Dynamic routing* (end
of Step 1; `plan` prints the `acp-dispatch` line), because the pools will have
moved by the time a queued slice is reached. Decide the **context window** now,
per slice: the default unless the slice reads a whole corpus or a long log.
Tag honestly: a `judgment` slice on a pool that is not judgment-tier (or on codex below
`plenty_min`) is refused or fails and is re-run at
higher cost; a `code` slice tagged `judgment` or `frontier` wastes a scarce turn.

Keep for **yourself** (the orchestrator), never delegate:

- anything security-relevant, or any change whose blast radius you'd have to
  verify anyway
- the final integration, every diff review, all tests, and all commits
- any decision that removes a feature the operator deliberately built
- in a Hermes-owned repo, integration, release and live activation: Hermes
  stays the authority there; report worktree, commit and test evidence to it

## Step 3 — the brief and the concurrency contract

**Brief shape.** A vague brief is copied into every slice and each one goes
wrong in its own way, so every brief names: the **objective** (what done looks
like), the **owned paths**, the **inputs** (only the notes, files and findings
this slice needs, plus the always-load set: this contract and the repo's
non-negotiables; list anything you left out on purpose), **tool guidance**
(graft before grep, the KB before the web), the **output format** (below), an
**acceptance check** (the command or observation that proves it), and the
**boundaries**. You pick the notes, not a cheap model: a wrongly dropped note
fails silently.

Every dispatched prompt carries the same hard rules. They exist because each one
has already been violated by a real agent on this machine:

- Edit **only** the listed files. Report anything else, don't fix it.
- **No git writes** — no add/commit/checkout/stash/restore/reset/rebase/clean.
  Read-only git is encouraged.
- **No test suite, no repo-wide formatter or linter.** The orchestrator runs
  tests centrally. A stray `ruff --fix .` rewrites other agents' files.
- **At most TWO test-running slices at once** (slices that run pytest or
  builds, through `bg`). Further slices wait, or are told to run no tests and
  leave them to the lead. 2026-10-31: five parallel pytest runs forked
  thousands of short git processes and drove load to 222 (swap 7.9 of 9.2 GB)
  on this 16 GB, 8-core Mac; the constraint here is memory pressure and
  process churn, not the load average (`bg`'s base is 2.5 per core since
  2026-11-01, `load-watch admit` allows 4.0 while compressor churn is low).
- Leave changes **uncommitted**. The orchestrator commits, staged **by path** —
  `git add -A` in a shared checkout stages other sessions' in-flight work.
- No package installs, no new directories, no scratch files inside the repo.
- **Launch no agents.** No herdr panes, `acp-run`/`acp-dispatch` or Agent
  calls of its own: only the orchestrator decides and dispatches what comes
  next. ("Hand off the way this was handed to you" was once read as that.)
- **A review or probe that exercises `acp-dispatch` pins the runner and checks
  it before trusting the result.** `dispatch` and `reroute` take
  `--acp-run <scratch fake>`: pin it and assert `shlex.split(rec["cmd"])[0]`
  equals the fake (`cmd` is a shell-quoted string). `resume` has no
  `--acp-run`; its new record inherits the resumed record's runner
  (`old_cmd[0]`), so assert the ORIGINAL scratch record's
  `shlex.split(rec["cmd"])[0]` equals the fake before resuming and the resumed
  record's afterwards, and never resume a record whose runner the reviewer did
  not create (2026-10-25: a reroute probe omitted the pin, fell through to the
  live Codex runner, ran 98 s and sent a real `hermes-ping`). An adversary or
  review brief says "no live agent, no network, no notifications" in exactly
  those terms: fake runner pinned and checked, no `hermes-ping`, no fetch.
- **Map callers before changing a return type or signature.** Use `graft callers SYMBOL --depth all`.
  For a genuinely unindexed script, enumerate literal symbol references with scoped `rg -n -F SYMBOL PATH`;
  inspect every hit, including dry-run, probe and error branches. The edit is complete only when every
  caller handles the new result. Read-only source excerpts follow the machine CLI rules too: use Python
  line slices or GNU `gsed` (2026-10-31: a missed dry-run caller printed a `None` generation).
- **Verify before acting.** Findings handed to an agent were written by another
  AI. Tell it so, and tell it that reporting a finding as wrong is a better
  outcome than a confident wrong edit.
- Report in a fixed shape: `CHANGED:` / `SKIPPED:` / `NOTES:` / `DONE`.

**A slice that drives an Android device** (adb, an emulator) adds three rules to the
brief (2026-10-11; ShizukuTendCF turns its Watchdog on by default, so a killed
Shizuku server comes back about 10 s later):

1. **One agent per device.** Name the device serials the slice may address (every
   `adb` call takes `-s <serial>`) and the ones it must never touch. Check that no
   other live claim owns the device before dispatching.
2. **Stop the server the way a user would.** Before a test that kills or replaces
   the Shizuku server, stop it through the app (`HEADLESS_STOP`) or switch the
   Watchdog off first, and switch it back on afterwards. A bare `kill` makes the
   Watchdog restart it, and the test then measures the restart, not the change.
3. **Leave the device as found**, or report exactly what was left (installed build,
   settings changed, grants given) in the report's cleanup section.

## Step 4 — dispatch, and make sure you are told when each slice finishes

Learning that an agent finished is the part that fails silently, so it is
designed here rather than left to chance.

**The rule: each slice is a FOREGROUND command inside its own Bash call with
`run_in_background: true`. Never end a command by launching a `&` job, and never
poll with `pgrep -f`.** The harness tracks a `run_in_background` call and
re-invokes you the moment it exits. A job backgrounded only by a shell `&` is
invisible to it: verified 2026-10-03, such a job ran to completion and produced
no notification at all, and the batch sat finished for over an hour until it was
next checked. `acp-run` does not change this; it is an ordinary command, and ACP
only makes its own exit code and stop reason trustworthy.

**A `run_in_background` slice or waiter dies with the session.** It is a direct
child of the Claude process (verified 2026-10-08: task pid 21672, ppid 58204,
the session's `claude`) and Claude Code cleans it up when it exits (docs,
*Background Bash commands*). It does not come back on `claude --resume`.
Everything below about notifications holds only while the session lives; for
work that must outlive it, see *Jobs and records* after the waiter paragraph.

**Dispatch a wave, not the whole queue:** the slices *Dynamic routing* (end of Step
1) assigns a pool right now. As each one finishes, re-plan and dispatch the next.

Send every slice in **one message as parallel Bash calls**, each
`run_in_background: true`, so each reports as it finishes and the first results
arrive first. **For every agent that speaks ACP, dispatch through
`acp-dispatch`** (`bin/acp-dispatch` in djbclark-ade, on PATH; it wraps
`acp-run`, whose agent list, flags and current status are in `model-routing`):

    acp-dispatch <agent> --model <m> --kind <kind> --name <name> --task <task> -C <repo> \
        -f "$OUT/brief-<name>.md" [--perm read-only|deny] [--timeout 2400]

It enforces what this step used to spell out in prose (2026-10-08): `--model`
is mandatory except for zcode, where it is accepted and still optional (item 2);
`--kind` is mandatory on a fresh dispatch (2026-10-18; `resume` and `reroute`
inherit it from the record);
the brief gets `docs/dispatch-footer.md` appended (report file
`$OUT/<name>-report.md`, final message is a pointer only, the `BLOCKED:`
protocol, never end a turn waiting on a background notification); the report,
its `.done` marker, the acp-run log, the stderr summary and the
`$OUT/jobs/<name>.json` record are written for you; the out dir is passed as
`--add-dir` so the agent can write its report there. Exit 0 = report ends in
`DONE`; 1 = report present but unfinished, or acp-run failed; 3 = finished with
no report (a delivery failure: re-task it, never reconstruct); 4 = the report
starts `BLOCKED: <question>` (answer it, then resume the slice); 5 = pool
unavailable before launch (re-plan with `--exclude`; this consumes no slice
attempt); 124 = timeout.
`acp-dispatch check $OUT` classifies every slice the same way later. **A Claude
Code Agent-tool sub-agent cannot be driven by a script**: paste
`acp-dispatch footer --report <scratchpad>/<name>-report.md` into its prompt
verbatim and check it with `acp-dispatch check <report>`.
(`$OUT` is `~/.local/state/bigteam/<task>/`, outside the repo; owned paths are
relative to `-C`. No trailing `&`: the Bash call itself is the background job.)
**Not the session scratchpad:** it is wiped when the session restarts, and on
2026-10-05 that took a batch's briefs and outputs with it mid-run. Briefs,
outputs, logs and diffs for a fan-out live under `~/.local/state/bigteam/<task>/`
until the work is committed or recorded in a repo.

1. **Ownership is checked after the run, not gated during it.** `acp-run` runs
   yolo for every agent (operator 2026-10-14): `--perm scoped:<owned files>` is
   gone (it now only warns and runs as `--perm all`), and no agent's edits are
   refused by path. Step 2's one-owner-per-file rule is enforced by the brief
   (name the owned files and say nothing else may change) plus a **mandatory
   post-run check**: as each slice finishes, run `git -C <slice dir> status
   --short` and `git -C <slice dir> diff --stat`, and flag every changed or new
   path outside that slice's owned files before integrating it (revert or
   re-assign it; never let it ride along silently). A security-sensitive or
   advisory slice that must read but not change anything runs `--perm read-only`
   (2026-10-19; claude, codex, opencode, zcode: reads allowed, any other tool
   trips, exit 77); `--role advise --perm deny` is refused, because `deny`
   gives claude no tools and the review prints fake tool calls (acp-run
   `FAILED fake-tool-calls`). `--perm deny` is for a text-only slice needing no
   tools. Neither is for every review (operator 2026-10-15: subagents run yolo
   unless clearly security-sensitive); where used they stay enforced,
   and on an agent that reads without asking under `deny` (crush, agy) add
   `--acp-arg=--tripwire-exempt-kinds=read,search`, or the first `grep` ends the
   slice with exit 77 and no report. cursor cannot deny at all (it takes
   permissions from its own config's `approvalMode`, never from ACP; acp-run
   refuses `cursor --perm deny`), so a cursor review runs under `all` with a
   read-only brief and a `git status` check after. Reserve `deny` for
   security-sensitive slices (prompt-injection exposure); everything else
   runs yolo (operator 2026-10-15).
2. **Always `--model`** (except `zcode`: acp-run sets `ZCODE_BIN`, so `--model`
   works as of 2026-10-15, and `acp-dispatch` still does not require one).
   Otherwise acp-dispatch refuses to run without it. The default is the
   agent's own, which for the claude adapter is the expensive settings model.
   A 2026-10-15 zcode prompt died `project_token_login_failed` at z.ai, which
   is outside acp-run. The README section has the levels and the compact cap.
3. **Per-slice files, all under `$OUT`:** `<name>.jsonl` is the acp-run event
   log (every tool call and permission decision, for when a slice goes wrong);
   `<name>-stderr.txt` holds the one-line summary (stop reason, tool calls,
   permissions allowed/denied, tokens, cost); `<name>-final.txt` is the agent's
   final message. When an agent answers there instead of in the report file,
   acp-dispatch recovers the report from it and warns (`report_source:
   final-message` in the record): nothing is lost, but the brief was not followed.
4. acp-run's exit 124 is a timeout (it cancels the session first); exit 1 is an
   agent error or other stop reason (`stop=cancelled` in `<name>-stderr.txt` with
   exit 1 is the same timeout, reported by the adapter). acp-dispatch keeps
   acp-run's exit in the record and exits 124 only when the timeout left no report.
5. **Budget the timeout from the work, and put the report before optional
   checks.** A slice that runs the test suite N times under load needs
   N × (suite time + `bg`'s load wait, minutes when load is high) on top of the
   edits; 1500 s does not cover a six-finding fix plus a per-finding mutation
   check (2026-10-08: the D-fix slice on herdr-sleeper was cancelled at 1704 s
   in its mutation check, after 683 tests had passed, and the report, the last
   step of the brief, was never written). So: order every brief **edits →
   tests → write the report → optional verification (mutation checks, extra
   ruff passes) → update the report**, and give expensive verification its own
   slice when the count of suite runs is more than two. acp-dispatch's default
   `--timeout` is 2400 for this reason; the cost of a cancel is the whole report.
   Use `--timeout 0` for no time limit (the rearm waiter also waits indefinitely).
   `acp-dispatch extend "$OUT/jobs/<name>.json" <seconds>` adds time to a running
   slice; `0` removes its deadline, applied within 30 seconds (2026-10-11).
6. **A cancelled slice is resumed, not re-tasked.** Use `acp-dispatch resume
   "$OUT/jobs/<name>.json" --timeout 14400 [--detach --no-wait]`; optional `-p`
   or `-f` supplies the continuation. It reuses the recorded session (legacy
   logs: `new_session.data.sessionId`), preserves old reports as `-r1-report.md`,
   `-r2-report.md`, and keeps the same out-folder report and `.done` paths.
   Agents advertising neither load nor resume exit 2. Only if resume fails,
   reconstruct from the diff with a fresh read-only slice.
   **A quota stop is resumed in place, automatically** (operator 2026-10-18:
   its thinking is work; never a fresh brief). When `finalize` writes
   `NO-REPORT: quota (...)` for a record with a session id, it schedules
   `acp-dispatch auto-resume` under launchd for the reset time plus 5 min
   (reset from acp-run's stderr, else aiuse's `resets_at`, else a 30-min
   back-off), gated on the pool's live headroom (20% left, re-checked 6 times
   10 min apart), up to 3 attempts; the record's `auto_resume` field shows
   `state`, `attempt`, `not_before_iso`, `label`. The `rearm` waiter keeps
   waiting through it to the real end; `check` on such a record prints
   `resume-scheduled` (exit 1: still running). An agy slice on a Claude/GPT
   model cannot reopen its session (agy strips the thought signatures Claude
   needs; `docs/model-routing.md`), so its resume continues in a new session
   with a checkpoint instead. Exit 3 stays a real no-report:
   for a quota stop without an automatic resume (`--no-auto-resume`, no
   session id, agent without load/resume, 3 attempts used) the `check` line
   ends with the exact `acp-dispatch resume <record> --detach --no-wait`
   command and the retry time; run that after the reset, never a new dispatch.
   **A slice whose process died without finalize is reaped, never "running".**
   The detached runner traps TERM/HUP/INT and finalizes with 128+signal
   (`NO-REPORT: killed: SIGTERM`); for the rest (SIGKILL, a reboot, power
   loss) `acp-dispatch reap [RECORD|DIR]` finalizes every record whose pid is
   gone or belongs to another process now (`pid_start` is stored at launch;
   pids are reused after a reboot), exit from the runner's exit file or
   launchd, else 255 `lost`, with a `reaped` reason. `check`, `wait` and
   `resume` apply the same rule first, so a dead slice never sits behind a
   waiter until its timeout; a launchd sweep (`acp-dispatch reap --install`,
   RunAtLoad + every 30 min) fixes records nobody is reading (2026-10-18).
   **A scheduled auto-resume survives a reboot:** `launchctl submit` jobs do
   not, so the same sweep re-submits any pending auto-resume (`scheduled`,
   `waiting-headroom`, `resuming`) whose launchd label is no longer loaded,
   same attempt and `not_before` (already past: it runs at once, still
   headroom-gated), once even with concurrent sweeps, never for a closed,
   manually resumed, rerouted or superseded record; `reap` prints a
   `resubmitted` line and the record gets `auto_resume.resubmitted`.
   **A restart/logout kill is attributed and resumed (2026-10-19):** a detached
   slice SIGTERMed within 180 s before `kern.boottime` gets
   `killed_by: system restart/logout (boot HH:MM)` and its failure reads
   `killed: SIGTERM (system restart)`; the same login sweep then resumes it in
   place (`resume RECORD --detach --no-wait`, a "the Mac restarted" prompt),
   once per boot (`restart_resume.boot`), never for a closed record, a DONE or
   BLOCKED report, `--no-auto-resume`, no session id or an agent that cannot
   reopen it. `reap` prints `restart-killed`, then `restart-resumed` /
   `restart-resume-skipped` / `restart-resume-failed`. A lead whose waiter
   ended on the restart re-arms it on the same record. Any `killed: SIG*`
   slice with a session also gets the `resume RECORD` command in its finalize
   detail.
   `wait` returns only once the record is finalized, not on the agent's own
   `.done` touch, so `wait && resume` never races finalize; `resume` passes
   the model acp-run actually applied (`model_applied`), not the alias.
7. **Budget pool room too.** Pass `--est-pct N` when the orchestrator can
   estimate the binding-window cost. A slice that will not fit exits 5 before
   launch. Near-fit and unmeasured pools automatically get checkpoint mode;
   use `--checkpoint` to force it. On quota death, `check` reports
   `quota-checkpointed` and prints an `acp-dispatch reroute <record> --agent A
   --model M` continuation command. The new record links `rerouted_from`; the
   successor gets the original brief, checkpoint and the slice dir's diff stat
   (the whole tree since 2026-10-14; it was limited to the `scoped:` paths).
   While a checkpoint slice runs, `check`/`wait` may add `checkpoint stale: …`
   when the agent is active but the report has not been rewritten recently —
   note it and, if the binding pool is nearly empty, consider `reroute` before
   quota kills the slice. A quota reset more than 6 h out is not auto-resumed:
   `check` prints a ready `reroute` line. A slice that failed on its tier
   (no-report or partial, not quota) climbs one rung, never straight to
   frontier: `check` prints `acp-dispatch reroute <record> --escalate`
   (2026-10-18). **Steer a running slice with `acp-dispatch tell <record>
   "<msg>"`** (inbox file plus the live session for Claude; `check` shows the
   replies). **Once its work is reviewed, CI'd and merged, record that:
   `acp-dispatch outcome <record> --ci pass --review pass --merged`**
   (`--not-merged`, `fail` likewise); `route_agent.py calibrate` re-ranks the
   pools from these fields (2026-10-18).
8. **Context window sits next to model and effort.** A slice that must read a
   whole corpus or a long log should ask for a bigger window. A small edit
   should keep the agent's default: a bigger window bills more per token on
   some services (xAI long-context rates from a 200k prompt; Cursor input
   above 256k at 2×, Fast at 3×; Copilot's long tier costs more AI credits)
   and can be slower. `acp-dispatch <agent> --model <m> --kind <kind> --effort high --context 500k`
   (or `1m`). `--effort` and `--context` are first-class: checked with the
   model before anything is written, stored on the job record, kept by
   `resume`. `--acp-arg` still forwards other flags; a dash-leading value
   needs `--acp-arg=--meta`. A direct call is
   `acp-run <agent> --model M --context 500k --effort high`. The model is
   applied first. Read `<name>-stderr.txt` for
   `acp-run: applied: model=... effort=... ctx=...`. `(unverified)` means that
   value could not be read back. A mismatch is failure class `config`, exit 1.
   A level or size the agent cannot take exits 2 and names the valid values.
   Codex context is fixed by the model: gpt-6.1-sol 500000 (475000 effective);
   every other visible model 272000 (258400); all have `max_context_window`
   872000. `--context 500k` only with `--model gpt-6.1-sol`; `--context 272k`
   only on the others; anything else exits 2 (the message names
   `--model gpt-6.1-sol`).
   The full table is `tools/acp-run/README.md`, section "Per-agent choices:
   vendor, model, effort, context (2026-10-15)".

For muse, which has no ACP route, and as a fallback for zcode and for
agy when its ACP client fails (it fails independently of the CLI), use the
per-CLI form from `model-routing`, with **stdin closed** and a `timeout` guard:

    { timeout 1500 <tui-invocation> < /dev/null; echo "---<name> exit=$?"; } > out-<name>.txt 2>&1

— again as its own `run_in_background: true` call, no `&`.

**One notification for the whole batch, if you prefer it:** a single
`run_in_background` call that starts the slices with `&` and ends in `wait`. The
`&` is fine there because the outer call is the tracked one; you get one event,
when the slowest slice ends. The broken shape is a call whose last act is
launching a `&` job: it returns at once, so the harness reports it done
immediately (false-early) or, without `run_in_background`, never reports it.

**Waiting on something that is not itself a tracked command** (a report file
another process will write) — run the wait as a `run_in_background` call and
bound it, so a file that never appears cannot hang forever:

    timeout 1800 bash -c 'until [ -e /abs/path/to/x-report.md.done ]; do sleep 10; done'

(Write the path out in full, or `export OUT` first: a `$OUT` inside the single
quotes is empty in the inner `bash -c`, so the loop would wait on `/x-report.md`
forever. Wait on the `.done` marker, not on the report: see *Jobs and records*.
A foreground `acp-dispatch` call is itself the tracked wait. Its record's `rearm`
field is one call to `bin/acp-dispatch-wait RECORD DONE` (2026-10-18) — bash, sleep
and grep while the slice runs (a resident Python waiter was 13-32 MB of RSS each,
and 26 of them were 306 MB during the 2026-10-18 memory stall), a real
`acp-dispatch wait --once` pass every 60 s and the moment the marker or the record's
`finished` appears, ending in `acp-dispatch check <record>` (2026-10-10) — so the
waiter exits 1 (partial), 3 (no-report) or 4 (BLOCKED) and
prints the verdict instead of exiting 0 whenever `.done` appears. A codex quota death had
left only `STATUS: working` behind a waiter that exited 0. When acp-run fails before
`DONE`, the report's last line is now `NO-REPORT: <class> (<agent>, <model>[, retry at
<time>]) ...`; a model refusal is class `refused` and is never recovered from the final
message as a `done` report. A `NO-REPORT: quota` does not end the waiter: finalize
schedules the in-place resume and `wait` waits through it, bounded, so the waiter
returns once the resumed run really ends; by hand, `check` says `resume-scheduled`,
exit 1, meanwhile (2026-10-18).) **A sub-agent must
never do its waiting by ending its turn:** a `run_in_background` completion
notice does not wake an Agent-tool teammate, it arrives only with the next
inbound message, so the agent stalls until someone writes to it (three of four
implementers on 2026-10-08). The footer says so; inside a sub-agent the wait is
a bounded foreground `until` or a Monitor.

**Never write the wait as `until ! pgrep -f '<pattern>'`.** `pgrep -f` matches
the waiting shell's own command line, which contains `<pattern>`, so it always
finds itself and the loop never exits. On 2026-10-03 two such waiters ran for
1.5 hours and the only notification was the one produced by killing them. For
liveness use the PID (`kill -0 $pid`) or `wait`; for completion, wait on the
report file or the `---<name> exit=` line.

**Waiting on a PR: one `bin/pr-wait` per PR head, never three waiters, never re-arm a live one.** `bin/pr-wait PR
[--head SHA] [--out PREFIX]` waits for the CI checks of that exact head and for Codex's `codex-review-state:v1` marker
for it (`completed` and `failed` both terminal), then prints one line and writes `PREFIX-{checks,codex,findings,open-findings,summary}.json`
(2026-10-23; separate CI, Codex and adversary waiters were two thirds of one lead's notification turns). **Read
`merge_ready` in the summary, not the exit code:** it is true only when at least one CI check succeeded and none
failed or is pending (skipped and neutral count beside a success, never alone), Codex's code review completed on
this head and its security review too when the marker carries `security_review`, no unresolved Codex review
thread of either kind is left (an earlier head's finding stays open until its thread is resolved: PR 32,
2026-10-23, a P1 left open past two pushes while a head-only filter read 0; security findings carry
`codex-security-review-finding:v1`, e.g. PR 20 thread 4361214081) and the marker's `has_unresolved_findings` agrees
with the threads per kind (`findings-mismatch` otherwise; never read it as a clean 0). A review that found
nothing states the pair as an explicit JSON `null` (`status: completed`), which counts as its statement only
beside no finding comment and no open thread of that kind; a MISSING key is `marker-unverified`, not a clean
review. When it is false,
`merge_blockers` says why, any of: `codex-<status>`, `security-failed` / `security-running` / `security-other-head`,
`findings-not-collected`, `marker-unverified`, `security-marker-unverified`, `no-checks`, `ci-pending`, `ci-failed`,
`ci-none-succeeded`, `open-findings`, `findings-mismatch`, `codex-skipped`.
`PREFIX-open-findings.json` lists the open threads of any head, outdated or not, each with `kind` (`code` or `security`). Exit 0 done, 1
timeout, 2 bad usage, no such PR or the lock guard busy, 3 Codex stuck, 4 a waiter for that head is already alive (the line names its pid and prefix: read its files, do
not start another), 5 the head moved (wait on the new head), 6 timed out while `gh` failed. After a push, start one for
the new head; a second for the same head is refused by itself.

**`pr-wait` requests the Codex review itself (2026-10-24):** the Codex bot reviews on PR open and draft-to-ready, not on a
push, so when a head has no Codex marker and no `@codex review` since its push it posts ONE comment `@codex review`. "Since
its push" is the server-stamped push time (the head's earliest check-suite `created_at`, or the latest force-push event of
the head if later), never a commit date and never a timeline position (GitHub places a `committed` item by the commit's own
date, so a request made between a local commit and its push would wrongly count for the new head); a request counts only
when an allowed author's `created_at` is later than that push time, and Codex's own receipts that quote the phrase never
count. With no server push stamp (no CI app) it leans toward posting; the cap of two per head bounds it. A review still
`running` after `--rerequest-after S` (default 600) is requested once more, never a third time, then the summary's
`codex_request_note` points to openai/codex#55890 (a manual request is sometimes stuck "Running"). `--no-request` only waits
(`--no-codex` never requests). The summary carries `codex_requested` (0-2) and `codex_request_note`; an undecidable case (a
`gh` call failed: check suites, timeline or user) posts nothing, says so and is retried on the next poll. Do not post
`@codex review` by hand while a `pr-wait` is alive.

**The Codex review can be run locally (2026-10-29):** `bin/local-review PR` (from any checkout of the repo; it fetches into its object store and adds one temporary worktree) runs `codex review --base
<base sha>` in a clean detached worktree at the PR's exact head, kills it after `--timeout` (default 1500 s), and files
`~/.local/state/local-review/<owner>__<name>-pr<N>-<head>.json` (counts by P0-P3, findings' titles; the full text stays in the `.out` beside it). Exit 0 clean, 1
findings, 2 usage, 3 failed (codex missing, timeout, non-zero exit, no final message, a head that moved, a final message that is not the transcript's own, one that reads as a refusal or ends in a question, a transcript that does not show the pinned base, a read-only sandbox and an `exec` block, or an unparseable final message: never "clean"), 4 a run
for that head is alive. Then `bin/pr-wait PR --local-codex` replaces the bot's marker with that file (implies `--no-codex`): `merge_ready` needs `clean` on this
head, else `local-codex-missing`, `local-codex-findings`, `local-codex-failed` or `local-codex-unreadable`. Run it after every push (it takes 2-6 minutes and about 0.3% of
the weekly Codex quota), fix every finding, and quote the summary line in the PR body. A finding in `.cursor/hooks.json` or `.claude/settings.json` that the review
worktree itself dirtied (the graft hook) is listed under `ignored_generated` and not counted. A PR whose author is neither the repository owner nor the authenticated gh user is refused (exit 2) unless `--allow-untrusted`, because the PR's own diff and AGENTS.md can steer the reviewing model; `pr-wait --local-codex` accepts a result filed that way as the operator's call.

### Jobs and records — work that must outlive the session

What survives a session is a file, not a process. Every slice and every
detached job follows the same contract (2026-10-08).

1. **Report through a temp file, `.done` last.** The report is
   `$OUT/<name>-report.md` (a basename starting `report`/`summary`/`findings`/
   `analysis` is refused by Claude Code for sub-agents); its first line is
   `STATUS: working` or `BLOCKED: <question>`, its last line `DONE`; then
   `$OUT/<name>-report.md.done` is touched as the very last act. Waiters wait on
   `.done`, never on the report, so a half-written file is never read.
   `acp-dispatch` does all of this; a hand-run command writes the file itself.
2. **A job record per slice that may outlive its launcher:**
   `~/.local/state/bigteam/<task>/jobs/<name>.json`, written the same way
   (temp + `mv -f`). `acp-dispatch` writes it with `name`, `agent`, `model`,
   every path (`brief`, `report`, `done`, `final`, `stderr`, `log`), `owner`,
   `started`/`finished`, `exit`, `status`, `report_source`, `cmd` and `rearm`;
   a hand-written one needs at least:

       {"owner": "<CLAUDE_CODE_SESSION_ID>", "started": <epoch>,
        "report": "<abs>/<name>-report.md", "done": "<abs>/<name>-report.md.done",
        "rearm": "timeout 1800 bash -c 'until [ -e <abs>/<name>-report.md.done ]; do sleep 10; done'",
        "cmd": "<what was launched, one line>"}

   `owner` is the id of the Claude session that launched it. Claude Code sets
   `CLAUDE_CODE_SESSION_ID` in every Bash call (checked 2026-10-08 with
   `env | ggrep -i session`; there is no `CLAUDE_SESSION_ID`). Use
   `${CLAUDE_CODE_SESSION_ID:-unknown}`. `rearm` is the exact bounded waiter
   with absolute paths inlined. A record is **open** until it carries a
   `"closed": <epoch>` key; `/handoff` lists open records of its session and
   `/baton` re-arms and closes them. Records are closed, never deleted.
3. **Work expected to outlive the session is launched detached, not as a child
   of it:** multi-hour runs, anything that must survive a `/new` or the TUI
   quitting. `bg` does not do this: `~/ops/site-private/bin/bg` only waits for
   load and then `exec`s `taskpolicy -c utility "$@"`, so the command stays a
   child of whoever ran it. The verified detached form is `launchctl submit`
   (flags checked against `man launchctl`, macOS 27, and run: the job's parent
   is launchd, pid 1). `acp-dispatch --detach` writes and submits exactly this
   kind of script (`--no-wait` returns at once with the rearm line; otherwise it
   waits on `.done`, bounded). For a non-ACP command, put the whole job in a
   small script so it reports the way item 1 says and removes its own label:

       # $OUT/run-<name>.sh   (chmod +x)
       #!/bin/bash
       export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
       OUT=<abs OUT>; N=<name>; L=bigteam.<task>.<name>
       [ -e "$OUT/$N-report.md.done" ] && { launchctl remove "$L"; exit 0; }
       <command> > "$OUT/$N-report.md.tmp" 2> "$OUT/$N-stderr.txt"; rc=$?
       printf 'exit=%s\nDONE\n' "$rc" >> "$OUT/$N-report.md.tmp"
       mv -f "$OUT/$N-report.md.tmp" "$OUT/$N-report.md"
       touch "$OUT/$N-report.md.done"
       launchctl remove "$L"

       launchctl submit -l bigteam.<task>.<name> \
           -o "$OUT/<name>.out" -e "$OUT/<name>.err" -- "$OUT/run-<name>.sh"

   Three facts verified 2026-10-08 that the script above is built around:
   **launchd restarts a submitted job every time it exits** (a bare job reran
   every ~20 s), so the script must `launchctl remove` its own label as its last
   line, and the first-line `.done` check stops a restart after a crash from
   redoing finished work; the job's environment is bare (`PATH=/usr/bin:/bin:
   /usr/sbin:/sbin`, `HOME` set, nothing else), so export what the command
   needs inside the script; and a submitted job does not survive a reboot. Not
   tested: an agent CLI under launchd (keychain and login state), and
   `claude --bg --exec '<cmd>'` (the background-session supervisor; per the docs
   its output is held in memory and cleaned about five minutes after the job
   exits, so it would still need the report-file contract above).
4. **What is and is not promised.** Only detached jobs that have a record are
   promised to outlive the session. Whether an ordinary `run_in_background`
   task survives a `/new` is NOT established as a guarantee: the test result
   below saw it survive in one Claude Code version and one case, and saw it die
   on quit. Do
   not hand work to the next session on the assumption that a background task or
   waiter will still be there.

**Single-run launchd waiters (macOS, verified 2026-10-31).** Bootstrap a plist with
`RunAtLoad: true`, `KeepAlive: false`, and no interval keys. Verify the live job's
properties lack `keepalive` before reporting it as one-shot: `launchctl submit`
created keep-alive jobs on this Mac. Model slices still use `acp-dispatch`.

**Why jobs are records on disk (investigation, 2026-10-08).** A Claude Code
docs and local-process investigation found: background Bash tasks are
children of the `claude` process and "automatically cleaned up when Claude Code
exits" (https://code.claude.com/docs/en/interactive-mode, *Background Bash
commands*), including anything under `setsid` or `timeout`; `claude --resume`
does not restore them (https://code.claude.com/docs/en/sessions); no flag,
hook or environment variable lets a new session list or adopt another
session's tasks. Named pipes were rejected: a pipe buffers about 64 KiB, a
writer blocks or fails with no reader, and the reader would itself be a
background process with the same exit problem. So the result is a file, the
completion signal is a `.done` marker written last, and a small record names the
owner, the paths and the exact waiter to re-arm; the cost is one wake turn per
completion and one re-arm turn per new session. Backgrounding the whole session
(`/background`) also keeps its tasks; `claude --bg --exec` was not tested.

**Test result (2026-10-08, Claude Code 2.1.295, a throwaway interactive
`claude --model haiku` session in a herdr pane, since closed).** Three
observations, all in one case:

1. `/new` is an alias of `/clear` in this version (the transcript echoes
   `/clear`). It starts a new transcript in the **same** `claude` process. A
   `run_in_background` `sleep 311` started before it kept running (still a child
   of the same `claude`), the footer of the new session showed it as a running
   shell, and when it finished the completion notification woke the **new**
   session (which did not recognize it as its own).
2. Quitting the TUI stops background tasks: `/exit` raises a prompt "Background
   work is running / The following will stop when you exit" with *Exit and stop
   tasks*, *Move to background and exit*, *Stay*. Choosing the first killed the
   `sleep 313` (verified with `ps`). So `/handoff` then `/new` in the same TUI
   keeps tasks; `/handoff` then quit, or a crash, or a new terminal tab does not.
3. A `launchctl submit` job is parented by launchd (pid 1), not by any Claude
   session, so it is independent of all of the above.

This is one version and one path. It does not make a background task a safe
carrier for work: the next session may be a different process, and it did not
recognize the inherited task as its own. Records and detached jobs stay the
contract.

**A slice that fails on quota** (429, `usage limit`, `RESOURCE_EXHAUSTED`) is
Step 1 item 3: try the same vendor's other model-family pool before reassigning.
Then **tell the next agent**, so it does not walk into the same wall:
`acp-dispatch` notes quota refusals automatically when a reset duration or timestamp is in stderr; manual calls use:
`aiuse note-exhausted <provider> [--family <gemini|claude_gpt|fable|...>]
--resets-in 4h53m [--reason '<the 429 text>']` (or `--resets-at <ISO>`). It is an
advisory override that expires at the reset time and shows up in
`aiuse --available` as `source: agent-reported`. Only record what a call really
returned; do not guess a reset time.

## Step 5 — integrate, and trust nothing on faith

- **Exit 0 is not success.** A file holding only a preamble, or a reviewer
  returning no findings, is a failed run. Check for an actual report. This holds
  for `acp-run` too: an agent can end its turn normally with a provider error
  as its whole reply. Since 2026-10-14 nothing refuses a slice that leaves its
  files (acp-run runs yolo): the post-run `git status --short` / `git diff
  --stat` check in Step 4 is what catches it.
- Inspect each preparation command's exit code before a dependent stage or
  commit. A failed preparation stops that mutation until its resulting files
  have been checked.
- Read every diff yourself before committing. Agents are good and still get
  ordering, alphabetisation and scope wrong.
- Run the checks centrally after the batch settles, **focused first**: lint
  and type-check on the changed files, then the tests that cover the diff
  (catch most breaks in seconds), then **the full suite, once, before any
  commit**. Focused checks are an early warning, never a replacement.
- **A green local check can be hollow.** A checkout missing `node_modules`, a
  venv or Ansible collections makes check scripts skip lint and tests
  silently, so "passes locally" was true of nothing. Rerun with the full
  toolchain, or grep the output for `skip`/`not installed`.
- Read new code meant to run unattended (notifications, checks) line by line:
  its own tests were written by the same pass that missed its bugs.
- **Done means the real artifact.** A plan, an analysis or a turn-cap exit
  is not completion; a committed change plus rerun checks is. Re-read the
  request for words like "workstation", "install", "running", "deployed":
  a repo or CI pin and the running install are separate things (2026-08-05:
  a Collie bump merged the CI pin and left `~/.collie` on the old version).
  Work with a PR is done when it is merged, or when why it stays open is
  written down; before starting a new phase, `gh pr list --state open` on
  every repo the work touched.
- When an agent refutes part of its own brief, that is the system working —
  prefer its evidence over your assumption, and say so.
- A slice that fails on tooling (not on the work) gets **reassigned to a
  different vendor** (`route_agent.py plan --exclude <service>`, *Dynamic
  routing*), not retried on the same one. The exception is a quota
  failure on one model-family pool: retry on the same vendor's other pool first
  (Step 1 item 3), because the vendor itself is not spent.
- **Three attempts per slice, then stop.** The first run plus two re-routes;
  count them in `$OUT/batch.log`. After the third failure on the same error,
  the slice goes to the operator with the evidence (`hermes-ping` plus the
  chat reply), not to a fourth vendor. The cap is a count you keep, not a
  sentence in a prompt.

## Step 6 — second opinion on contract decisions

For a protocol/contract/API decision, or any recommendation to delete
functionality, get one independent opinion from a **differently sourced** vendor
than the one that proposed it, and make it adversarial: tell it not to defer,
and ask it to check each claim with file:line evidence. Then put the decision in
front of the operator if it removes something they deliberately built.

## Known failure modes, already paid for

| symptom | cause | action |
| --- | --- | --- |
| `copilot` hangs or `shared writer lock ... changed` | headless `--allow-all-tools` disables itself when it can't reach a policy server, then waits for an approval no TTY can give | reassign the slice; keep copilot timeout-bounded |
| `agy` CLI returns `RESOURCE_EXHAUSTED (code 429)` on every model while `aiuse` shows headroom, or looks hung for ~2m20s | per-client burst limit on the CLI login (2026-10-03: ~304 requests in 3 h); the CLI retries 8 times in-process, and `--print-timeout` cuts it with exit 0 and partial output | stop; `grep 'attempt [0-9]* failed' ~/.gemini/antigravity-cli/log/cli-*.log`; use `acp-run agy` or reassign; do not loop probes |
| `agy` runs with a flag as its prompt | `-p` is a required-value string flag | always `-p='<prompt>'`; a non-zero exit here is the guard working |
| `zcode` hangs with ~0 CPU | `--mode build`/`edit` gates tools behind an impossible approval | default yolo only; `ZCode Built-in skipped` on stderr is benign |
| `opencode.json` turns up modified | every `opencode run` rewrites it in cwd | `git checkout -- opencode.json`, or avoid in tracked repos |
| `opencode/*` model fails on funds | that's the prepaid Zen catalogue | use `opencode-go/*` for the free bundle |
| a stray empty dir appears | agy has done this | `git status --porcelain` after every batch |
| `.zcode/acp/sandbox.json` appears in the repo | `acp-dispatch zcode` writes its per-cwd sandbox config into `-C <repo>` (2026-10-09); a graft hook in a subdirectory cwd also drops a nested `graft/` + `.gitignore`/`.ignore` there | both are regenerable: `rm -rf .zcode` (and the nested graft trio when the repo root already has `graft/`) before committing |
| `acp-run` exits 1 with `FAILED quota/plan/auth/transient/refused` (or 5: empty reply, every permission denied) | since 2026-10-05 acp-run detects provider failures that arrive as a normal `end_turn` (plan-gated reply, reply cut off by a transport error, quota text); `refused` (2026-10-10) is the model declining (a short reply starting "Sorry, I cannot ..." / "I must decline ..."), never retried, and acp-dispatch ends the report `NO-REPORT: refused (<agent>, <model>): <first sentence>` (exit 3) instead of recovering it as a deliverable: re-route the slice to another model (agy `gemini-pro-agent` declined a security-advisory slice) or reword the brief's authorization context; `reply truncated; edits may be present` means check the tree; a `quota` stop is resumed in place automatically (`resume-scheduled`, exit 1; 2026-10-18) | read the stderr line and the log; for quota, let the scheduled resume run (or run the printed `acp-dispatch resume <record>` after the reset); reassign only a non-quota failure; for truncated, review what was edited |
| no notification when an agent finishes | it was launched with a trailing shell `&` and no `run_in_background` call, so the harness is not tracking it | run each slice as a foreground command in its own `run_in_background: true` call (Step 4) |
| a wait loop never ends | `until ! pgrep -f '<pattern>'` matches its own shell | wait on the report file, a PID or `wait`; bound it with `timeout` |
| `RESOURCE_EXHAUSTED` / "usage limit" from a vendor you thought had headroom | `used_percent` read as free; or the pool was drained since the probe; or that model family's pool is spent while a sibling pool is fine | decide from `remaining_percent`, preflight, re-probe per batch, retry on the sibling model family |
| seven `opencode-go/*` slices fail in 15-21 s with `ServiceUnavailableError` / `Internal service failure` | the pool is in an outage, which quota snapshots do not show | automatic preflight exits 5, records a 15-minute outage override, and launches no slice; re-plan with `--exclude opencode-go` |
| zcode says `1310 ... Weekly/Monthly Limit Exhausted` with a reset time | z.ai's pool is exhausted but aiuse has no live collector for the TUI | automatic preflight classifies quota, records the reset for `zai`, exits 5 and launches nothing; re-plan with `--exclude zai` |

## What this skill is not for, and when to use it unasked

A single-file edit, a lookup, or anything where the coordination overhead
exceeds the work. Fan-out has a real fixed cost: writing the slices, enforcing
the contract, reviewing the diffs. Don't count slices to decide, though: a
discrete task that would read many files, logs or long outputs into this
session belongs in a fan-out even as one or two slices, because keeping this
context small is itself the goal (2026-10-08). Do it yourself only when the
work is small enough that its tokens cost less than the brief and review.

**Use it proactively** (operator, 2026-10-15): nobody has to say "/bigteam".
Whenever a prompt contains separable, discrete work, or the context-size hook
has fired, slice it and send it out at the minimum spec that does it well; a
single lookup goes to a minimum-spec Agent sub-agent instead (`effort-routing`).
The orchestrator's own context is also a cost: Claude Code compacts it by itself
at 300k tokens (`autoCompactWindow`, verified 2026-10-25), and in a herdr pane, Orca terminal or Paseo agent the
orchestrator compacts earlier at a wave boundary with `self-slash "/compact
<focus>"`, or runs the `handoff` skill then `self-slash "/new"` on a topic change
(the fresh session gets `/baton` from self-slash itself, 2026-10-19), without
asking.

**Provider-specific context controls (2026-10-25).** Read [context hygiene](../../docs/context-hygiene.md) before a long Go slice. Cached input still debits the shared monthly allowance; neither the model context capacity nor a small uncached input count is a cost budget. OpenCode V2 uses native safe-point compaction and current input plus cache tokens. At a completed task, write the owned handoff and Tier 1 checkpoint before a supported fresh-session/baton cycle; a dispatched slice never clears its parent.

**Bound source inspection before printing (2026-10-25).** Generated SDK declarations can repeat schemas over megabytes. Select a known symbol and cap its byte span before iterating or printing; use at most 2,000 characters per excerpt. A missing end delimiter is a failed lookup, never permission to print the rest of a file. Save bulky evidence privately and return only the fields needed for the decision.
