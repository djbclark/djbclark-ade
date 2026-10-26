# Model tiers as data: design (2026-10-26, design only, nothing built)

Operator ruling (djbclark, 2026-10-26, verbatim): "We should actually optimize use of Fable if an agent feels it
would actually be a significantly better option than Opus. Also we should write things so that when the next model
that supercedes fable comes out, our gates shift, so that the new frontier model is like current fable and current
fable becomes treated like current opus. We should do the same type of thing for the popularly acclaimed 2nd best AI
coding vendor, at this time that is codex astra as the 2nd top frontier model."

Problem: every gate that rations a scarce model names that model. `claude-fable-5-1`, `claude-opus-5-5`, `fable`,
`opus`, `gpt-6-astra` and `gpt-6.1-sol` appear as literals, regexes, substrings and prose in about 40 places
(section A). When a model supersedes Fable, the gates keep rationing Fable 5.1 and let the new model through
ungated, or block it as unknown in one place and wave it through in another. Decision: one versioned file,
`config/model-tiers.toml`, maps **roles** to concrete ids per vendor. Every gate reads roles. A `promote` operation
shifts a vendor's ladder in one reviewed commit. The Fable allowance the `away` profile needs (section C) is written
against roles from the first slice. The literal names stay in slice 1 and move to the roles file in slice 3 (section D).

Base: origin/master 3350bd5 plus origin/feat/gates-profile (the `away` profile design: `config/gates.toml`,
`bin/ade_gates.py`, `bin/gate-profile`, `docs/gates.md`), both read on 2026-10-26. Line numbers below are master's
unless a branch is named.

## A. Inventory: every hard-coded model name or tier rule

The kinds: **(a) tier role**, a rule about a rank of model (frontier, judgment, everyday, bulk) even when it is
spelled with a name. **(b) concrete id**, a literal model id or alias. **(c) vendor/pool/window name**, an aiuse
pool family, window label or quota key the code matches. **(d) prose**, text an agent reads as policy. One site
can be two kinds; it is listed under its main kind, with the other kind noted.

### A1. (a) Tier roles (24 sites)

| # | where | what it encodes |
| --- | --- | --- |
| A1.1 | `config/routing.toml:54` | `frontier_per_wave = 1`: at most one `frontier` slice per pool per wave |
| A1.2 | `config/routing.toml:62` | `fable_min_left = 10.0`: below this much of the Fable sublimit, claude frontier falls back to Opus (a frontier-1 floor) |
| A1.3 | `config/routing.toml:113` | `[dispatch] fable_gated_efforts = ["xhigh","max"]`: frontier-1 at xhigh/max needs `ACP_OPERATOR_APPROVED=fable-xhigh` |
| A1.4 | `config/routing.toml:116` | `[dispatch] frontier_models = ["gpt-6-astra","fable"]`: substring list; also (b) |
| A1.5 | `config/routing.toml:157-160` | `[lead] model = "opus"`, `pipeline_model = "sonnet"`: lead = judgment, pipeline lead = everyday; also (b) |
| A1.6 | `config/routing.toml:144` | `[dispatch.estimate_floor] "codex:frontier" = 60.0`: frontier-2 slice reserves 60% of the codex 5-hour window |
| A1.7 | `config/routing.toml:185,229` | `good_at.frontier`: codex 1, claude 2. Lower ranks first, so `frontier` prefers astra over Fable today (scarcity, not quality; see C7) |
| A1.8 | `config/routing.toml:165` | `[escalation] ladder = [... "judgment","frontier"]`: kinds, not models; unchanged by this design |
| A1.9 | `bin/route_agent.py:1268` | `GOVERNOR_JUDGMENT_MODEL = "anthropic/claude-opus-5-5 --effort high"` (omp judgment while the governor holds claude); also (b) |
| A1.10 | `bin/route_agent.py:1334-1348` | `suggest_model`: claude `frontier` becomes `"opus --effort high"` while `sublimits["fable"] < FABLE_MIN_LEFT`; also (b), (c) |
| A1.11 | `bin/route_agent.py:1507-1519` | the plan enforces `FRONTIER_PER_WAVE` per pool |
| A1.12 | `bin/route_agent.py:235` | `judgment`/`frontier` only on a `judgment_tier` service |
| A1.13 | `bin/acp-dispatch:700-704` | `is_frontier_model`: substring match on `FRONTIER_MODELS` |
| A1.14 | `bin/acp-dispatch:4093-4094` | a frontier model needs `--kind frontier` |
| A1.15 | `bin/acp-dispatch:4044-4049` | `"fable" in a.model` at a gated effort needs `fable-xhigh`; also (b) |
| A1.16 | `bin/acp-dispatch:4106-4110` | `frontier` is advise-only unless `frontier-exec` |
| A1.17 | `bin/claude-fleet-governor:41-48,564,576-581` | Fable becomes Opus at any level (no lead on frontier-1). Opus/Fable become Sonnet at tight/critical. A Fable original is restored as Opus |
| A1.18 | `bin/claude-quota-guard:96` | `watch_fable = 15.0` (frontier-1 sublimit watch trigger; mirrored in `config/gates.toml [quota_guard]` on feat/gates-profile) |
| A1.19 | `bin/claude-quota-guard:122-145` | `_advice`: "no Fable or Opus Agent-tool sub-agents", "a lead on Opus or Fable hands off ... Sonnet 5.5 high"; also (d) |
| A1.20 | `claude/hooks/context_size_nudge.py:220-241` | `_successor_target`: Fable to Opus; tight: Fable/Opus to Sonnet; critical: Fable to Opus (differs from the governor, which takes critical to Sonnet: R7) |
| A1.21 | `claude/hooks/frontier_agent_gate.py:17,27,30` | `FRONTIER_AGENTS = {"fable-deep": "Fable"}`, `"fable" in model`, approval key `fable-deep` |
| A1.22 | `claude/hooks/jev_effort_hook.py:103` | `("opus","fable")` substring = judgment or frontier session |
| A1.23 | `bin/watch:445-446` | refuses a route whose model contains `fable` |
| A1.24 | `bin/failover.py:104,212-216` | `DENY` includes `opus`, `fable` (judgment and above denied as failover); the claude route is `haiku`/`sonnet` only |

