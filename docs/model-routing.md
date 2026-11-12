# Model and effort routing

Snapshot **2026-11-09** (model tiers as data; rewritten by slim-down E7 on 2026-11-08; the 2026-08-23 service matrix, the
per-service effort tables and the dated policy updates that were here are in git history). Goal: know which models are
reachable through which pool on this machine, which budget each spends, and route every slice by vendor × model ×
effort × context window. The method is the `model-routing` skill (`skills/model-routing/SKILL.md`); this page is the
record of what feeds it and why. Percentages drift constantly: re-probe, never trust a page for balances.

Current operator decision: Pi is the sole general-purpose third-party TUI; vendor monthly-plan clients and Hermes remain. The legacy omp/OpenCode transport rows below are marked `retired = true` in policy, so they cannot win automatic dispatch. Their pool metadata is preserved for a validated Pi migration. Pi catalog discovery remains disabled in the generic router to avoid merging independent vendor pools. See [migration evidence and acceptance](tui-security-and-pi-migration.md); API checks and vendor subscription allowances stay distinct.

## A. Where the numbers live

A1. `config/routing.toml` (kinds, each pool's ranks per kind and suggested `--model [--effort]`, the quality band, the
plenty gate, burn-first and pace knobs, the never-route list and aliases, dispatch gates and estimate floors, the lead's
model) and `config/gates.toml [frontier]` (the frontier allowance, `docs/gates.md`). Print both with
`bin/route_agent.py policy --md` (or `policy` for JSON); no other file restates them.
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
A2. `bin/route_agent.py plan --kinds …` applies them to the live quota and prints one `paseo run --provider … --no-wait` line per slice;
`route`, `show`, `services [--check-models]`, `calibrate`, `substrate` and `hermes-chain` are its other commands.
A2a. **Unattended dispatch (2026-11-12):** `Choice.dispatch` adds the provider-native mode from `[dispatch].unattended_modes`: Claude `bypassPermissions`, Codex and Antigravity `full-access`. Pi reports no selectable modes in `paseo provider ls --json`, so no mode is passed. This prevents workers from inheriting Default permissions.
A3. **Monthly `good_at` re-rank (2026-11-10):** `route_agent.py calibrate --json --since 30` proposes rank
deltas from recent dispatch outcomes. The optional Paseo schedule `routing-recalibrate` (Day 1 09:00,
`--mode auto`) applies those suggestions; inventory + create line in `docs/scheduling.md` and
`config/install.toml [[install.jobs]]` (Carried #33 residual; launchd job retired in slim-down E5).

A4. **Canary waves (2026-11-12):** `[routing].canary_pools` names antigravity, openai_api and zai, whose meters cannot establish exhaustion before a refusal. Each `plan` assigns at most one agent per named pool, including aliases, and prints per-pool max=1 (`canary_pool_max` in JSON). The lead must observe one successful canary turn, re-probe quota/refusals, and only then expand within the normal `max_parallel`. The planner does not attest live canary success; another plan is not permission to launch a second unproven canary. No elapsed-time release is used.

## B. The pools (J2 pool audit, `docs/slim/log.md`, 2026-11-06; grok retired 2026-11-07)

| Pool (router service) | Paseo provider | Billing | Notes |
|---|---|---|---|
| B1. `claude` | claude | subscription (5-hour and weekly windows; Fable a <=50% sublimit of the weekly) | the lead's own pool; Opus judgment, Sonnet code, Fable frontier |
| B2. `omp` (retired transport) | omp, disabled | the Claude Max plan's monthly API credits (an expiring grant) | `api-only` first, then judgment (adversary rounds), code, bulk; skipped while omp has no enabled Anthropic login |
| B3. `codex` | codex | subscription ($100 plan, aiuse `prolite`) | astra for frontier only; everyday models while every window has `plenty_min` left |
| B4. `cursor-auto`, `cursor` | cursor | subscription (Auto and third-party sublimits) | Auto is burn-first; GrokBot's separate Cursor pool (`grok-bot`) is never a target |
| B5. `cursor-cloud` | none (`bin/cursor-cloud launch`) | API price on the Cursor pool | leaves the Mac, pushes a branch; acp-dispatch stopped launching it with the Paseo shim |
| B6. `opencode-go`, `opencode-zen-free` (retired transport) | opencode, disabled | Go Plus subscription (one shared monthly allowance); the free zen models | bulk and mechanical, never code (djbclark 2026-10-30); section F |
| B7. `antigravity-argon` | antigravity | Google AI Pro subscription (Gemini 4 Argon weekly window) | frontier FALLBACK only, behind codex and claude (operator 2026-10-31); restored 2026-11-07 for tendcf/nix2cf's review route 3; needs the `agy` CLI on PATH (`ade-install` component `antigravity-cli`) and dispatches `gemini-4-argon-high` (the provider folds effort into the id) |
| B8. `clinepass`, `hermes` | none; hermes | Cline-pass API; the operator's assistant | never a delegation target; ClinePass is the Hermes/Dann lifeline (`substrate`, `hermes-chain`) |
| B9. `opencode-zen` (paid) | opencode | prepaid | retired until an operator top-up |

B10. Retired from the router: agy (the agy TUI; Google's plan is the antigravity provider), copilot (the CLI; Paseo's
Copilot provider replaces it, no router row), zai/zcode, alibaba/qwen, devin, crush, kiro, cline, goose, muse, aider,
venicecode, pi (2026-11-06), grok (the SuperGrok CLI, 2026-11-07). They are `never_route`, so an aiuse account or a Paseo
provider row with their name never becomes an unprofiled service. `github` and `realtime-web` remain kinds with no pool.

## C. The registry: `paseo provider ls --json` (2026-11-07)

C1. `route_agent.py` builds the service list from the curated rows plus `paseo provider ls --json` rows whose `enabled`
is `"Enabled"` and whose `status` is `available` (read with a 15 s timeout; never raises). Right after the daemon starts a
row reads `loading`: the call is repeated twice, 3 s apart, and a row still loading is treated as absent with a note on
stderr. Names pass through `[routing].aliases` (Paseo's `opencode` provider is the `opencode-go` pool) and
`never_route`. It replaced acp-run's agent table, the non-ACP headless list and Orca's roster.
C2. `paseo provider models <provider> --json` gives the provider's model ids; `route_agent.py services --check-models`
checks every suggested model against it (exit 1 when one is not listed, 2 when Paseo cannot list a provider). Not yet run
against the Mac's daemon: run it there after the merge.

## D. Quota: aiuse first, `paseo usage ls --json` second

D0. **Family matching (2026-11-12):** quota rows and snapshot windows count only for the declared `pool = [provider, family]` or primary `pool_family`. Unknown/missing family metadata cannot authorize a family-scoped route. Cursor’s `grok_bot` allowance never funds Composer or Auto: `cursor` conservatively retains the policy’s included `third_party` family (actual Composer billing-family validation remains separate) and `cursor-auto` claims `auto`. Antigravity `gemini`, `gemini_argon` and `claude_gpt` do not substitute for one another. Claude `default` supplies shared headroom; `fable` and `model_sublimits` constrain only that model, never create shared headroom. Providers with one unnamed pool retain null-family readings. Dispatch eligibility loads quota for every scoped/measured service, including Claude code; model-to-pool mapping names the explicit shared/default or included family. Native Paseo report/account IDs are not inferred as quota families; familyless reports remain unknown.

D1. `aiuse --available --json` stays the primary reading (it applies the operator's credits override, Admin API
readings and grant expiry at read time; 20 s timeout, memoised 30 s; the snapshot file is the fallback).
D2. `paseo usage ls --json` is the second source: one report per `sourceId`. A report whose `report.status` is
`available` gives its windows (`remainingPct`, else 100 − `usedPct`; `resetsAt`) and `balances` (`remaining`/`limit` as a
percentage), a window naming Fable being the Claude Fable cap; any other status (`unavailable` with a `problem`, `error`),
or a report whose `windows` or `balances` is not a list, is **unknown, never a pass**. A `balances` entry with a positive
`limit` counts as one more window of the pool, so a nearly spent balance can only make the pool read tighter (it errs safe). `icon` (inline SVG) and `loginErrors` are dropped. A report older than 25 minutes keeps only
an exhausted window, as aiuse's own `fresh` rule does.
D3. The two merge per pool by the same rule aiuse's own rows use (`_merge_pool`): the tightest known reading wins and an
unknown never loosens or replaces a reading. `route_agent.py show` and the `quota_source.pools` field of
`plan --json`/`route --json` say which source each pool came from (`aiuse`, `snapshot`, `paseo`, `aiuse+paseo`).
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
Malformed overlays fail before publishing runtime state. Legacy file readers and
the tier writer remain unchanged; no model promotion ships with this adoption.
G2. Today's table (re-check with `bin/ade-model-tiers show`):

| role | claude (rank 1) | codex (rank 2) |
| --- | --- | --- |
| frontier | `claude-fable-5-1` (`fable`) | `gpt-6-astra` |
| judgment | `claude-opus-5-5` (`opus`) | `gpt-6.1-sol` |
| everyday | `claude-sonnet-5-5` (`sonnet`) | `gpt-6.1-sol` |
| bulk | `claude-haiku-5-5` (`haiku`) | `gpt-6-luna` |

G3. Succession: `ade-model-tiers promote --vendor V --new ID --reason TEXT [--cascade N] [--dry-run]` shifts the ladder
(default cascade 2: new → frontier, old frontier → judgment; the displaced judgment goes to `[former]`). `set` changes
one role without shifting. No secrets, no network. Edit in a claimed worktree; the merge is the atomic apply.
G4. Untiered models (e.g. `gemini-4-argon`) stay as literals in `[dispatch].frontier_models`; frontier matching is the
union of that list and every spelling/alias of each tiered vendor's frontier role.

## H. Reasons kept from the earlier matrix

H1. 2026-10-18: four astra slices at once emptied codex's 5-hour window, so the frontier models are reached only through
`--kind frontier`, capped per wave, and in-flight slices reserve their estimated quota per service.
H2. 2026-10-20: the Claude weekly window ran out 2.6 days before its reset; Opus sub-agents (~53%) and a Fable lead
(~30%) were the burn. Hence `[lead]` (Opus judgment lead, Sonnet pipeline lead, never Fable: operator 2026-10-23) and
adversary rounds on omp first at that time (that client was archived 2026-11-08 and is no longer a fallback). Since 2026-11-07 (operator) Fable leads are allowed for now: the one line to flip back is
`fable_lead = true` in `[lead]` of `config/routing.toml` (false or absent restores never-a-Fable-lead).
H3. 2026-11-01: a cheap model as the daily coding driver was checked against Terminal-Bench 4.0 and this repo's own
review of Flash-written code (four BLOCKs): code stays on tier-1 models (Sonnet 5.5, GPT-6.1 Sol); cheap models only for
bulk and mechanical work a stronger model reviews.

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
2. A `frontier` slice is never silently downgraded. If the route would run on a non-frontier model (claude's Fable
   sublimit short, so `suggest_model` falls to Opus, with no other frontier pool) `adjust` prints `REFUSED`, logs a
   `refuse` event, leaves the kind's state alone and exits 3. A move to another frontier pool is allowed.
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
false` makes `adjust` plain `plan` plus rules 2 and 3 (no state, no log). Config keys and defaults: `config/routing.toml [routing.adjust]`. Known limits (adversary round 2): the tracked pool follows the wave as planned, so a wave-cap on another kind
can make a hold yield early or log a `switch` that quota did not cause; a hold is never pruned except by expiry. Not built:
effort or model-tier changes inside a pool (`docs/dynamic-model-effort.md` G4, still gated), automatic calls from other tools, and
cross-kind promotion (a kind never moves to a different kind's pools).
