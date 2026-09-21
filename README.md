# djbclark-ade

Reference architecture for running Claude as a **graph of agents**, at two
altitudes, using tools already installed on this machine. Prompted by
[Graph Engineering with Claude](https://x.com/0xCodez/article/2079141496981184512)
(@0xCodez, 2026-07-20), which is a tutorial for Claude Code's built-in
*dynamic workflows* feature — not a new product. This repo adds the second
altitude the article doesn't cover: [Orca](https://github.com/stablyai/orca)
(forked to [djbclark/orca](https://github.com/djbclark/orca)), which
orchestrates whole agent *processes* rather than in-process subagents.

## Two graphs, two altitudes

**Micro graph — Claude Code dynamic workflows (in-process).**
Inside a single Claude Code session, the `Workflow` tool runs a plain
JavaScript orchestration script that spawns subagents: `agent()` for one
node, `parallel()`/`pipeline()` to fan work out, JSON-schema contracts on
every node's output, `phase()` for progress grouping. Coordination costs
zero model tokens because it's code, not a conversation turn. Ceiling: one
Claude Code process, one model account, one machine.

See [`.claude/workflows/graph-audit.js`](.claude/workflows/graph-audit.js)
for a working example — fan out N review dimensions, verify each finding
adversarially, synthesize a report. Saved workflows surface as skills by
name in any Claude Code session in this repo (verified 2026-08-23), so
invoke it as `/graph-audit`, optionally with args like
`{"target": "src/"}` — or just ask for "the graph-audit workflow on
<path>".

**Macro graph — Orca orchestration (cross-process).**
Orca's `orchestration` layer is a task DAG across *separate* agent CLI
processes — Codex, Claude Code, OpenCode, Cursor, Gemini, Grok, droid — each
in its own git worktree, possibly on another machine (`--on <environment>`).
A coordinator creates a Run, creates Tasks with `--deps`, dispatches each to
a worker with `worker-start --agent <cli> --worktree ...`, and waits on
`worker_done`/`escalation` via a blocking `check --wait`. This is the same
node/edge vocabulary as the article — a Task is a node, a dependency is an
edge — but the nodes are whole agent sessions with their own filesystems,
not subagents inside one context window. Ceiling: however many worktrees
and machines you're willing to run concurrently; monitorable from the Orca
mobile app.

Full command reference: `orca skills get orchestration` (version-matched to
the running Orca build, currently 1.4.188 — don't rely on a cached copy of
this doc, the binary is the source of truth).

## How they compose

A macro-graph node (an Orca Task dispatched to a Claude Code worker) can
itself run a micro-graph (a dynamic workflow) as its job body. Concretely:
create a Run, create one Task per service whose spec says "run the
graph-audit workflow here", `worker-start` each Task with `--agent claude`
in its own worktree, then block on `check --wait` until every worker
reports `worker_done`. The runnable command sequence lives only in
[`docs/orca-integration.md`](docs/orca-integration.md) — one copy, so this
README can't drift from it (a drift the first graph-audit run actually
caught); the binary-served `orca skills get orchestration` remains the
authority over both.

Each worker is a full Claude Code session that fans out *its own* subagents
in-process via `Workflow` — free coordination inside each node, paid-for
(a real process, a real worktree) coordination between nodes. Use the macro
graph when nodes need process/filesystem isolation, a different CLI or
model account per node, cross-machine placement, or human-in-the-loop
monitoring from the phone. Use the micro graph for everything inside one
node's boundary — it's cheaper and has no worktree/process overhead.

**Heterogeneous fleets are a requirement here, not an option.** The micro
graph is Claude-only by construction — Workflow subagents are always
Claude. The macro graph is the heterogeneity layer: Orca's orchestration
lifecycle (`worker_done`, `ask`/`reply`, escalation, heartbeats) is
CLI-agnostic, so one DAG can dispatch Tasks to claude, codex, opencode,
grok, or cursor workers (all installed on this machine) and they
interoperate through the same structured mailbox instead of sharing a
context window. Group addresses (`@claude`, `@codex`, `@opencode`, …)
exist for genuine fan-out messages. Route each Task to whichever agent is
best or cheapest for it — the article's model-tiering move (step 12),
generalized across vendors.

**A third altitude already exists on this machine and isn't duplicated
here:** `ralph-tui` + beads runs a continuous, scheduled controller loop
over the `ops-djbclark` suite (stayturgid / site-djbclark / site-private /
Shizuku) — the article's pattern 11 (loop-until-dry) applied at the
repo-controller level, converting a PRD into beads issues that agents work
continuously. See the `ralph-tui-orchestration` skill for that system; it's
orthogonal to this repo, which is a generic template for other projects.
**Status 2026-09-21: dormant** — the `ralph-tui` binary is gone from PATH
and its controller workspaces were deleted with `~/src/ops-worktrees/` on
2026-08-23; only `~/.config/ralph-tui/` survives. See
[`docs/coding-factory.md`](docs/coding-factory.md).

## Layout

- `.claude/workflows/graph-audit.js` — the micro-graph example (pipeline,
  schema-validated nodes, adversarial verify, synthesis).
- `docs/orca-integration.md` — exact, runnable Orca commands for dispatching
  a macro-graph fleet, plus what to check before running one live.
- `docs/model-routing.md` — which models are reachable via which service
  on this machine, and the vendor × model × effort routing policy that
  keeps tokens spent on judgment, not plumbing.
- `skills/model-routing/SKILL.md` — canonical source of the machine-wide
  model-routing skill (live copy deployed at `~/.claude/skills/`).
- `AGENTS.md` — the entry point for any AI agent working here: pointers,
  standing orders, machine context. `CLAUDE.md` includes it.

## Status (2026-08-23)

`graph-audit` has run twice for real, pointed at this repo itself:

1. First run (pre-edit script): slow but complete (7 agents, ~33 min,
   finishing in the background long after its findings were read from the
   journal mid-run). Final tally: five findings, four confirmed, one
   refuted — all four confirmed ones were independently identified and
   fixed before the run even finished.
2. Second run (17 agents): the full Audit → Verify → Synthesize graph
   completed, confirming 9 findings — including two prompt-injection
   channels in the workflow's own prompts and a missing-`--ack` deadlock
   in the Orca doc's fan-out loop. All nine are fixed as of this commit,
   and the workflow now accounts for confirmed vs refuted vs
   unadjudicated outcomes explicitly.

A live heterogeneous macro-graph dispatch has also completed: one claude
worker plus one codex worker under a single Run, both tasks settled
`completed`, with failure/recovery lessons recorded in
[`docs/orca-integration.md`](docs/orca-integration.md).
