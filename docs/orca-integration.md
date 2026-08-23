# Running the macro graph with Orca

Commands below are transcribed from the live, version-matched guide
(`orca skills get orchestration`, Orca 1.4.188). Re-run that command before
trusting this file for a different Orca version — the guide explicitly
warns it changes between releases.

## Preconditions

- `orca status --json` shows `runtime.state: "ready"`.
- Orchestration is enabled — verified live 2026-08-23: `orca orchestration
  task-list --json` answers with a structured `run_required` protocol
  error (task commands need a Run bound via `run-create`/`run-use` first),
  not a feature-disabled error.
- `orca` resolves correctly for this shell (`which orca` → `/usr/local/bin/orca`
  on this machine; not `orca-dev`/`orca-ide` since there's no dev checkout
  and this is macOS, not Linux).

## Minimal fan-out: N workers, one coordinator

```bash
orca orchestration run-create --objective "Audit N services with graph-audit" --json
# capture the returned run id

# --worktree new-child makes child worktrees of the COORDINATOR's repo, so
# this example fans out over slices of this repo. The graph-audit workflow
# works here because its script ships in this repo's .claude/workflows/ —
# a worker in a different repo would not have it. For cross-repo dispatch,
# use an exact worktree selector (or new-top-level --repo <selector>) and
# make sure the target repo carries the workflow script first.
orca orchestration task-create --spec "In your worktree, run the graph-audit workflow (script: .claude/workflows/graph-audit.js) on docs/ and report findings" --json
orca orchestration task-create --spec "In your worktree, run the graph-audit workflow (script: .claude/workflows/graph-audit.js) on .claude/ and report findings" --json
# capture each returned task id

orca orchestration worker-start --task <task_a> --worktree new-child --name slice-docs --agent claude --setup run --json
orca orchestration worker-start --task <task_b> --worktree new-child --name slice-claude --agent codex --setup run --json

# One check --wait returns ONE bounded Delivery (up to 50 messages), and an
# un-acked check replays that same batch — so loop: wait, process every
# message, release or reuse each settled worker, then acknowledge and wait
# again, until every expected Dispatch settles. Timeouts and {count:0} are
# checkpoints, not failures (tasks routinely run 15-60 minutes).
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 --json
# ...process the messages; for each accepted worker_done with no follow-up:
orca orchestration worker-release --dispatch <dispatch_id> --json
# acknowledge the processed Delivery and keep waiting, in one call:
orca orchestration check --ack <delivery_id> --wait --types worker_done,escalation,question --timeout-ms 900000 --json
```

## What NOT to do

- Don't run `task-create` / `dispatch --inject` / `check --wait` for a plain
  "hand this off to another agent" request — that's a full ownership
  transfer, not supervised orchestration. Only use the loop above when
  explicitly asked to supervise, wait for completion, or coordinate a DAG.
- Don't release a worker just because of a timeout, heartbeat, or TUI-idle
  state — only after an accepted `worker_done`/`escalation`, or explicit
  user instruction to stop.
- Don't guess subcommands/flags from this file for a future Orca version.
  Re-run `orca skills get orchestration` — it's served by the binary so it
  can never drift from what will actually execute.

## Resolved questions (2026-08-23)

- The orchestration feature is on for this install — see the probe under
  Preconditions.
- Local `--agent claude` workers run the same `claude` binary as any other
  terminal on this machine, so they spend the active cswap-selected
  account's quota (`cswap switch <n>` moves new sessions; Orca's own usage
  tracker watches the same accounts). Residual caveat: a worker dispatched
  to another machine with `--on <environment>` uses that machine's
  logged-in credentials — check them before remote dispatch.

## Live-run lessons (2026-08-23, mixed claude + codex fleet)

A real two-worker heterogeneous dispatch (run_e36379cdc849: one claude
worker, one codex worker, child worktrees under
`~/orca/workspaces/djbclark-ade/`) settled both tasks `completed`. What
the receipts taught:

- **`agent_prompt_stalled` can be a false death.** The codex worker was
  marked failed ~18s after dispatch (cold CLI boot took ~17s to accept the
  prompt) — but `worker-read --dispatch <id>` showed the prompt had landed
  and codex was working. Check the transcript before treating a stalled
  dispatch as a dead worker.
- **Late `worker_done` from a revoked dispatch is rejected but not lost.**
  Orca forwarded it to the coordinator as a high-priority message with the
  original body embedded (`_orcaLifecycleRejection`), and the preamble's
  taskId+dispatchId payload rule is exactly what prevents it from settling
  the current dispatch. You get the work's content; the task still needs a
  proper retry to settle.
- **The retry that works:** `worker-start --task <t> --retry-of
  <failed_ctx> --worktree <same child worktree path> --terminal <same
  handle>` — the warm terminal accepted input instantly and its
  `worker_done` was accepted. `--terminal` *without* `--worktree` fails
  with `terminal_worktree_mismatch` (the worktree defaults to the
  coordinator's).
- **Follow release receipts literally.** One `worker-release` returned
  `release_unknown` / `tab_not_found`; the receipt's own recovery
  (worker-show, then repeat worker-release) settled it as `retained` with
  no process action. Don't substitute `terminal close`.
- **Task specs are edge contracts.** The codex worker ran the literal
  `git ls-files *.md` from its spec — a top-level glob that misses
  `docs/*.md`. It did exactly what the contract said; the contract was the
  bug. Spec precision is the coordinator's job (the article's steps 3-4,
  proven at the macro altitude).

## Orca-shipped skills

The stubs from the Orca repo's `skill-stubs/` are installed at
`~/.agents/skills/` (orchestration, orca-cli, computer-use,
orca-per-workspace-env). `orca skills list --json` enumerates every topic
the running binary serves; `orca skills get <name>` prints its
version-matched guide. Install more as needed — the currently-installed
set is not a boundary.