Further role-bearing defaults, same kind: `bin/claude-settings-env:44` `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` (sub-agent
default = everyday); `tools/acp-run/acp-run:2972` headless fallback `model = a.model or "sonnet"`;
`skills/dialogue/scripts/dialogue.py:225-254` the `DIALOGUE_FABLE_MODEL` seat override; agent frontmatter
`claude/agents/adversary.md:4` (`opus`), `backend.md:4` and `ux.md:4` (`sonnet`), `fable-deep.md:5` (`fable`).

### A2. (b) Concrete ids (11 sites)

| # | where | literal |
| --- | --- | --- |
| A2.1 | `bin/claude-fleet-governor:94-96` | `OPUS = "claude-opus-5-5"`, `SONNET = "claude-sonnet-5-5"`, `HANDOFF_SUCCESSOR = "omp/anthropic/claude-sonnet-5-5"` (also passed to `bin/paseo-set-model`) |
| A2.2 | `bin/claude-fleet-governor:106-107` | regexes `claude-fable[...]`, `claude-(opus|fable)[...]` (family patterns) |
| A2.3 | `bin/claude-quota-guard:117-119` | `_SELF_SLASH ... claude/claude-sonnet-5-5`, `_ADVERSARY ... anthropic/claude-opus-5-5` |
| A2.4 | `claude/hooks/context_size_nudge.py:74-76` | `FABLE_MODEL = "claude-fable-5-1"`, `SUCCESSOR_OPUS`, `SUCCESSOR_SONNET` |
| A2.5 | `config/routing.toml:195,224,260,284,325,386,416,432` | `[[service]] models`: claude aliases (`opus`/`fable`/`sonnet`), omp `anthropic/claude-*-5-5`, codex `gpt-6-astra`/`gpt-6.1-sol`/`gpt-6-luna`, agy `claude-opus-5-5`, copilot `claude-sonnet-5.5` (dotted), cursor `claude-sonnet-5-5`/`claude-haiku-5-5`, opencode-go `opencode-go/gpt-6-luna` |
| A2.6 | `bin/failover.py:212-214,221` | `models=("haiku","sonnet")`, `model_allow` regex, `native_models` `claude-haiku-5-5`/`claude-sonnet-5-5`, agy `claude-sonnet-5-5` |
| A2.7 | `bin/claude-cost-mix:44-46` | price table keyed by id (`claude-fable-5-1` 10.0/0.025 ...); reporting only |
| A2.8 | `claude/agents/adversary.md:9` | comment: `acp-dispatch omp --model anthropic/claude-opus-5-5 ...` |
| A2.9 | `claude/hooks/frontier_agent_gate.py:41-44` | the ask message names `opus` and `gpt-6.1-sol` |
| A2.10 | `tools/acp-run/acp-run:2181-2214` | alias resolution: `fable` resolves to the newest `claude-fable-*` (claude ACP lists both `fable` and `claude-fable-5-1[1m]`) |
| A2.11 | tests | `tests/test_claude_quota_guard.py` (fixtures `fable=`), `tests/test_claude_fleet_governor.py`, `claude/hooks/handoff-tools/tests/test_context_size_nudge.py:414-531`, `tests/test_acp_dispatch.py:191` (`"fable"`/`"astra"` in model) |

### A3. (c) Vendor, pool and window names (7 sites)

| # | where | name |
| --- | --- | --- |
| A3.1 | `bin/route_agent.py:656-658,812-816` | `SUBLIMIT_FAMILIES = ("fable",)`; a `quota_scope == "model_sublimit"` window with `max_share_of_parent_percent` is stored in `sublimits[family]` |
| A3.2 | `bin/route_agent.py:1297,1345` | `"fable_weekly"` short name; `sublimits.get("fable")` |
| A3.3 | `bin/claude-fleet-governor:98,243,450` | `FABLE_KIND = "fable_weekly"`; the label test `startswith("Claude Code weekly") and "Fable" in label` |
| A3.4 | `bin/claude-quota-guard:270-282,352-361` | Fable window = `"fable" in label` or `pool_family == "fable"` or `quota_scope == "model_sublimit"`; a summary row is relabelled `"Claude Code weekly \u2014 Fable"` |
| A3.5 | `aiuse schema` 1.3 (read 2026-10-26) | Claude rows: `pool_family` `default` (shared) and `fable` (cap), `quota_scope` `shared`/`model_sublimit`, `shared_pool_family: "default"`, `max_share_of_parent_percent: 50`; aiuse drops the `fable` pool when the cap is exhausted |
| A3.6 | `config/routing.toml:137-144` | estimate-floor keys `"codex:frontier"`, `"codex:judgment"`, `"codex"` |
| A3.7 | codex in aiuse | no model sublimit: astra, sol and luna all draw the one account's 5-hour and weekly windows. Frontier-2 has no Fable-like pool (R4) |

### A4. (d) Prose (10 groups)

| # | where | size |
| --- | --- | --- |
| A4.1 | `skills/model-routing/SKILL.md:580-735` *Routing policy* items 1a-1d, 2, 4d, 4e (the one copy, AGENTS.md order 7) | 49 lines name Fable/Opus/astra |
| A4.2 | `docs/model-routing.md` | 44 lines |
| A4.3 | `bin/route_agent.py:58-74` module doc; `:562-563` `policy_markdown` text ("not on Fable ... `fable-deep`") | |
| A4.4 | `config/routing.toml` comments `:5-10,111-112,154-156,184-195,228-260` | |
| A4.5 | `claude/agents/fable-deep.md` (name, description, body); `adversary.md:8-14` comment (the `model: "sonnet"` override at tight/critical) | |
| A4.6 | `skills/bigteam/SKILL.md` (21), `skills/dialogue/**` (~60), `skills/research/SKILL.md` (10), `skills/effort-routing/SKILL.md` (7), `skills/handoff/SKILL.md` (4), `skills/helm/auto.md` (4) | |
| A4.7 | `docs/queue.md` (30); dated handoffs and reviews under `docs/handoffs/`, `docs/software-factory-reviews/` | history: never rewritten |
| A4.8 | `~/.agents/AGENTS.md` (= `~/CLAUDE.md`, `~/.claude/CLAUDE.md`) item 32: "Judgment is Opus `high`; codex `gpt-6-astra` and Fable `high` only via `frontier` ... claude codes on Sonnet 5.5, never Fable"; item 30's Fable cache note lives in memory | Opus 5.5+ edits only: wording proposed in C8 |
| A4.9 | `djbclark-ade/AGENTS.md` order 7: route per the SKILL.md policy (no model names) | no change needed |
| A4.10 | `bin/claude-quota-guard` `_advice` text, `frontier_agent_gate.py` ask text (also A1.19, A2.9) | |

