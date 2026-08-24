# AGENTS.md — djbclark-ade

You are an AI agent working on djbclark's machine. This repo is the
operating guide for running AI agents as **graphs** here — read this file,
then follow the pointers. Everything in it applies to any agent (Claude
Code, Codex, OpenCode, Crush, Cline, Copilot, Grok, Cursor, …), not just
the one that wrote it.

## What this repo is

A reference architecture plus live operating knowledge for two altitudes
of agent-graph work, verified by real runs on 2026-08-23:

- **Micro graph** — Claude Code dynamic workflows: in-process subagent
  fan-out coordinated by plain JavaScript, zero-token orchestration.
- **Macro graph** — Orca orchestration: a task DAG across separate agent
  CLI processes in their own git worktrees, CLI-agnostic lifecycle
  (`worker_done`, ask/reply, escalation).

Start with [README.md](README.md) for the architecture and how the
altitudes compose (a macro node can run a micro graph as its body).

## Read before acting

- [docs/model-routing.md](docs/model-routing.md) — **which AI/service to
  use for what work**: every service on this machine mapped to its
  TUI/CLI, monthly-subscription vs prepaid vs free, chronic-waste pools
  worth burning, per-service effort levers. Numbers are dated snapshots —
  always re-probe (`aiuse --json`, ~1 min, JSON starts after two preamble
  lines; `cswap list` for Claude windows).
- [docs/orca-integration.md](docs/orca-integration.md) — runnable macro-
  graph command sequences plus hard-won live-run lessons (stall false
  deaths, rejected-late `worker_done` semantics, the retry recipe, the
  ack loop). The authoritative command reference is served by the binary:
  `orca skills get orchestration` — never trust a cached copy.
- [docs/queue.md](docs/queue.md) — work the operator has explicitly
  queued but not started, plus outstanding blockers. Check it before
  proposing new work; add to it rather than starting something big
  unasked.
- [docs/ai-memory-landscape.md](docs/ai-memory-landscape.md) — the six
  levels of AI memory this machine is building toward, their source, live
  per-area status, and how they map onto the published CoALA/7-type
  taxonomies and the 2026 cross-vendor portability work. The plans
  themselves live in the ops repos; this is the orientation layer.
- [docs/upstream-issues.md](docs/upstream-issues.md) — filed-nowhere-yet
  bug drafts for third-party projects (graft statusline, hindsight config
  docs), written from problems verified here.
- [docs/mcp-servers.md](docs/mcp-servers.md) — the MCP server roster for
  Claude Code sessions on this machine: what each server is, where it's
  configured, the Hermes Agent MCP registration, the Beeper re-auth recipe,
  and why this repo's graft statusline says "not built" (cosmetic).
  Re-probe with `claude mcp list`.
- [.claude/workflows/graph-audit.js](.claude/workflows/graph-audit.js) —
  runnable micro-graph example (schema-validated fan-out → adversarial
  verify → synthesize). Claude Code sessions in this repo can invoke it
  as `/graph-audit`. It has audited this repo itself, twice; its
  confirmed findings are fixed.
- [skills/model-routing/SKILL.md](skills/model-routing/SKILL.md) —
  canonical source of the machine-wide model-routing skill (Claude Code's
  live copy is deployed at `~/.claude/skills/model-routing/`).
- [skills/gmail-search/SKILL.md](skills/gmail-search/SKILL.md) —
  canonical source of the gmail-search skill: the Hermes-built local
  Gmail FTS5 index (~192k messages, ~100ms queries), searched via CLI,
  not MCP (live copy at `~/.claude/skills/gmail-search/`).
- [vendor/README.md](vendor/README.md) — sidecar index of everything this
  repo references that lives elsewhere on the system: vendored copies
  (prepaid gate scripts, a dated Orca orchestration guide snapshot) and
  pointers to things with their own homes (aiuse, cswap, the Orca fork,
  hooks, the LiteLLM proxy).

## Standing orders (operator-issued; they bind every agent here)

1. **Continuous operation — never stop work because context is large.**
   Externalize heavy work (subagents, background workflows, Orca
   workers), keep state on disk continuously, and let the harness's
   compaction bridge context windows. A handoff document is an artifact
   you write *without stopping*, reserved for work where the conversation
   itself is the state.
2. **Commit AND push at opportune moments.** After each coherent unit of
   work. On a sweep, also catch artifacts living outside any repo that
   should be tracked. Never push secrets or ignored local state.
