# Dated quota and price overrides (design, 2026-11-21)

Status: **design, no live wiring.** Nothing here changes `config/ade.toml`, `bin/route_agent.py`, aiuse or any
installed file. Slice `dated-quota-overrides`, lead 3152a605; operator asks relayed by session 264ce667 (src-00).

Summary: (1) on the operator's Google AI Ultra 20x plan (since 2026-11-21) every agy Gemini model draws **one**
shared Gemini pool and every Claude/GPT model draws **one** shared Claude/GPT pool; no model has its own window,
so the Pools table's "Argon has its own weekly window" is out of date. (2) Dated changes go in a new tracked file,
`config/dated-changes.toml`, read by `route_agent.py` at plan time. Each entry is a half-open
`[starts_at, ends_at)` change to an allow-listed field. A quota-shaped change takes effect only on a pool that aiuse
measures as its own; a price change on a subscription pool is recorded but changes nothing. Dated *plan* prices
stay in aiuse, which already supports them. (3) Google's Claude/GPT pool is a real second source of Claude Sonnet
and Opus 5.5 and could take load off the Anthropic weekly window. Below is a proposal with its limits and risks.

## 1. Which agy models share a quota window

### 1.1 Evidence

1. **aiuse reading, 2026-11-21 14:32Z** (`aiuse --json`, CodexBar source, the 15-minute antigravity query gate in
   force): one antigravity account with four windows. They are `Gemini 5-hour` and `Gemini weekly` (pool
   `google:gemini`, hint "gemini-* models (except gemini-4-argon*)") and `Claude/GPT 5-hour` and `Claude/GPT weekly`
   (pool `google:claude_gpt`, hint "claude-* / gpt-* models"). There is **no** Argon window
   (`antigravity-quota-summary-gemini-argon-wtu-weekly`), and `aiuse --available --json` has no `google:gemini_argon`
   entry. Plan: `monthly_price 199.99` (Ultra 20x).
2. **aiuse-79's live calls** (`~/src/aiuse/docs/antigravity-pools.md`, sections "Capacity errors" and "Gemini 4
   model lineup"; durable report
   `~/.local/state/agent-reports/53cbec7a-2384-40be-8891-5461934c5e24/live-usability-test-calls-report.md`):
   1. 12:13Z, **before** the plan change (Pro): `claude-sonnet-5-5-low` and `gpt-oss-120b-medium` moved
      `Claude/GPT 5-hour` from 0 to 5.2 and weekly to 2.6. `gemini-3.8-flash` and `gemini-4-argon-low` moved
      `Gemini 5-hour` by 2.1 and a separate `Gemini 4 Argon weekly` by 0.4.
   2. 14:20Z, **after** the move to Ultra 20x: one `agy --model gemini-4-{carbon,neon,hydrogen,argon} -p=...` call
      each. The 14:32Z read moved only `Gemini 5-hour` (+1.97) and `Gemini weekly` (+0.68). Claude/GPT stayed at
      0, and CodexBar reported no per-model window. The four calls were read together, so this shows which pool
      they draw, not each model's share.
3. **Google's docs** ([models](https://antigravity.google/docs/models), [plans](https://antigravity.google/docs/plans),
   read 2026-11-21, untrusted data). The in-app usage panel has exactly two meters, "Gemini Models" and "Claude and
   GPT models", each with a 5-hour and a weekly limit. Ultra gets "the highest, most generous quota, refreshed every
   five hours" and "the highest weekly rate limits". Carbon is Ultra-only. Orchestrator "pairs two models": a
   planner (Neon by default, or Carbon, Argon, Claude Opus 5.5) and an executor (Hydrogen by default, or Claude
   Sonnet 5.5). GPT-OSS-120b and the Claude 4.6 entries "will be removed on November 30, 2026". Overage beyond the
   baseline quota uses purchased AI credits at "standard Gemini Enterprise consumption pricing" if the
   **AI Credit Overages** setting is `Always`. It is `Never` by default.
