# Checkpoint and recovery architecture

Status: proposed implementation contract, researched 2026-11-04. This updates the
[Paseo plan](paseo-only-rearchitecture.md); it does not enable recovery or change runtime defaults.
Tracks [issue 278](https://github.com/djbclark/djbclark-ade/issues/278). Its incident motivates the
work; its diagnosis and file-by-file solution are inputs, not verified requirements. Section F (2026-11-04) inventories what Paseo itself provides.

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
an older snapshot over it. Quota stops wait for the eligible pool; user cancellation does not auto-resume.

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

## F. Paseo-native capability inventory (2026-11-04)

Facts below are from upstream source at getpaseo/paseo master `5d1a2c1` (CLI 0.15.0), read on
2026-11-04. They are not a live probe: the operator's daemon is 0.14.x, and D1 confirms them.

F1. What Paseo persists. Each agent is one JSON record at `$PASEO_HOME/agents/<cwd>/<id>.json`
(default `~/.paseo`), written by temp file and rename (`docs/data-model.md`). A record holds
`lastStatus` (initializing, idle, running, error, closed), a `persistence` handle (provider,
sessionId, nativeHandle), labels, `archivedAt` (a soft delete), `lastError` and config. Schedules
are in `$PASEO_HOME/schedules/<id>.json`; finish-notification intent is in
`finish-subscriptions.json`. Paseo does not store transcripts: the daemon keeps timeline items in
memory, and provider history is the durable authority (`docs/timeline-sync.md`). Queued prompts
are in memory only; a clean shutdown flushes them, but a crash can lose them.

F2. Restart behaviour. At startup, `prepareStartup` (`server/agent/restart-recovery/index.ts`)
rewrites any stored `running` or `initializing` status to `closed`, not `error`, before plugins
start. A `closed` agent is persisted and resumable. `paseo send <id>` resumes it implicitly;
`paseo agent reload <id>` restarts the process and resumes the durable session under the same
Paseo id; `paseo agent import <sessionId> --provider P --cwd` adopts an outside provider session.
ACP agents use `session/load` when advertised, else `unstable_resumeSession`. The unfinished turn
is not resumed and is lost. There is no `paseo resume` command. The global
`agents.resumeOnStartup` (default OFF) sends one prompt (`Resume working.`, or
`agents.resumePrompt`) to each agent that was running. It is best effort, with no retry and no
exactly-once guarantee, and it cannot exclude a session. Not recommended here: it overlaps F4.

F3. Plugin hooks and their limits. Hooks relevant to recovery: `agent.create.after`,
`agent.turn.before`, `agent.turn.after` (its outcome covers success, failure and `canceled`;
`timeline` is deprecated and always empty), `agent.close.after` and `agent.archive.after`.
Notification delivery is live and best effort: no replay, no persistence, no automatic retry.
Waiting hooks time out at 30 s. There is no daemon-start hook and no per-tool-call hook; tool calls
come from a timeline refetch after `agent.turn.after`. `agent.open.before` with `reason: "resume"`
fires on a post-restart resume. No dedicated reconciliation hook exists. A second source read
(2026-11-04, under review) found that plugin entry code (`contribute()`) receives no SDK handle,
only hook and RPC contexts do, so a startup reconcile must run lazily on the first hook or RPC;
that `prepareStartup` runs before plugins start, so a plugin never sees Paseo's own `running`
state after a restart; and that registering `agent.open.before` makes Paseo invalidate open
sessions when the plugin starts or reloads. D1 confirms all three on the live daemon version.

F4. Community plugin `sm1ee/session-recovery` (16ba577, 2026-10-30), audited read-only on
2026-11-04 from source; nothing was run. Verdict: ADOPT-WITH-SETTINGS. It listens to turn,
permission, close and archive events and journals them at
`<PASEO_HOME>/plugin-data/session-recovery/state.json`, written atomically (temp file, sync,
mode 0600, rename). Intent is written as `sending` before each send. An uncertain send goes to
`review/uncertain_send` and is never replayed. Attempts (default 3; 60 s delay doubling to a
15 min cap; refused after 24 h) survive restarts. `holds.json` lists open records for
`session-janitor` to skip. The plugin never archives or deletes; it makes only localhost calls.
Its default `enabled=true` restarts top-level sessions after a daemon restart, which B2 allows
only with the operator's approval. Edge case: a user stop during daemon shutdown is treated as an
interruption (`shuttingDown()`), so it can be continued. Recommended: `enabled=false` until
approved; `recoverSubagents`, `retryTransientErrors` and `continueGoals` off; no companion
preloads; an explicit `daemonHome`; Paseo at least 0.11.4 with receipts advertised. Installing it
is an operator decision (AGENTS.md order 11). It is not installed by this change.

F5. The recovery ladder, in the plan's native, existing-plugin, new-plugin order. (1) Paseo-native
`paseo send`, `agent reload` and `agent import` are the resume mechanism (F2). (2)
`sm1ee/session-recovery` gives automatic continuation once approved (F4), with `enabled=false`
until then. (3) Passive capture of artifact evidence (repo, base and head, dirty-tree hash,
untracked paths, interruption evidence; tool-call receipts are deferred to G1) by an ADE plugin. It is
`plugins/ade-recovery` (section G), a standalone passive plugin whose records G1 reads later
(kept separate because G1's future `agent.open.before` tools would make every capture fix reload
idle agents).

F6. Legacy `acp-dispatch --checkpoint` (CHECKPOINT_TEXT, stale-report check, ACP resume/load,
fresh-session fallback via checkpoint_context) is frozen as of 2026-11-04. It keeps working for
dispatched slices until D5 replaces `acp-dispatch`, gets no new features, and its resume ladder
is superseded by F5. Tracked in [issue 278](https://github.com/djbclark/djbclark-ade/issues/278).

## G. Interim implementation: ade-recovery v1 (2026-11-04)

Code and tests: `plugins/ade-recovery` (OVERVIEW.md, `server/types.ts`), reader `bin/paseo-checkpoint`.
Issue 278. Status and the probes it depends on are in G.8.

G.1. What it captures, per agent, in one record:
- identity: serverId, Paseo agent id, provider, cwd, host, boot id, platform, workspace and parent ids.
- persistence: `sessionId` and the sha256 of the native handle. The handle itself is never written.
- lifecycle: state, daemon instance, `closedAt`, `archivedAt`.
- the last 20 turns, with outcome codes only.
- git evidence: repo top, linked-worktree flag, branch, head, and base (merge-base with origin HEAD,
  or recorded at create).
- tracked fingerprint: sha256 over path and blob id from `git hash-object --no-filters` (no `-w`)
  for each tracked change against HEAD.
- untracked paths (capped, redacted names) and a stat fingerprint over path, size and mtime.
  Contents are never read.
- interruption history, last 20. A later turn never clears it.
- `missingTelemetry`: each field it could not read, with the reason.

G.2. What it never does:
- send a prompt, reload, archive, create, close or interrupt an agent;
- call `timeline.refetch`, which loads provider history and can start a provider;
- write to git: no stage, commit, stash, reset, or `hash-object -w`;
- store tool calls, titles or command lines.

G.3. Hooks: exactly five notification hooks: `agent.create.after`, `agent.turn.before`,
`agent.turn.after`, `agent.close.after`, `agent.archive.after`. It does not register
`agent.open.before`, because that makes Paseo invalidate open sessions on every plugin start or
reload (F3; [`skills/ade-paseo-plugin/SKILL.md`](skills/ade-paseo-plugin/SKILL.md), "In this repo").

G.4. Where records live:
`${ADE_STATE_ROOT:-${XDG_STATE_HOME:-~/.local/state}}/ade/<serverId>/ade-recovery/recovery/v1/<agent>.json`,
with the previous generation at `<agent>.prev.json`. Files are 0600 in 0700 directories. A
`writer.lock` names the writer by pid and start token. Each record carries a sha256 integrity
digest; a corrupt current file falls back to `.prev.json`.

G.5. Verdicts (`bin/paseo-checkpoint show` and `list`):
- `resumable-native`: only when the last turn ended cleanly, was observed, the tree still matches,
  and no interruption came later.
- `needs-review`: an interrupted turn, and any case that is neither of the other two. `--no-live`
  also gives this verdict.
- `do-not-resume`: a user stop or an archive.

G.6. Shutdown detection: `$PASEO_HOME/local-credential` is present while the daemon runs and absent
once it shuts down. A turn cancelled while it is absent is recorded as `canceled-during-shutdown`
evidence, not as a user stop.

G.7. CLI, read only:
- `bin/paseo-checkpoint list [--json] [--server-id S] [--no-live]`: one line per recorded agent.
- `bin/paseo-checkpoint show AGENT_ID [--json] [--server-id S] [--no-live]`: verdict, reason codes
  and evidence for one agent.
- `--no-live` skips live git against the record's cwd, so the verdict then needs review.
- Exit codes (show): 0 resumable-native, 1 needs-review, 2 do-not-resume, 3 not found, 64 usage
  error. Exit codes (list): 0 ok, 64 usage error.
- Environment: `ADE_STATE_ROOT` / `XDG_STATE_HOME` (state base), `PASEO_HOME` (default `~/.paseo`).

G.8. Status (2026-11-04): not installed on any daemon. Installing a live plugin waits for the
operator's yes (AGENTS.md order 11). Tests: `bin/pytest -q tests/test_ade_recovery_plugin.py`.
D1 must confirm these probes on the operator's daemon first:
- the SDK handle is usable after a hook returns;
- `hosts.list` is permitted to the plugin;
- `local-credential` is present while the daemon runs;
- Paseo's compiler accepts `.ts` relative imports;
- `process.ppid` is the daemon;
- shutdown hook order.

G.9. Deferred to G1: tool-call receipts, C5 effect receipts, artifact snapshots, retention, and an
RPC for reading records.
