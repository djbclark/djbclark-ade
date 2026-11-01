# Model and effort routing

Goal: know exactly which models are reachable through which service on this
machine, which budget each spends, and route every graph node by vendor ×
model × effort × context window so tokens are spent where judgment lives. Facts are a
**snapshot dated 2026-08-23**, verified against `aiuse --json` (the
operator's own tool, github.com/djbclark/aiuse — allow ~1 min) and direct
CLI probes. Percentages drift constantly — re-probe, don't trust this file
for balances.

Failure chains (what runs when a chosen model fails) are a different
document: `skills/fallback-chains/`. Re-read its live sources before
quoting a chain, and update its snapshot if you change one.

> **Update 2026-10-19 (operator): Codex is now on the $100 plan.** `aiuse`
> reports plan label `prolite`, billing `subscription_window`, one window
> "Codex weekly quota (2)" at 100% left, resetting 2026-10-26T17:41Z (no
> 5-hour window in that snapshot; it may reappear). The 5-hour scarcity notes
> dated 2026-10-18 below (the 5-hour window, "one slice at a time", the codex
> `estimate_floor`) predate the upgrade and await re-calibration from
> `route_agent.py calibrate`; routing policy (which model does what) is
> unchanged.
>
> **Update 2026-10-18 (operator): the frontier models are scarce.** A lead put
> four plektra "small issues" slices on codex `gpt-6-astra` at high/xhigh
> together; codex's 5-hour window ran out and all four stopped waiting for the
> reset. Since then: judgment is Opus 5.5 at `high` first, omp Opus next, and (2026-10-25)
> codex `gpt-6.1-sol` at `high` as an eligible, lower-ranked pool only while every codex
> window has >= 50% left; codex astra and Fable 5.1
> (`high`) are reached only through the `frontier` kind, one slice per pool
> per wave (two on claude under the standing allowance of 2026-10-27 while the quota guard
> passes, `docs/gates.md`), for work that really needs them (codex's everyday models, `gpt-6.1-sol` and
> `gpt-6-luna`, also take `judgment`/`code`/`bulk`/`mechanical` while every codex window has
> >= 50% left, operator 2026-10-25); `acp-dispatch` allows one fresh
> codex slice in flight machine-wide (replaced the same night by a per-service
> in-flight quota reservation, see *Routing policy* below) and refuses Fable
> `xhigh`/`max` without `ACP_OPERATOR_APPROVED=fable-xhigh`. Where the 2026-10-15 text below says
> "use them fully", read this instead.
>
> **Update 2026-10-15 (operator): the routing policy is now cost against code
> quality, every TUI, any directory.** The one copy is
> `skills/model-routing/SKILL.md`, *Routing policy (operator, 2026-10-15)*;
> `bin/route_agent.py plan` applies it and prints the `acp-dispatch <agent>
> --model M --kind K --effort E` line per slice. In short: (1) Claude Fable 5.1 at
> `xhigh` and codex's top frontier model (`gpt-6-astra`) are used **fully** for
> serious-effort work (judgment, adjudication, security-relevant changes,
> whole-corpus reads, adversarial review); (2) **Fable and "claude" are one
> pool**: Fable is a <=50% sublimit of the shared weekly and bills the 5-hour
> window too, so the "separate Fable weekly" wording below is **wrong**; (3)
> everyday work goes to the other pools (agy Claude/GPT, Cursor Auto, zai
> GLM-5.3, opencode-go (bulk and mechanical only, never code: djbclark 2026-10-30), agy Gemini, crush/SIPB) at the minimum spec that does
> it well, proactively through `/bigteam` and minimum-spec sub-agents; (4)
> **grok and copilot are reserves** (**grok released 2026-10-18**: GrokBot moved to its own Cursor pool, so grok is an ordinary subscription pool and copilot the only reserve) with a hard floor of 60% left (GrokBot and
> GitHub-side Copilot review ran on them; copilot read 100% used that day);
> after an adversarial review the same day, only an explicit kind reaches
> them (`github` for copilot, `realtime-web` for grok), a stale or missing
> reading fails closed, `acp-dispatch claude` is judgment-only (Fable xhigh;
> Haiku lookups go through the Agent tool), and clinepass is `NEVER_ROUTE`;
> (5) **hermes is never a delegation target** (gated in acp-run/acp-dispatch);
> **omp, the Claude API credits, is a normal tier since 2026-10-19** (operator:
> `api-only` work first, else `code`/`bulk` slices so the credits are spent before
> each monthly expiry); never an all-vendor fan-out; (6) the context window is a per-slice choice (`--context`),
> default unless a whole-corpus read; (7) compaction is automatic
> (`autoCompactWindow` 400000 in `~/.claude/settings.json`; herdr/Orca sessions (both retired from djbclark-ade 2026-10-31; `self-slash` keeps those hosts until D6) and Paseo sessions
> compact earlier via `self-slash`; a topic change runs the `handoff` skill then
> `/new`). Snapshot numbers below are older and only illustrate the shape.
>
> **Update 2026-10-10 (operator): use agy's Claude/GPT pool heavily while it has
> headroom** (5h 100% left, weekly 49% left, critical burn alert). Via
> `acp-run agy --model claude-opus-5-5 --effort high` / `--model claude-sonnet-5-5 --effort high` (agy 1.4.1, 2026-10-18, dropped the effort-suffixed ids), 2-3 slices
> at a time, gated on `aiuse --available`; `skills/model-routing/SKILL.md`
> (*Reading quota numbers* item 4) and `skills/bigteam/SKILL.md` (*agy Claude/GPT
> pool*) carry the rule, `bin/route_agent.py` the `antigravity-claude` service.
>
> **Revised later on 2026-10-10: Claude/GPT over ACP need a client-name workaround.** The agy
> ACP server listed only `gemini-*` models, so `claude-opus-5-5-high` failed with `no model`
> while `aiuse` showed the pool at 100% left. The cause is client-side:
> agy_acp_server 1.3.0 offers non-Gemini models only to clients whose ACP `clientInfo.name` is `zed`, `xcode` or `JetBrains.*` (`supports_third_party_models()` in its `model_selection.py`), so `acp-run` identifies itself to agy as `zed` (0b56897).
> `acp-run agy --info` then listed `claude-opus-5-5-{low,medium,high}`,
> `claude-sonnet-5-5-{low,medium,high}` and `gpt-oss-120b-medium`, and a
> `claude-sonnet-5-5-low` probe answered. Since agy 1.4.1 (2026-10-18) it lists bare `claude-opus-5-5` and `claude-sonnet-5-5` and takes the effort as `--effort`. The gate is deliberate in Google's code
> (google-antigravity/antigravity-cli#1168 and pingdotgg/t3code#16489 report it), so this
> is a workaround, not a fix, and a later `.par` release could close it. `acp-dispatch`
> checks `--model` before it detaches. Detail: `skills/bigteam/SKILL.md` (*agy Claude/GPT
> pool*, item 3).
>
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
> a fast fail; no probe loops (one probe, reuse the answer); burn the
> Claude/GPT pool while `aiuse` shows headroom (2026-10-10 update above); and if one client 429s while `aiuse`
> shows headroom, try the other. Detail and the source skill:
> `skills/model-routing/SKILL.md` ("agy has a burst limit").

## The service matrix: aiuse line ↔ TUI/CLI ↔ billing

**How `bin/route_agent.py` reads pool state (2026-10-20):** it runs `aiuse --available --json`
(argv list, 20 s timeout, exit 0 or 3 accepted), not the snapshot file, so routing and the
quota gate see what `aiuse` itself reports: the operator credits override (`aiuse set-credits`,
`aiuse refresh-credits omp`), Admin API readings, grant expiry and `reading_expired` (aiuse
3.8; those fields are read with `.get`, so the Homebrew 3.7.2 output works too). A pool the
snapshot knows that a fresh `--available` omits (exhausted, excluded, hidden) reads 0% left.
If aiuse is missing, fails, times out or prints malformed JSON, it logs on stderr, falls back
to `latest.json`, and says so as `quota_source` in `plan --json` / `route --json` and a
WARNING in `plan` text (`show` prints a `quota source:` line). `ROUTE_AGENT_AIUSE_JSON=<path>`
feeds canned output (tests; reported as source `canned`, logged on stderr every use, and it
takes precedence over `ROUTE_AGENT_AIUSE=off` and `AIUSE_SNAPSHOT`); `ROUTE_AGENT_AIUSE=off` or
`AIUSE_SNAPSHOT` pins the file-only read (tests/conftest.py sets `off`); `ROUTE_AGENT_AIUSE_BIN`
and `ROUTE_AGENT_AIUSE_TIMEOUT` (seconds, 0 to 60, default 20) override the binary and timeout.
The spawn result is memoised for 30 s (elapsed seconds are added to its ages on reuse, so a blocking dispatch's finalize never reads a start-time quota as current). The admission looks that judge the pool after a wait (the post-load-wait reading in `dispatch`, and the stamped plenty-gate recheck after the load and capacity waits) bypass the memo (`load_snapshot(bypass_memo=True)`, 2026-10-25, PR 73), so a wait shorter than 30 s cannot hide a drained pool. Unparseable rows, non-finite percentages and unknown ages
never read as headroom: the first falls back to the file, the others read unknown or stale.

The aiuse path reads the `--available` row contract: each row's top-level `provider`,
`pool_family`, `usable_now`, `headroom_percent`, `binding_window`, `available_at`,
`reading_expired` and `requires_operator_approval`. `windows[]` (which 3.7.2 attaches) is detail
only, filling the per-window labels, the Fable sublimit and the pace and reset fields; it can
tighten a pool's `remaining` but never loosen it, and a payload without `windows[]` (the
documented minimal form) routes the same. `usable_now: false` or zero headroom reads 0% left.
A `fable` family row is a sublimit of the shared Claude pool, not a pool of its own.
Pools in the payload's `excluded[]` (operator-ruled-out, or an auth-failed account) read 0% left under the same fresh-payload condition as the absent-pool rule, even when the snapshot file has no row for them, so `route()` never treats them as unmeasured; an invalid excluded row is ignored, and the file fallback does not consult `excluded[]`.

`aiuse --json` (JSON starts after two preamble lines) reports one
`snapshot.accounts[]` entry per provider; `alerts[]`/`suggestion` rank
where quota is going to waste. Mapping, verified 2026-08-23:

| aiuse provider | CLI / TUI on this machine | Plan | Billing | Windows |
|---|---|---|---|---|
| `claude` (gmail) | `claude` (Claude Code; cswap acct 2; Orca/ralph-tui drive it (Orca retired from djbclark-ade 2026-10-31; Paseo is the harness now)) | Max-class | monthly sub | 5h + weekly; **Fable is a <=50% sublimit of the same weekly** (aiuse `max_share_of_parent_percent`), not a separate pool (corrected 2026-10-15) |
| `claude` (mit) | **permanently gone** (operator, 2026-08-23) — removed from cswap | — | — | — |
| `codex` | `codex` (v0.149) | ChatGPT Plus until 2026-10-18; **$100 plan (aiuse `prolite`) since 2026-10-19** | monthly sub | weekly (resets 2026-10-26; a 5-hour window may reappear) |
| `antigravity` | `agy` (v1.1.18; ralph-tui-antigravity-plugin exists) | Google AI Pro | monthly sub | Gemini 5h/weekly **plus Claude/GPT 5h/weekly** |
| `copilot` | `copilot` (v1.0.77; broke 2026-08-23 on stale pkg cache — fix: `rm -rf ~/Library/Caches/copilot/pkg`) | Individual Pro | monthly sub | premium requests (monthly) |
| `cursor` | `cursor` (v3.17.8) | Cursor Pro | monthly sub | included / Auto / other-models (monthly) |
| `grok` | `grok` (v1.0.5; ralph-tui-grok-plugin exists) | SuperGrok | monthly sub | usage limit |
| `zai` | `zcode` TUI (Z.ai's own, v0.16.9; `zcode -p`; GLM-5.3 / GLM-5.3-Flash × low/high/max; not in Orca's roster or herdr's agent kinds (both retired from djbclark-ade 2026-10-31)) | lite | monthly sub | 5h + weekly |
| `clinepass` | Cline TUI (Orca agent `cline`; Orca retired from djbclark-ade 2026-10-31) + LiteLLM proxy `localhost:4000` (`clinepass-deepseek`, `clinepass-minimax-m3`, `clinepass-kimi-k3`) consumed by Hindsight + hermes | Cline API key | subscription windows | 5h + weekly + monthly |
| `opencode-go` | `opencode` Go Plus (`opencode-go/*`); routine MiniMax M3 (bulk), GPT-6 Luna (mechanical); never a code slice (djbclark 2026-10-30); DeepSeek V4.1 Flash is the main-loop substrate model only | $40/month | subscription shared allowance | 5h + weekly + monthly |
| `opencode-zen` | `opencode` provider `opencode` (`opencode/*`: claude, gpt, gemini, deepseek, glm catalogs) via gated `opencode-ralph-tui-zen` | prepaid | **prepaid balance** | balance |
| `openrouter` | gated `opencode-ralph-tui-openrouter` | prepaid | **prepaid balance** | balance |
| `deepseek` | gated `opencode-ralph-tui-deepseek` | prepaid | **prepaid balance** | balance |
| `devin` | `devin` (v3000.5.20) — **disabled in Orca's TUI roster** (Orca retired from djbclark-ade 2026-10-31), so its 100%-unused windows are deliberate dormancy | ? | sub (ACUs) | daily + weekly |
| `alibaba` / `alibabatokenplan` / `qwencloud` | `bl` (Bailian, v1.17.1; bailian-* skills) | **ID verification pending, expected live ~2026-08-26** | token plan + PAYG | — until verified |
| `muse` | the Muse service (own account via gmail; `opencode-go/muse-spark-1.2-contributor` surfaces its models) | ? | ? | ? |
| (not in aiuse) | `opencode` provider `sipb` — MIT SIPB-hosted models (ollama-style: qwen3-coder:30b, deepseek-r1:32b, gemma…). **For agent/coding use, only `qwen3.6:35b-a3b-q4_K_M` runs tasks reliably** — deepseek-r1:32b fabricates success, qwq:32b truncates every agent-sized stream, exaone-deep:32b/gemma3:27b return the over-long `null`; see forgejo.mit.edu/djbclark/sipb-llms `report/REPORT.md` §3.1 | MIT affiliation | free | none |

Monthly-subscription pools: claude, codex, antigravity, copilot, cursor,
grok, zai, clinepass (window-shaped), devin, opencode-go. Free: sipb.
Prepaid real money: opencode-zen, openrouter, deepseek — all three
**effectively empty on 2026-08-23** (Zen -$0.04, DeepSeek $0.00,
OpenRouter $1.13), and gated anyway by the wrapper scripts, which require
an explicit fresh human decision per run (keys come from
`~/.config/codexbar/config.json`). **Operator decision 2026-08-23: the
prepaid tier is retired for now** — revisit only on an explicit top-up.

## The registry is `acp-run --list`

**Since 2026-10-08 the registry is `acp-run --list`** (plus the installed
non-ACP headless TUIs, now only muse). Orca's agent roster, once read by
`bin/route_agent.py` only with `ROUTE_AGENT_INCLUDE_ORCA=1` (intersected with
installed binaries, because 12 of its 28 enabled names were not installed
here), is retired from djbclark-ade (2026-10-31): do not route through it.
Orca stays installed and configured on the machine, untouched; the flag's
code path goes away with the plan's D-phase sweep. The 2026-08-23 description
of the roster and its macro-graph `worker-start --agent <name>` dispatch was
removed from this page (git history has it).

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

**Superseded (2026-10-18):** two claims in that snapshot no longer hold. Fable is a
≤50% sublimit of the one Claude weekly, not a separate budget (global rule 32;
`skills/model-routing/SKILL.md` *Routing policy*). The blanket "never bulk-route to
clinepass" was retired 2026-08-24: the burn alert governs it (AGENTS.md standing
order 7), and the `cline` CLI is uninstalled and operator-gated since 2026-10-17.

Parsing gotcha: `aiuse --json` prints two preamble lines *and* the JSON's
opening `{` is part of what a naive `tail -n +3` strips. Take everything
from the first `{` instead, or the parse fails with "Extra data".

## Effort and context levers per service

Updated 2026-10-15. The old "no separate effort knob" line for grok, cursor,
copilot, agy and opencode is retired: each of those has an effort control,
and several have a context-size control. The full table (exact model ids,
effort spellings, context sizes, and what is not reachable) is
`tools/acp-run/README.md`, section "Per-agent choices: vendor, model, effort,
context (2026-10-15)".

Ask for a bigger window when the work is a whole-corpus read or a long log:
`acp-run <agent> --model M --effort high --context 500k` (also `256k`, `1m`,
and the sizes that agent's section lists). Leave the default for a small edit.
A bigger window bills more per token on some services (xAI long-context rates
from a 200k prompt; Cursor input above 256k at 2×, Fast at 3×; Copilot's long
tier costs more AI credits) and can be slower. Order: provider, model, other
`--set`, effort, context. A level or size the agent cannot take exits 2 before
any prompt and lists the valid values. Stderr, before the summary:
`acp-run: applied: model=... effort=... ctx=...`. Unreadable values are
`(unverified)`. A requested value the agent reports differently is failure
class `config`, exit 1. `acp-dispatch` takes `--effort` and `--context` as
first-class flags (checked with the model before the job is written, stored on
the record, kept by `resume`):
`acp-dispatch <agent> --model M --kind K --effort high --context 500k`. `--acp-arg`
still forwards other flags; a dash-leading value needs `--acp-arg=--meta`.

**A quota stop is resumed in place, automatically** (operator 2026-10-18: a
session's thinking is work; three codex slices stopped by the 5-hour limit were
about to be re-tasked from fresh briefs). `acp-dispatch finalize` writes the
`NO-REPORT: quota (...)` line as before, then schedules `acp-dispatch
auto-resume RECORD` under launchd for the reset time (acp-run's stderr, else
aiuse's `resets_at`, else a 30-min back-off) plus 5 min; the runner gates on
`aiuse --available --json --live` (20% left, 6 checks 10 min apart), then
reopens the same ACP session (`acp-run --resume`) with a prompt saying the stop
was the limit, not the agent. **Exception: agy on a non-Gemini model**
(2026-10-18): agy_acp_server strips the thought signatures Vertex Claude needs
on every session/load, so the reopened session 400s with `thinking.signature:
Field required`
(https://github.com/google-antigravity/antigravity-cli/issues/1281; untested since f633339: acp-run now
reopens agy with `session/resume`, which agy advertises, and a Gemini session resumed that way with nothing
replayed; whether resume also strips Claude signatures is unknown: retest after the Claude/GPT weekly
reset, 2026-10-24); `resume` (manual or automatic) starts a new session instead,
with a checkpoint (git status and diff stat, the old session's last tool calls,
the report it began), and acp-run fails a reply that is a provider error JSON
as class `provider`. Up to 3 attempts per slice; the record's
`auto_resume` field shows state, attempt, `not_before_iso` and the launchd
label. The `rearm` waiter waits through it; `check` says `resume-scheduled`
(exit 1, still running); exit 3 stays a real no-report and, for a quota stop
without an automatic resume (`--no-auto-resume`, no session id, an agent
without load/resume, 3 attempts used), ends with the exact `acp-dispatch resume
<record> --detach --no-wait` and the retry time. Direct `acp-run` use prints
the same kind of line on a quota stop: the session id and the `acp-run <agent>
... --resume <sid> -p ...` command that continues it.

**A dead slice is never "running".** A detached slice killed without finalize
(a reboot's SIGTERM, SIGKILL, power loss) used to keep `exit: null, finished:
null` forever (2026-10-17: trackpad-settings, pid 51407, read as running for
hours; a waiter sat until its timeout). The runner now traps TERM/HUP/INT and
finalizes with 128+signal; the record stores `pid_start` with the pid, and one
rule (`dead_reason`) says whether an unfinished record's process is gone (pid
dead, or reused by another process). `acp-dispatch reap [RECORD|DIR]`
finalizes such records once (exit from the runner's exit file, else launchd's
last exit status, else 255 `lost`; `finished` from the log's last write;
`reaped: {reason, exit_source, at}`); `check`, `wait` and `resume` apply the
rule first, and a launchd sweep
(`acp-dispatch reap --install`; `launchd/com.djbclark.acp-dispatch-reap.plist`,
RunAtLoad + every 30 min) covers records nobody reads. `wait` returns only
once a record is finalized or reaped (the agent's own `.done` touch no longer
ends it), and `resume` waits up to 120 s for finalize and passes
`model_applied`, the id acp-run reported, instead of a family alias; acp-run
itself now resolves an ambiguous family alias (`fable` over `claude-fable-5-1`
and `claude-fable-5`) to the newest version, the same way on a fresh and a
resumed session.

1. **claude.** Effort `low` / `medium` / `high` / `xhigh` / `max` via `--effort` (Opus 4.6 and Sonnet 4.6 have no `xhigh`; Haiku 4.5 and older have none). `--context 200k` sets `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`. `--context 1m` is the model's own window and does not add `[1m]`. Any other size exits 2. Workflow `agent()` and Orca `worker-start --model --effort` still set the session tier.
2. **codex.** Effort includes `ultra` on gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-5.6-sol and gpt-5.6-terra; luna models stop at `max`. Context is fixed by the model: gpt-6.1-sol 500000 (475000 effective); every other visible model 272000 (258400); all have `max_context_window` 872000. `--context 500k` only with `--model gpt-6.1-sol`; `--context 272k` only on the others; anything else exits 2 (the message names `--model gpt-6.1-sol`). The launch-time `CODEX_CONFIG` (`model_context_window`, merged with any `CODEX_CONFIG` already set; a value that is not a JSON object exits 2) is how the size is set. The window in effect is 95% of SIZE (`--context 400k` reads back 380000, `applied: ctx=400k/380000`); a read-back that is not 95% of SIZE is failure class `config`. The flag does not swap the model. `~/.codex/config.toml` still holds the CLI default.
3. **copilot.** `--effort` sets `reasoning_effort` (launch `--reasoning-effort` is the same knob). `auto` and `claude-haiku-4.5` have no option. Context is a launch flag: `200k` / `256k` / `272k` become `--context default`; `1m` becomes `--context long_context`. The words `default` and `long` are not `--context` values. `--model` is repeated on that server command because `set_config_option model` resets the tier. A tier that does not land is failure class `config`, exit 1. acp-run does not filter on Copilot's 1M product table. Long measured 922000 on gpt-5.5 and costs more AI credits.
4. **opencode.** `--effort` is the variant list on the `effort` option (`default` means no variant). `--context` exits 2. `limit.context` is fixed per model in the models.dev catalog.
5. **cursor.** `--effort` picks the `thought_level` option whose id is not `thinking` (`reasoning_effort`, `effort`, or `reasoning`). `xhigh` matches `extra-high`. `--set reasoning_effort=LEVEL` works only on grok-4.7, claude-sonnet-5-5, claude-haiku-5-5, gemini-4-argon and gemini-3.8-flash. `--context` sets option `context` where the model has one (`256k`/`500k`, `300k`/`1m`, `200k`/`1m`, `272k`/`1m`).
6. **grok.** Effort is option `reasoning_effort`: `low` / `medium` / `high` / `xhigh` on grok-4.7, grok-4.7-build-fast and grok-4.6; grok-4.5 stops at `high`. Context is `session/set_model` `_meta.contextWindow`, and the size must be one that model offers. grok-4.7 is `256k` / `500k` (`300k` exits 2). (The `ocx-*` ids, OpenAI models through the opencodex proxy, went with the proxy on 2026-10-19.) Read-back is `_x.ai/session/info` `context.total`.
7. **qwen.** No clamp: only a listed `reasoning_effort` value is accepted. Toggle-only models (qwen3.5-plus, qwen3.6-plus, qwen3.7-plus, kimi-k2.5, qwen3-max-2026-01-23) offer `none` / `default`; `low` exits 2. qwen3.8-max offers `none` / `low` / `medium` / `xhigh` (`high` and `max` exit 2). glm-5, glm-4.7 and MiniMax-M2.5 offer low through max. The coder models have no option. `--model qwen3.8-max` selects `qwen3.8-max(openai)`. `--context` exits 2.
8. **cline.** `--effort` is the launch flag `--thinking` (`none` / `low` / `medium` / `high` / `xhigh`). `max` exits 2. `default` adds no flag. There is no ACP option, so effort read-back is `(unverified)`. Omitted, ACP sends `reasoning_effort` `none`. `--context` exits 2.
9. **hermes.** `--model` works via `session/set_model` (read-back `(unverified)`). `--effort` and `--context` exit 2. `config_options` is null and `--set` is stored and ignored. A bigger window is a model id such as `openai-codex:gpt-6-astra-900k`. An ambiguous short name (`claude-sonnet-5.5`) exits 2. Effort in `config.yaml` `agent.reasoning_effort` is what the process starts with.
10. **zcode.** acp-run sets `ZCODE_BIN` (fixed 2026-10-15), so `--model` works. `acp-dispatch` still treats it as optional. Effort is option `thought`: GLM-5.3 and GLM-5.3-Flash are `low` / `high` / `max` (default max). `medium` and `xhigh` exit 2; there is no neighbor map. `--context N` sets `ZCODE_ACP_AUTO_COMPACT_THRESHOLD` (a compaction cap, not a window); ctx read-back is `(unverified)`. The GLM-5.3 window itself is fixed at 1,000,000. A 2026-10-15 prompt died `project_token_login_failed` at z.ai, unrelated to acp-run.
11. **agy.** `--effort low` / `medium` / `high` rewrites the model id to `<base>-<level>` (`gemini-3.8-flash`, `claude-opus-5-5`, `claude-sonnet-5-5`). `xhigh` and `max` exit 2. They are not rewritten to high. `gpt-oss-120b` is fixed at medium. `--context` exits 2 (Gemini 3.x Flash is 1,048,576; Claude and GPT-OSS windows were not measured).
12. **crush.** `--model` is `session/set_model` and works only with a private data dir (`ACP_RUN_CRUSH_DATA`, or `--perm deny`, or `--strip-user-config`); otherwise exit 2. The default `CRUSH_GLOBAL_DATA` (`~/.local/share/crush-acp`) is not enough. `--effort` and `--context` exit 2. Read-back is `(unverified)`. The SIPB models here have no `reasoning_levels`.
13. **bl.** Model choice per call. No effort or context knob in this matrix. Token Plan vs PAYG routing stays in the bailian-web-search skill.
14. **devin.** Not installed.

Exact ids, levels and sizes: `tools/acp-run/README.md`, section "Per-agent choices: vendor, model, effort, context (2026-10-15)". Regenerate with `acp-run <agent> --info --all-models`.

## Which AI for which work (judgment snapshot, 2026-08-23)

- **Claude Fable 5.1 @ high** — the rare call that really needs it: an
  adjudication nothing cheaper settles, whole-corpus analysis (1M native).
  `xhigh` almost never, and only with the operator's yes for that run
  (2026-10-18; "use it fully", 2026-10-15, is withdrawn). It does **not** have its own bucket: Fable is a
  sublimit of at most 50% of the shared Claude weekly and bills the 5-hour
  window too (corrected 2026-10-15).
- **Claude Sonnet 5** — default agentic-coding workhorse; best harness
  integration (workflows, skills, Orca (retired from djbclark-ade 2026-10-31), this repo).
- **Claude Haiku 4.5 @ low** — mechanical fan-out nodes: extract,
  classify, reformat.
- **Codex (gpt-6-astra @ high for frontier; 2026-10-18)** — the second frontier pool,
  `--kind frontier` only for a slice that really needs astra to look it over (a
  security-relevant or concurrency fix's final review, debugging that
  defeated real attempts). Its in-flight slices reserve quota against a new
  one (2026-10-18): its 5-hour window holds about one hard slice.
  **Everyday kinds too, while its quota is plentiful (operator 2026-10-25:
  "if we have lots of codex quota and it is the best of available options we
  can use it for non-frontier")**: `judgment` on `gpt-6.1-sol --effort high`,
  `code` on `gpt-6.1-sol --effort medium`, `bulk` and `mechanical` on `gpt-6-luna --effort low`, only while the
  tightest codex window (5-hour and weekly) has at least
  `[routing].plenty_min` (50%) left, a window with no reading counting as not plentiful
  (2026-10-25); below it, or with no fresh reading,
  codex is frontier-only again, and `acp-dispatch` judges the gate again on the reading taken
  after the load wait (the detached runner too). Estimates match history on kind and effort,
  and `[dispatch.estimate_floor] "codex:judgment"` (25) holds until three comparable slices
  (recorded kind and effort equal the request's; a request without `--effort` has none) exist; the per-window estimates obey the same floor.
  It competes on the normal ranking (judgment r3,
  behind claude and omp; code r15, mechanical r12, bulk r20), one slice per wave; astra never takes an
  everyday kind. (2026-10-19: the account is now the $100
  plan, `prolite`; the 5-hour note predates the upgrade, so re-calibrate with
  `route_agent.py calibrate` before relying on "one hard slice".)
- **Gemini via agy** — big-context reading, summarization, multimodal,
  bulk research; the most-wasted subscription → default overflow for
  non-critical bulk. Its Claude/GPT windows are unexplored.
- **Copilot** — GitHub-shaped work (PR review, inline suggestions, repo
  Q&A) on the premium-request pool.
- **Cursor Pro** — IDE-centric composer sessions; its "Auto" pool for
  cheap interactive edits.
  Cursor Cloud Agents are launched with `bin/cursor-cloud launch --repo <url>
  --ref <branch> --prompt-file F` (key from `sudo-secretspec`, `autoCreatePR`
  always false, the lead opens the PR after the adversary review), inspected
  with `status`, `run`, `usage`, and continued with `followup`. Since 2026-10-20
  a cloud slice is also an ordinary dispatch: `acp-dispatch cursor-cloud --model ID
  --kind code|bulk|mechanical --name N -f BRIEF -C REPO` (repo and ref from the
  checkout's `origin` and branch; refused unless HEAD is pushed; record with
  `cloud_agent_id`, a 30 s poller that `reap`/`resume` restart if it dies, report with
  `BRANCH:` (from the API, the result text or `ls-remote`, else `unknown`), `COST:`, and a
  `BLOCKED:` first line when the agent is blocked; no local load gate or cap).
  `route_agent.py` carries a `cursor-cloud` service (code 24, bulk 26, mechanical 18;
  never frontier or judgment) that reads the aiuse `cursor` row (`shares_pool`):
  eligible after every local Cursor row, never a kind's default.
- **Grok (SuperGrok, 45% left)** — realtime X/news/web angle, quick
  standalone questions.
- **z.ai GLM (lite) via zcode** — budget bulk coding on its own
  5h/weekly windows. Since 2026-10-08 `acp-run zcode` (third-party
  `zcode-acp-server`) drives it. acp-run sets `ZCODE_BIN` to the package's
  `vendor/zcode.cjs` (fixed 2026-10-15). The earlier "refuses every switch"
  failures were that missing variable: the server followed `which zcode`, a
  symlink, and never injected `ZCODE_BUILTIN_PROVIDER_CONFIG_FILE`. `--model`
  works and stays optional in `acp-dispatch`. Effort is option `thought`
  (`low` / `high` / `max` on GLM-5.3, default max; no neighbor map). The
  window is fixed at 1,000,000; `--context N` is only a compact cap.
  A 2026-10-15 prompt died `project_token_login_failed` at the z.ai login,
  unrelated to acp-run. Detail is the levers section above and
  `tools/acp-run/README.md`. Headless `zcode -p` stays as the fallback and
  runs GLM-5.3 at max.
- **OpenCode Go Plus** — shared paid subscription allowance. Routine Flash,
  MiniMax and Luna models only for execution; costly models require bounded
  read-only advice. See `config/go-model-policy.json` and the cost guard in
  `skills/model-routing/SKILL.md` (2026-10-25).
- **sipb (MIT)** — free, no-cost, non-Big-Tech option for light tasks and
  experiments where a 30B-class local model suffices.
- **ClinePass via LiteLLM** — reserved plumbing for Hindsight/hermes;
  not a general routing target.
- **Devin** — autonomous end-to-end PR-shaped tasks; currently 100%
  unused, activation is an open operator question.

## Routing policy (2026-10-15; the one copy is `skills/model-routing/SKILL.md`)

**Claude fleet governor (2026-10-23).** `bin/claude-fleet-governor` projects the Claude 5-hour and weekly windows to
their resets from the aiuse snapshots and keeps the subscription from running out first. Levels: `tight` (a window
projected ≥ 90% at its reset, 5-hour left < 25, weekly left < 30) and `critical` (exhaustion more than 10 min before the
reset and within 45 min, or any window left < 10). `run` moves live Paseo `claude` agents in place through
`bin/paseo-set-model`: Fable → Opus always, Opus/Fable → Sonnet 5.5 at tight/critical (originals recorded, restored
after the reset when the level is `ok` and the agent was not changed by hand), and at critical one handoff steer per
running agent per reset period toward omp API credits. Exit 0/1/2, 10 stale data, 11 a call failed, 12 internal error; state
`~/.local/state/ade/fleet-governor.json`; launchd `com.djbclark.claude-fleet-governor` (300 s, `--install`).
`route_agent.py` reads the state's `level` (under 30 min old): at tight/critical `code`, `bulk`, `research` and
`mechanical` never go to claude, and `judgment` prefers omp `anthropic/claude-opus-5-5`.
The governor's and the guard's numbers live in `config/gates.toml` and a temporary profile can loosen them (2026-10-26,
`bin/gate-profile`, [`docs/gates.md`](gates.md)); the level `route_agent.py` reads is computed from the active profile.

1. **Frontier models only for what really needs them (2026-10-18):** judgment
   is `acp-dispatch claude --model opus --kind judgment --effort high` first
   (2026-10-25: omp Opus next; codex `gpt-6.1-sol --effort high` while every codex window
   has `plenty_min` left, rank 3; never astra or Fable); the
   `frontier` kind, one slice per pool per wave (two on claude under the standing allowance, 2026-10-27, while the quota guard passes: `docs/gates.md`), reaches codex `gpt-6-astra`
   (`acp-dispatch codex --model gpt-6-astra --kind frontier --effort high`;
   in-flight slices reserve quota, so a second one is refused when the first
   leaves no room) and Fable 5.1 (`fable-deep`, or `acp-dispatch claude
   --model fable --kind frontier --effort high`; both are read-only advisors
   unless `ACP_OPERATOR_APPROVED=frontier-exec`; `xhigh` needs `ACP_OPERATOR_APPROVED=fable-xhigh`). Fable is a <=50%
   sublimit of the one shared Claude weekly (and bills the 5h window); under
   10% of its cap the router suggests `opus --effort high`.
2. **Everyday work on the other pools**, cheapest adequate first: agy
   Claude/GPT (>= 40% left), Cursor Auto, codex `gpt-6.1-sol` / `gpt-6-luna`
   (only while every codex window has >= 50% left, operator 2026-10-25; never
   astra), zai GLM-5.3, opencode-go (bulk and mechanical only), agy Gemini
   for bulk and big-context reads, crush/SIPB for light bulk. Minimum spec
   (model × effort × context) that does it well. Start on the cheap eligible
   tier and escalate through `acp-dispatch reroute` on a verified failure
   (operator, 2026-10-18; it replaced "route up when unsure").
   **Exception, 2026-10-03:** antigravity's CLI has a burst limit (roughly 60
   generation requests an hour per login) that `aiuse` cannot see, so spread its
   work over hours, prefer `acp-run agy`, and never fan out a batch at it.
2a. **The Claude API credits (omp, operator 2026-10-19)**: the pool `aiuse` labels
   "omp credits" is the Claude Max plan's monthly API credits, an expiring grant. A
   normal tier used with discernment: first for work that needs API access and cannot
   run through a TUI or ACP (kind `api-only`: SDK paths such as the Claude route in
   `bin/failover.py`, a verdict classifier, batch jobs), otherwise ordinary `code` and
   `bulk` slices via `acp-run omp --model anthropic/claude-sonnet-5-5`, so the credits
   are fully used before they expire each month and never left unspent. No
   `ACP_OPERATOR_APPROVED=omp`. `route_agent.py` tags the route "burn before reset"
   while the balance is 30+ points above an even spend over the month; omp's own
   default model is Copilot's, so `acp-run omp` insists on `--model anthropic/...`.
   One copy of the rule: `skills/model-routing/SKILL.md`.
3. **Reserve, floor 60% left, one small slice, only when that vendor is the
   point:** copilot (GitHub-side Copilot review). grok is an ordinary pool since
   2026-10-18 (GrokBot has its own Cursor pool).
4. **Never:** hermes as a target; clinepass (Hindsight/hermes lifeline); prepaid or
   credits-backed models without a fresh operator decision (the Claude Max plan's
   monthly API credits, run through omp, are the exception: see 2a); devin; an
   all-vendor fan-out.
5. **Probes over memory**: `aiuse --available` (exit 3 = nothing usable;
   ignore `kind:"conserve"` pace alerts for go/no-go), `cswap list` (Claude:
   5h, 7d and Fable together), `route_agent.py plan --kinds ...`, then
   `acp-run <agent> --info` for ids; re-plan at every slice boundary.
   Probe agy **once** and reuse the answer: every `agy -p` is a generation request
   against its hourly burst budget (see the 2026-10-03 correction).
6. **Context hygiene:** Claude Code compacts by itself at 400k
   (`autoCompactWindow`); herdr/Orca sessions (retired from djbclark-ade 2026-10-31; `self-slash` keeps those hosts until D6) and Paseo sessions compact earlier at a natural
   boundary via `self-slash`; a topic change runs the `handoff` skill then
   `/new`. Nothing here asks the operator.

**Where the numbers live (2026-10-18).** `config/routing.toml` is the source of
truth for the kinds, each service's `good_at` ranks, the frontier model list
and the pace and burn-first knobs; `bin/route_agent.py policy --md` prints it
as a table, so copy no numbers from this file. A fresh `acp-dispatch` requires
`--kind` (exit 2 without it) and an eligible agent and model;
`ACP_OPERATOR_APPROVED=route-override` skips only the eligibility check. A
frontier model runs only with `--kind frontier`, by default as a read-only
advisor (`--role advise`; `--role exec` needs
`ACP_OPERATOR_APPROVED=frontier-exec`). Escalation is cheap-first and now a
ladder, not a judgment call (operator decision 1.4, 2026-10-18): a slice that
failed on its tier (no-report or partial, not quota) climbs ONE rung of
`[escalation]` in `config/routing.toml` (mechanical -> bulk -> code -> judgment
-> frontier; `research` -> judgment via `[escalation.next]`) through
`acp-dispatch reroute RECORD --escalate` — `check` prints the command, the
agent/model come from `route_agent`'s top route for the next kind excluding
the failed pool, and the top rung refuses (exit 2). A quota stop whose reset
is more than `[dispatch].auto_resume_max_wait_hours` (6) away is rerouted the
same way instead of waiting for an in-place auto-resume.
As of 2026-10-26, preflight-unavailable records retain the original task text,
permission mode, effort/context and continuation settings. A refused dispatch
preserves an existing launched run and appends its refusal, even with `--force`.
A repeated preflight-only refusal refreshes the record with the latest task and
permission intent, including when replacing a legacy thin unavailable record.
Reroute refuses missing or unreadable original context with exit 2 before launch;
recover a legacy thin record with `reroute RECORD --agent A --model M -f FILE`
(or `-p TEXT`) and explicit `--perm all|read-only|deny` when an unavailable
record lacks permission intent. Recovery never changes a recorded permission;
reroutes inherit it and run the usual permission and routing gates. Effort/context
are inherited only for the same agent and model; a different target uses its
defaults, and escalation uses its selected route's effort when supplied.

Scoring is pace- and reset-aware: a computed
burn-first bonus goes to a pool that would waste quota at its reset, and a pace
penalty to a pool burning fast. `route_agent.py calibrate` reports done rates,
and `bin/routing-recalibrate` (monthly, launchd) has Opus re-rank `good_at`
from them.

**Lead sessions, adversary rounds and the quota guard (2026-10-23).** On 2026-10-20 the
Claude Code weekly window hit 100% at 17:07Z, 2.6 days before its reset, and every
orchestrating session stopped, which stopped every other pool too; an `aiuse` `conserve`
alert had said so since 06:02Z and nothing read it. The burn was Opus 5.5 (~53%: the
`adversary` Agent-tool sub-agent, judgment slices, Orca workers (Orca since retired from djbclark-ade, 2026-10-31)) and Fable 5.1 (~30%: the
lead session itself). The rules (`skills/model-routing/SKILL.md`, *Routing policy* items 12
and 13; `config/routing.toml` `[lead]`): a lead session runs on Opus 5.5 at high (Sonnet 5.5
at medium when it only drives a pipeline, high only for a judgment turn; djbclark 2026-10-23), never Fable; adversary rounds go to `acp-dispatch
omp --model anthropic/claude-opus-5-5 --kind judgment --effort high` first; an unpinned
Agent-tool sub-agent or teammate runs Sonnet (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, set in the
live settings by running `bin/claude-settings-env`, whose `--check` shows drift, 2026-10-23), so pass `model: "opus"` for judgment. The guard that
makes the numbers act: `bin/claude-quota-guard` (`check` every 15 minutes under launchd after
`--install`, `status [--json]`) derives `ok` / `watch` / `tight` / `critical` from the Claude
windows (weekly, 5-hour, Fable cap) and the snapshot's Claude `conserve` alerts, writes
`~/.local/state/ade/quota-guard.json`, and sends one `hermes-ping` per level per reset
period (the mark survives level drops; a new weekly reset clears it). `aiuse --available`
drops every pool with `usable_now: false`, so an exhausted Claude is an absent row (exit 0):
the guard then reads the payload's top-level `excluded[]` (an operator exclusion) or the newest
snapshot's `accounts[]` (a snapshot has no `excluded` key) and calls an exhausted or
`usable_now: false` Claude `critical`; a snapshot-only Claude that is not blocked is still at
least `watch` (`source: snapshot-only`: a live 429 or a note the snapshot predates). The Fable
pool is dropped the same way once the Fable cap is exhausted: the guard reads that window from
the snapshot (0% left, `watch`). A weekly "projected to run out" alert counts as
`tight` only for the weekly windows (never the Fable cap) and is ignored while that window
is `pace_early` (early-week projections swing wildly). Data older than 3 hours (the oldest of
the payload's age, each judged pool's own age and the snapshot's age: a dead collector) is
`stale: true` / "(stale)": the level is at least `watch` with a "run `aiuse --live --json`"
advice line, level pings are suppressed and one ping per stale episode says so. At `critical` the adversary
line is qualified: omp only while `aiuse --available --json` still lists it (aiuse rate-gates
omp when every Claude weekly window is exhausted). aiuse exit 3 (nothing usable) is `critical`
whatever the snapshot shows (even when aiuse printed non-object JSON beside it); a live
`available` row without `windows[]` (a `pool_family: "fable"` row is the Fable cap, never the shared weekly) is judged by its own
`headroom_percent` / `binding_window` / `usable_now`. Exit codes 0 / 1 / 2 / 3 for the
levels, 10 when Claude appears nowhere, any container (`available`, `excluded`, `accounts`,
`alerts`, `windows`) is present but not a list of objects, the snapshot does not parse, aiuse
could not be read or another check holds the lock. Exit 10 never writes a level: the level,
advice and number fields stay as they were, but a failed read (not a held lock) records
`unreadable_since` / `last_unreadable_at` and, on the second failing run in a row, sends one ping per episode
(`last_unreadable_pinged_at`); the next good read clears them. 64 for a bad
`CLAUDE_QUOTA_GUARD_THRESHOLDS`, 69 for `--install` off macOS (launchd only; use a systemd
user timer or cron). The UserPromptSubmit hook `claude/hooks/quota_nudge.py` reads only the
state file and prints its `advice` once per session and level, and `[quota-guard unreadable]`
once per session once the guard has pinged about an unreadable episode and failed again
within 2 hours (a one-off hiccup or a stopped guard prints nothing); its once-per-session
memory is updated under a flock.

## Formerly open questions — resolved by operator, 2026-08-23

- zai GLM lite is consumed by the `zcode` TUI.
- `muse` is the Muse service itself (own account).
- Devin is dormant deliberately (also disabled in Orca's roster; Orca retired from djbclark-ade 2026-10-31).
- Bailian is awaiting ID verification, expected live ~2026-08-26.
- Prepaid tier retired until an explicit top-up.
- MIT Claude account is gone forever; removed from cswap 2026-08-23.

## OpenCode Go cost policy — 2026-10-25

The October audit found real work plus expensive-model and large-context burn;
Go is not free. Routing now chooses MiniMax M3 / GPT-6 Luna / DeepSeek V4.1 Flash
for bulk / mechanical / code. Grok 4.7, Kimi K3/K2.7 Code, GLM 5.3 and DeepSeek
V4 Pro are bounded advisors; the complete reviewed classification is
`config/go-model-policy.json`. No costly main-loop escalation is emitted by
`route_agent.py substrate`. `acp-dispatch` and direct `acp-run` refuse costly
execution, unclassified Go models, and advisory runs without read-only scope
and a positive deadline of at most 600 seconds. Dispatch advice also needs
`--role advise --kind judgment|research|frontier`; direct ACP needs
`--go-advisory`. Raw native UI/model selection bypasses the ACP gate, so this
is a local orchestration policy, not a provider billing cap.

Use a short self-contained brief; OpenCode ACP does not expose a smaller context
window. The Go plugin warns/compacts well before model capacity, counts cached
input and stops compaction loops. See [context hygiene](context-hygiene.md).
Historic free-tier snapshots above do not authorize free fan-out today.
