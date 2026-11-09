---
name: fan-out
description: >-
  Slice parallel work, assign owners and verify reports. Launch slices with native
  Paseo (`paseo run` / `paseo wait` / `paseo send`); do not start new work through
  `acp-dispatch` (Wave 6 deletion, docs/slim/wave6-follow-up.md). Use for "fan this
  out", "parallelize this", or an explicit delegation request. Select the destination
  host for remote work.
---

# fan-out: slice the work, hand it out, collect the reports

Canonical copy: `~/src/djbclark-ade/skills/fan-out/` (edit it there, never through a TUI path).

## Preferred transport (2026-11-09)

Use native Paseo `paseo run` / MCP `create_agent` for new slices. Preserve the routing,
claimed workspaces, report and review requirements below. `bin/acp-dispatch` is a
transitional shim over `paseo run` and is scheduled for deletion (soft deadline
2026-11-20; checklist `docs/slim/wave6-follow-up.md`). Do not teach it as the
default launch path. For another computer, select its host explicitly and transfer
any needed files before launch; a local brief/report path is not shared storage.
See [old way versus new way](../../docs/old-way-new-way.md), including plugin advice
and the cross-host acceptance checks. Keep `{serverId, agentId}` together and prove
receipt with an ack.

## 1. Slice first

Cut the work into slices that touch disjoint files, each with one owner and a check you can run on its result
(a test, a diff, a report section). Shared files (a changelog, an index) stay with the lead. Pick each slice's
agent and model with `~/src/djbclark-ade/bin/route_agent.py plan --kinds KIND` (kinds and pools:
`skills/model-routing/SKILL.md`). Print the launch line with
`~/src/djbclark-ade/bin/route_agent.py show` (Pi already emits native `paseo run --provider pi/… --no-wait`).
Every brief ends with the shared delivery contract, `docs/dispatch-footer.md`: a report file whose last
line is `DONE`, a `.done` marker touched last, and `BLOCKED: <question>` as the first line instead of a
question at the end of a turn. Fill `{report}`, `{lead}`, `{done}`, `{inbox}` and `{replies}` yourself
(or, while the shim still exists, `bin/acp-dispatch footer --report PATH` prints the filled footer for an
Agent-tool prompt only — not a launch).

## 2. In process: the Agent tool or a Workflow

For lookups, reviews and edits that fit this session's worktree, use the Agent tool (one sub-agent per slice,
launched together) or a Claude Code Workflow (`/graph-audit` is a worked example). Paste the filled footer into
each prompt. Read the report file, never the sub-agent's final message: the harness cuts that at 4,000 characters.

## 3. Out of process: a slice in its own worktree

A slice that edits code gets its own linked worktree (AGENTS.md order 9:
`git worktree add -b NAME ~/src/<repo>-NAME-wt origin/master`) and runs as a Paseo agent there.
Claim the worktree (`ade_claims.py new --ttl`, docs/git-guard.md) before anyone writes.

Gate capacity first: `load-watch admit` (exit 75: retry later). Then launch with the line from
`route_agent.py show`, adding placement and the brief. Minimal native shape:

```bash
# after: route_agent.py plan / show → e.g. paseo run --provider pi/<model> --no-wait
paseo run --provider PROVIDER/MODEL --no-wait \
  --new-workspace local --cwd ~/src/<repo>-NAME-wt \
  --label ade.kind=KIND --label ade.name=NAME --label ade.lead=LEAD \
  "$(cat brief-with-footer.md)"
```

As verified on 2026-11-07, agent-origin runs, or runs with `PASEO_WORKSPACE_ID` set, must explicitly
select a workspace: `--cwd` alone inherits the parent agent's workspace and directory.
`--new-workspace local` imports the assigned directory while preserving the parent link; it creates
no Git worktree. Verify the returned `cwd` against the assigned directory before treating a launch as
correctly placed.

Read-only review slices: prefer `bin/review-launch` / `bin/review-pr` (the enforced review boundary,
docs/review-boundary.md), not a free-form `paseo run` with a "change nothing" note.

While `acp-dispatch` still exists it can wrap admit + footer + labels for non-Pi agents; new
briefs must not depend on it surviving past Wave 6.

## 4. Collect

- `paseo wait <agent-id> --json` (or `paseo wait` on the id returned by `paseo run`) for turn end;
  then read the report artifact and the `.done` marker. Contract exit meanings used by the old shim
  (0 DONE, 1 unfinished, 3 no report, 4 BLOCKED / pending permission, 124 timed out) are still the
  lead's classification when checking files — implement them by reading the report, not by assuming
  a shim exit code.
- `paseo ls -a -g --json` (filter on your `ade.*` labels) shows what runs; `paseo permit ls` the
  permission cards.
- `paseo send --json --no-wait <id> "message"` plus `Please reply: ack <your id>` reaches a running
  slice (standing order 10). `queued` / `accepted` is not proof of delivery: wait for the named ack.
- Verify each result against the artifact (the diff, the tests), then record outcomes for
  `route_agent.py calibrate` the way your lead already does (bigteam `outcome` records remain readable
  while the shim's `outcome` subcommand exists; after deletion, write the calibrate row yourself).

## 5. Worked example

Three independent fixes in one repository, one review:

1. Lead writes `a.md`, `b.md`, `c.md` (one owner per file set, the check each slice runs) and three
   worktrees `~/src/r-a-wt`, `~/src/r-b-wt`, `~/src/r-c-wt`, each claimed.
2. For each slice: `route_agent.py plan --kinds code` → `show` → `paseo run … --new-workspace local
   --cwd ~/src/r-a-wt …` with the brief+footer (same for `b` and `c`).
3. While they run, the lead does its own part (standing order 3), then `paseo wait` / report checks
   on each id.
4. A BLOCKED report: answer with `paseo send` (and require ack), or re-brief under a new `--name` /
   label.
5. Each DONE slice: review its diff, push its branch, open the PR; one read-only review per PR via
   `bin/review-pr` / `bin/review-launch`, not a free-form coding agent.
