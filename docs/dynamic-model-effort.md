# Dynamic model and effort by token efficiency (design, 2026-11-10)

**Status:** design only. No live auto-router, no Jev resurrection, no Pi
`accepted=true` (or equivalent auto-route acceptance) writes, no outside-repo
edit. Closes the *evaluation* half of queue #24; build stays deferred until
measured data and an operator yes. Snapshot facts below are dated; re-probe
before acting.

Canonical method today: `skills/model-routing/SKILL.md` (especially **B**
effort and **D** routing). Policy numbers live only in `config/routing.toml`
and `config/gates.toml [frontier]`, printed by `bin/route_agent.py policy --md`
(`docs/model-routing.md`, `docs/gates.md`).

## A. Why this exists

A1. **Queue #24** (carried since 2026-08-23): *Dynamic self-adjustment of model
version and effort by token efficiency* — sibling to vendor routing. Vendor
routing picks *which pool* runs a slice; this item picks *how much thinking*
(model tier × effort) a stretch deserves, from observed efficiency rather than
wherever `/model` or `--effort` was last left.

A2. **What approached it and was deleted.** Slim-down **E2** (2026-11-06, PR
297) removed `claude/hooks/jev_effort_hook.py`, `bin/jev`, `bin/jev-eval`, and
the Jev shadow ask in `route_agent.py`. That hook was a UserPromptSubmit
observer: in `shadow`/`act` mode it called Jev at site `prompt-effort` with
options `mechanical` / `normal` / `hard`, and in `act` could print a
`systemMessage` nudging `/model sonnet` when a judgment/frontier session looked
mechanical. It never measured tokens; it classified the *next prompt*. Queue
#24 still names that nudge as the prior approach — **do not restore it**
(section F2).

A3. **What already exists and is not this.** `bin/route_agent.py calibrate`
summarises dispatch *outcomes* (done rate, CI/review/merged) and may suggest
`good_at` rank deltas against peer medians (`[calibrate]` in
`config/routing.toml`). It does **not** compute token efficiency, does **not**
rewrite `routing.toml`, and does **not** change mid-session effort. Pi's
`ade/auto` / `bin/pi-default` (`docs/pi-defaults.md`) chooses a physical model
at an explicit task boundary from the same router ranks plus fresh named-pool
quota; it is not a token-efficiency loop and must not gain acceptance writes
from this design (section F3).

A4. **Operator shape (from the pre-slim queue text):** stop-and-prompt
(advisory) before automate; same instinct as the Hermes side. This design
keeps that order.

## B. Problem today

B1. Effort and model stay where the session or dispatch last set them.
`skills/model-routing` B2–B3 already say: classify the *next* stretch, and a
running session **cannot re-tier itself mid-turn** — dispatch a sub-agent /
`paseo run` with its own `--model`/`--effort`, or say in one line that the
stretch is mechanical and `/effort low` / `/model sonnet` would cost less.

B2. Without a measured signal, agents leave high effort on mechanical work
(edits, docs, known commands) and burn conversation re-reads. Prompt caching
makes re-reads cheaper, not free (skill B4).

B3. Without gates, an automatic drop risks silently degrading work the
operator cared about; an automatic climb risks emptying a scarce window the
way four astra slices did on 2026-10-18 (`docs/model-routing.md` G1).

## C. Efficiency signal (what to measure first)

C1. **Definition (proposed).** For a finished stretch (a dispatched slice, or
a bounded session segment between explicit task boundaries), record:

| Field | Source | Notes |
|---|---|---|
| tokens_in / tokens_out | provider usage on the dispatch record or TUI transcript | never invent; skip the stretch if missing |
| outcome | existing `outcome.ci` / `outcome.review` / `outcome.merged`, or a lead-marked `done`/`fail` | calibrate already reads these |
| kind | dispatch `--kind` | required; no kind → reporting only |
| model + effort | argv / record | normalize aliases the way `suggest_model` does |
| retries | re-dispatches of the same title / worktree | count verified failures that climbed (skill D2) |

