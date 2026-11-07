---
name: fan-out
description: >-
  Fan separable work out and collect it: the lead's own Agent-tool or Workflow fan-out for in-process work,
  `acp-dispatch` (the Paseo shim) or `paseo run --no-wait` for a slice in its own worktree, `paseo ls` and
  `acp-dispatch wait` to collect, the shared delivery footer on every brief. Use for "fan this out",
  "parallelize this", "use the other agents too", or when the context-size hook says to delegate. Replaces
  the bigteam skill (slim-down E6, 2026-11-06).
---

# fan-out: slice the work, hand it out, collect the reports

Canonical copy: `~/src/djbclark-ade/skills/fan-out/` (edit it there, never through a TUI path).

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
each prompt: `~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md` prints it
filled in (the `agent_footer_gate` hook appends it when a prompt lacks it). Read the report file, never the
sub-agent's final message: the harness cuts that at 4,000 characters.

## 3. Out of process: a slice in its own worktree

A slice that edits code gets its own linked worktree (AGENTS.md order 9:
`git worktree add -b NAME ~/src/<repo>-NAME-wt origin/master`) and runs as a Paseo agent there:

    ~/src/djbclark-ade/bin/acp-dispatch claude --model sonnet --kind code --name NAME \
        -f brief.md -C ~/src/<repo>-NAME-wt --task TASK --detach --no-wait

`acp-dispatch` writes `~/.local/state/bigteam/TASK/NAME-brief.md` (your brief plus the footer), gates on
`load-watch admit` and the agent cap (exit 75: retry later), and runs `paseo run --no-wait` with the
labels `ade.via=acp-dispatch`, `ade.kind`, `ade.name`, `ade.lead`. `--perm read-only` for a review: Claude
runs through `bin/review-launch` (the enforced review boundary); every other agent runs best effort, in its
default mode with a brief note to change nothing (`perm_note` in the record; operator ruling 2026-11-07). A plain `paseo run --no-wait --provider P/M --mode M --cwd DIR "<prompt>"`
works too when you need none of that, but then you write the footer into the prompt yourself.

## 4. Collect

- `acp-dispatch wait ~/.local/state/bigteam/TASK/jobs/NAME.json` blocks on `paseo wait` and exits with the
  contract: 0 DONE, 1 unfinished, 3 no report, 4 BLOCKED (or a pending permission), 124 timed out.
  `--once` looks once without blocking (75 while unfinished); `bin/acp-dispatch-wait RECORD DONE` loops on it.
- `acp-dispatch check ~/.local/state/bigteam/TASK` classifies every slice of the task at once.
- `paseo ls -g --label ade.via=acp-dispatch` shows what runs; `paseo permit ls` the permission cards.
- `acp-dispatch tell RECORD "message"` reaches a running slice (its inbox plus `paseo send`; `accepted`,
  exit 5, is not proof of delivery: ask for an ack).
- Verify each result against the artifact (the diff, the tests), then
  `acp-dispatch outcome RECORD --ci pass --review pass --merged` for `route_agent.py calibrate`.

## 5. Worked example

Three independent fixes in one repository, one review:

1. Lead writes `a.md`, `b.md`, `c.md` (one owner per file set, the check each slice runs) and three
   worktrees `~/src/r-a-wt`, `~/src/r-b-wt`, `~/src/r-c-wt`.
2. `acp-dispatch claude --model sonnet --kind code --name a -f a.md -C ~/src/r-a-wt --task fixes --detach --no-wait`,
   the same for `b` and `c` (the agent and model from `route_agent.py plan --kinds code`).
3. While they run, the lead does its own part (standing order 3), then `acp-dispatch wait` on each record.
4. A BLOCKED report: answer with `acp-dispatch tell`, or re-brief under a new `--name`.
5. Each DONE slice: review its diff, push its branch, open the PR; one read-only review per PR with
   `acp-dispatch claude --model sonnet --kind judgment --perm read-only --name rev-a -f review.md -C ~/src/r-a-wt`.
