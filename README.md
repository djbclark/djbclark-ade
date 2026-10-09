# djbclark-ade — an agentic development environment

One operator, many agent TUIs. This repo is the operating kit for running a
fleet of coding agents on one Mac as a single environment: the skills every
agent loads, the tools that start and steer them, and the docs that record
what was verified. It is the canonical git home for the orchestration and
session-hygiene pieces (moved here from `~/ops/site-djbclark` on 2026-10-08;
their old paths are symlinks into this checkout).

## The pieces

1. **Many TUIs.** Claude Code, Codex, Hermes, Cursor, opencode, Cline,
   Copilot, Qwen, muse, zcode, Antigravity (`agy`) and others, each on its own
   subscription or quota pool. [`skills/model-routing`](skills/model-routing/SKILL.md)
   and [`docs/model-routing.md`](docs/model-routing.md) say which one gets
   which work.
2. **herdr and Orca as the terminal fabric.** Every session lives in a herdr
   pane (workspace / tab / pane) or an Orca terminal, so it is visible,
   addressable and can be typed into by another session.
   [`docs/orca-integration.md`](docs/orca-integration.md) covers Orca's task DAG.
3. **ACP for agent-to-agent control.** [`tools/acp-run`](tools/acp-run/README.md)
   drives any agent that speaks the Agent Client Protocol: one-shot, an
   `--interactive` loop in a visible pane, `--resume`, scoped permissions.