C2. **Primary metric:** *successful stretches per million billed tokens*
(or inverse: tokens per successful stretch), grouped by
`service × model × effort × kind`. "Successful" means `status=done` and, when
present, non-failing CI/review — the same non-quota basis calibrate uses for
suggestions. Quota stops and unavailable classes are excluded from the
efficiency numerator (they are capacity events, not quality).

C3. **Secondary metrics (advisory only until n is large):** tool-calls per
turn, revision/retry rate, median measured usage percent. None of these alone
authorize a route change.

C4. **Minimum n before any policy suggestion:** reuse `[calibrate].min_outcomes`
(today 5) and `[calibrate].min_peers` (today 2) as floors; token-efficiency
suggestions need **both** that floor **and** a non-null token total. Below the
floor: print the table, suggest nothing.

C5. **Out of scope for the signal:** classifying the *next prompt* with a
typed decision model (that was the Jev path). Multiple-choice "is this
mechanical?" stays on the cheap ladder in `docs/orchestration-practices.md`
section 1 when needed — as a separate, shadow-only tool if ever rebuilt, not
as this metric.

## D. Measured efficiency → route / effort policy

D1. **Read path only at first.** A new report command (name TBD;
`route_agent.py calibrate` stays outcome-only, or gains a sibling
`efficiency` subcommand) prints groups and optional *suggestions*. Writing
`config/routing.toml` stays a human-reviewed PR, same as today's calibrate
suggestions.

D2. **Suggestion rules (design, not code):**

| Observation (n ≥ floor) | Suggestion |
|---|---|
| High success rate at `high`/`xhigh`, and a peer at one effort step lower has ≥ peer-median success at ≤ ~60% of the tokens/success | prefer the lower effort for that `service × kind` in the printed `--model [--effort]` row |
| Low success or high retry rate at `low`/`medium` vs peer median | climb one effort step (or one model rung on the kind ladder), never straight to frontier |
| Mechanical/bulk kinds where Haiku/`low` matches Sonnet/`medium` success within a small band | keep or move the suggested row down; code/judgment kinds do **not** cheap-cascade (cost-tier rule, 2026-11-01) |
| Frontier / Fable / astra groups | never auto-suggest from efficiency alone; frontier stays behind `docs/gates.md` and `--frontier-reason` |