4. **Paseo** `paseo usage ls --json` (2026-11-21 14:40Z): sources `claude`, `codex`, `cursor`, `grok` only. Paseo
   reports nothing for antigravity, so aiuse (through CodexBar) is the only reading.

No quota was spent by this slice: the per-model calls above were aiuse-79's, and the lead ruled out more probes.

### 1.2 Per model (Ultra 20x, 2026-11-21)

| Model (agy `/models`) | Window(s) it draws | Evidence | Confidence |
|---|---|---|---|
| Gemini 4 Neon | `google:gemini`: Gemini 5-hour + Gemini weekly (shared) | 1.1 item 2.2 (joint read), item 1, Google's single "Gemini Models" meter | high for "shared pool, no own window"; medium for its share (joint read only) |
| Gemini 4 Carbon | same shared Gemini pool | same; Ultra-only | high / medium as Neon |
| Gemini 4 Argon | same shared Gemini pool **on Ultra**. On Pro (12:13Z the same day) it also had its own `Gemini 4 Argon weekly`, now gone | 1.1 items 1, 2.1, 2.2 | high that no Argon window is reported now; whether it comes back is unknown |
| Gemini 4 Hydrogen | same shared Gemini pool | 1.1 item 2.2 | high / medium as Neon |
| Orchestrator | no window of its own. It draws what its planner and executor draw: Gemini only with the default Neon (or Carbon, Argon) + Hydrogen; **both** pools with an Opus 5.5 planner or a Sonnet 5.5 executor | Google's Orchestrator section only; never called | medium (from the docs) |
| Gemini 3.8 Flash | shared Gemini pool | 12:13Z call on Pro moved Gemini 5-hour; aiuse `models_hint`; not called on Ultra | medium-high |
| Claude Opus 5.5 | `google:claude_gpt`: Claude/GPT 5-hour + weekly | aiuse `models_hint` (claude-*), Google's "Claude and GPT models" meter; never called | medium-high |
| Claude Sonnet 5.5 | `google:claude_gpt` | 12:13Z call moved Claude/GPT 5-hour 0 → 5.2 (on Pro) | high for the pool (made before the plan change) |
| GPT-OSS 120B (Medium) | `google:claude_gpt` | same call | high; **removed 2026-11-30** |