Count: 24 (a), 11 (b), 7 (c), 10 (d) groups.

## B. `config/model-tiers.toml`

### B1. Roles

Four roles per vendor, from most to least scarce: `frontier`, `judgment`, `everyday`, `bulk`. A role names a model.
Effort stays with the caller (`routing.toml` rows keep `--effort`). So codex's `judgment` and `everyday` can both
be `gpt-6.1-sol`, at `high` and `medium`. The words `frontier-1` and `frontier-2` are **ranks of vendors**, not
roles. `frontier-1` is the `frontier` role of the rank-1 vendor (Fable 5.1 today), `frontier-2` that of the rank-2
vendor (codex gpt-6-astra today). Gates written for "frontier-1" follow the rank, so a rank swap moves them with no
code change.

### B2. Shape (draft; values as of 2026-10-26)

```toml
# Model tiers: roles to concrete models, per vendor (docs/model-tiers-design.md).
# Edited only by `bin/model-tiers` (promote/set/rank/undo) in a claimed workspace, merged by PR.
[meta]
schema = 1
updated = "2026-10-26"

# Vendor rank by acclaimed coding quality, best first. Data, not code: swap with
# `model-tiers rank --order codex,claude --reason TEXT`, which records date and reason here.
[rank]
order = ["claude", "codex"]
since = "2026-10-26"
reason = "djbclark 2026-10-26: Fable is the top frontier coding model; codex astra is the acclaimed second"

[vendor.claude]
# A model string belongs to this vendor when it matches; an UNKNOWN id that matches is treated as `frontier`
# (the strictest role) by every gate until `model-tiers set/promote` names it (fail closed).
family = '^(anthropic/|claude/|omp/anthropic/)?(claude-[a-z]+-[0-9][\w.\[\]-]*|opus|sonnet|haiku|fable)$'
roles = { frontier = "claude-fable-5-1", judgment = "claude-opus-5-5", everyday = "claude-sonnet-5-5", bulk = "claude-haiku-5-5" }
# How each route spells an id. `{id}` canonical, `{alias}` the model's alias. Per-model exceptions live under [model."..."].
spell = { claude = "{alias}", claude-code = "{alias}", paseo = "{id}", omp = "anthropic/{id}", agy = "{id}", cursor = "{id}", copilot = "{id_dotted}" }
cascade = 2          # roles `promote` shifts by default: frontier -> judgment only (B4)
# Which aiuse window carries a role's own cap (C5). A role with no entry is bounded by the shared windows only.
pools = { frontier = { pool_family = "fable", quota_scope = "model_sublimit", label_has = "Fable" } }

[vendor.codex]
family = '^(opencode-go/)?gpt-[0-9][\w.-]*$'
roles = { frontier = "gpt-6-astra", judgment = "gpt-6.1-sol", everyday = "gpt-6.1-sol", bulk = "gpt-6-luna" }
spell = { codex = "{id}", opencode-go = "opencode-go/{id}" }
cascade = 2
pools = {}           # no model sublimit: every role draws the account's 5-hour and weekly windows (A3.7)

[model."claude-fable-5-1"]
vendor = "claude"
alias = "fable"
display = "Fable 5.1"
[model."claude-opus-5-5"]
vendor = "claude"
alias = "opus"
display = "Opus 5.5"
[model."claude-sonnet-5-5"]
vendor = "claude"
alias = "sonnet"
display = "Sonnet 5.5"
spellings = { copilot = "claude-sonnet-5.5" }
[model."claude-haiku-5-5"]
vendor = "claude"
alias = "haiku"
display = "Haiku 5.5"
[model."gpt-6-astra"]
vendor = "codex"
display = "GPT-6 Astra"
[model."gpt-6.1-sol"]
vendor = "codex"
display = "GPT-6.1 Sol"
[model."gpt-6-luna"]
vendor = "codex"
display = "GPT-6 Luna"

# Ids that held a role and no longer do: still classified (by `last_role`), so a session left on one is
# recognised, never mistaken for an unknown frontier model. `promote` appends here.
[former]
# "claude-fable-5" = { vendor = "claude", last_role = "frontier", until = "2026-10-1x" }
```

Only vendors whose models gates ration are tiered (claude, codex). Every other `routing.toml` row (minimax, glm,
gemini, grok, the opencode-go open-weight models) is **untiered**: those models match no `family` pattern, and their
rules stay as they are.

### B3. The loader and the role API (`bin/model_tiers.py`)

| call | returns |
| --- | --- |
| `load(path=None)` | parsed, validated tiers. A missing or unparsable file falls back to `DEFAULTS`, a copy of today's table in the module (the same fail-safe as `ade_gates`: tests fail when file and defaults drift); logged once to stderr |
| `resolve(vendor, role, route=None)` | the spelling for that route, e.g. `resolve("claude","judgment","omp") == "anthropic/claude-opus-5-5"` |
| `classify(model) -> (vendor, role, status)` | strips `[1m]`-style suffixes, `--effort ...` and route prefixes. `status` is `current`, `former` (role = `last_role`) or `unknown`. Unknown inside a vendor's `family` gives role `frontier`. No family match gives `(None, None, "untiered")` |
| `frontier_tokens()` | every spelling and alias of each vendor's `frontier` role. Replaces `[dispatch].frontier_models` |
| `rank(vendor)` | 1-based rank; `ranked_frontier(n)` gives `(vendor, id)` |
| `pool(vendor, role)` | the `pools` entry or `None` |
| `display(vendor, role)` | "Fable 5.1", used by every advice and ask text |