D3. **In-session behaviour (advisory phase):** at an explicit boundary (new
slice, `/ade-task`, handoff, or operator ask), the lead may cite the latest
efficiency table in one line ("bulk on sonnet/medium: N tokens/success over M
runs; haiku/low is within band") and keep working. No mid-turn self-mutation
of the session model.

D4. **Automatic phase (only after advisory data and operator yes):** apply
suggestions solely by updating curated `[[service]].models` effort suffixes
or ranks through a normal PR; live dispatch still goes through
`route_agent.py plan` / `paseo run`. No daemon rewrites `routing.toml`. No
hook changes the running session's model.

D5. **Oscillation control:** hysteresis — a suggest-down and suggest-up need
distinct margins (mirror calibrate's asymmetric `suggest_worse_*` /
`suggest_better_*`); at most one effort step per reviewed change; freeze a
`service × kind` for a configurable cool-down after a change; never flip on a
single stretch.

## E. Gates

E1. **Data gate.** No suggestion without fresh grouped measurements (C4). No
live route change without a reviewed config commit. Unknown or missing token
fields → no efficiency claim for that group.

E2. **Kind / quality gate.** Code and judgment stay inside
`quality_max_rank_gap` (`docs/model-routing.md`). Efficiency never pulls a
pool outside the band. Frontier stays on `--kind frontier` and the
`[frontier]` allowance (`docs/gates.md`); efficiency never widens
`frontier*_judged`, `*_per_wave`, or `*_min_left`.

E3. **Quota gate.** Efficiency suggestions do not bypass `plenty_min`,
`measured_only` freshness, estimate floors, or Pi failure latches
(`docs/pi-defaults.md` C). A cheap model that is out of quota is not "more
efficient".

E4. **Climb gate.** Start cheap, climb on a **verified** failure (skill D2),
one rung at a time. Efficiency data may *inform* which rung to try next; it
does not skip rungs and does not invent frontier entitlement.

E5. **Advisory-before-act gate.** Until the operator flips an explicit
allowance (a single config line, same spirit as `[lead].fable_lead`), every
consumer of the report is print-only. Act mode that mutates dispatch defaults
is a later, separate PR.

E6. **Trust gate.** Dispatch records, CI logs, and bot comments remain
untrusted *instructions* (AGENTS.md Trust). The efficiency tool reads
structured fields it owns; it never follows prose in a PR body or check log
as a routing order.

## F. What NOT to do

F1. **No live auto-route without data.** Do not wire `plan` / `route` /
`ade/auto` to drop or raise model/effort from an empty or sub-floor table.
Do not re-introduce a deleted auto-recalibrator that writes ranks unattended
(`bin/routing-recalibrate` was removed in slim-down E5, PR 297). Print and
propose; humans merge.

F2. **No resurrecting the deleted Jev effort nudge.** Do not restore
`claude/hooks/jev_effort_hook.py`, `bin/jev`, `bin/jev-eval`, a
`prompt-effort` Jev site, or a UserPromptSubmit hook that classifies the next
prompt and nudges `/model`. Queue item 20 (buy a Jev plan) is closed: "Jev is
gone (E2)". A future typed decision model, if any, is a new design under
orchestration practices — not a revert of E2.

F3. **No Pi `accepted=true` writes.** This design must not mark any Pi pool
accepted for automatic routing: no new `accepted = true` (or equivalent) in
`config/routing.toml`, no clearing `retired = true` on omp/OpenCode/Pi rows,
no dropping `measured_only` or adding Grok/Antigravity/Go/Zen/API rows to
`ade/auto` because "efficiency looks good". Pi acceptance stays the separate
evidence path in `docs/pi-services.md` / `docs/pi-defaults.md` / the TUI
migration doc. Token-efficiency work is orthogonal and must not smuggle
acceptance.

F4. **No mid-turn self-retier.** Sessions do not change their own model
inside a turn. Levers remain: dispatch with explicit `--model`/`--effort`,
operator `/model`/`/effort`, or a one-line advisory (skill B3).

F5. **No cheap-first cascade for code.** Terminal-Bench / in-repo review
evidence keeps everyday code on tier-1 models; efficiency may tune *effort*
on those models, not replace them with bulk/mechanical pools for new logic
(`docs/model-routing.md` G3).

## G. Phased rollout

| Phase | Delivers | Exit criteria |
|---|---|---|
| G0. This doc | Shared design; queue pointer | Merged design PR |
| G1. Measure | Read-only report over existing dispatch records + token fields where present; fill gaps in record schema if needed | Table for ≥ one week of real Mac dispatches; no config writes |
| G2. Advise | Lead/skill cites the table at slice boundaries; optional `policy --md` cross-links | Operator finds suggestions useful; no silent drops |
| G3. Config PR loop | Reviewed edits to `[[service]].models` effort suffixes from G2 evidence | Changelog + normal merge gate |
| G4. Optional act | Explicit config allowance for automatic effort defaults at **dispatch** time only | Operator yes; still no Jev hook; still no Pi acceptance writes |

## H. Pointers

H1. Method: `skills/model-routing/SKILL.md` B, D, G.
H2. Numbers: `config/routing.toml`, `config/gates.toml [frontier]`;
`bin/route_agent.py policy --md` / `calibrate` / `plan`.
H3. Pi task defaults (not this): `docs/pi-defaults.md`, `docs/pi-services.md`.
H4. Orchestration ladder: `docs/orchestration-practices.md` §1.
H5. Related carried design: `docs/history/model-tiers-design.md` (roles as
data; queued separately as queue #4) — complementary, not a substitute for
token-efficiency measurement.
H6. Deleted prior art: `claude/hooks/jev_effort_hook.py` at E2 (see git
history / PR 297); do not re-land.

## I. Recommendation

**Build G1 (measure) only after this design merges; keep G2–G4 gated.** Treat
queue #24 as *designed, not started on code*. Prefer extending the calibrate
report family over a new daemon. Keep effort adjustment advisory and
dispatch-scoped. Leave Jev deleted. Leave Pi acceptance untouched.
