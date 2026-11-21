# Model and effort routing

Snapshot **2026-11-09** (model tiers as data; rewritten by slim-down E7 on 2026-11-08; the 2026-08-23 service matrix, the
per-service effort tables and the dated policy updates that were here are in git history). Goal: know which models are
reachable through which pool on this machine, which budget each spends, and route every slice by vendor × model ×
effort × context window. The method is the `model-routing` skill (`skills/model-routing/SKILL.md`); this page is the
record of what feeds it and why. Percentages drift constantly: re-probe, never trust a page for balances.

**2026-11-13 operator ruling, Fable short:** "If we are out of Fable use for a time period we should wait, not automatically
degrade. If we already automatically degraded, we should make a list of stuff for Fable 5.2 to check on when it comes back,
and we should have a timer to start up work 1 minute after the next time window starts." A claude `frontier` slice is Fable or
it waits (other frontier families are not a degrade); `bin/fable-wait` keeps the list and arms the one-shot wake
(`skills/model-routing/SKILL.md` D3a, `docs/scheduling.md`).

Current operator decision: Pi is the sole general-purpose third-party TUI; vendor monthly-plan clients and Hermes remain. The legacy omp/OpenCode transport rows below are marked `retired = true` in policy, so they cannot win automatic dispatch. Their pool metadata is preserved for a validated Pi migration. Pi catalog discovery remains disabled in the generic router to avoid merging independent vendor pools. See [migration evidence and acceptance](tui-security-and-pi-migration.md); API checks and vendor subscription allowances stay distinct.

## A. Where the numbers live

