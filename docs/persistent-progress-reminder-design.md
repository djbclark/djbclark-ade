# Persistent progress reminder — design, 2026-11-12

## A. Decision and bounded outcome

A1. **Design only.** The operator selected a persistent, cheap progress reminder
in the [audit walkthrough](https://github.com/djbclark/djbclark-ade/blob/bc745559008d43c6b6ae2aa1bfb675c55bfd6d7d/docs/slim/audit-walk-decisions-2026-11-12.md#L8).
This proposal adds no executable, job, plugin, runtime setting or send. The source
base inspected is `dc3463b16c400a3c7af00a4aef3a8cbb4a0e1276`.

A2. Proposed first implementation: one deterministic ADE utility and a private
local inbox, driven by the existing host scheduler. It checks **explicitly
declared unfinished work**, records a notice on a meaningful change or due time,
and makes delivery uncertainty visible. No model runs in the poller. A notice
does not complete work, authorize repair or prove that a person read it.

A3. Keep `/watch load`, `/loadwatch`, load-watch and process deadlines intact.
Do not restore old relay/self-slash dependencies, self-deploying checkouts,
mailbox crawling, automatic session creation/restart, permission answers, mode
changes, model switching or automatic review/merge. Other selected walkthrough
capabilities retain their own implementation owners and gates.

## B. Evidence and facilities to reuse

| Item | Inspected behavior | Design consequence |
|---|---|---|
| [Old rumination-watch](https://github.com/djbclark/djbclark-ade/blob/fb3b9deb044cfde79cdc7ab2623224e2d8d7658a/bin/rumination-watch) | No-model change/due checks; idle plus declared next steps; cooldowns; ancestry-aware handoff check. Also legacy relay, self-deploy and optional seat waking/creation. | Recover the cheap checks and durable uncertainty handling; omit those runtime actions. Mere quietness previously missed idle work for hours. |
| [deadline agent checks](../bin/deadline) | `paseo ls -g --background --json`, inspect `UpdatedAt`, age threshold and cooldown. Current sender permits closed agents; idle-alert cooldown is recorded before its detached sender finishes. | Reuse source-shape lessons, not its alert/delivery implementation. Timestamp age alone does not prove idle, unfinished work or notification. Do not disable process enforcement. |
| [ade-sched](scheduling.md) | Host shell jobs use launchd/systemd/cron; agent judgment uses Paseo schedules. Reconcile has ownership/readback and linked-worktree guards. | A deterministic five-minute sweep belongs in ade-sched, not a paid agent schedule. Proposed new label: `com.djbclark.ade-progress`; retain the retired rumination label. |
| [ade-recovery-d1](../bin/ade-recovery-d1) | Read-only runtime/prerequisite measurement, not a recovery guarantee. | Re-probe installed native capabilities before accepting a delivery adapter. |
| Native Paseo source, pinned [lifecycle](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/docs/agent-lifecycle.md) and [prompt path](https://github.com/getpaseo/paseo/blob/4df5307eaab6b22d06fe54a45c68211b3413f45c/packages/server/src/server/agent/agent-prompt.ts) | Idle/running are live states; closed records can retain resumable sessions. Prompting loads a stored runtime and starts work; steering can fall back to replacement. | An idle preflight followed by ordinary `paseo send` cannot guarantee no restart/interruption. The target can close/change between calls. |
| site-djbclark `bin/hermes-ping` / `bin/inbox-target` | Local source inspection found registered destination resolution and eventual `hermes send`; no independent delivery/readback contract in the wrapper. | Do not infer human delivery from exit zero, hard-code a chat/topic, copy the helper or alter that repository. A future adapter needs its own verified receipt/readback. |

B1. No `paseo` executable was available on this cloud host. The upstream source
pin is **not** the installed Mac version or a live compatibility result. No
daemon, skill link, scheduler or notification endpoint was exercised. The graft
CLI was unavailable; inspection used the named source and historical git blobs.

## C. Small input and deterministic checks

C1. **Explicit enrollment.** Proposed `ade-progress declare` records an obligation
for an exact task, host/user and `{server_id, agent_id}`. Required fields are a
unique task ID, generation, nonnegative `pending_count`, state (`open`, `waiting`
or `retired`; unfinished states require a positive count),
creation/update time and `review_after` UTC. Optional fields name a checkpoint,
one workspace realpath/claim and recorded commit, a known deadline, or an existing
producer receipt. A declaration does not grant authority to run that receipt's
commands. No enrollment means no inference that an arbitrary quiet agent has work.

C2. Declarations live outside worktrees in
`~/.local/state/djbclark-ade/progress/v1/`, owned by the user (directory 0700,
records 0600). Only the explicit owner/orchestrator changes a declaration;
generation checks reject stale updates. Handoff retargeting requires the separate
handoff protocol's successor acknowledgement, never a guessed replacement agent.
Retiring an obligation stops reminders; it is not product acceptance evidence.

C3. Proposed checks, each returning `clear`, `changed`, `due` or `unknown`:

| Check | Deterministic trigger | Suppression/limit |
|---|---|---|
| Due unfinished work | Declaration remains open with positive pending count and `review_after <= observed_at`. | An explicitly waiting task gets a due review notice, never an instruction to bypass its blocker. No free-text TODO inference. |
| Idle with declared work | Same declaration is open; exact unarchived, live native agent is positively idle, has no pending card/turn, and has been unchanged for 30 minutes. | Missing activity, busy, closed, errored, ambiguous identity and provider uncertainty are not idle. Active declared deadline/background work suppresses the idle notice. |
| Stale handoff/checkpoint binding | Explicit checkpoint's recorded commit cannot be reconciled with the one enrolled workspace at/after its review time. | An ancestor of HEAD is normal advancement, not stale. Shallow/missing history, missing file, multiple mappings or git failure is unknown; never fetch/reset or read another workspace to guess. |
| Registered receipt changed | A bounded, versioned producer fact for that task/attempt/head changes state. | No raw PR bodies, transcripts or broad open-PR polling. Invalid/missing producer data stays unknown. Producer authority decides completion, not this utility. |

C4. Cheap defaults: five-minute cadence; at most 16 declarations, four native
inspects and 45 seconds per pass. Batch one native list; inspect only candidates;
bound each subprocess by the remaining pass budget (argv lists, no shell).
Cache unchanged local facts by identity/generation, not solely mtime. Persist a
round-robin cursor so overflow cannot starve later tasks. Unscanned tasks are
explicitly partial, never resolved. No model call, transcript indexing, recursive
workspace scan, process attribution or routine network request is part of a pass.

C5. A fixed notice template carries task ID, count, reason enum, observation
age and a local evidence reference. It does not copy a next-step paragraph or
execute instructions found in a checkpoint/remote artifact. Bare age/unknown
source-health problems are combined into one health notice on transition, not
one page per task. Clock rollback/nonfinite/future observations suppress sends
and record clock uncertainty; they do not reset cooldowns or invent elapsed time.

## D. Notices, cooldown and verified delivery

D1. First implementation publishes to the **local durable inbox only**. Proposed
commands (not implemented) are `declare`, `scan`, `inbox`, `ack` and `retire`.
State-changing commands default to `--dry-run`; explicit `--yes` is required.
`scan --dry-run` prints the plan without creating state/locks or contacting a
delivery endpoint; `inbox` only reads records. Read-only native observations, when
requested, must be reported separately from a fully offline plan.

D2. An event key binds host/server, task, declaration generation, reason and
relevant evidence fingerprint. A scan tick, updated observation timestamp or
unrelated commit is not a new event. Defaults: a newly changed condition is
recorded once; an unresolved due/idle condition can produce another reminder
after three hours, with at most one inbox digest per pass. Explicit snooze moves
the next review time; acknowledgement records receipt and its generation, not
task completion. A genuinely changed blocker can supersede an older pending
notice; generations prevent an old acknowledgement hiding it.

D3. Delivery states are distinct:

| State | Evidence / permitted claim |
|---|---|
| `prepared` | Durable intent; no send claim. |
| `published-local` | Atomic inbox artifact read back with matching notice ID, generation and content hash. Delivered to the local inbox only; user/agent has not been proved notified. |
| `attempting` | External invocation may occur; outcome not yet known. |
| `accepted` / `queued` | Endpoint accepted work; delivery remains pending. |
| `delivered-transport` | Adapter-specific authoritative receipt/readback matches the exact endpoint, recipient and notice. Does not prove reading or work completion. |
| `acknowledged` | Explicit authenticated recipient acknowledgement matches notice/generation. |
| `unknown` | Timeout, crash, malformed/mismatched receipt or possible acceptance; no blind resend. |
| `not-accepted` | Structured adapter evidence proves no admission; bounded retry is allowed. |

D4. Local publication and external notification have separate cooldowns and
receipts. Only verified inbox readback advances the inbox publication cursor;
only verified external delivery advances that route's delivered cooldown.
Failed/unknown publication cannot silently count as told. An unknown external
send remains visible in the local inbox and awaits receipt reconciliation or an
explicit owner retry that records the prior uncertain attempt and duplicate
risk; no exactly-once external-delivery claim or automatic alternate-route replay. Provably unaccepted
attempts may retry after 5/15/60 minutes (three attempts), then remain unresolved.

D5. **Automatic agent prompting stays unavailable unless a native adapter can
atomically admit only to the exact already-live idle runtime without loading,
unarchiving, replacing, resuming or answering permissions.** Plain inspect then
`paseo send --behavior steer` does not meet that condition. Recheck identity,
declaration generation, pending permissions and native runtime revision in the
same admission operation. Without demonstrated native support, keep the event
in the inbox and say `agent_delivery=unavailable`; do not build an ADE sidecar
that races the daemon. A future non-waking operator-notification adapter can be
qualified separately with a registered destination and message-ID readback.

D6. This limit matters: an inbox-only MVP persists useful reminders but **cannot
promise to attract attention or keep a stopped session moving**. It is not a
replacement for an operator channel until that channel's receipt contract is
proved. It can observe a stopped session and show a due obligation without
waking it. No new automatic restart authority is inferred from historical
rumination-watch's optional auto-seat behavior.

## E. Recovery, persistence and adjacent capabilities

E1. Use a stable nonblocking per-host/user lock over fresh reads, event selection
and state publication. Each notification attempt has an immutable ID/receipt;
write pending intent before effects and atomically replace state beside its
destination. Two workers cannot send the same attempt concurrently. Lock busy
exits without effects; OS process exit releases it. A crash does not authorize
repeating a possibly admitted send. Corrupt state is preserved and reported;
no empty-state fallback or automatic reconstruction from vague prose.

E2. On restart, reconcile exact local artifact IDs/hashes before marking them
published. A crash after rename/before recording publication must discover that
same artifact rather than produce another notice. An interrupted external
attempt becomes unknown until adapter readback resolves it. A retained receipt
can settle delivery, never complete the subject task. Superseded/retired tasks
retain their attempts; do not replay them to a successor or another host.

E3. The scheduler runs an explicit `scan --yes` from a durable checkout through
normal ade-sched inventory/ownership/readback. This PR adds neither that row nor
a plist. No self-fetch, checkout movement, self-update or implicit backend switch.
Host sleep/offline time is unavailable time: coalesce missed ticks into one
current evaluation after wake, not a burst of historical sends. Report scanner
build SHA, last successful local scan, per-source freshness and last verified
delivery separately. A local scanner cannot detect its own host outage; a
separate observer would require a separate contract. A loaded timer alone is
not evidence of successful scans or received notices.

E4. Keep interfaces narrow instead of adding a workflow/event framework:

| Capability owner | Reminder integration | Outside reminder authority |
|---|---|---|
| Quota recovery | Later validated fact with pool ID, observation time, advisory level and next reset/review time; waiting-for-quota suppresses idle nudges. | No credential values, inferred quota, provider switch, spending profile change, resume or acceptance flip. Quota feature recovery stays selected, not silently dropped. |
| Handoff/recovery | Exact task generation and verified successor binding; stale checkpoint notice. | No successor creation, predecessor archive or continuation. A session-local watchdog is not a persistent scanner. |
| Review coordination | Immutable attempt/head, provider availability and due review receipt from its owner; changed/due notice. | No launch, invented verdict, marker, thread resolution or merge. An unavailable review is not a completed review. |
| Existing deadlines/load-watch | Respect declared active work and reference their own incident/deadline IDs. | No process kill/throttle or duplicate ownership of deadline enforcement. |

E5. Before enabling external idle notices, qualify **one** notice owner for
overlapping deadline/progress alerts. Current deadline age alerts have no shared
progress-event deduplication contract. Do not pretend otherwise or disable the
deadline sweep globally. A later targeted filter or explicit job configuration
can transfer idle-notice ownership while retaining process deadlines; until
then this design adds local inbox evidence and no second automatic agent send.
Quota/review adapters remain absent until their producer schemas and delivery
budgets are verified; no placeholder fact is treated as authoritative.

## F. Implementation and acceptance sequence

F1. First source slice: enrollment validation, pure event planner, locked atomic
local inbox and readback/recovery. Keep runtime installer/inventory absent. Add
provider-neutral fixtures rather than copying old rumination-watch or building
a generic workflow service. This design alone does not authorize implementation
or installation of the persistent reminder.

F2. Required fixture tests:

- Determinism: unchanged facts stay quiet; due crossing and material changes
  emit once; snooze, acknowledgement, retirement and generation conflicts work.
- Idle plus declared work: healthy idle alone, busy/closed/archived/error agents,
  permissions, unknown activity, active background/deadline work and stale
  provider data never trigger agent admission. No declaration means no nudge.
- Handoff ancestry: same/ancestor commit is normal; divergent/missing object and
  git timeout are distinct; no checkout mutation, fetch or cross-workspace guess.
- Concurrency/crash: two scans, stale writer, disk full, truncated JSON, crash
  around every rename/admission/receipt write, and receiver-before-sender crash
  preserve evidence and avoid duplicate attempts. Test real processes for locks.
- Delivery: queued/accepted/timeout/malformed/wrong host/recipient/notice receipts
  cannot count as delivered; ambiguous attempts never replay automatically.
  A close-between-inspect-and-send fixture must show the unqualified path sends
  **nothing**. Tests of a proposed atomic adapter are not installed-daemon proof.
- Availability/cost: cold dry-run writes nothing, absent CLI/helper/scheduler is
  explicit, capped/partial scans do not resolve unseen work, clock jumps and
  host wake coalesce, no model calls/legacy relay/git deployment/session launch.

F3. Separate later runtime acceptance: inspect installed host/CLI versions and
native schemas, qualify no-wake delivery or retain inbox-only mode, validate
normal scheduler activation and post-restart scan/readback, then exercise a
closed/idle/running/card matrix and dropped receipts in an explicitly authorized
isolated canary. Verify absence of unintended provider starts and repeated
messages. Host/operator evidence is required; source, mocks and an accepted
receipt cannot establish it. No live experiment ran for this design.