CLI `bin/model-tiers`: `show [--json]`, `resolve`, `classify MODEL`, `validate`, `promote`, `set`, `rank`, `undo`,
`render [--check]`, `log`. Exit codes: 0 ok, 2 usage, 3 validation failed, 4 dry-run diff non-empty under `--check`.

What reads roles (after slice 3, section D):

| consumer | today | after |
| --- | --- | --- |
| `route_agent.py` `suggest_model`, `GOVERNOR_JUDGMENT_MODEL`, `SUBLIMIT_FAMILIES` | literals | `resolve("claude","judgment","omp")`; the claude frontier fallback = `resolve(v,"judgment")`; sublimit families from `pools` |
| `routing.toml [[service]] models` | literal ids | placeholders `"@judgment --effort high"`, resolved per service via `spell[service]`. A literal id is still allowed for untiered models |
| `routing.toml [dispatch].frontier_models`, `[lead]` | literals | removed (from `frontier_tokens()`); `[lead] model = "@judgment"`, `pipeline_model = "@everyday"` |
| `acp-dispatch` `is_frontier_model`, the xhigh gate | substring | `classify(model).role == "frontier"`; the xhigh gate keyed on the claude frontier role (approval keyword renamed `frontier-xhigh`, `fable-xhigh` kept for this one migration as noted in D) |
| `claude-fleet-governor` `OPUS`/`SONNET`/regexes, `HANDOFF_SUCCESSOR` | literals | `classify`: frontier to `resolve(claude, judgment, paseo)` at any level; frontier/judgment/unknown-in-family to `everyday` at tight/critical; successor `omp/` + `resolve(claude, everyday, omp)` |
| `claude-quota-guard` Fable window, `_advice` | label/family literal | window matched by `pools.frontier` of the claude vendor; advice text built from `display()` (C4) |
| `context_size_nudge.py`, `jev_effort_hook.py`, `bin/watch`, `failover.py` | literals | `classify`; failover `DENY` = roles `frontier`, `judgment` of tiered vendors plus its non-model denials |
| `frontier_agent_gate.py` | `fable-deep`, `"fable" in model` | agents whose frontmatter says `# tier: frontier`, plus `classify(model).role == "frontier"` |
| `claude-settings-env`, `acp-run` fallback, agent frontmatter | `sonnet`/`opus`/`fable` | written by `model-tiers render` from the declared tier (B5) |
| SKILL.md / docs/model-routing.md "today" table | prose | a generated block `<!-- model-tiers:start --> ... <!-- model-tiers:end -->` (B5) |

### B4. Succession: `promote`, `set`, `rank`, `undo`

`model-tiers promote --vendor claude --new claude-fable-6 [--alias fable] [--display "Fable 6"] [--cascade N]
[--pool-family F] --reason TEXT [--dry-run]`

1. **Run it in a claimed workspace** (AGENTS.md order 9). It edits `config/model-tiers.toml` and rerenders the
   generated regions (B5). Nothing live reads the workspace, so the shift takes effect when the commit merges to
   master and the shared checkout fast-forwards. That merge is the atomic step, and it goes through the normal
   adversary + PR path.
2. **The shift.** `new` becomes `frontier`. The old `frontier` becomes `judgment`. With `cascade` 3 or 4 the old
   judgment becomes everyday and the old everyday becomes bulk. A role pushed off the end, or past `cascade`, moves
   to `[former]` with its `last_role` and the date. Default `cascade = 2` (both vendors) is the operator's sentence:
   "the new frontier model is like current fable and current fable becomes treated like current opus". With claude
   cascade 2, Opus 5.5 leaves judgment and goes to `[former]`; it is not made the everyday coder (OPEN 2). A new
   everyday or bulk release (a Sonnet 6) is `model-tiers set --vendor claude --role everyday --id ... --reason`,
   not a promote. Duplicates shift by role: codex after promoting `gpt-7` is frontier gpt-7, judgment gpt-6-astra,
   everyday gpt-6.1-sol, bulk gpt-6-luna.
3. **Validation (exit 3 on failure, before any write).** (i) The new id is in the vendor's live model list:
   `acp-run claude --info` / `acp-run codex --info` (claude: the id or `[1m]` variant, plus the alias resolving to
   it through the newest-version rule at `acp-run:2211`). `--no-probe` skips this offline and records
   `probe = "skipped"` in the audit line. (ii) The `family` pattern matches the new id; if not, promote stops and
   asks for `--family`. (iii) Every role that has a `pools` entry still maps to a live aiuse window. With
   `aiuse --available --json` (fallback: the newest snapshot) a window must carry the role's `pool_family` and
   `quota_scope`, and its `models_hint` must name the role's model. A frontier model with no matching sublimit
   needs `--pool-family F` (the renamed family) or `--no-pool` (state that the new frontier has no cap). Without
   either, the pool entry is written `unverified = true`, and gates treat that role's cap as exhausted (C5).
   (iv) `render --check` succeeds. (v) A literal scan finds no copy of an outgoing id outside `[former]`, history
   docs and the allowlist (`tests/test_model_tiers_literals.py`, slice 4). This is the check that catches a gate
   left on a retired id.
4. **Dry run** prints a unified diff of `model-tiers.toml` and every rendered file, plus a "gates that change"
   table: each consumer in B3 with its before/after resolution (e.g. `governor: Fable->Opus move now targets
   claude-fable-6 -> claude-fable-5-1`).