3. **Never idle on a long-running process — start parallel work by
   default.** When something is backgrounded (a backfill, a build, a
   fleet dispatch, a subagent), immediately pick up the next
   parallelizable task rather than waiting or asking whether to. Choose
   work that cannot contend with what is running — different files,
   different databases, different repos — and say what you started. The
   only reasons not to: the next step genuinely depends on the running
   result, or the parallel work would touch the same resource.
4. **Verify against the artifact, not a proxy — and retract loudly.**
   Every wrong claim made here on 2026-08-23 came from trusting a proxy:
   grepping output for a substring and calling it a status check (the
   "graft not built" retraction), reading a bank's *name* instead of an
   agent's provider config (deleting a live bank), and repeating an
   auto-generated page that said PRs awaited merge weeks after they
   merged. Before asserting a fact, check the thing itself — exit codes
   and structured output over string matching, config files over
   filenames, `gh pr view` over memory. When you do get one wrong, say so
   plainly and correct the record in the same breath; a retraction
   written down is worth more than the original claim.
5. **Number every set of options, hierarchically and uniquely.** When
   you offer choices, next steps, or findings the operator might act on
   selectively, number them — and if a single reply contains more than
   one list, **never restart at 1**. Number the sets and use dotted
   labels: the first set is `1.1`, `1.2`, …, the second `2.1`, `2.2`, …
   Two bare `3.`s in one message is ambiguous and wastes a round trip
   asking which was meant. Keep labels stable within a conversation — if
   you re-present a list, silently renumbering invalidates any
   instruction already given against the old numbers. This binds every
   agent here.
6. **Flag best-practice deviations.** If a request or existing config
   conflicts with current best practices, say so and propose the
   improvement — but don't relitigate decisions the operator made
   knowingly.
7. **Routing discipline**: free and chronically-unused pools first for
   bulk work; claude/codex for judgment (tier inside them); **never**
   bulk-route to clinepass (infrastructure lifeline); the prepaid tier is
   retired until an explicit operator top-up.

## Machine context you should know

- **Orca is the fleet registry**: ~25 TUI agents preconfigured (see
  docs/model-routing.md, "Orca is the fleet registry"); macro-graph
  dispatch reaches any enabled one via
  `orca orchestration worker-start --agent <name>`.
- The broader ops-suite conventions (worktree/PR/release flow, memory
  rules) live in `~/CLAUDE.md` and the site-private repo — they govern
  `~/ops` and are not duplicated here. This repo itself is an ordinary
  repo: commit to master, push to `djbclark/djbclark-ade`.
- Facts in this repo carry snapshot dates. Probes beat memory; when you
  verify something has changed, update the doc in the same breath
  (standing order 2).

<!-- graft:start -->
## Graft — repo context graph

This repo is indexed in `graft/`: small linked markdown nodes that explain each
system and carry exact file:line spans, kept in sync with the code through git.

For ANY task here — understanding how something works, finding where code lives,
or scoping a change — get context from the graph before grepping or opening
source files. Re-ask freely (it's cheap) and reuse literal identifiers you
already have (symbol, error string, file name) as the query. New to this repo?
Run `graft map` first — a token-budgeted orientation (dir clusters, hubs,
hotspots), no LLM, no key.

- Run `graft ask "<your question>" --source` → ranked nodes with the relevant
  code spans inlined (each hit's ≤8-line crux by default; `--full` for whole
  definitions when the crux isn't enough). Match the tool to the task shape:
  for understanding or editing, the top node IS the answer — cite its
  `covers:` file:line spans and edit straight from `--source`. For
  exhaustive tasks ("every occurrence / every caller of this pattern"), ranked
  results are top-N, not complete — run `graft grep "<literal>"` instead
  (exhaustive over indexed files, grouped by enclosing symbol), falling back
  to raw `grep -rn` only for unindexed files.
- `graft skeleton <file>` → every definition's signature + span, ~10× cheaper
  than reading the file; use it to skim an API surface.
- `graft callers <symbol>` gives precomputed, exact edges — who calls this.
  Add `--direction out` for what it calls, or `--depth N` to walk
  transitively for the full blast radius. For structural questions, skip
  ranking and use this directly.
- Or browse: `graft/INDEX.md` lists every node; follow the links.
- Monorepos and folders of multiple repos rank fairly across sub-projects —
  hits carry `[scope/]` labels naming which one they're from. Narrow with
  `graft ask "<task>" --in <scope>/` once you know where you're working.

If a returned span is truncated ("+N more lines"), open the file at that exact
range before finalizing. Only open source files when a node genuinely lacks a
needed detail, and then at the exact file:line the node points to — never
re-read whole files.

After big code changes, refresh the graph with `graft build` (deterministic,
no API key, $0).
<!-- graft:end -->
