---
name: fan-out
description: >-
  Slice parallel work, assign owners and verify reports. Prefer native Paseo agent/workspace
  operations; Wave 6 dispatch shims are transitional only. Use for "fan this out",
  "parallelize this", or an explicit delegation request. Select the destination host for remote work.
---

# fan-out: slice the work, hand it out, collect the reports

Canonical copy: `~/src/djbclark-ade/skills/fan-out/` (edit it there, never through a TUI path).

## Preferred transport (2026-11-07)

Use native Paseo `create_agent` / `paseo run` for new slices, preserving the routing, claimed
workspaces, report and review requirements below. For another computer, select its host explicitly and
transfer any needed files before launch; a local brief/report path is not shared storage.
See [old way versus new way](../../docs/old-way-new-way.md), including plugin advice and the
cross-host acceptance checks. Keep `{serverId, agentId}` together and prove receipt with an ack.
Recipe detail: [docs/orchestration-practices.md](../../docs/orchestration-practices.md).

## 1. Slice first

Cut the work into slices that touch disjoint files, each with one owner and a check you can run on its result
(a test, a diff, a report section). Shared files (a changelog, an index) stay with the lead. Pick each slice's
agent and model with `~/src/djbclark-ade/bin/route_agent.py plan --kinds KIND` (kinds and pools:
`skills/model-routing/SKILL.md`). Every brief ends with the shared delivery contract,
`docs/dispatch-footer.md`: a report file whose last line is `DONE`, a `.done` marker touched last, and
`BLOCKED: <question>` as the first line instead of a question at the end of a turn. Paste the filled
footer into every Agent-tool or `paseo run` brief (`{report}`, `{lead}`, `{done}`, `{inbox}`, `{replies}`);
`agent_footer_gate` appends it when an Agent-tool prompt lacks it.

## 2. In process: the Agent tool or a Workflow

For lookups, reviews and edits that fit this session's worktree, use the Agent tool (one sub-agent per slice,
launched together) or a Claude Code Workflow (`/graph-audit` is a worked example). Paste the footer into
each prompt (see `docs/dispatch-footer.md`). Read the report file, never the
sub-agent's final message: the harness cuts that at 4,000 characters.

## 3. Out of process: a slice in its own worktree

A slice that edits code gets its own linked worktree (AGENTS.md order 9:
`git worktree add -b NAME ~/src/<repo>-NAME-wt origin/master`) and runs as a Paseo agent there.
After `route_agent.py plan` / `route` and `load-watch admit`:

```bash
paseo run --provider PROVIDER/MODEL --no-wait \
  --workspace wks_… --cwd ~/src/<repo>-NAME-wt \
  --label ade.kind=KIND --label ade.name=NAME --label ade.lead=LEAD \
  --label ade.task=TASK \
  "$(cat brief-with-footer.md)"
# or, minting for a claimed worktree: --new-workspace local --cwd ~/src/<repo>-NAME-wt …
```

Take `Choice.dispatch` from `route_agent.py plan` **as-is** (native `paseo run --provider …`), then append
only placement flags and the positional brief (`paseo run` has no `--prompt-file`). Write the footer into
the brief yourself. Create a workspace only with native `paseo workspace create` or
`paseo run --new-workspace …` when deliberate — ordinary dispatch never mints workspaces.
As verified on 2026-11-07, agent-origin runs, or runs with `PASEO_WORKSPACE_ID` set, must explicitly select a workspace:
`--cwd` alone inherits the parent agent's workspace and directory. Pass `--workspace` (validated against
`paseo workspace ls --json` and `-C` / `--cwd`) and never emit `--new-workspace` on an ordinary launch.
With a caller, unreadable or missing workspace metadata refuses instead of using the ambient workspace.
Paseo 0.15.3 native inspect omitted workspace ids when checked on 2026-11-08; pass `--workspace` explicitly.
Only a launch without `PASEO_AGENT_ID` may use `PASEO_WORKSPACE_ID` as its fallback.
Verify returned `cwd` and `workspaceId` against the assignment before treating a launch as correctly placed.

For a review slice: Claude runs through `bin/review-launch` (the enforced review boundary); every other agent
runs best effort, in its default mode with a brief note to change nothing (operator ruling 2026-11-07).

The operator's temporary all-tabs-with-the-lead arrangement is described in `docs/workspace-layout.md`.
Use the lead's existing workspace/session cwd for placement, while every writer's brief names a separate claimed
execution worktree and every repository tool call targets it explicitly. Never turn a report folder into a workspace.

## 4. Collect

- `paseo wait <id> --json` blocks until the agent is idle; classify by the report / `.done` artifacts
  (same meanings as orchestration-practices §5): 0 DONE, 1 unfinished / still running, 3 no report,
  4 BLOCKED (or a pending permission), 124 timed out. Poll with short `paseo wait` / `paseo ls` looks when
  you must not block.
- `paseo ls -a -g --json` (filter on your `ade.*` labels) classifies every slice of the task at once
  against its report paths.
- `paseo ls -g --label ade.task=TASK` shows what runs; `paseo permit ls` the permission cards.
- `paseo send --json --no-wait <id> --prompt "…"` reaches a running slice (`accepted`,
  exit 5, is not proof of delivery: ask for an ack).
- Verify each result against the artifact (the diff, the tests), then record outcomes for
  `route_agent.py calibrate` (ci / review / merged fields in the measured history).

## 5. Worked example

Three independent fixes in one repository, one review:

1. Lead writes `a.md`, `b.md`, `c.md` (one owner per file set, the check each slice runs) and three
   worktrees `~/src/r-a-wt`, `~/src/r-b-wt`, `~/src/r-c-wt`.
2. For each slice, take `route_agent.py plan --kinds code`'s `Choice.dispatch` and run it with
   `--workspace <workspace-a|b|c> --cwd ~/src/r-<name>-wt --label ade.name=<name> --label ade.task=fixes`
   plus the positional brief (agent and model from the plan).
3. While they run, the lead does its own part (standing order 3), then `paseo wait` on each agent id.
4. A BLOCKED report: answer with `paseo send --json --no-wait`, or re-brief under a new `--label ade.name=…`.
5. Each DONE slice: review its diff, push its branch, open the PR; one read-only review per PR through
   `bin/review-launch` (Claude) or a judgment `paseo run` brief that says change nothing, in the same
   claimed workspace/cwd as the slice.