Caveat on all of the above: every measured reading is CodexBar's view of agy. A third-party summary
([UsageBox](https://usagebox.com/articles/google-antigravity-pricing-limits-2026), 2026-10-20, untrusted) says agy's own
`/usage` (alias `/quota`) "Model Quotas panel" shows what is left per model. Reading that panel spends no quota and
is the cheapest cross-check that Ultra has no hidden per-model cap (question 7).

Neither Google pool is Anthropic's. aiuse keeps `google:claude_gpt` apart from `anthropic:subscription`
(`antigravity-pools.md`, "Two different Claude products"). No measurement here proves that an Opus call through agy
leaves the Anthropic windows unmoved. Google's billing and aiuse's model say it does.

### 1.3 What that means for the repo today (findings, not fixed here)

1. `config/ade.toml` `antigravity-argon` (`pool = ["antigravity", "gemini_argon"]`, `window = "Gemini 4 Argon weekly"`)
   has no reading on Ultra. As a fallback with no fresh reading it fails closed. On 2026-11-21
   `route_agent.py show` printed no `antigravity-argon` line at all. Its note and Neon's still say "Google AI Pro
   plan".
2. `antigravity-neon` read `unknown (unmeasured/stale)` in the same `show`. aiuse had `google:gemini` at 98% left
   but 11 minutes old, past the 10-minute fresh limit, while the 15-minute query gate allows only 15-minute
   freshness. Worker d4a88209 owns that stale-reading fix.
3. Google's models page gives Neon "up to 512K tokens"; both rows' notes say "1M context".
4. aiuse's static `model_pool_family` (`gemini-4-argon*` → `gemini_argon`) now names a family that no longer exists.
   That is aiuse-79's to change (section 2.7).

## 2. Design: operator-entered dated changes

### 2.1 What a dated change is

A dated change is a fact the operator knows ahead of time that changes routing inputs on a set date:

1. a per-token price (Carbon $2/$10 per 1M through 2026-11-30, $4/$20 from 2026-12-01; Google lists the same
   schedule for Argon, and Gemini 3.8 Flash $0.75/$3.75 through 2026-12-31, $1.50/$7.50 from 2027-01-01, on the
   [Gemini API pricing page](https://ai.google.dev/gemini-api/docs/pricing), paid tier, read 2026-11-21);
2. a model leaving or joining a pool's menu (GPT-OSS-120b and Claude 4.6 leave agy 2026-11-30);
3. a stricter headroom floor for a period on a pool that is truly its own (a floor for a week). A dated entry only
   tightens quota limits and never loosens them;
4. an operator-approved rank change for a period (rare; gated).

What it is **not**: a quota measurement. Which windows exist, and how full they are, comes only from aiuse. A dated
entry never creates a pool, and it never raises the headroom a reading shows.

### 2.2 Where it lives

Recommendation: **a new tracked file `config/dated-changes.toml`**. Entries target `[[service]]` names from
`config/ade.toml` or aiuse `pool_id`s, and changes land by PR like every other routing input.

1. **Not aiuse.** aiuse measures quota per account and knows nothing of ADE services, kinds or ranks. Per-token
   prices and menu changes are routing inputs. Dated **plan** prices are aiuse's already: `[plans.<name>]` takes
   `starts_at`/`ends_at` and `phases` (`~/src/aiuse/src/aiuse/config.py` `_plan_entry_bounds`, `monthly_price`
   "honoring … active starts_at/ends_at phases"). A monthly-price change goes there (aiuse-79), not here.
2. **Not the quota-advisory spending profiles** (`docs/quota-advisory.md`). Those are untracked operator intent and
   "never alter ranks". A dated change that alters routing has to be reviewed, versioned config.
3. **Not a section of `config/ade.toml`.** That would work (the `ade_config` overlay and validation come free), but
   the file is already 1,400+ lines. The operator should edit one small, obvious file. A section is the fallback if
   the operator prefers one config home (question 1).
4. Machine-local overrides (`~/.config/djbclark-ade/local.toml`) are the wrong home: a price date is a fact about the
   world, not about this Mac.

### 2.3 Schema

```toml
# config/dated-changes.toml — operator-entered dated routing changes (docs/dated-quota-overrides.md)
schema = 1

[[change]]
id = "carbon-api-price-2026-12"            # unique, stable; named in plan output and refusals
target = { service = "gemini-api-carbon" } # HYPOTHETICAL row: no such [[service]] exists, so this entry is
                                            # held back until one does (an unknown target is a load error, rule 3).
                                            # A target is a [[service]] name, or { pool_id = "google:claude_gpt" }, or
                                            # { service = "...", model = "gemini-4-carbon" } for one model of a row
field = "price_per_mtok"                    # allow-listed, see 2.4
value = { input = 4.00, output = 20.00, cached_input = 0.20 }
starts_at = "2026-12-01T00:00:00Z"          # inclusive; explicit UTC offset required (Z or ±HH:MM)
# ends_at = "..."                           # exclusive; optional (open-ended)
source = "https://ai.google.dev/gemini-api/docs/pricing"
checked_at = "2026-11-21"                   # when the source was last read; drives staleness
entered_by = "djbclark 2026-11-21"
# operator_approved = "djbclark 2026-11-21" # required only for gated fields (2.4)

[[change]]
id = "agy-gpt-oss-removed"
target = { pool_id = "google:claude_gpt", model = "gpt-oss-120b" }
field = "available"
value = false
starts_at = "2026-11-30T00:00:00Z"          # "will be removed on November 30, 2026"
source = "https://antigravity.google/docs/models"
checked_at = "2026-11-21"
entered_by = "djbclark 2026-11-21"
```

Rules:

1. Times are ISO 8601 with an explicit offset; date-only and naive values are refused (the same rule as the
   spending profiles). Google writes "through November 30" with no zone. The recommended convention is the earlier
   instant for a change that makes a pool worse (a price rise, a removal): UTC midnight (`Z`), which is eight hours
   before Pacific midnight. Being a few hours early about a rise costs nothing, while being late misranks.
   Record the assumption in a comment.
2. Half-open `[starts_at, ends_at)`, the same convention as aiuse's plan phases. Two active entries for the same
   (target, field): the later `starts_at` wins. Equal `starts_at` is a load error. A price that goes up is one
   entry with no `ends_at`. An introductory price that ends is an entry with `ends_at`, and the base price comes
   from the row.
3. Unknown fields, unknown targets, duplicate ids and `starts_at >= ends_at` are load errors in the file's CI lint.
   A service target must name a `[[service]]`; a `pool_id` target must be one aiuse's `semantics.pool_id_map` lists
   (for example `google:claude_gpt`), whether or not a service claims it; `{ pool_id, model }` is legal only for
   `available`.
   At routing time a malformed entry is dropped with a warning in `show` and `plan --json` (`dated.warnings`), and
   routing goes on without it. The lint keeps a malformed entry from landing, so a calendar date can never break
   routing.

### 2.4 Allow-listed fields and where each applies

| field | applies to | effect in `route_agent.py` | gated |
|---|---|---|---|
| `available` | a service; one model of a service; or one model of a `pool_id` (`{ pool_id, model }`: a menu fact about a pool, applied to every service that claims that pool now or later, and recorded and printed while none does) | only `false` is accepted (`true` is a load error): that service (or that kind's model) is ineligible; the refusal names the change id. It can only remove a candidate, so it never overrides `never_route`, `[disabled_services]`, operator-disabled pools, Pi pool acceptance, `fallback_after`/`fallback_kinds` or any other gate | no |
| `price_per_mtok` | a service billed per token (`billing = "prepaid"`, an API key, AI credits) | recorded on the service and printed in `policy --md` and `plan --json`. **No rank effect today**: `route()` ranks on `good_at` rank, headroom pressure, pace and burn-first, with no cost term (question 2) | no (inert) |
| `floor_percent` | a `pool_id` aiuse reports as its own pool (`quota_scope = "pool"`, not a model sublimit) | **tighten only**: the effective floor is the maximum of the dated value and every existing floor (`min_headroom`, the service's `reserve_floor`, repo and kind floors, and aiuse's `floor_percent` once shipped; `pool_fits` today takes `max(min_headroom, reserve_floor)`). `[routing].plenty_min` is not a floor: it only gates `plenty_kinds` and effort, and the dated floor neither reads nor changes it. A dated value below them changes nothing; there is no loosening path | no |
| `good_at` | a service, per kind | replaces the listed kinds' ranks during the period | yes: needs `operator_approved` **and** `ends_at` (a rank change is always for a bounded period) |

**Separate-pool guard.** This is the brief's "applied only where the model truly is a separate pool", made
mechanical:

1. A quota-shaped field (`floor_percent`) applies only when its `pool_id` appears in the current aiuse reading as an
   entry of its own, and no other `[[service]]` claims the same `pool` tuple with a different model. Otherwise the
   entry is **inert**, with the reason `shared pool google:gemini` or `no reading for google:gemini_argon`. It
   never errors and never adds headroom.
2. A price on a subscription pool is **inert** with reason `subscription billing`. On Ultra, Carbon's API price
   does not change what an agy Carbon call costs. Google meters agy "by the amount of work done", not by list
   price, and Carbon shares the Gemini pool with Neon. The price matters only for the separately billed Gemini API
   key (and for AI credits, if the overage setting were `Always`).
3. `available = false` always applies: a model leaving the menu is real whatever pool it draws. It only removes;
   nothing in this file can make an ineligible service eligible.
4. Inert entries are listed once per `show` and `plan` run (`dated.inert: [{id, reason}]`), so the operator can see
   that an entry they made does nothing today and why.

### 2.5 How `route_agent.py` reads it

1. A new pure module `bin/ade_dated.py` with `load(path) -> list[Change]`, `active(changes, now) -> dict` and
   `apply(services, active, quota) -> (services, applied, inert, warnings)`. It never writes, uses no timer, and
   needs no daemon. "Reacts on the date" because every `plan` and `route` call compares the date to `now`.
2. `route()` and `plan()` call `apply()` **after** `load_snapshot()`, since the guard needs the reading. They work on
   `dataclasses.replace` copies, so `SERVICES` is never mutated, and `Choice` and `plan --json` gain
   `dated: {applied, inert, warnings}`.
3. `now` is UTC from the system clock. A new `--at ISO` flag on `plan`, `route` and `show` previews the ranking on a
   date ("what changes on 2026-12-01?") using the current quota reading, and prints `PREVIEW at …` on every line
   it affects. `--at` never dispatches: `Choice.dispatch` refuses under a preview.
4. `policy --md` prints the active entries and every entry starting in the next 14 days.
5. `bin/quota_nudge.py` (the batch reminder) adds one line per entry starting or ending in the next 3 days, so the
   lead sees an upcoming change before it happens.

### 2.6 Expiry and staleness

1. **Expiry** needs no cleanup to be correct: an entry past `ends_at` is inactive. Thirty days after `ends_at`,
   `show` warns `expired dated change <id>: delete it`. The CI lint reports that as a warning, not a failure, so CI
   never goes red just because a date passed on an unrelated PR.
2. **Staleness**: each entry has a `checked_at` date. An entry not re-checked in 30 days (`review_after_days`,
   default 30, settable per entry) still applies, but `show` and the batch reminder warn `re-verify <source>`.
   Prices and menus change without notice ("Usage limits for this service are subject to modification").
3. **Contradicted by measurement**: an optional `expect_pool_id` on a model entry (for example Carbon → `google:gemini`)
   is checked against aiuse's model-to-family map on each run. A mismatch, such as aiuse starting to report a
   `gemini_carbon` family, warns `pool changed for gemini-4-carbon: re-check <id>`. That is how a model becoming
   its own pool gets noticed.

### 2.7 Proposal for aiuse (aiuse-79 owns `~/src/aiuse`; nothing here edits it)

1. Dated plan price: the existing `[plans.gemini] phases` with `starts_at`/`ends_at` already covers a monthly-price
   change. No new aiuse schema is needed for that.
2. `model_pool_family` should follow the windows actually reported. Today `gemini-4-argon*` → `gemini_argon` is
   static. With no Argon window reported, Argon draws `gemini`, and a dispatcher that maps Argon to `gemini_argon`
   finds no pool.
3. Per-service floors `floor_percent` / `floor_basis` (already queued by aiuse-79, handoff b7e2 item 2): the ADE side
   reads them when present. A dated `floor_percent` here only tightens them.
4. Optional, later: a per-model price table is not aiuse's job unless aiuse grows the Cloud-billing collector the
   handoff mentions. The ADE file stays the one place for per-token prices.

### 2.8 Tests a build slice needs

1. Parse: a naive or date-only time is refused; so are `starts_at >= ends_at`, an unknown field, an unknown service or
   `pool_id`, a duplicate id, two entries with equal `starts_at` for one (target, field), `good_at` without
   `operator_approved` or without `ends_at`, `available = true` (or any non-false value), a `{ pool_id, model }` target
   on any field but `available`, and a `pool_id` aiuse does not list. The GPT-OSS example passes.
2. Boundaries with an injected `now`: one second before `starts_at` inactive, at `starts_at` active, at `ends_at`
   inactive; an entry across a DST change keys on its explicit offset.
3. A later `starts_at` wins over an earlier open-ended entry.
4. `available = false` removes the service from `plan` and the refusal names the id. A model-level entry removes
   only that kind's model.
5. The guard: `floor_percent` on a pool aiuse reports on its own applies; on a shared pool, on a model sublimit,
   or with no reading it is inert with the right reason; it never raises `remaining`. Tighten-only: with an existing
   floor of 15 (`min_headroom`) or a `reserve_floor`, a dated `floor_percent = 5` leaves the effective floor at the
   existing value, and `floor_percent = 25` raises it to 25 (property test over the max rule).
6. A price on a subscription service is inert. A price on a prepaid service is recorded, and `plan` output is
   byte-identical to the run without it (no cost term).
7. `--at` preview: only the applied entries differ, every affected line says PREVIEW, and dispatch refuses.
8. Staleness and expiry warnings appear in `show`, `plan --json` and the batch reminder, and the lint exits 0 on
   them.
9. The tracked `config/dated-changes.toml` passes the lint (a test like `_check_frontier_orders`).
10. Golden: with the file absent or empty, `route`, `plan` and `show` output match today's.
11. `available = false` on a service that `never_route`, `[disabled_services]`, Pi acceptance or `fallback_after`
    already excludes leaves it excluded; no entry in the file can make an excluded service eligible.

### 2.9 Build order (later slices; each needs its own yes where marked)

1. `bin/ade_dated.py` with tests 1–3 and 9–10, and the file with one entry: GPT-OSS leaving (a `{ pool_id, model }`
   target, legal for `available` under 2.3 rule 3). The Carbon price entry is held back (not committed) until a
   Carbon `[[service]]` row exists: an unknown service target is a load error.
2. Wiring into `route()` and `plan()`, `--at`, `policy --md`, the batch-reminder line (tests 4–8 and 11).
3. Only after question 2: a cost term for per-token pools.

## 3. Claude 5.5 through agy and Anthropic weekly pressure (proposal only)

**State on 2026-11-21:** `route_agent.py show` read `claude 70.0% remaining, pace 1.75×, reset in 139.2h`. codex,
cursor and opencode-go read 0%, `google:claude_gpt` 100% / 100%. No ADE service routes the Claude/GPT pool today:
`antigravity` is in `never_route`, and no `[[service]]` claims `["antigravity", "claude_gpt"]`.

**Candidate:** a curated row, provisionally `antigravity-claude`, with `pool = ["antigravity", "claude_gpt"]`,
`agent = "antigravity"`, models from `paseo provider models antigravity` (the effort is part of the id, for example
`claude-sonnet-5-5-low` as aiuse-79 called it; the Opus 5.5 ids still need to be read from that list),
`billing = "subscription"`, `access = "cli-only"`, `max_parallel = 1`. It would take `code` and `research`, ranked
a few steps behind `claude` for those kinds. As Anthropic pressure (pace 1.75×) raises claude's penalty, `route()`
would move some of those slices to it. It is **not** `judgment_tier`: the adversary, merge-gate reviews and
judgment stay on Anthropic Opus under the routing policy. It is not a frontier pool either.

**Limits:**

1. The pool size is unknown in absolute terms (aiuse sees only percents). On Pro, one Opus-high review emptied the
   5-hour window in about 35 minutes (2026-10-03, `antigravity-pools.md`). Ultra 20x is "highest", but nobody has
   measured how much higher.
2. Readings are up to 15 minutes old (the antigravity query gate) and have lagged a real exhaustion before (frozen
   percent, 2026-10-18). Until the stale-reading fix (d4a88209) lands, the row would read `unknown` most of the
   time and fail closed.
3. Burst 429s and transient capacity errors ("This model is unavailable right now", 2026-11-21 12:06Z) happen even
   with headroom.
4. GPT-OSS leaves 2026-11-30. The row should name Claude models only.

**Risks:**

1. **Harness:** the work runs in agy's agent loop, not Claude Code. The ADE's Claude Code hooks (for example
   `peer_trust_gate`, `bash_habits_gate`, `secret_read_gate`, `archived_send_gate`) do not run inside it. The PATH
   shims (`libexec/agent-bin/gh`, `paseo`, the git guard) apply only if agy's process PATH carries that directory,
   which a pilot must check. Slices given to it should be ones where that loss is acceptable: docs, research, code in
   a claimed worktree with a Claude-side review.
2. **Data path:** the code and prompts go to Google rather than Anthropic. For the operator's own repos that may be
   fine; for SIPB, client or secret-adjacent work it is the operator's call.
3. **Money:** if the agy **AI Credit Overages** setting is `Always`, work past the baseline quota bills purchased
   credits. It must be `Never` before any automatic routing (question 6).
4. **Quality drift:** the same model id through Google may differ in thinking budget, context window and tool
   behaviour. A pilot should compare a few slices before ranks are trusted.
5. **Terms:** Google's FAQ, as the UsageBox summary quotes it, says that using an Antigravity login inside
   third-party tools (Claude Code, OpenCode, …) breaks the Terms of Service and can get the account suspended. Paseo's
   antigravity provider runs Google's own `agy`, which matches `access = "cli-only"`. A Pi community OAuth route to
   the same login (the `config/ade.toml` comment on line 33) must never carry this row.

**Pilot shape (if approved):** add the row with `fallback_after = ["claude"]` first, so it is used only when the
Anthropic pool is short. After a week of reports, consider lowering it to a normal rank for `code`/`research`. Each
step is a config PR.

## 4. Operator questions

1. Is `config/dated-changes.toml` (a small tracked file) the right home, or do you want a `[[dated_change]]` section
   inside `config/ade.toml`?
2. Should `route_agent.py` get a cost term for per-token pools? Without one, a dated price is recorded and printed
   but changes no ranking anywhere. On the agy subscription, Carbon's price change has no effect either way.
3. For dates Google gives without a time zone ("through November 30"), is UTC midnight (the earlier instant, 2.3
   rule 1) the convention you want, or Pacific midnight?
4. The `antigravity-argon` row has no reading on Ultra (no Argon window). Retire it, or repoint it to the shared
   Gemini pool beside Neon? And should the "Google AI Pro" and "1M context" notes on both rows be corrected (Ultra
   20x; Google says Neon is up to 512K)?
5. Should dated `good_at` (rank) changes exist at all, and must every one carry `operator_approved`?
6. For section 3: is Google's Claude/GPT pool acceptable as a Claude Sonnet/Opus 5.5 relief pool for your own repos
   (`code`, `research`; never judgment or adversary)? And can you confirm that agy's **AI Credit Overages** setting
   is `Never`?
7. Could you open agy's `/usage` (`/quota`) Model Quotas panel once and say whether it shows anything per model
   beyond the two Gemini and Claude/GPT meters? It spends no quota. After that, should the per-model share test run
   (one call per Gemini 4 model, with a 15-minute-gated read between calls), to show whether Carbon spends more of
   the shared pool per call than Neon? aiuse-79 lists it as optional, and it would spend a little Ultra quota.

## 5. Prior art and sources

Prior art / docs checked: aiuse `docs/antigravity-pools.md`, handoff b7e2 and its live-call report (read only);
aiuse `config.py` plan phases; `docs/quota-advisory.md` spending profiles; Google's Antigravity
[models](https://antigravity.google/docs/models) and [plans](https://antigravity.google/docs/plans) pages and the
[Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) page (firecrawl, 2026-11-21); a web search for
Orchestrator quota and for Carbon's introductory price found nothing beyond Google's pages.
