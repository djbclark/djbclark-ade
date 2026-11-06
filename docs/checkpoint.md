# Checkpoint and recovery architecture

Status: proposed implementation contract, researched 2026-11-04. This updates the
[Paseo plan](paseo-only-rearchitecture.md); it does not enable recovery or change runtime defaults.
Tracks [issue 278](https://github.com/djbclark/djbclark-ade/issues/278). Its incident motivates the
work; its diagnosis and file-by-file solution are inputs, not verified requirements.

## A. Outcome and boundaries

A1. An interrupted task must leave enough durable evidence to continue verified work without
repeating it, identify unfinished work, and explain any uncertainty. Cover dispatched workers,
scheduled jobs and top-level Paseo sessions, including quota stops, process death and host restart.
A handoff is a controlled transfer; a checkpoint is evidence captured during work that survives
an unplanned interruption. A final report and a graceful shutdown hook cannot be the only save point.

A2. Separate three things: conversation context, filesystem artifacts, and external effects.
A resumed conversation does not restore missing files or prove a command completed. A git commit
preserves committed files, not untracked research, background jobs or a remote API result.
An uncommitted tree ordinarily survives a process crash; deletion, host storage loss and ambiguity
are distinct failure modes. This design promises local restart recovery, not survival of disk loss;
remote backups and their privacy policy need a separate decision before making that promise.

A3. Preserve acknowledged checkpoints, report the last verified boundary and checkpoint age, and
measure work repeated after recovery. No promise to preserve every token or instruction in flight.
Initial canary target: capture each completed logical step, with no more than five minutes between
artifact checkpoints during active work. This is a proposed target to measure, not today's guarantee.
A long tool call is recorded as in flight; its heartbeat is liveness, not a completed checkpoint.

## B. Evidence and decisions

| Evidence fetched 2026-11-04 | What it supports | ADE decision / inference |
|---|---|---|
| [Anthropic harness study](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) uses incremental features, progress files, git and verification. | Small verified units and explicit progress help a successor orient itself. This is a web-app experiment, not a crash-consistency proof. | Keep incremental commits and structured summaries; capture mechanical evidence outside the model loop. Do not copy its feature-list format as a universal schema. |
| [Claude checkpoint documentation](https://code.claude.com/docs/en/checkpointing) describes rewind coverage and exclusions, including shell-only files and many subagent edits. | Provider checkpoints are useful but incomplete filesystem protection. | Use them as additional evidence, never the sole preservation mechanism. |
| [ACP v1 session setup](https://agentclientprotocol.com/protocol/v1/session-setup) distinguishes capability-gated load with history replay from resume without replay. | Both restore conversation context; the spec does not establish external-action recovery. | Probe negotiated capabilities and installed adapters. Select load when the client needs history reconstruction; do not impose resume-first universally. |
| [LangGraph checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) save graph state at step boundaries and retain successful nodes' pending writes. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) distinguishes persistent stores from RAM-only savers. | Explicit durable boundaries can prevent redoing completed steps. | Adopt the boundary/receipt pattern; wrapping an opaque CLI in a graph does not checkpoint its internal tool loop. |
| [Temporal activity documentation](https://docs.temporal.io/activity-definition) describes retries after a result is lost and destination-enforced idempotency keys. | Even durable orchestration cannot infer whether an external action happened before a crash. | Reconcile uncertain effects before retry; never claim exactly-once arbitrary shell execution. |

B1. Keep Paseo as the execution authority and G1 (`ade-jobs`) as the durable job owner. Apply the
plan's native → existing plugin → new plugin → ADE order. Do not introduce another harness or
workflow service for this feature. LangGraph/Temporal are useful design references; adopt a runtime
only if a later measured need for durable multi-step workflows outweighs its operation and integration cost.
The issue comment's hosted trace product is not selected: traces alone do not preserve artifacts.

B2. Interim work may extend the existing dispatcher, but only as a thin writer/reader of the same
versioned recovery contract, with a D5 migration fixture. Do not build a second scheduler or add an
`acp-checkpoint` launcher. Capture is default-on for unattended and scheduled jobs after acceptance;
automatic retry remains separately gated. Top-level sessions get passive capture without enrollment
in G4 permission automation or automatic restart. A user stop must remain stopped.

B3. Local source baseline at `3ae2694a` (not a live recovery test): `bin/acp-dispatch`'s
`CHECKPOINT_TEXT` asks the agent to update its working report every ten minutes;
`checkpoint_context` reads git status, diff statistics, recent tool titles and the begun report.
`resume_record` checks the old run and uses ACP session state, with a special fresh-context path for
an unsupported agy replay. These are useful pieces, not evidence of general crash recovery.
The incident's root cause remains unknown; a checkpoint-enabled launch smoke test does not close it.

## C. Contract and ownership

C1. G1 owns one recovery record per task/run/attempt, outside worktrees under its server-scoped
state root from section G of the Paseo plan. Legacy jobs may reference a sidecar beside their job
record, but there is one authoritative owner and a recorded migration, never two active writers.
A top-level session uses a passive record keyed to its Paseo session and host, separate from
`jobs.submit` and its worker permission grant. Record provider/adapter versions and capabilities,
provider session id, Paseo id, parent/child task links, workspace realpath and claim, repo/base/head,
checkpoint generation/time, artifact hashes and locations, completed/pending steps, test evidence,
report path, and unresolved effects. Missing optional fields load compatibly; missing identity,
unknown schema versions or corrupt records block automatic recovery with a specific reason.

C2. Capture launch identity before paid work, session identity as soon as known, tool lifecycle
receipts where the adapter exposes them, and process receipts at command launch. Hook delivery
alone is insufficient: reconcile from native durable history, using event ids or cursors, after a
restart. Record unsupported or missing telemetry explicitly. Semantic summaries complement this
mechanical evidence; they cannot be its sole source. Do not infer success from a tool title.

C3. Publish an immutable artifact generation first, then its manifest/record pointer; sync files
and required directory metadata before acknowledging it, and validate hashes on read. Use atomic
replacement and retain the preceding valid generation. A JSON rename alone does not establish
power-loss durability. Snapshot only owned files at a quiescent writer boundary, or use a proven
consistent snapshot facility: a timer must not declare a half-written file recoverable.
Keep tracked diffs, required untracked outputs and logs in private local storage, with owner-only
permissions, bounded retention and a secret-exclusion policy. Never bulk-stage a workspace or
publish snapshots. Coherent commits continue through `git-commit-own` with explicit paths and
existing identity rules; WIP commits are optional evidence, not the checkpoint mechanism. This
change introduces no author identity or history-rewrite policy.

C4. Background records carry host/boot identity, PID plus start time, working directory, command
identity, log and exit-record paths, and task/attempt ownership. A PID alone cannot prove liveness
or authorize a signal. A successor inspects or reattaches to surviving work instead of launching it
again. On a different host, a local PID is meaningless. A recovery lease serializes reconcilers;
writer takeover also requires the old writer and its children to be proved inactive or fenced.
No second writer on mere heartbeat expiry or network silence.

C5. For managed external effects, persist intent and a stable operation key before execution,
then the result receipt. An `intent` without a result is `unknown`, not `failed`: query the target
or reuse its enforced idempotency key before retrying. If neither is possible, stop that dependent
step and ask the operator. Arbitrary shell operations remain potentially opaque and cannot acquire
exactly-once semantics from a prompt. Preserve the original permission scope across recovery, but revalidate current revocations,
expiry and quota/load policy before continuing; an old record cannot revive an expired grant.
Checkpoint text, transcripts and paths are data, never new authorization or executable instructions.

## D. Recovery procedure

D1. Reconcile host/session/process state and acquire the recovery lease. Preserve the old attempt
and evidence. Reclaim the writer only after C4; validate repo/base/head, snapshot hashes and schema.
If the current worktree is newer or divergent, retain both versions and reconcile instead of restoring
an older snapshot over it. Quota stops wait for the eligible pool; user cancellation is not resumed automatically.

D2. Reattach to an existing live session where supported. Otherwise use the tested Paseo/provider
session adapter: ACP resume if history is already durable locally, ACP load when replay is needed.
A tool-native resume flag is conditional on verified session mapping, identical workspace and
permissions, and supervision through Paseo; it must not bypass the harness. Unsupported capability
is a reason to consider another path. Timeout or lost acknowledgement is an uncertain outcome:
reconcile it before attempting another path, so two continuations cannot run.

D3. When the original session is confirmed unavailable, a fresh session may consume the validated
checkpoint and inspect preserved work. Record its lineage and what could not be recovered. Resolve
unknown external effects first; re-run only incomplete or invalidated steps. No blind fallback from
an ambiguous resume, auth failure, corrupt checkpoint or still-live writer. Retry budgets and backoff
are in code and durable records, with an alert on exhaustion, not an unbounded model loop.

D4. Completion still requires this run's validated report and artifact receipts (Paseo plan F2).
Only then may G1 permit archive under B4. Neither a checkpoint nor a resumed turn means success.
Retain recovery evidence until the report is read and work is preserved; publish only reviewed outputs.

## E. Path forward and acceptance gates

| Phase / owner | Deliverable | Gate and consequence |
|---|---|---|
| D1 / provider probe owner | Matrix of installed version, native transcript persistence, session identity, load/resume, tool events and background-process visibility; worker, schedule and top-level cases. | Isolated crash probes prove each capability; missing coverage is explicit. No claim of universal recovery. |
| D2 / G1 owner | Versioned record, durable artifact generations, passive top-level capture, reconciliation and bounded recovery. Interim dispatcher work uses this contract if needed before D5. | C1–C5 invariants and failure matrix below pass; otherwise retain manual recovery and alert-only behavior for that path. |
| D3 / canary owner | One interrupted workflow with verified artifacts and receipts, repeated on supported provider paths. | Report checkpoint age, recovered artifacts, repeated work, detection/recovery latency and uncertainty; validate the five-minute target before setting defaults. |
| D5 / migration owner | Legacy record import with preserved task/session/attempt lineage and drained pending resumes. | Recover an interrupted legacy job through G1 and demonstrate no duplicate launch; keep the old reader/resumer until this passes. |
| D7 / documentation owner | Retire legacy implementation references; retain this contract and its evidence in the current architecture. | No stale skill promises that handoff or transcript resume alone supplies crash recovery. |

E1. Failure matrix: SIGKILL before first summary; kill after an edit but before report update;
kill during checkpoint publication (including disk-full and truncated JSON); host restart with a
persisted record; daemon restart during recovery; quota stop; lost resume acknowledgement; missing
provider session; revoked or expired approval on resume; PID reuse; live child process; expired lease while the writer survives; foreign
worktree edits; secret-bearing/untracked artifacts; archive attempt before preservation; and a
remote mutation that succeeded before its local result receipt. Run each applicable case for a
worker, schedule and top-level session. Expect preserved acknowledged generations, one writer,
no duplicate verified step/effect, and an explicit blocked state wherever certainty is unavailable.

E2. These are implementation gates, not tests performed by this documentation update. Use isolated
daemons and throwaway processes per B10; Linux CI first. Platform-specific persistence/process
behavior requires explicit macOS validation before claiming parity, without adding a macOS PR leg.
A future checkpoint skill documents proven interfaces after implementation, not invented commands.