4. **Skills, linked everywhere.** Each skill is one directory in
   [`skills/`](skills/); the [`skill-everywhere`](https://github.com/djbclark/site-djbclark/blob/master/bin/skill-everywhere.md) script
   (`~/ops/site-private/bin/skill-everywhere`, README beside it) symlinks it into every TUI's skills dir, so one edit here reaches all of
   them.

## The loop

1. **Find and decide** — [`session-finder`](skills/session-finder/SKILL.md)
   (`fleet.py`) lists every live session of every TUI, says where it lives
   and which repos it is touching, and decides how work on a topic
   continues: message the running session, `/baton` from its handoff, resume
   a stopped one, or start a clean agent. `fleet.py conflicts` refuses
   overlap.
2. **Start** — `session-finder/launch.py` starts a session over ACP
   (`acp-run --interactive`) in a visible herdr tab or Orca terminal, with a
   claim on the files it will touch, and can `reply` to it later through its
   inbox.
3. **Answer everything from one window** — [`helm`](skills/helm/SKILL.md)
   (`helm.py scan`, no model tokens) collects every session waiting on the
   operator, reads its pending question verbatim, ranks the walk by how much
   unattended work each answer unlocks, and relays one item per prompt;
   idle sessions are told to audit themselves with `/loose`. Design record:
   [`docs/helm.md`](docs/helm.md). [`bin/fleet-watch`](bin/fleet-watch)
   (launchd, every 5 min) pings Hermes only when the picture changes.
   [`herdr-tidy`](skills/herdr-tidy/SKILL.md) then closes the panes that are
   safely idle and writes the ledger `/helm-all` reads them back from
   ([`docs/herdr-tidy.md`](docs/herdr-tidy.md)).
4. **Carry work across sessions** — [`loose`](skills/loose/SKILL.md) finds
   what is unfinished and walks it with [`steps`](skills/steps/SKILL.md);
   [`handoff`](skills/handoff/SKILL.md) writes the deep Tier 2 document,
   [`session-handoff`](skills/session-handoff/SKILL.md) the Tier 1 pointer,
   and [`baton`](skills/baton/SKILL.md) (also `/resume`) picks it up in a fresh session.
5. **Fan out** — [`bigteam`](skills/bigteam/SKILL.md) slices a job into
   disjoint, file-scoped assignments and dispatches them across vendors by
   quota pool, then integrates the results.

## Layout

| Path | What |
|---|---|
| [`skills/`](skills/) | The skills (table below). |
| [`tools/acp-run/`](tools/acp-run/) | `acp-run`, the ACP client every launcher uses. |
| [`bin/`](bin/) | `acp-dispatch` (hand a slice to an agent and get its report back: wraps `acp-run`, appends [`docs/dispatch-footer.md`](docs/dispatch-footer.md), writes report/`.done`/record, exit codes for no-report and `BLOCKED:`), `fleet-watch` (fleet change notices), `cow-pasture` (APFS copy-on-write workspaces), `herdr-sleeper` (idle-pane sleep), `herdr-jump` (focus a `w22:t4` address from a `prefix+:` popup), `herdr-ai` (natural language to Herdr commands from a `prefix+alt+i` popup), `orca-reorg-watch`, `route_agent.py`. |
| [`claude/commands/`](claude/commands/) | Claude Code slash commands `/orc` (the primary herdr orchestrator), `/orc-meta` (its watchdog), and the thin wrappers `/helm-all`, `/session-finder-all`, `/resume`, `/herdr-tidy`, `/orca-tidy` (herdr-tidy over Orca terminals). |
| [`docs/`](docs/) | Design records and dated operating knowledge (list below). |
| [`plugins/`](plugins/) | `herdr-sleeper` herdr plugin (dev source of djbclark/herdr-sleeper). |
| [`.claude/workflows/graph-audit.js`](.claude/workflows/graph-audit.js) | Micro-graph example workflow (`/graph-audit`). |
| [`vendor/`](vendor/README.md) | Vendored snapshots and pointers to things with their own homes. |
| [`AGENTS.md`](AGENTS.md) | Entry point for any agent working here (`CLAUDE.md` links to it). |

## Skills

| Skill | One line |
|---|---|
| [`bigteam`](skills/bigteam/SKILL.md) | Run a prompt as a multi-vendor fan-out: probe every quota pool, slice into file-scoped assignments, dispatch, integrate. |
| [`model-routing`](skills/model-routing/SKILL.md) | Which vendor × model × effort for which work; reading `aiuse` pools. |
| [`effort-routing`](skills/effort-routing/SKILL.md) | Match this session's own reasoning effort to the stretch of work in front of it. |
| [`session-finder`](skills/session-finder/SKILL.md) | Which session is or ever was on a topic (live or ended, handoff chains, memory; `/session-finder-all` searches everything), where it lives, and how the work continues (`fleet.py`, `launch.py`). |
| [`helm`](skills/helm/SKILL.md) | Answer every waiting session of every TUI from one window, ranked by work unlocked (`helm.py`); `/helm-all` adds ended sessions that still hold open work, panes `herdr-tidy` closed and sleeping panes that are gone. |
| [`herdr-tidy`](skills/herdr-tidy/SKILL.md) | Close idle herdr panes safely, every TUI, Hermes, shells and herdr-sleeper stubs: `tidy.py` classifies each pane, performs the precondition (`/handoff`), writes a close ledger with the exact resume command, closes the tab; fails closed. `/herdr-tidy`; `--host orca` does the same for Orca terminals (`/orca-tidy`). |
| [`autorename`](skills/autorename/SKILL.md) | Title the current Claude session the way `/rename` does and offer to move its tab out of a generic herdr workspace (`autorename.py`, `herdr_place.py`; nudge hook `autorename_nudge.py`). |
| [`herdr-orchestration`](skills/herdr-orchestration/SKILL.md) | Drive a multi-agent handoff chain through herdr panes instead of clipboard relays; `references/workspace-layout.md` is the workspace/tab/pane naming and re-arrangement procedure. |
| [`ralph-tui-orchestration`](skills/ralph-tui-orchestration/SKILL.md) | The Ralph TUI + Beads multi-repo controller (dormant since 2026-08-23). |
| [`cow-workspaces`](skills/cow-workspaces/SKILL.md) | Isolated agent workspaces as APFS `cow` pastures (`bin/cow-pasture`), not worktrees. |
| [`handoff`](skills/handoff/SKILL.md) | Deep Tier 2 handoff document, chain-tagged and mined from the whole conversation. |
| [`session-handoff`](skills/session-handoff/SKILL.md) | Read/write the out-of-tree Tier 1 session pointer for any git repo. |
| [`baton`](skills/baton/SKILL.md) | Start-of-session resume from the Tier 1 pointer (`/baton`, `/resume`). |
| [`loose`](skills/loose/SKILL.md) | Audit the session for loose ends, step through them, then offer `/handoff` or quit. |
| [`steps`](skills/steps/SKILL.md) | Walk open items one multiple-choice prompt at a time, recommendation first. |

## Install (this machine)

Skills are reached through one hub, `~/ops/site-private/skills/<name>`, which
every TUI's skills dir links to. For a skill that lives here the chain is
`~/.claude/skills/<name>` → `~/ops/site-private/skills/<name>` →
`~/ops/site-djbclark/skills/<name>` → `~/src/djbclark-ade/skills/<name>`. To
add one:

```sh
ln -s /Users/djbclark/src/djbclark-ade/skills/<name> ~/ops/site-djbclark/skills/<name>
ln -s ../../site-djbclark/skills/<name> ~/ops/site-private/skills/<name>
~/ops/site-private/bin/skill-everywhere <name>          # link into every TUI
~/ops/site-private/bin/skill-everywhere --check <name>  # verify
```

How each TUI finds skills, and how to prove one loaded: the script's
[README](https://github.com/djbclark/site-djbclark/blob/master/bin/skill-everywhere.md).

`acp-run` is on PATH as `~/.local/bin/acp-run` → `~/ops/site-private/bin/acp-run`
→ `~/ops/site-djbclark/tools/acp-run/acp-run` → here; `fleet-watch`'s launchd
job runs `~/ops/site-private/bin/fleet-watch`, which resolves here the same
way. `helm.py` imports `fleet` from the sibling `skills/session-finder/`.

## Docs

1. [`docs/model-routing.md`](docs/model-routing.md) — every service on this
   machine mapped to its TUI, subscription vs prepaid vs free, effort levers.
2. [`docs/orca-integration.md`](docs/orca-integration.md) — runnable Orca
   macro-graph sequences and live-run lessons.
3. [`docs/helm.md`](docs/helm.md) — helm's design record and what was verified.
4. [`docs/agent-sleep.md`](docs/agent-sleep.md) — idle agents and RAM: Orca
   hibernation and `herdr-sleeper`.
5. [`docs/coding-factory.md`](docs/coding-factory.md) — the unattended
   issue → PR → merge question, answered.
6. [`docs/queue.md`](docs/queue.md) — work queued by the operator, and blockers.
7. [`docs/ai-memory-landscape.md`](docs/ai-memory-landscape.md) — the levels
   of AI memory this machine is building toward.
8. [`docs/mcp-servers.md`](docs/mcp-servers.md) — the MCP server roster.
9. [`docs/upstream-issues.md`](docs/upstream-issues.md) — bug drafts for
   third-party projects.
10. [`docs/herdr-jump.md`](docs/herdr-jump.md) — jump to a Herdr address
    (`w22:t4`) from the keyboard: why Herdr has no such action, the
    `bin/herdr-jump` popup, and the third-party navigator evaluation.
11. [`docs/herdr-tidy.md`](docs/herdr-tidy.md) — closing idle herdr panes
    safely: the pane classes, the close ledger, the cracks closed in
    `fleet.py`/`helm.py` (busy-background, undetected TUIs, closed and sleeping
    items), the first pass (2026-10-08) and the requests left for herdr-sleeper.
12. [`docs/herdr-ai.md`](docs/herdr-ai.md) — `bin/herdr-ai`: type "move to the
    sleeper tab" or "rename this workspace ops" in a popup; a fast free model
    plans Herdr commands from a snapshot index, the script validates every id
    against the snapshot and asks for a `y` before anything destructive.

## Architecture: agent graphs at two altitudes

The repo began (2026-08-23) as a reference architecture for running Claude as
a **graph of agents**, prompted by
[Graph Engineering with Claude](https://x.com/0xCodez/article/2079141496981184512)
(@0xCodez, 2026-07-20), a tutorial for Claude Code's built-in *dynamic
workflows*. It adds the second altitude the article doesn't cover:
[Orca](https://github.com/stablyai/orca) (forked to
[djbclark/orca](https://github.com/djbclark/orca)), which orchestrates whole
agent *processes* rather than in-process subagents.

### Two graphs, two altitudes

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

### How they compose

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
continuously. See the [`ralph-tui-orchestration`](skills/ralph-tui-orchestration/SKILL.md)
skill (in this repo since 2026-10-08) for that system.
**Status 2026-09-21: dormant** — the `ralph-tui` binary is gone from PATH
and its controller workspaces were deleted with `~/src/ops-worktrees/` on
2026-08-23; only `~/.config/ralph-tui/` survives. See
[`docs/coding-factory.md`](docs/coding-factory.md).

### graph-audit and macro-graph status (2026-08-23)

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
