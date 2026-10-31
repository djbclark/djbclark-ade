# Raw response: acp-run claude --set model=opus --set effort=high (2026-10-19 15:00 EDT)

Verified model (usage_update _meta): claude-opus-5-5; cost reported $0.1947342

---

MODEL: claude-opus-5-5

## Overall

The skeleton is right: a code orchestrator, roles talking only through files, and one worktree per job. The weak spots are the edges of the state model (crashes, side effects, who is allowed to write) and the trust boundary around agents. The scope is about twice what a v1 needs.

## P0: fix before writing code

**1. The "sole writer" rule is already broken.** `factory approve`, `rework` and `retry` are CLI commands that mutate jobs while `factory run` may be running. Pick one:
- (a) a per-job `flock` that every writer must take, or
- (b) CLI commands only append to a `commands.jsonl` file, which the orchestrator reads.

(b) keeps the invariant real. Also add a global lock so two `factory run` processes can't drive the same job.

**2. The resume rule is unsafe.** "Artifact exists and parses → advance" will advance on:
- a half-written `build.md`,
- a builder that wrote `build.md` and then crashed before committing,
- a stale review file left from an earlier round.

Instead:
- Append a `run_started{run_id, role, round, pid/pgid}` event before launching, and `run_finished{exit, artifact_sha256}` after.
- Advance only on `run_finished`.
- Have agents write to `runs/<run_id>/`. The orchestrator copies verified artifacts into place.
- On restart, kill or reap orphaned process groups first. Otherwise an orphaned builder keeps editing the worktree while a fresh one starts.
- Reset the worktree to the last recorded `head_sha` before rerunning a build. `prompt_retries` on a builder is not idempotent without this reset.

**3. Make the events log the source of truth.** Treat `events.jsonl` as the record and `job.json` as a snapshot rebuilt from it. You already write both, so make the direction explicit.

**4. Side effects aren't idempotent.** GitHub comments, labels and merges will repeat after a resume. Give each side effect an event ID and check for it before acting, like an outbox.

**5. The state diagram has holes:**
- `paused_quota` always goes back to `spec`. It needs a `resume_state` and should return to wherever it paused.
- `failed → spec` reruns the whole job. Retry should rerun only the failed step.
- `approve` has no failed or paused exits. `cancelled` isn't in the diagram at all. `queued` can't be cancelled.
- `ready` doesn't handle base drift: main moves and the merge conflicts. Add a stale/rebase check before `merged`.
- Nothing cleans up worktrees on `merged`, `abandoned` or `cancelled`.

**6. Read-only is not a sandbox.** A reviewer running in a "throwaway copy" still has a shell, network access and your `$HOME`. The builder runs arbitrary repo code by design, and it inherits your env: the `gh` token (which can push or merge) and `AGENT_WEBHOOK_*`. Minimum fix:
- Run every role with a scrubbed env.
- Use a separate push-only token, or none at all, with the orchestrator doing the push.
- Add bwrap or a container in the first release that runs unattended.
- Bind `factory serve` to 127.0.0.1. `http.server` serves the whole directory, including logs that may hold secrets.

**7. The orchestrator must check the builder's output itself.** "Deterministic" means it doesn't take the builder's word. It should:
- run `verify` itself in the worktree,
- check that commits exist on a branch descending from `base_sha`,
- reject diffs that touch `factory/`, CI config or lockfiles unless the spec allows it.

## P1: design weaknesses

**8. First-line verdict parsing is brittle.** Agents add preamble. Have each role also write a small `verdict.json` (`{verdict, reasons[]}`). Treat a missing or unparseable verdict as CHANGES, then retry once.

**9. The rework loop will churn.** For round N+1, reviewers need the diff since round N plus their own earlier review. Otherwise they re-review from scratch and contradict each other (UX vs code). Give the builder one merged list of findings with the reviewer quoted, not four raw files.

**10. The approver adds little.** If every reviewer passed and a human merges anyway, an LLM approver costs an Opus call to tell `ready` from `needs-human`. Cut it in v1: all PASS → `ready`. Bring it back only if auto-merge is ever enabled.

**11. Cost guards are mostly unenforceable as written:**
- USD only works for agents that report cost. Budgets mixing USD, tokens and call counts can't be compared or summed.
- Hard caps should be things you can always measure: wall-clock seconds and call count per job and per day. Treat USD as advisory.
- The budget is checked only between calls, so one 30-minute builder call can blow through it. Base the per-call timeout on the remaining budget.
- The daily cap only blocks `next`. In-flight jobs need a check too.
- Rough scale: 4 reviewers × 3 rounds plus Opus spec and approver is about 16 calls per job. The example `roles.toml` (Opus for spec) contradicts the cheap-first rule in §8.6.

**12. Guards land too late.** M6 is too late. M1 already runs real agents unattended, so basic timeouts, call caps and the daily cap belong in M1.

**13. Fallbacks undermine Goal 1.** A silent swap to `cline` breaks model comparison and changes cost. For v1, pause instead of falling back. If fallbacks stay, mark those runs and leave them out of the stats.

## Dashboard

- Put a "Needs you" section at the top: needs-human, ready, failed, paused, each with a one-line reason and age. That's what you'll actually look at in a minute.
- A table beats 8 kanban columns when there are 1–2 parallel jobs.
- Add stuck detection: running state with no heartbeat or log growth for more than N minutes means the job is stuck. A static board can't tell "working" from "hung" any other way.
- "Self-contained, no build step" plus markdown rendering means you either vendor an MIT library (e.g. `marked`) or show `<pre>`. Decide now.
- The model comparison view: with tens of jobs the numbers are noise. Cut it until you have a few hundred runs.
- UI actions, even on localhost, need a CSRF token if they ever ship.

## Cut from v1

- Approver role
- UI/UX reviewers (off by default; v1 runs security + code)
- Spec-kit vs OpenSpec bake-off: use plain markdown, add a tool later if specs are actually the bottleneck
- GitHub Issues backlog: `factory run "<feature>"` is enough. Add M4 once the loop is reliable.
- Fallback agents
- Parallel jobs: `max_parallel_jobs = 1` until crash-resume has been tested by actually killing it at every state
- SSE, live log tail, UI actions, model comparison

That leaves M0 + M1 + M2 (with guards and sandboxing folded in) + M3.

## Suggested answers to the open questions

1. Start in `kool-ade/tools/factory` and split it out once its interface with `acp-run` settles.
2. Never auto-merge in v1.
3. Plain markdown spec.
4. Cheap models everywhere except security. Set hard call and time caps before setting USD caps.
5. Security and code reviewers on by default.
6. Local CLI first. GitHub Issues later. Skip `backlog.md`.
7. A failed reviewer blocks, with one automatic retry. Make it skippable only through an explicit `factory approve --skip-reviewer X`, which gets logged.

## Test plan to add to the doc

Kill the orchestrator with `kill -9` at every state and in the middle of every run, then check:
- no duplicate side effects,
- no orphaned agent processes,
- the worktree matches `head_sha`,
- the job finishes.

That one test proves Goal 3, and most of the P0 problems above will show up while doing it.
