# Hindsight restructure — execution plan (adjudicated 2026-08-23)

This repo is **private**; this file records operational detail that should not
go in a public repo. It still contains **no secret values** — only document
IDs and masked prefixes.

Produced by a Fable-tier adjudication of the open question in
`~/ops/site-private/memory/project_hindsight_memory_restructure.md`. All claims
below were verified against the plugin source
(`~/.hindsight/coding-agents/dist/index.js`, v0.3.4 pinned) and the live server
at `127.0.0.1:8888`. Nothing was modified during the investigation.

## Two findings that change the plan

**1. The carve-out question dissolves — the plan misattributed where sessions
land.** `gitProjectName()` falls back to `basename(cwd)`, *not* a parent walk
(index.js:65–77). Verified live: `~/.claude` → `::.claude`, `~/.hindsight` →
`::.hindsight`, `~/.hermes` (is a git repo) → `::.hermes`,
`~/.hermes/hermes-agent` → `::hermes-agent`. **None of them were ever in
`::djbclark`** — only true home-cwd (`~`) sessions are. So the drafted
blacklist never threatened config work, and `mapPathToBank` is the wrong
instrument anyway (it is longest-prefix over the whole subtree, so mapping `~`
would swallow every nested repo). The right instrument for an exact rename is
the undocumented per-bank **`bank` alias** (index.js:333).

**Ruling:** keep home-cwd enabled, aliased to `coding-agent::home-ops`. 140
sessions have cwd `~` — the largest population on the machine — and its 5 docs
already in the bank carry 137 substantive facts (bridge work, config ops). It
is heterogeneous by topic but coherent by domain: machine operations.

**2. Delay is destroying data.** Live state has already moved past the plan:
**113 documents / 2618 memory units** (plan said 77 / 1756), and the
session→cwd mapping has decayed from the plan's **94% to 79.5%** (58 of 73
conversation docs) because Claude Code garbage-collects old session JSONLs.
Every unmapped doc dates 08-15..08-19. **Attribution is lost permanently, week
by week, until this runs.**

## What is lost under the chosen topology (stated plainly)

- Sessions with cwd in `~/src`, `~/tmp`, `/tmp`, `/private/tmp`,
  `~/orca/workspaces` (the parent itself), or unresolvable: **no memory at
  all**. Fix when it matters: `cd` into the repo.
- **Cross-project auto-recall ends.** Repo A no longer sees repo B's history
  injected. Cross-project knowledge flows only through skills + CLAUDE.md and
  deliberate `hindsight-shared` recall. Intended, but a real behavior change.
- 15 historical docs (141 facts) keep no attribution — archived, not deleted.
- `::home-ops` still mixes topics internally; the relevance problem survives
  inside that one bank. If it proves noisy after a month, add
  `"coding-agent::home-ops": {"disabled": true}` — a one-line, fail-open
  reversal.

## The config

Staged, validated, and **not yet live** at
`~/.hindsight/coding-agent.json.staged`. Backup of the current live file:
`~/.hindsight/coding-agent.json.bak-2026-08-24`. Hooks re-read config on every
invocation, so applying it needs **no restart** and rollback is a `cp`.

Notable keys and why: `retainTags: ["repo:{gitProject}"]` gives every future
fact provenance (the thing whose absence made per-repo filtering impossible);
`mapPathToBank` folds Orca workspace clones into their project's bank (they
are *not* git worktrees, so without it each becomes a one-off bank) and points
`/tmp` + `/private/tmp` at the disabled `::tmp` id to kill scratchpad litter;
`banks.*.bank` aliases rename the dot-named config banks so no dotted ids
reach the server. `optInOnly`/`optInPaths` are deliberately omitted — the
blacklist fails open, per the operator's chosen philosophy.

**Residual risk:** `bank` and `mapPathToBank` are undocumented keys of a
pinned plugin version. Re-verify both in `dist/index.js` after any plugin
upgrade. (Both belong in the upstream docs correction —
see [upstream-issues.md](upstream-issues.md).)

## Leak remediation — must happen BEFORE migration

A full scan of all 113 documents, 2618 memory units, 16 mental models, 16
knowledge pages, and 801 LLM-request rows found **no full-length key anywhere
in the bank**. Stored material is 12–18 chars; OpenRouter and DeepSeek tokens
are stored ellipsis-truncated. **The full keys live in on-disk session
transcripts under `~/.claude/projects/`, not in Hindsight** — so *rotation is
the control that actually closes the incident*, not the purge. Treat the
18-char `sk-lit…` token as possibly complete.