5. **Audit and ping.** A non-dry run appends a JSON line (`ts`, `op`, `vendor`, `before`, `after`, `reason`,
   `probe`, `pool`, `set_by`, workspace HEAD) to `~/.local/state/ade/model-tiers.log` and writes the same `before`
   and `after` into the commit message it prepares (the caller commits with `git-commit-own`). It sends one
   `hermes-ping "djbclark-ade: model-tiers promote claude: claude-fable-6 -> frontier, Fable 5.1 -> judgment
   (merge to apply)"`.
6. **`undo`** applies the inverse of the newest audit line whose `after` equals the current file. It refuses if the
   file changed since (then `git revert` the promote commit). It audits and pings like promote. A merged promote
   is undone by merging the undo commit or by `git revert` of the promote commit; both are one revertable commit.
7. **`rank --order codex,claude --reason TEXT`** rewrites `[rank]` (with `since`). It swaps which vendor's frontier
   gets the frontier-1 gate keys and which gets frontier-2 (C2). Validation, dry-run, audit and ping are the same.

**Effect when a merged promote runs (no code edit):** the routing rows for `@frontier`/`@judgment`, dispatch's
frontier test, the xhigh gate, the governor's moves and restore target, the quota guard's frontier cap window
and advice names, the context nudge's successor, the agent gate, failover's denials, the jev hook, `bin/watch`,
`claude-settings-env`, agent frontmatter, and the generated "today" tables in SKILL.md and docs/model-routing.md.
**Not automatic:** prose outside generated blocks (the literal scan warns), `claude-cost-mix` prices (a new id
without a price is reported as `unpriced`, never guessed), measured estimate history (`[dispatch.estimate_floor]`
stays keyed by role class, `codex:frontier`, so it moves with the role, but the new model's first slices have no
history), and `~/.agents/AGENTS.md` item 32 if it still names models (C8 removes the names).

### B5. Rendering what cannot read TOML at run time

Claude Code reads agent frontmatter `model:` itself, and `CLAUDE_CODE_SUBAGENT_MODEL` is an env var. So each
agent file declares its tier in a YAML comment on the model line, `model: opus  # tier: judgment`, and
`model-tiers render` rewrites the value from `resolve("claude", tier, "claude-code")`. `claude-settings-env`'s
default comes from `resolve("claude","everyday","claude-code")` at run time (it is Python). Docs get a generated
block, the table in B6. `render --check` runs in CI. Aliases: Claude Code's `fable`/`opus` aliases follow the
newest model of that family, so a same-family release (Fable 5.2) is picked up by `model: fable` before anyone
runs promote. After a promote, the judgment role may be a former frontier model in the same family
(`claude-fable-5-1` as judgment while `fable` means Fable 6). The alias then no longer distinguishes the roles,
and the render must write the full id. Whether Claude Code agent frontmatter and the Agent tool's `model`
parameter accept a full id is **unverified** (R2; slice 4 proves it first).

### B6. The tier table (2026-10-26)

| role | claude (rank 1) | codex (rank 2) |
| --- | --- | --- |
| frontier | `claude-fable-5-1` (`fable`) = **frontier-1** | `gpt-6-astra` = **frontier-2** |
| judgment | `claude-opus-5-5` (`opus`) | `gpt-6.1-sol` (at `high`) |
| everyday | `claude-sonnet-5-5` (`sonnet`) | `gpt-6.1-sol` (at `medium`) |
| bulk | `claude-haiku-5-5` (`haiku`) | `gpt-6-luna` |
| own cap | frontier: aiuse `pool_family = "fable"`, `model_sublimit`, at most 50% of the shared weekly | none |

## C. The frontier policy under tiers (baseline and `away`)

### C1. Baseline (today's rule, written in roles)

Frontier-1 and frontier-2 are reached only through `acp-dispatch --kind frontier` (advise unless
`frontier-exec`). The work must really need a frontier model (SKILL.md item 1b). The cap is `frontier_per_wave`
per pool. Frontier-1 needs at least `frontier1_min_left` (10) of its cap, otherwise route_agent suggests claude
judgment. Frontier-1 at xhigh/max needs operator approval. An Agent-tool sub-agent on frontier-1 asks the operator
(`frontier_agent_gate.py`). No lead session runs frontier-1 (the governor moves it to judgment). Nothing new at
baseline.

### C2. `away` (operator absent; quota should be spent)

An agent **may** use frontier-1 when it judges frontier-1 *significantly better* than claude judgment for this
piece of work. It must state why in one line, and every one of these still holds:

1. **Reason.** acp-dispatch: `--frontier-reason "TEXT"` (one line, 10-200 chars, stored in the dispatch record and
   the slice's log). Agent tool: a prompt line `frontier-reason: TEXT`. A missing or empty reason gets the
   baseline treatment.
2. **Cap.** Frontier slices per wave stay capped (`frontier1_per_wave`). Agent-tool frontier-1 calls are capped
   per America/New_York day machine-wide (`frontier1_agent_calls_per_day`), counted from
   `~/.local/state/frontier-gate/agent-calls.jsonl`.
3. **Cap floor.** The frontier-1 cap must have at least `frontier1_min_left` left. The quota guard's level must be
   `ok` or `watch` with a reason other than the frontier-1 cap. At `tight` or `critical` the baseline rules apply,
   because those levels are the stop signal in every profile.
4. **Unchanged under away:** advise-only (no `frontier-exec`; judgment work is read-and-advise anyway), the
   xhigh/max approval, and no lead session on frontier-1 (the governor's frontier-to-judgment move runs at every
   level; a Fable lead burned about 30% of a week's quota, `context_size_nudge.py:72-73`).

Frontier-2 (astra) is treated the same way: `--frontier-reason`, its own `frontier2_per_wave`. Its floor is
headroom on the codex binding window (`frontier2_min_left`, default equal to the 60% astra estimate floor) because
codex has no sublimit (R4). The Agent tool cannot reach codex models, so frontier-2 has no Agent-tool cap.

### C3. Gate keys (`config/gates.toml`, a third gate `[frontier]`)

The keys fit the existing floors schema (numeric, `loosen` lower/higher, `bound`). `bin/ade_gates.load_gates`
is generic over `gate`, so the new consumers call `load_gates("frontier", now, DEFAULTS)` and the loader does not
change. A judged use is allowed only when its key is above 0, so baseline 0 is exactly today's rule.

```toml
[frontier]                         # read by acp-dispatch, route_agent.py, frontier_agent_gate.py, claude-quota-guard
frontier1_judged = 0               # 1 = an agent may pick frontier-1 on its own judgment (C2); 0 = `frontier` kind as today
frontier2_judged = 0
frontier1_per_wave = 1             # moves from routing.toml frontier_per_wave (claude pool)
frontier2_per_wave = 1             # (codex pool)
frontier1_agent_calls_per_day = 0  # Agent-tool frontier-1 calls allowed without asking, per NY day (0: always ask)
frontier1_min_left = 10.0          # percent of the frontier-1 cap; moves from routing.toml fable_min_left
frontier2_min_left = 60.0          # percent left on the codex binding window

[floors.frontier]
frontier1_judged = { loosen = "higher", bound = 1 }
frontier2_judged = { loosen = "higher", bound = 1 }
frontier1_per_wave = { loosen = "higher", bound = 2 }
frontier2_per_wave = { loosen = "higher", bound = 1 }     # astra's 5-hour window holds about one hard slice (2026-10-18)
frontier1_agent_calls_per_day = { loosen = "higher", bound = 6 }
frontier1_min_left = { loosen = "lower", bound = 10.0 }   # a profile may not lower the cap floor
frontier2_min_left = { loosen = "lower", bound = 40.0 }

[profiles.away.frontier]           # DRAFT: operator confirms at activation
frontier1_judged = 1
frontier2_judged = 1
frontier1_per_wave = 2
frontier1_agent_calls_per_day = 4
```

`watch_fable` (`[quota_guard]`, feat/gates-profile) is renamed `watch_frontier1` in slice 3, with the baseline and
code default moved in the same commit. Rank-based names mean a `rank` swap re-targets these keys with no edit.
`gate-profile set away` already validates every gate in the file, so the floors also refuse a looser frontier
value under any other profile.

### C4. Quota-guard advice, role-based (exact draft text)

Placeholders render from tiers: `{F1}` = `display(rank-1 vendor, frontier)` ("Fable 5.1"), `{J}` = claude judgment
("Opus 5.5"), `{E}` = claude everyday ("Sonnet 5.5"), `{E_id}` = `resolve(claude, everyday, claude)`, `{ADV}` = the
adversary command with `resolve(claude, judgment, omp)`, `{until}` = the profile end in New York time, `{min}`,
`{left}` = frontier-1 cap floor and current value, `{n}` = `frontier1_agent_calls_per_day`.

**Baseline** (rendered, today's meaning unchanged):

| level | text |
| --- | --- |
| watch | `Claude quota watch: no {F1} (frontier) or {J} (judgment) Agent-tool sub-agents. Adversary rounds via {ADV}. Route code/bulk slices to other pools.` |
| tight | `Claude quota tight: no {F1} or {J} Agent-tool sub-agents. Adversary rounds via {ADV}. Route code/bulk slices to other pools. A lead on {J} or {F1} hands off now and continues on {E} high: self-slash --finish --successor claude/{E_id} --thinking high (Paseo; herdr/Orca: handoff then relaunch on {E}). No acp-dispatch claude slices.` |
| critical | today's critical text with the same substitutions |

**Away** (`frontier1_judged = 1` in the active profile):

| level | text |
| --- | --- |
| ok (`quota_nudge.py` daily line) | `[gates] away profile active until {until}: {F1} (frontier) is allowed where you judge it significantly better than {J}; give the reason in one line (acp-dispatch --kind frontier --frontier-reason "..."; Agent tool: a "frontier-reason: ..." prompt line), at most {n} Agent-tool calls today. gate-profile clear restores normal routing.` |
| watch (weekly) | `Claude quota watch (away until {until}): {J} Agent-tool sub-agents as needed; {F1} only where significantly better than {J}, with a one-line frontier-reason, at most {n} Agent-tool calls today. Adversary rounds via {ADV}. Route code/bulk slices to other pools.` |
| watch (frontier-1 cap, `{left}` < `watch_frontier1`) | `Claude quota watch (away until {until}): the {F1} cap has {left}% left, so no {F1}: use {J}. Adversary rounds via {ADV}.` |
| tight, critical | baseline text, unchanged: away loosens when tight starts (gates.toml), not what tight means |

The guard already records the reason window (`weekly`/`five_hour`/`fable`) for its level. The advice picks the row
from that reason, and `fable` becomes `frontier1` in slice 3.

### C5. Pool names fail closed

The `pools` entry is the only place a pool family or window label is named. Each gate that needs a role's cap
looks the window up through it: route_agent `sublimits`, the guard's frontier window, the governor's `FABLE_KIND`.
When the window cannot be found, the outcome depends on the data source:

| case | outcome |
| --- | --- |
| aiuse dropped the family (exhausted cap, the documented behaviour) and the snapshot has it at 0 | today's behaviour: 0% left |
| neither aiuse nor the snapshot has a window matching the entry, or the entry is `unverified` | the cap counts as **0% left**: route_agent suggests judgment for claude frontier, judged use is off, the guard reports `watch` with reason `frontier1-pool-missing` and advice `aiuse lists no {pool_family} window for {F1}: run model-tiers validate` (pinged once per episode) |
| a model `classify` cannot place inside a tiered family | role `frontier` everywhere (needs `--kind frontier`, the governor moves it off a lead, the agent gate asks) |

So a renamed pool or a new frontier model with a differently named cap shows up as a visible watch and the
strictest routing. It never silently removes the cap.

### C6. `frontier_agent_gate.py` under tiers

Frontier sub-agents = agents whose frontmatter says `# tier: frontier` plus any `model` that `classify` places at
`frontier` (unknown in-family ids included). Decision order:

1. `FRONTIER_GATE_OFF=1`, or `ACP_OPERATOR_APPROVED` contains `frontier-agent`: allow, as today. The keyword
   `fable-deep` is accepted for one migration and its removal is listed in slice 3.
2. Load the `[frontier]` gate through `ade_gates`. If `frontier1_judged == 0` or `frontier1_agent_calls_per_day ==
   0`: ask (baseline).
3. Read `quota-guard.json`. Missing, older than 30 min, level `tight`/`critical`, or a frontier-1-cap reason: ask.
   Frontier-1 cap below `frontier1_min_left`: ask.
4. No `frontier-reason:` line (10-200 chars) in the prompt: ask, and the ask text names the away allowance and the
   line format.
5. Count today's `allowed-judged` lines in the log. At the cap: ask. Below it: allow, logging `decision:
   "allowed-judged"`, the reason, the profile name and its `until`.

Steps 2-5 never allow on an error; a parse error asks. The hook's existing fail-open for any other exception
stays (unchanged scope; R8). "Ask" while the operator is away blocks that sub-agent, which is the safe outcome for
a scarce model.

### C7. Conflicts with standing rules, and minimal wording for djbclark

1. **`~/.agents/AGENTS.md` item 32** names models and allows frontier "only via `frontier`". Under away, the Agent
   tool reaches frontier-1 without the `frontier` kind, so the item conflicts. Proposed replacement for its first
   sentence (only Opus 5.5+ edits the file, same length; the session that applies it re-checks the 14,000-byte cap):
   "**Routing policy: minimise cost, maximise code quality, not tokens. Model names come from
   `djbclark-ade/config/model-tiers.toml`: judgment is claude's judgment tier (Opus 5.5) at `high`; each
   vendor's frontier tier (Fable 5.1, codex gpt-6-astra) only via `frontier`, or, while a gate profile allows it,
   where an agent judges it significantly better than judgment and says why in one line; codex otherwise: ample
   quota and top router rank (2026-10-25); frontier at `xhigh` almost never; claude codes on its everyday tier
   (Sonnet 5.5), never frontier**". The rest of the item is unchanged.
2. **djbclark-ade `AGENTS.md` order 7** names no model. Optional clause: "model names: `config/model-tiers.toml`".
3. **SKILL.md *Routing policy* items 1b, 1d, 2, 4d, 4e** say "Fable 5.1", "gpt-6-astra", "Opus 5.5". Rewrite in
   roles with the generated "today" table (slice 5). Add item 1e for the away allowance (slice 1).
4. **`good_at.frontier` prefers codex (1) over claude (2)** (A1.7) while the operator ranks Fable first. Vendor rank
   (quality) and routing preference (scarcity) are different axes, so this design does **not** let rank reorder
   `good_at`. The operator decides whether away should prefer frontier-1 (OPEN 4).
5. **"Fable is scarce" (frontier_agent_gate.py docstring, fable-deep "invoke rarely")** stays true at baseline.

## D. Migration plan

Order: slice 1 is what the away profile needs and lands first, stacked on `feat/gates-profile` (or right after it
merges). Slices 2-5 can wait until after the absence. Each slice is one PR with an adversary round and a
CHANGELOG line.

| slice | files | tests | adversary focus | overlaps in-flight |
| --- | --- | --- | --- | --- |
| **S1 away frontier allowance** (literal names kept; texts built from module constants, which S3 replaces) | `config/gates.toml` (`[frontier]`, floors, `[profiles.away.frontier]`), `bin/acp-dispatch` (`--frontier-reason`, per-wave key from the gate), `bin/route_agent.py` (`frontier1_per_wave`/`frontier1_min_left` from the gate; `routing.toml` keys removed in the same commit), `bin/claude-quota-guard` `_advice` (away rows, C4), `claude/hooks/quota_nudge.py` (daily line), `claude/hooks/frontier_agent_gate.py` (C6), `docs/gates.md`, SKILL.md item 1e, `config/routing.toml` | `tests/test_frontier_agent_gate.py` (each step of C6, cap boundary, stale guard, no reason, expired profile), `tests/test_claude_quota_guard.py` (advice per level x profile), `tests/test_gates.py` (floors refuse looser), `tests/test_acp_dispatch.py` (reason required when judged; recorded) | self-approval by writing a reason (bounded by cap and floors); the cap counter spoofed by log edits; a stale or missing guard state must ask; profile expiry mid-wave; `FRONTIER_GATE_OFF` | **feat/gates-profile** (gates.toml, guard, quota_nudge, docs/gates.md, SKILL.md, tests/conftest.py): stack on it; **fix/relay-codex-submit** (SKILL.md, a different section) |
| **S2 tiers file + loader** | `config/model-tiers.toml`, `bin/model_tiers.py`, `bin/model-tiers` (`show/resolve/classify/validate`), docs (this file becomes `docs/model-tiers.md`), README roster | `tests/test_model_tiers.py`: classify (suffixes, prefixes, former, unknown-in-family gives frontier, untiered), resolve spellings, DEFAULTS==file drift, bad file falls back | the fail-closed paths; regex `family` too broad or too narrow (catastrophic backtracking, `anthropic/` prefix) | none (new files); CHANGELOG/README conflict trivially with relay and prior-art branches |
| **S3a routing reads roles** | `bin/route_agent.py`, `config/routing.toml` (`@role` placeholders, drop `frontier_models`, `[lead]`), `bin/acp-dispatch` (classify, `frontier-xhigh`), `tests/test_route_agent*.py`, `tests/test_acp_dispatch.py` | the policy output is identical before and after (`route_agent.py policy --json` golden diff) | an `@role` that fails to resolve must refuse, never route an empty model | after S1 (same files) |
| **S3b gates read roles** | `bin/claude-fleet-governor`, `bin/claude-quota-guard` (pool map, `watch_frontier1`), `claude/hooks/context_size_nudge.py` (R7 decided there), `claude/hooks/frontier_agent_gate.py` (tier frontmatter, drop `fable-deep` key) | governor/guard/nudge suites re-pointed at a tiers fixture; a promoted fixture shows every move retargeted | a regex replaced by classify must still catch `[1m]` and dated suffixes; a missing pool gives watch, never ok | feat/gates-profile (same files): after it merges |
| **S3c remaining readers** | `bin/failover.py`, `bin/watch`, `claude/hooks/jev_effort_hook.py`, `bin/claude-settings-env`, `tools/acp-run/acp-run` (fallback default), `skills/dialogue/scripts/dialogue.py` | existing suites | failover must still deny judgment and frontier of every tiered vendor | none known |
| **S4 succession ops** | `bin/model-tiers` `promote/set/rank/undo/render/log`, frontmatter `# tier:` comments in `claude/agents/*.md`, generated blocks in SKILL.md and docs/model-routing.md, `tests/test_model_tiers_literals.py` (literal scan with allowlist) | promote/undo round trip on a temp copy; dry-run diff; probe stubbed; pool validation cases; render idempotent | promote writing outside the workspace; audit line injection (reason text); ping argv quoting | SKILL.md (generated block only) |
| **S5 prose** | SKILL.md *Routing policy* to roles, docs/model-routing.md, bigteam/dialogue/research/effort-routing skills, fable-deep rename to `frontier-deep` with every caller migrated (OPEN 3), `~/.agents/AGENTS.md` item 32 via an Opus 5.5 dispatch after approval | `render --check`, literal scan | none (docs); the item-32 edit follows the condense-proof rule | fix/relay-codex-submit, feat/gates-profile (SKILL.md) |

Rollback: S1 is ended immediately by `gate-profile clear` (baseline = 0 allowances) or by reverting its PR; every
key it adds has a baseline equal to today's behaviour. S2 adds no consumer. S3 slices fall back to `DEFAULTS` (today's ids) when
the file is unreadable, and each is a single revertable PR whose golden-policy test proves no behaviour change. S4
`undo` or `git revert` of a promote commit.

## E. Risks

| # | risk | mitigation |
| --- | --- | --- |
| R1 | a promote leaves a gate on a retired id (a literal missed in S3, a rendered file not rerun) | the literal scan (S4) fails CI on any outgoing id outside `[former]`/history; `render --check` in CI; promote's validation step (v); unknown in-family ids classify as frontier, so the failure mode is "too strict", never "ungated" |
| R2 | aliases: `fable` follows the newest Fable before promote, and after promote a former frontier in the same family needs a full id where Claude Code may accept only aliases | S4 first proves whether frontmatter and the Agent tool accept full ids. If they do not, `render` refuses a tier whose alias would resolve to a different role's model, and `promote`'s dry run says so before anything is written: the agent files keep their last good value and the operator chooses (a full-id route through `acp-dispatch claude --model <id>`, or a different cascade) |
| R3 | a vendor renames models or families (a successor not called `claude-fable-*`) | `family` pattern + fail-closed classify; promote stops when the new id misses `family`; `acp-run --info` probe |
| R4 | quota pools do not exist for a role; codex has no Fable-like cap | `pools` is per role and optional; frontier-2's floor is binding-window headroom (`frontier2_min_left`) plus the 60% estimate floor; a declared-but-missing pool counts as exhausted (C5) |
| R5 | a rank swap changes which vendor gets the Agent-tool gate | only claude models reach the Agent tool; the gate keys on "claude vendor's frontier role" with the caps of claude's rank (C3); the dry run of `rank` lists it |
| R6 | briefs, skills and memory quote model names in prose and go stale | generated "today" blocks; S5 rewrite to roles; the literal scan warns on policy docs; history docs never rewritten |
| R7 | two gates disagree today: at `critical` the governor moves Fable to Sonnet while `context_size_nudge` hands Fable to Opus | S3b makes both read one role rule (critical: frontier and judgment go to everyday); decided there with a test |
| R8 | `frontier_agent_gate.py` fails open on an unexpected exception, which under away means an uncapped frontier-1 call | the judged path never allows on error (C6); widening the fail-closed beyond that is out of scope, noted for S3b's adversary |
| R9 | self-approval: any agent can write a `frontier-reason:` line | by design (operator ruling); bounded by the per-day and per-wave caps, the cap floor and the guard level; reasons logged for review after the absence |
| R10 | promote during the absence | none planned; promote needs a PR merge, which the lead does not do unattended for tiers (OPEN 5) |

## F. DECIDED / OPEN

DECIDED:

1. Roles are `frontier`, `judgment`, `everyday`, `bulk` per vendor. `frontier-1`/`frontier-2` are vendor ranks,
   stored as data in `[rank]`.
2. One file, `config/model-tiers.toml`, changed only by a reviewed commit. Its effect starts at merge, and code
   `DEFAULTS` are the fail-safe.
3. Unknown in-family model = `frontier` (strictest). A declared role pool missing from aiuse = cap exhausted and a
   visible `watch`.
4. `promote` default cascade 2 (new to frontier, frontier to judgment); deeper shifts are explicit.
5. Away allowance keys go in a new `[frontier]` gate in `config/gates.toml`, within the existing floors schema, so
   the loader does not change. Baseline 0 = today's rule.
6. Away leaves unchanged: advise-only frontier, the xhigh approval, no lead on frontier-1, and tight/critical texts.
7. Vendor rank does not reorder `good_at` routing preference.
8. S1 ships first, stacked on feat/gates-profile, with literal names; roles land after the absence.

OPEN (only djbclark can answer):

1. Away values: frontier-1 slices per wave 2 (or 1)? Agent-tool frontier-1 calls per day 4? Frontier-2 per wave
   stays 1?
2. On a claude promote, does Opus 5.5 leave the ladder (cascade 2, the reading of your sentence), or move to
   everyday so the old everyday drops to bulk (cascade 4)?
3. Rename `fable-deep` to `frontier-deep` (every caller migrated, S5), or keep the name?
4. Under away, should `frontier` kind prefer Fable over astra (today astra ranks first for scarcity)?
5. Approve the item-32 wording in C7.1 (an Opus 5.5 session applies it)?
6. Should the xhigh/max approval also cover frontier-2 (astra at xhigh/ultra), which is ungated today?