A1. `config/ade.toml` (kinds, each pool's ranks per kind and suggested `--model [--effort]`, the quality band, the
plenty gate, burn-first and pace knobs, the never-route list and aliases, dispatch gates and estimate floors, the lead's
model) and `config/ade.toml [gates.frontier]` (the frontier allowance, `docs/gates.md`). Print both with
`bin/route_agent.py policy --md` (or `policy` for JSON); no other file restates them.
Model frontier vs near-frontier classification and the current standings snapshot live in
[`docs/model-rankings.md`](model-rankings.md) (the ranking page; linked from `[dispatch].frontier_models`).
Since **2026-11-10**, runtime routing reads these values through
`ade_config.load_effective`: a valid `config/ade.toml` replaces the legacy base
when present, and `~/.config/djbclark-ade/local.toml` overlays it per leaf
(service arrays replace whole). `ROUTING_POLICY` isolates the routing domain
from unified/local routing values. Invalid inputs stop initialization; the final
overlaid routing policy retains the legacy shape/default validation. `policy`
reports base/local source provenance. Explicit `load_policy(path)` and
`reload_policy(path)` remain isolated legacy reads. The router's tier helpers
use one validated effective model-tier snapshot, refreshed by default reload;
`MODEL_TIERS_TOML` isolates that domain and preserves its legacy default fallback.
See [config precedence](config-migration.md).
A2. `bin/route_agent.py plan --kinds …` applies them to the live quota and prints one `ade-worker-run --lead … --slice … --cwd … -- --provider … --no-wait` line per slice (rd-01, 2026-11-14; `--lead` defaults to `$PASEO_AGENT_ID`; a missing input leaves `<lead>` / `<slice>` and fills `dispatch_warnings`; `route` still prints the bare `paseo run` template);
`route`, `show`, `services [--check-models]`, `calibrate`, `substrate` and `hermes-chain` are its other commands.
A2a. **Unattended dispatch (2026-11-12):** `Choice.dispatch` adds the provider-native mode from `[dispatch].unattended_modes`: Claude `bypassPermissions`, Codex and Antigravity `full-access`. Pi reports no selectable modes in `paseo provider ls --json`, so no mode is passed. This prevents workers from inheriting Default permissions.
A2b. **PR Radar adapter (2026-11-14):** `bin/pr-radar-route` is the routing script of the pr-radar Paseo plugin (a third-party
plugin; it runs the script with its context JSON on stdin and reads launch overrides from stdout). It is the **single
implementation**: pr-radar's `examples/pr-radar-route.py` is not a copy of this file (omercnet/paseo-plugins#618 replaced
the synced copy with a self-contained 55-line example, on purpose; nothing keeps the two byte-identical). This script stays
stdlib only, no ADE imports. The PR-signal to kind mapping lives in `pick_kind` (operator
ruling 2026-11-14): `reviewRequestedFromMe` or `isSecurity` is `judgment`, `authorKind == "bot"` is `bulk`, everything
else (Issues-tab items included) is `code`. It runs `route_agent.py route --kind K [--repo NAME] --json`, 25 s timeout
(`NAME` is the bare lowercase repo name, dropped when outside `[a-z0-9._-]` or starting with `-`), and prints `{provider, model,
thinkingOptionId, modeId, reason}` parsed from the routed `dispatch` line; `modeId` stays as routed (yolo for every PR, bot
and non-owner authors included) and `contextMode`/`profile` (pr-radar's field names) are never set; a template value
(`<id from: …>`, any `<` or `>`) in the dispatch is refused, never passed on. Router choice: `$PR_RADAR_ROUTE_AGENT`
(tests), else the sibling `route_agent.py` when the script's parent has `config/routing.toml` (an ADE checkout or
worktree), else `~/src/djbclark-ade/bin/route_agent.py`, else the sibling (vendored copy). Only the named fields of the
context are read; titles and comments are untrusted and never forwarded. On failure (bad stdin, timeout, router non-zero
exit: its exit code, and as reason its JSON `reason` on stdout (the no-headroom case) with the last stderr line after it, else its
stderr; unparsable answer; template dispatch or value, `cursor-cloud launch …` included) stdout stays empty and pr-radar falls back to its
defaults. Tests: `tests/test_pr_radar_route.py` (stubbed router, no live quota).
A3. **Monthly `good_at` re-rank (2026-11-10):** `route_agent.py calibrate --json --since 30` proposes rank
deltas from recent dispatch outcomes. The optional Paseo schedule `routing-recalibrate` (Day 1 09:00,
`--mode auto`) applies those suggestions; inventory + create line in `docs/scheduling.md` and
`config/ade.toml [install.jobs]` (Carried #33 residual; launchd job retired in slim-down E5).

A4. **Canary waves (2026-11-12):** `[routing].canary_pools` names antigravity, openai_api and zai, whose meters cannot establish exhaustion before a refusal. Each `plan` assigns at most one agent per named pool, including aliases, and prints per-pool max=1 (`canary_pool_max` in JSON). The lead must observe one successful canary turn, re-probe quota/refusals, and only then expand within the normal `max_parallel`. The planner does not attest live canary success; another plan is not permission to launch a second unproven canary. No elapsed-time release is used.

A4a. **Antigravity is never routed through Pi (operator 2026-11-21).** "I think we need to keep the antigravity paseo provider/agy, Pi only seems to work with agy API pre-paid money or something. For now we should remove antigravity from pi and route to the native antigravity adapter in paseo." Every Antigravity route (the `antigravity-neon` and `antigravity-argon` pools, `ui-automation` r2 included) dispatches `--provider antigravity/<id>` on Paseo's native provider. `config/pi-pool-acceptance.toml` has `[pools.antigravity] accepted = false`, `provider_models("pi")` drops `antigravity/*` (`PI_EXCLUDED_NAMESPACES`), `bin/pi_defaults.py` skips such a model, and `tests/test_pi_defaults.py::test_no_pi_pool_resolves_to_an_antigravity_model` pins it.

A5. **Model families: the newest version, automatically (operator 2026-11-21).** Ruling: "the newest version of agents are always used, eg astra should have automatically routed to 6.2, not 6.0, as soon as 6.2 was released" and "we never need to judge newer versions of agents, we can just assume they are better". A `[[service]].models` id with `*` or `?` (`gpt-*-astra`, `gpt-*-sol`, `gpt-*-luna`, `gemini-*-neon-high`, `gemini-*-argon-high`, `grok-*` on `cursor-grok`, B4a) names a family; `route_agent.py plan`/`route`/`adjust` resolve it, once per process, to the newest id `paseo provider models <provider> --json` lists. The order is by **version**, read from the numbers the `*` stands for (`6.2` > `6.1` > `6`, `4` > `3.8`, `6.10` > `6.9`), never lexical (`bin/model_family.py`). The `*` matches version text only (1-3 digits per dotted part), so `gpt-*-sol` never picks `gpt-7-mini-sol`, `-lite`, `-flash`, `-preview` or a dated id as the newest of its line, and `?` is one digit; a different line is a different family and is named explicitly. There is no canary or eval gate for a newer release. A plain id is a literal and keeps working: Pi pools (`zai`, `cursor`, `clinepass`) and Cursor Cloud stay literal because `bin/pi_defaults.py` and `config/pi-pool-acceptance.toml` pin physical ids, and claude's `opus`/`sonnet`/`haiku`/`fable` are CLI aliases the CLI maps itself. A `[dispatch].frontier_models` token with `*` is a family too (`gpt-*-astra` makes `gpt-6.2-astra` frontier the day it resolves). Optional per-family hold, unset by default: `[routing.model_holds."gpt-*-sol"]` with `model`, `until` (YYYY-MM-DD, the last day it holds) and `reason`; an expired hold is ignored and the plan says so. The catalog unreadable (or no id matching): the last id recorded in `~/.local/state/djbclark-ade/route-model-resolved.json` (`ROUTE_AGENT_MODEL_STATE`), and the plan prints `model: ...` saying it is from state; with no record the family string stays in the launch line and `dispatch_warnings` says so. `route_agent.py models [--json]` lists every family with its newest id, and `show` prints a line for a family whose newest id changed (`CHANGED from X at T`), is held, or fell back to state. Tests: `tests/test_model_family.py`; `ROUTE_AGENT_MODEL_CATALOG_JSON=<file>` (JSON `{provider: [ids]}`) is the suite's canned catalog.

## B. The pools (J2 pool audit, `docs/slim/log.md`, 2026-11-06; grok retired 2026-11-07)

| Pool (router service) | Paseo provider | Billing | Notes |
|---|---|---|---|
| B1. `claude` | claude | subscription (5-hour and weekly windows; Fable a <=50% sublimit of the weekly) | the lead's own pool; Opus judgment, Sonnet code, Fable frontier (Fable short: wait for the window, never Opus; 2026-11-13, `bin/fable-wait`) |
| B2. `omp` (retired transport) | omp, disabled | the Claude Max plan's monthly API credits (an expiring grant) | `api-only` first, then judgment (adversary rounds), code, bulk; skipped while omp has no enabled Anthropic login |
| B3. `codex` | codex | prepaid: OpenAI API credits (aiuse pool family `openai_api`), not the ChatGPT subscription (the 2026-10-19 `prolite` $100-plan wording was replaced by the 2026-11-17 split, `config/ade.toml` `[[service]] name = "codex"`) | the newest `gpt-*-astra` for frontier only; the newest `gpt-*-sol` (family, A5; gpt-6.2-sol today) for judgment, code (rank 13, ahead of `cursor-auto`'s 14), research and `ui-automation` (rank 4) only while the prepaid balance is fresh and at least `plenty_min` |
| B3a. `codex-subscription` | codex | subscription: the Codex/ChatGPT windows (pool family `default`; split from B3 on 2026-11-17) | the newest `gpt-*-luna` for bulk and mechanical only; the sol and astra families are API-credit models and live on B3 |
| B4. `cursor-auto`, `cursor` | cursor | subscription (Auto and third-party sublimits) | Auto is burn-first; GrokBot's separate Cursor pool (`grok-bot`) is never a target |
| B4a. `cursor-grok` | cursor (Paseo's native provider, `cursor-agent`) | subscription: draws the Cursor third-party pool (`shares_pool = "cursor"`, the `cursor` row's reading, as `cursor-cloud` does) | **operator 2026-11-21** (`skills/research` 1b: research lead and reviewer are the latest xAI model): `models = { frontier, research } = grok-*`, a family (A5) resolved to the newest `grok-N.M` in `paseo provider models cursor --json` (grok-4.7 on 2026-11-21; Paseo lists grok-4.7/4.6/4.5, the effort variants are `agent --list-models`' business). frontier r4 (after Neon, ahead of Argon, `judgment_tier`), research r14, `max_parallel = 1`. For a `frontier` slice a pool whose frontier model is not a `frontier_models` model (this row and Neon) is a slice-only pool: it never gets the burn-first bonus (computed or static) and it sorts behind every `frontier_models` pool (Astra, Fable, Argon aside as a fallback) that has room, whatever the pressure or pace penalty says (`_frontier_slice_only`, adversary PR 899 MED-1 rounds 1 and 2); it takes a frontier slice only when no such pool has room. That order binds kind `frontier` only: for `research` (r14, behind claude 10, Neon 11, Composer 12, codex 13) the burn bonus still applies, so an underspent Cursor pool does make grok the research pick. A research lead gets the grok dispatch line from `plan --kinds research`, never a hand-built one (`skills/research` 1b); `route_agent.py models` only reads the newest id. `[dispatch].frontier_slice_models` carries `grok-*`, matched against the whole model id (`grok-4.7`, not `grok-4.7-fast` or `grok-3-mini`), so `adjust` does not refuse it for `frontier`; it is not a `frontier_models` token (no frontier floor/gate). `grok` and `grok-bot` stay in `never_route`: this is neither the retired standalone xAI CLI nor the GrokBot Chief-of-Staff pool. If `paseo provider models cursor` lists no grok id (the cursor login lapsed, 2026-11-21 morning) and the state file has no earlier one, the family is `unresolved`, `dispatch_warnings` says so, and nothing is invented; after a good resolution a lapsed login keeps the last id from state (A5, `plan` prints "from state"). |
| B5. `cursor-cloud` | none (`bin/cursor-cloud launch`) | API price on the Cursor pool | leaves the Mac, pushes a branch; the deleted acp-dispatch shim stopped launching it with Paseo |
| B6. `opencode-go`, `opencode-zen-free` (retired transport) | opencode, disabled | Go Plus subscription (one shared monthly allowance); the free zen models | bulk and mechanical, never code (djbclark 2026-10-30); section F |
| B7. `antigravity-argon` | antigravity | Google subscription: Gemini 4 Argon had its own weekly window on Google AI Pro; **since 2026-11-21 the plan is Google AI Ultra 20x** and every Gemini model, Argon included, draws the one shared `google:gemini` pool, so this row has no reading of its own and fails closed ([dated-quota-overrides.md](dated-quota-overrides.md) 1.2 and 1.3) | frontier FALLBACK, behind codex and claude (operator 2026-10-31), and since 2026-11-16 a last-resort `research` pool since 2026-11-16 (`fallback_kinds`, rank 24), with `fallback_after` gating every requested kind (both roles share that one window); restored 2026-11-07 for tendcf/nix2cf's review route 3; needs the `agy` CLI on PATH (`ade-install` component `antigravity-cli`) and dispatches the newest `gemini-*-argon-high` (a family, A5; `gemini-4-argon-high` today; the provider folds effort into the id) |
| B7a. `antigravity-neon` | subscription: **Google AI Ultra 20x since 2026-11-21**; every Gemini model draws the one shared `google:gemini` 5-hour + weekly pool, and the `antigravity-argon` row has no reading (so it fails closed), see [dated-quota-overrides.md](dated-quota-overrides.md) 1.2 and 1.3 | **promoted 2026-11-21** (operator, Neon A3/A4 + Q3; canary passed 2026-11-21, lead 8ec213c7): a normal pool at `neon-high` (never `xhigh`): frontier r3, judgment r2, `ui-automation` r2, research r11, code r13; `fallback_after` and the research `fallback_kinds` last-resort are dropped, so it competes on rank (before, it was argon's frontier 5 / research 24 behind codex and claude). Canary pool (one agent until a turn succeeds). Dispatches the newest `gemini-*-neon-high` (a family, A5; `xhigh` is the provider's max effort and nothing routes to it). A Neon probe on 2026-11-19 returned `Resource has been exhausted` at 4.8 % window use ([docs/model-rankings.md](model-rankings.md) B3). **Context is up to 512K tokens in Antigravity**; the 1M is the Gemini API figure (<https://antigravity.google/docs/models>, read 2026-11-21), and the Pi Google-OAuth route (1M/262K, `config/pi-pool-acceptance.toml`) is switched off, A4a |
| B8. `clinepass`, `hermes` | none; hermes | Cline-pass API; the operator's assistant | never a delegation target; ClinePass is the Hermes/Dann lifeline (`substrate`, `hermes-chain`) |
| B9. `opencode-zen` (paid) | opencode | prepaid | retired until an operator top-up |

B9a. **Antigravity models and dated changes (read 2026-11-21).** `paseo provider models antigravity --json` lists 27 models: Neon, Carbon, Argon and Hydrogen at `low`/`medium`/`high` (Neon and Hydrogen also `xhigh`), the three Orchestrator ids (`gemini-pro-orchestrator`, `-neon`, `-argon`: planner plus executor, fixed effort), Gemini 3.8 Flash, Claude Opus 5.5 and Sonnet 5.5, and `gpt-oss-120b-medium`. Only Argon (B7) and Neon (B7a) have router rows; Carbon, Hydrogen and Orchestrator are listed but **not routed**. Antigravity's own table marks Carbon as Ultra/Enterprise only (included in the Ultra 20x plan the operator moved to on 2026-11-21, B7a): Ultra-only. A canary on 2026-11-21 (lead 8ec213c7) completed one read-only `gemini-4-carbon-high` turn, so the account is entitled; there is still no Carbon router row, and a row needs the operator's rank decision. On **2026-11-30** Antigravity removes `gpt-oss-120b` and the Claude 4.6 models (they are not the 5.5 ids routed here; footnote on <https://antigravity.google/docs/models>, read 2026-11-21). On **2026-12-01** the Gemini API price of Carbon and Argon rises from $2/$10 to $4/$20 per 1M tokens (Neon stays $3/$15, Hydrogen $1.50/$7.50; <https://aistudio.google.com/docs/pricing>); that touches only an API-key path, which the router never uses (SKILL C7), not the subscription windows. **Carbon (2026-11-21, operator):** the canary passed (entitled), but Carbon shares the one Gemini pool with Neon and ranks below it, so no `antigravity-carbon` row was added: it would only be a second name for the same window. Add one when a kind needs Carbon over Neon; Hydrogen and Orchestrator trials are queued in `docs/queue.md`.

B10. Retired from the router: agy (the agy TUI; Google's plan is the antigravity provider), copilot (the CLI; Paseo's
Copilot provider replaces it, no router row), zai/zcode, alibaba/qwen, devin, crush, kiro, cline, goose, muse, aider,
venicecode, pi (2026-11-06), grok (the SuperGrok CLI, 2026-11-07). They are `never_route`, so an aiuse account or a Paseo
provider row with their name never becomes an unprofiled service. `github` and `realtime-web` remain kinds with no pool,
and `api-only` survives only on the archived `omp` row, so the unprofiled-kind diagnostic ignores retired pools.

**Frontier order is a cost ordering.** `codex` carries `frontier = 1` and `claude = 2`, so a frontier slice usually
goes to the astra family even though `model-tiers` ranks Fable 5.2 above it: astra is the cheaper frontier
family, and the Fable gate plus `[dispatch.repo_overrides.REPO].frontier_order` still decide when Fable takes one
(2026-11-16, operator decision). It is a preference **inside the score**, not a hard precedence: a Codex window at 20%
scores worse than a fresh Claude one, so Fable can win. The config says both, because an unexplained inversion reads
as a bug.

**An unprofiled kind says so.** `bin/route_agent.py route --kind github` answers `no pool profiles github: declared
kind, no live pool ranks it`, not "no pool has room": those kinds lost their only pools with copilot and the Grok CLI
(2026-11-06/07). The diagnostic names the reason rather than claiming a pool was busy.

## C. The registry: `paseo provider ls --json` (2026-11-07)

C1. `route_agent.py` builds the service list from the curated rows plus `paseo provider ls --json` rows whose `enabled`
is `"Enabled"` and whose `status` is `available` (read with a 15 s timeout; never raises). Right after the daemon starts a
row reads `loading`: the call is repeated twice, 3 s apart, and a row still loading is treated as absent with a note on
stderr. Names pass through `[routing].aliases` (Paseo's `opencode` provider is the `opencode-go` pool) and
`never_route`. It replaced the deleted acp-run's agent table, the non-ACP headless list and Orca's roster.
C2. `paseo provider models <provider> --json` gives the provider's model ids; `route_agent.py services --check-models`
checks every suggested model against it (exit 1 when one is not listed, 2 when Paseo cannot list a provider). Not yet run
against the Mac's daemon: run it there after the merge.

## D. Quota: aiuse first, `paseo usage ls --json` second

D0. **Family matching (2026-11-12):** quota rows and snapshot windows count only for the declared `pool = [provider, family]` or primary `pool_family`. Unknown/missing family metadata cannot authorize a family-scoped route. Cursor’s `grok_bot` allowance never funds Composer or Auto: `cursor` conservatively retains the policy’s included `third_party` family (actual Composer billing-family validation remains separate) and `cursor-auto` claims `auto`. Antigravity `gemini`, `gemini_argon` and `claude_gpt` do not substitute for one another. Claude `default` supplies shared headroom; `fable` and `model_sublimits` constrain only that model, never create shared headroom. Providers with one unnamed pool retain null-family readings. Dispatch eligibility loads quota for every scoped/measured service, including Claude code; model-to-pool mapping names the explicit shared/default or included family. Native Paseo report/account IDs are not inferred as quota families; familyless reports remain unknown.

D1. `aiuse --available --json` stays the primary reading (it applies the operator's credits override, Admin API
readings and grant expiry at read time; 20 s timeout, memoised 30 s; the snapshot file is the fallback).
When the payload is `fresh: false` and `stale_pools` names only some rows, just those rows are re-judged, and a row keeps its
own reading only when all of these hold: its provider is `antigravity` (`STALE_REUSE_PROVIDERS`, the one pool whose aiuse fresh
limit sits below its query gate); it is a usable row with no `error`, blocked `state` or `reading_expired`; its own age is at
most 20 minutes (`STALE_REUSE_MAX_AGE`: the 900 s gate plus one 180 s sampler step) and its headroom at least 50%
(`STALE_REUSE_MIN_LEFT`); and **no Paseo agent on that provider is live or was created since the reading**
(`paseo ls -a -g --json`, any `provider` path segment equal to it, so `pi/antigravity/...` counts; `created` has only coarse
relative units, so its smallest possible age is used; an unreadable list counts as busy; `ROUTE_AGENT_PASEO_LS_JSON` feeds
canned output in tests). The last condition is the 2026-11-12 burst-drain guard: nothing reserves pool room for a slice already
dispatched, so a reading that predates a dispatch is not trusted, and a wave's second `plan` reads the pool unknown again. Any
other row reads unknown, as before. Why the reuse exists: aiuse's antigravity fresh limit is 600 s but the pool is queried at most
every 900 s (agy answers fast probes with 429s) and `aiuse --live` cannot beat that gate, so a healthy reused reading was stale
about a third of the time and `plan` refused research with Gemini at 100% (2026-11-21, twice). The plan's quota source line says
`reused reading kept for ...`.
D2. `paseo usage ls --json` is the second source: one report per `sourceId`. A report whose `report.status` is
`available` gives its windows (`remainingPct`, else 100 − `usedPct`; `resetsAt`) and `balances` (`remaining`/`limit` as a
percentage), a window naming Fable being the Claude Fable cap; any other status (`unavailable` with a `problem`, `error`),
or a report whose `windows` or `balances` is not a list, is **unknown, never a pass**. A `balances` entry with a positive
`limit` counts as one more window of the pool, so a nearly spent balance can only make the pool read tighter (it errs safe). `icon` (inline SVG) and `loginErrors` are dropped. A report older than 25 minutes keeps only
an exhausted window, as aiuse's own `fresh` rule does.
D3. The two merge per pool by the same rule aiuse's own rows use (`_merge_pool`): the tightest known reading wins and an
unknown never loosens or replaces a reading. `route_agent.py show` and the `quota_source.pools` field of
`plan --json`/`route --json` say which source each pool came from (`aiuse`, `snapshot`, `paseo`, `aiuse+paseo`).
D3a. **Accounts of one pool (rq-37, 2026-11-15; PR 708 Lows 3 and 4).** Rows and reports are told apart by the account
they read, not by the pool key. aiuse `--available` rows carry `account`, an email label that is **not** an identity (one
email can sit in two organizations): a row is identified only when it also names an organization (`ORG_FIELDS` in
`_aiuse_identity`), and aiuse emits none today, so every aiuse row is unidentified and folds as another account. Paseo
reports carry `id` (`claude:<account>`; `sourceId` is only the provider). Nothing matches an aiuse account to a Paseo
account: the two sources fold as readings of one quota per pool key, not per account. A non-cap row or report of an identified account and
family that repeats what is already folded under the key is one reading of one quota: known beats unknown (`_merge_caps`).
Any other second row (a different account, or one with no account at all, which cannot be shown to be the same) folds as
**another account** (`_merge_pool(accounts=True)`, `_folds_as_accounts`): the tighter figure, a window either cannot measure
stays None, and an unreadable row leaves an `(unmeasured)` None window so the measured account cannot open the plenty
gate alone. A Fable cap row is no account of its own, so `cap_only` is gone. An unreadable Paseo report of another account
adds that same marker to a measured pool (before, it was dropped and the pool could open on the other account).
A2c. **Default frontier order (rq-37, 2026-11-15; PR 708 Low 5).** `plan --kinds frontier` orders the pools that passed
every gate by `[dispatch.repo_overrides.REPO] frontier_order` when the repository declares one (only tendcf: Astra,
Fable, Argon). A repository with none (the default, and `--repo` omitted) has no order: the router's score decides, so a
claude burn-first bonus can put Fable ahead of a usable Astra, and a fallback (Argon) always sorts behind the pools it
sits behind. That default is intended (a fixed order is a per-repository rule, not a fleet rule); it is pinned by
`tests/test_route_agent_rt01.py`.
A2d. **Profile skip (rt-bulk, 2026-11-15):** `route` and `plan` pass over a pool with no model profile for the kind (no `models[kind]`: its line would carry a `--provider` placeholder that `dispatch_warnings` blocks) and name it under `skipped` (an additive key of the plan and route JSON; a queued slice's reason lists the same pools); the placeholder and its warning are emitted only when no pool that can take the kind has a profile, and a profiled pool with no headroom queues the slice instead.
D4. Pausing a session at a quota limit and continuing it after the reset is the Paseo plugins' job (session-guard,
usage-auto-resume; PLAN D4). The fleet governor (`level` → no claude code slices), the quota guard (`ok/watch/tight/
critical` and its state file) and gate profiles (the `away` profile) were deleted on 2026-11-07.

## E. The frontier allowance's Claude reading

E1. `ade_gates.read_guard_state()` returns `route_agent.claude_quota_state()`: the merged snapshot's `claude` entry (its
tightest window, the Fable sublimit, the reading's own age, the source, and why it is unknown when it is). The allowance
passes for claude only while that reading is under 30 minutes old, known, at least `frontier1_window_min_left` (30) on the
tightest window (the old quota guard's tight level) and at least `frontier1_min_left` (15, the old guard's Fable stop) on the
Fable cap; otherwise the
closed rules apply (one frontier slice per pool per wave, an Agent-tool Fable call asks). Details: `docs/gates.md`.

## F. OpenCode Go cost policy (2026-10-25)

This records the retired OpenCode transport policy, not a Pi enforcement guarantee. The bounded Pi Go smoke is not automatic-routing or continuation acceptance; preserve cost/context policy while evaluating the replacement. Hermes direct API/substrate configuration is unchanged.

The October audit found real work plus expensive-model and large-context burn; Go is not free. Routing chooses MiniMax M3
for bulk and GPT-6 Luna for mechanical work, never a code slice (djbclark 2026-10-30); DeepSeek V4.1 Flash stays only the
main-loop substrate model (`route_agent.py substrate`). Kimi K3/K2.7 Code, GLM 5.3 and DeepSeek V4 Pro (and the Grok
models Go offers) are advisory only (`--perm read-only` requested, best effort since the 2026-11-07 internal-trust ruling: opencode has no
read-only mode, so the slice runs in its default mode with a logged note); the reviewed classification is `config/go-model-policy.json`. Raw
native model selection bypasses the dispatch gate, so this is a local orchestration policy, not a provider billing cap.
Keep briefs short (OpenCode exposes no smaller context window); the Go plugin compacts early (`docs/context-hygiene.md`).

## G. Model tiers as data (2026-11-09)

G1. Design: `docs/history/model-tiers-design.md`. This slice ships the file, the loader (`bin/model_tiers.py`), the CLI
(`bin/ade-model-tiers`) and the first readers (`route_agent`, `load_effective`). Full consumer migration (routing.toml
`@role` placeholders, render, literal scan) stays later.
Runtime adoption **2026-11-10**: router tier reporting, frontier tokens, sublimit
families and judgment fallback consume the final effective `[model_tiers]` tree.
Malformed overlays fail before publishing runtime state. Explicit legacy-file readers remain isolated;
`ade-model-tiers promote|set` now writes the unified production subtree.
G2. Today's table (re-check with `bin/ade-model-tiers show`):

| role | claude (rank 1) | codex (rank 2) |
| --- | --- | --- |
| frontier | `claude-fable-5-2` (`fable`) | `gpt-6-astra` |
| judgment | `claude-opus-5-5` (`opus`) | `gpt-6.1-sol` |
| everyday | `claude-sonnet-5-5` (`sonnet`) | `gpt-6.1-sol` |
| bulk | `claude-haiku-5-5` (`haiku`) | `gpt-6-luna` |

G3. Succession: `ade-model-tiers promote --vendor V --new ID --reason TEXT [--cascade N] [--dry-run]` shifts the ladder
(default cascade 2: new → frontier, old frontier → judgment; the displaced judgment goes to `[former]`). `set` changes
one role without shifting. On the default unified source, the writer regenerates only `[model_tiers…]`, preserves every
byte outside that subtree, and atomically replaces the file; comments between the tier tables are regenerated, not
preserved. Explicit `MODEL_TIERS_TOML` paths retain the legacy whole-file format. No secrets, no network. Edit in a
claimed worktree; the merge is the atomic apply. The projection-drift test canonicalizes regenerated tier formatting on
both sides and compares all other bytes exactly. After an intentional tier change, carry the new tier data into the
frozen `tests/fixtures/config/legacy/config/model-tiers.toml` fixture as well; otherwise that test correctly reports
the production/fixture drift.
G4. Untiered models are listed in `[dispatch].frontier_models` as families (e.g. `gemini-*-argon`, `gpt-*-astra`; a `*` stands for a version, A5); frontier matching is the
union of that list and every spelling/alias of each tiered vendor's frontier role.

## H. Reasons kept from the earlier matrix

H1. 2026-10-18: four astra slices at once emptied codex's 5-hour window, so the frontier models are reached only as the `frontier` kind (`route_agent.py plan`), capped per plan, and in-flight slices reserved their estimated quota per service (acp-dispatch, gone 2026-11-14; now re-plan before each launch, model-routing D5).
H2. 2026-10-20: the Claude weekly window ran out 2.6 days before its reset; Opus sub-agents (~53%) and a Fable lead
(~30%) were the burn. Hence `[lead]` (Opus judgment lead, Sonnet pipeline lead, never Fable: operator 2026-10-23) and
adversary rounds on omp first at that time (that client was archived 2026-11-08 and is no longer a fallback). Since 2026-11-07 (operator) Fable leads are allowed for now: the one line to flip back is
`fable_lead = true` in `[lead]` of `config/ade.toml` (false or absent restores never-a-Fable-lead).
H3. 2026-11-01: a cheap model as the daily coding driver was checked against Terminal-Bench 4.0 and this repo's own
review of Flash-written code (four BLOCKs): code stays on tier-1 models (Sonnet 5.5, the newest GPT sol, Gemini 4 Neon); cheap models only for
bulk and mechanical work a stronger model reviews. **Carried out 2026-11-21 (operator, Neon A7):** `codex` code rank 15 -> 13 (ahead of `cursor-auto`'s 14),
`zai` lost its `code` rank and model (Z.ai keeps mechanical, bulk and research), and `[routing].quality_max_rank_gap.code` went 10 -> 8, so with claude's
rank 12 as the best the code band ends at 20 (`cursor` stays, `zai` and `cursor-cloud` (24) are outside). `antigravity-neon` joined code at 13 (A3/A4).

## Predictive quota signals (W7, 2026-11-12)

`python3 bin/quota_signals.py --wave-start <previous-wave-start-ISO-time>` reads
`aiuse --available --json` and `paseo usage ls --json` using bounded argv-list
subprocesses, then prints JSON schema 1 with `pools[]`. Each pool has `routable`,
`conserve`, `surplus`, `reason`, and per-window projections. This is advisory
measurement eligibility: `routable` does not grant model/task eligibility or
permission to spend. No launchd, fleet-watch, router, notification or state writes
are wired in W7. Defaults and expected independent pools live in
[`config/quota-signals.toml`](../config/quota-signals.toml).

Per-pool `collected_at` must be within `max_age_seconds`, not in the future, and
strictly newer than the supplied previous wave start (PR 571 E1a). Envelope
freshness never substitutes for that timestamp. A stale, missing, ambiguous-account,
unknown-window or exhausted pool is unroutable. Missing configured pools remain
visible even though aiuse's available-only response omits exhausted pools. Unknown
or failed Paseo data cannot create entitlement; fresh aiuse can stand alone.
Only explicitly mapped sources constrain split pools; a provider aggregate must
not grant quota to an independent Antigravity family. Model sublimits do not
exhaust a shared pool: both aiuse and Paseo exclude Fable windows from the shared
cap. aiuse windows with another explicit pool_family are skipped; model-only
windows apply only to a model sublimit pool. Model pools also retain windows
of their declared shared_pool_family parent (from the model-cap window or row); parent exhaustion/unknown readings
and forecasts still bind the model. Filtering to zero applicable windows
leaves the pool unknown and unroutable. Cursor total/auto/third_party included
usage and grok_bot are explicit expected pools. A healthy Grok Bot reading never
hides absent or exhausted Auto/Composer pools (2026-11-12 incident).

For a clocked window, estimated consumption per minute is
`pace_ratio * 100 / window_minutes`. Projected remainder at reset is current
remainder minus that rate times minutes from collection to reset. A tighter
Paseo reading reduces each aiuse window by the difference between the aiuse
binding headroom and Paseo's tighter cap; this is deliberately pessimistic when
window identities differ. Stale Paseo reports retain only a zero veto, until a
known reset passes. Early, missing or non-finite pace produces no prediction.
Any forecast deficit above `conserve_deficit_percent` signals `conserve`.
`surplus` requires projected unused headroom above `surplus_min_percent` within
`surplus_horizon_hours`, every window forecastable, and no projected negative remainder in any window
(even a deficit smaller than the conservation alert threshold).
Missing pace alone does not invalidate a fresh quota measurement. These linear
forecasts assume steady spending and do not reserve in-flight sibling usage.

Offline replay uses `--aiuse-json PATH --paseo-json PATH --now ISO-TIME`; the
sanitized fixtures under `tests/fixtures/quota-signals/` document both inputs.
Exit 0 means JSON was produced, including unknown pools; exit 2 means invalid
arguments/config. Collector failures become unknown measurements, never a pass.

A Z.ai 429 code 1302 is a request-rate limit, not exhaustion (PR 571 E1b): this
script does not convert errors into exhausted quota or relax the five-agent
concurrency rule. W8 (below) owns adjustment/restoration. W9/W10 retain the operator's
seed at `claude/hooks/quota_nudge.py` (the brief's `bin/` path does not exist).
Its useful freshness and silent-on-missing-state principles are preserved here;
its session nudges, profile state and locks remain untouched for those units.

## Launch-time pool adjustment and restoration (W8, 2026-11-12)

`bin/route_agent.py adjust --kinds code,bulk [--dry-run] [--json] [--exclude …]` plans a wave like `plan`
and adds memory (`bin/route_adjust.py`; state and change log in `~/.local/state/ade/route-adjust/`,
`$ADE_ROUTE_ADJUST_DIR` overrides). It reads the same merged quota (`aiuse --available --json` plus
`paseo usage ls --json` via `load_snapshot`) as `plan`; it does not call `quota_signals.py`, whose output stays advisory.

Method, per kind. The kind's last routed pool is *held off* when its reading drops below its floor (the router's
`min_headroom`, a reserve's own floor, codex's `plenty_min` for an everyday kind, claude's Fable sublimit floor for
`frontier`) or when the slice no longer fits (`pool_usable`). New launches of that kind then go to the next pool the
router would pick (`plan`'s quality band, wave caps and frontier gates all still apply; a held pool is *avoided*,
not excluded, so the band's anchor stays where plain `plan` puts it). The tracked pool of a kind is the one its first
slice in a wave gets; later slices of the same kind neither move it nor log. Holds are keyed by repository too
(`repo:kind`), because the estimate floors are repo-scoped. A held pool is restored only
when it reads at least `restore_margin` points above its floor AND has been held `min_dwell_seconds`, so a pool
hovering at its floor does not flap; the margin is applied to every reading and then the router's own `pool_usable`
is asked, so it sits on the floor that actually binds (estimate floors and measured history included). With no
acceptable other pool, an usable held pool is restored early (`plan(kind_exclude=…)` is soft, and also yields when
the only alternative would be refused), so a hold never strands a kind.

Rules, each tested offline with fixture quota:

1. A snapshot with no readings or older than `max_age_seconds` changes no hold and releases none (the E1a
   per-pool `collected_at` rule still stands: re-read with `aiuse --available --live --json` before a wave). A pool
   with no reading is never displaced: absence of data is not a shortfall.
2. A `frontier` slice is never silently downgraded. If the route would run on a non-frontier model `adjust` prints
   `REFUSED`, logs a `refuse` event, leaves the kind's state alone and exits 3. A move to another frontier pool is allowed. "Frontier model" is a `[dispatch].frontier_models`/model-tiers token (`is_frontier_model`) or a `[dispatch].frontier_slice_models` family (`is_frontier_slice_model`, whole-id match: `gemini-*-neon-high`, `grok-*`): Neon is frontier r3 (2026-11-21) but stays out of `frontier_models`, which also floors and gates every Neon judgment/code slice, so `adjust` does not refuse a Neon frontier route.
   Since 2026-11-13 claude's short Fable sublimit no longer produces such a route: `suggest_model` never swaps in Opus and
   `route` does not offer claude for `frontier` while Fable is short (operator: wait, do not degrade; `plan` prints
   `WAIT for Fable 5.2 ...` with the window's reset, `bin/fable-wait` keeps the list and the one-shot wake), so this refusal
   is the backstop for a profile that names a cheaper frontier model.
3. `[routing.adjust].never_target` (omp, always, whatever the file says) is excluded from every kind and checked again
   on the result by exact match on the pool name, its agent and the model's provider prefix, or an `omp-` family name
   (never a substring: `cursor/composer-2.5` is allowed). Rules 2 and 3 also hold with `enabled = false`.
4. Running agents are never touched: the output is a launch line for a NEW `paseo run`. No hook, daemon or schedule
   calls `adjust`; the lead runs it where it ran `plan` (D1).
5. A hold expires after `max_hold_seconds` even without a fresh reading; a timestamp in the future counts as expired.
6. State is `state.json` (atomic replace; a corrupt or wrongly typed file reads as no holds), written under a lock
   that gives up after 30 s (then `adjust` plans read-only and says so). The log and lock refuse symlinks, and
   `$ADE_ROUTE_ADJUST_DIR` must be absolute.

Every change is one JSON line in `changes.jsonl` and one `adjust: {…}` line on stderr: `route` (first pool for a
kind), `switch` (from, to, why), `restore` (from, to), `hold` (a hold placed with no route line to carry it),
`expire`, `refuse` (once per change, not per call), and `release` (a pool is eligible again without being chosen). `adjust --status` prints the saved holds; `--dry-run` writes nothing. `[routing.adjust].enabled =
false` makes `adjust` plain `plan` plus rules 2 and 3 (no state, no log). Config keys and defaults: `config/ade.toml [routing.adjust]`. Known limits (adversary round 2): the tracked pool follows the wave as planned, so a wave-cap on another kind
can make a hold yield early or log a `switch` that quota did not cause; a hold is never pruned except by expiry. Not built:
effort or model-tier changes inside a pool (`docs/dynamic-model-effort.md` G4, still gated), automatic calls from other tools, and
cross-kind promotion (a kind never moves to a different kind's pools).