Purge surface: 2 documents, 1 knowledge page (`kp-f57c…`, "Core concepts"),
1 mental model (`mm-a1ae…`, also "Core concepts"), orphaned observations
(document deletion does *not* cascade to observations), and 11 LLM-request
rows in Postgres (no DELETE endpoint — direct SQL).

**Active amplifier:** the "Core concepts" mental model auto-refreshes and
feeds the token back into every refresh prompt, writing a fresh LLM-log row
each time. It keeps re-spreading until cleared.

Ordering rationale: purge **before** migration, because `document-transfer`
copies content into ZIPs and new banks (multiplying the surface by N), and
provenance-tagging triggers re-consolidation that would re-derive observations
from tainted documents. Only the config backup and key rotation may precede it.

Documents cannot be text-redacted — `UpdateDocumentRequest` accepts only
`tags`, so secret-bearing docs must be deleted. Facts *are* curatable via
PATCH; observations are not (bank-wide reset only, and they rebuild).

## Migration mapping (recompute at execution time — the bank grows daily)

73 conversation docs: 58 map, 15 do not. Improved method over the plan's:
read the authoritative `cwd` field from the first record of
`~/.claude/projects/*/<session_id>.jsonl` rather than decoding the directory
name.

Targets: `::tendcf` 22 docs/363 facts · `::site-private` 12+4/160+71 ·
`::home-ops` 5/137 · `::sudo-secretspec` 5/157 · `::lungfish` 4/44 ·
`::djbclark-ade` 3+2/50 · `::KIRA` 2/45 · `::aiuse` 1/12 · `::claude-config`
1/16 · `::autonomy-research` 1/11.

**The 15 unmapped (20.5%, not the plan's 6%)** go to a dedicated archive bank
`coding-agent::unattributed-2026-08`, tagged `repo:unknown`. No cwd resolves
to that name, so it never receives live writes; it stays recallable on demand.
Do **not** guess attributions from content.

**Stays in hermes-shared** (the curated cross-project channel, which must
survive — Hermes's memory provider points at it independently): the
`source:upload` curated notes, the 4 initiative markers (they anchor `kp-`
pages; moving them orphans the links), all mental models and knowledge pages.
Delete the 17 zero-fact `survey-baseline:*` markers.

## Execution checklist

| # | Step | Who |
|---|---|---|
| 1 | Rotate OpenRouter, DeepSeek, ClinePass keys at their providers | **operator** |
| 2 | Back up live config — **done 2026-08-23** | agent |
| 3 | Purge: 2 doc DELETEs, knowledge-page DELETE, mental-model clear, bank-wide observation DELETE, 2 fact PATCHes | **operator** |
| 4 | Re-run leak scans; confirm zero non-noise hits before any export | agent |
| 5 | Write the staged config live (stops new pollution immediately; no restart) | **operator** |
| 6 | Post-purge baseline backup ZIP (secret-free by construction) | agent |
| 7 | Recompute doc→bank mapping; PATCH `repo:<name>` provenance tags | agent |
| 8 | Per bank: export ZIP by explicit `document_id` → import `on_conflict=skip` → poll operation → verify counts | agent |
| 9 | Delete transferred docs from hermes-shared (spot-check recall first) | **operator** |
| 10 | Delete the 17 `survey-baseline:*` docs | **operator** |
| 11 | `consolidate`, then refresh the cleared mental model | agent |
| 12 | `PUT` the rewritten hermes-shared mission (current one describes the retired integration) | **operator** |
| 13 | Stray-bank deletions after confirming each is dead: `test-bank`, `hermes-default-hermes`, `hermes-telegram`, `herdr-shared` | **operator** |
| 14 | Postgres LLM-request purge — **last**, since steps 11 write new rows | **operator** |
| 15 | Final leak re-scan + smoke-test three cwds (`~/src/tendcf` → `::tendcf`, `~` → `::home-ops`, `/private/tmp/...` → disabled) | agent |
| 16 | Mark the plan executed in site-private memory, recording the carve-out ruling and the `bank`-alias finding | agent |

Exact commands for every step are in the adjudication transcript; the
operator-only ones are deletions and the live-config write, held back
deliberately.

## Rollback

Config: `cp ~/.hindsight/coding-agent.json.bak-2026-08-24
~/.hindsight/coding-agent.json` — effective on the next hook call, restores
exact prior behavior. Data: the post-purge baseline ZIP re-imports with
`on_conflict=skip`; new per-repo banks are disjoint and can be deleted
cleanly. Derived state (observations, mental models, pages) rebuilds via
`consolidate` + `refresh`. **Deliberately unrecoverable:** the two purged
documents (that is the point) and attribution for the 15 archived docs.

Prefer surgical fixes over rollback if one bank misbehaves — the design fails
open by construction, so a single `disabled` or `bank` line fixes it.
