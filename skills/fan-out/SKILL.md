---
name: fan-out
description: >-
  Slice parallel work, assign owners and verify reports. Prefer native Paseo agent/workspace
  operations; acp-dispatch is a transitional compatibility shim. Use for "fan this out",
  "parallelize this", or an explicit delegation request. Select the destination host for remote work.
---

# fan-out: slice the work, hand it out, collect the reports

Canonical copy: `~/src/djbclark-ade/skills/fan-out/` (edit it there, never through a TUI path).

## Preferred transport (2026-11-07)

Use native Paseo `create_agent` / `paseo run` for new slices, preserving the routing, claimed
workspaces, report and review requirements below. The dispatch examples below are compatibility
recipes while the shim remains installed. For another computer, select its host explicitly and
transfer any needed files before launch; a local brief/report path is not shared storage.
See [old way versus new way](../../docs/old-way-new-way.md), including plugin advice and the
cross-host acceptance checks. Keep `{serverId, agentId}` together and prove receipt with an ack.

## 1. Slice first

Cut the work into slices that touch disjoint files, each with one owner and a check you can run on its result
(a test, a diff, a report section). Shared files (a changelog, an index) stay with the lead. Pick each slice's
agent and model with `~/src/djbclark-ade/bin/route_agent.py plan --kinds KIND` (kinds and pools:
`skills/model-routing/SKILL.md`). Every brief ends with the shared delivery contract,
`docs/dispatch-footer.md`: a report file whose last line is `DONE`, a `.done` marker touched last, and
`BLOCKED: <question>` as the first line instead of a question at the end of a turn.

## 2. In process: the Agent tool or a Workflow

For lookups, reviews and edits that fit this session's worktree, use the Agent tool (one sub-agent per slice,
launched together) or a Claude Code Workflow (`/graph-audit` is a worked example). Paste the footer into
each prompt: `~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md --lead "$PASEO_AGENT_ID"`
prints it filled in (`--lead` defaults to `$PASEO_AGENT_ID` when set, so the completion notice targets the
requester rather than the literal `main` placeholder; the `agent_footer_gate` hook appends the footer when a
prompt lacks it). Read the report file, never the
sub-agent's final message: the harness cuts that at 4,000 characters.

## 3. Out of process: a slice in its own worktree

A slice that edits code gets its own linked worktree (AGENTS.md order 9:
`git worktree add -b NAME ~/src/<repo>-NAME-wt origin/master`) and runs as a Paseo agent there:

    ~/src/djbclark-ade/bin/acp-dispatch claude --model sonnet --kind code --name NAME \
        -f brief.md --workspace <existing-workspace-id> -C ~/src/<repo>-NAME-wt --task TASK \
        --lead "$PASEO_AGENT_ID" --detach --no-wait

`acp-dispatch` writes `~/.local/state/bigteam/TASK/NAME-brief.md` (your brief plus the footer), gates on
`load-watch admit` and the agent cap (exit 75: retry later), and runs `paseo run --no-wait` with the
labels `ade.via=acp-dispatch`, `ade.kind`, `ade.name`, `ade.lead`. `--perm read-only` for a review: Claude
runs through `bin/review-launch` (the enforced review boundary); every other agent runs best effort, in its
default mode with a brief note to change nothing (`perm_note` in the record; operator ruling 2026-11-07). A plain
`paseo run --no-wait --provider P/M --mode M --workspace wks_… --cwd DIR "<prompt>"` works when you need none of that,
but then you write the footer into the prompt yourself. Create a workspace only with native `paseo workspace create` or
`paseo run --new-workspace …` when deliberate — `acp-dispatch` never mints workspaces.
As verified on 2026-11-07, agent-origin runs, or runs with `PASEO_WORKSPACE_ID` set, must explicitly select a workspace:
`--cwd` alone inherits the parent agent's workspace and directory. `acp-dispatch` passes `--workspace` (validated against
`paseo workspace ls --json` and `-C`) and never emits `--new-workspace` on an ordinary launch.
With a caller, unreadable or missing workspace metadata refuses instead of using the ambient workspace.
Paseo 0.15.3 native inspect omitted workspace ids when checked on 2026-11-08; pass `--workspace` explicitly.
Only a launch without `PASEO_AGENT_ID` may use `PASEO_WORKSPACE_ID` as its fallback.
Verify returned `cwd` and `workspaceId` against the assignment before treating a launch as correctly placed. The shim stores
`paseo_cwd`, `selected_workspace_id`, and `returned_workspace_id`, and emits a `placement_warning` if any are missing or
different; it leaves the paid agent running.

The operator's temporary all-tabs-with-the-lead arrangement is described in `docs/workspace-layout.md`.
Use the lead's existing workspace/session cwd for placement, while every writer's brief names a separate claimed
execution worktree and every repository tool call targets it explicitly. Never turn a report folder into a workspace.

## 4. Collect

- `acp-dispatch wait ~/.local/state/bigteam/TASK/jobs/NAME.json` blocks on `paseo wait` and exits with the
  contract: 0 DONE, 1 unfinished, 3 no report, 4 BLOCKED (or a pending permission), 124 timed out.
  `--once` looks once without blocking (75 while unfinished); `bin/acp-dispatch-wait RECORD DONE` loops on it.
- `acp-dispatch check ~/.local/state/bigteam/TASK` classifies every slice of the task at once.
- `paseo ls -g --label ade.via=acp-dispatch` shows what runs; `paseo permit ls` the permission cards.
- `acp-dispatch tell RECORD "message"` reaches a running slice (its inbox plus `paseo send`; `accepted`,
  exit 5, is not proof of delivery: ask for an ack).
- **Push on completion:** each brief's footer (rule 22) requires the slice, after `DONE` and `{done}`, to
  `paseo send --json --no-wait` its requester `done: <title>, <PR URL>` (or `done: <title>, <status>[, <report>]`)
  plus `Please reply: ack <slice id>` — never relay. Prefer
  `~/src/djbclark-ade/bin/completion-notice --send --requester <lead-id> --title TITLE --pr URL`
  (or `--status DONE --report PATH`). The lead treats that notice (and the named ack) as the wake-up; do not
  invent an APPROVE. Prefer the notice over polling `wait` when the slice can reach you.
- Verify each result against the artifact (the diff, the tests), then
  `acp-dispatch outcome RECORD --ci pass --review pass --merged` for `route_agent.py calibrate`.

## 5. Worked example

Three independent fixes in one repository, one review:

1. Lead writes `a.md`, `b.md`, `c.md` (one owner per file set, the check each slice runs) and three
   worktrees `~/src/r-a-wt`, `~/src/r-b-wt`, `~/src/r-c-wt`.
2. `acp-dispatch claude --model sonnet --kind code --name a -f a.md --workspace <workspace-a> -C ~/src/r-a-wt --task fixes --lead "$PASEO_AGENT_ID" --detach --no-wait`,
   with the separately selected existing workspace for `b` and `c` too (the agent and model from `route_agent.py plan --kinds code`).
3. While they run, the lead does its own part (standing order 3), then `acp-dispatch wait` on each record.
4. A BLOCKED report: answer with `acp-dispatch tell`, or re-brief under a new `--name`.
5. Each DONE slice: review its diff, push its branch, open the PR; one read-only review per PR with
   `acp-dispatch claude --model sonnet --kind judgment --perm read-only --name rev-a -f review.md --workspace <workspace-a> -C ~/src/r-a-wt --lead "$PASEO_AGENT_ID"`.
