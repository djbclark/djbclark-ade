# Persistent progress reminder — design, 2026-11-12 (revised for the operator's ruling)

## A. Decision

A1. **Design only.** The operator selected a persistent, cheap progress reminder in the
[audit walkthrough](slim/audit-walk-decisions-2026-11-12.md#1-load-monitoring-and-persistent-progress). This document adds no executable,
job, plugin, setting or send.

A2. **Operator ruling (2026-11-12, via lead 8cd86203).** When an *enrolled* agent with
*declared open work* has been idle at or past its threshold, deliver **both**: (a) one
`hermes-ping "<repo>: <one line>"` to the operator and (b) a wake of that idle agent through
native `paseo send --json --no-wait <id>` with a short nudge naming its declared work. The
primary operator-facing surface is a Paseo inbox-style UI (section D); the local inbox is the
durable record. The earlier "no send unless Paseo gains an atomic-admission primitive" rule is
withdrawn: the inspect-then-send race is acknowledged and bounded (E3), not a veto.

A3. The ruling also asked: *is there a Paseo built-in or extension for this?* Answer in section B:
**no built-in detects "idle >= N minutes with declared work" without a model turn**, so the
detector is a small deterministic script run by `bin/ade-sched`; Paseo supplies the UI surface
(Progress panel) and the wake transport (`paseo send`).

A4. Out of scope, unchanged: restoring old relay/self-slash, self-deploying checkouts, mailbox
crawling, session creation/restart, permission answers, mode/model changes, automatic review or
merge. `/watch load`, load-watch and `bin/deadline` stay intact.

## B. Paseo built-ins and extensions, checked 2026-11-12

Sources: Paseo checkout `~/src/paseo` HEAD `376be9086544a8d591533930f77ca58a9c99412c`
(2026-10-25; its CLI package says 0.13.0) versus the installed app `0.16.0-beta.2` — source
evidence only, **not** an installed-version compatibility result. Installed plugins were read, not
modified. Nothing here created a heartbeat, schedule or plugin.

| Candidate | Evidence | Idle + declared work, no model? | Delivers to agent / operator? | Verdict |
|---|---|---|---|---|
| Heartbeat (`paseo heartbeat`, MCP `create_heartbeat`) | `packages/cli/src/commands/heartbeat/index.ts:58-85`: a cron schedule whose target is the caller agent, `--max-runs`, `--expires-in`. | No. It fires a *prompt* into the agent: one model turn per firing, with no condition. | Agent only. | Rejected: a recurring model prompt (`~/CLAUDE.md` item 13). |
| `paseo schedule` / `create_schedule` | `packages/protocol/src/schedule/types.ts:20-43`: targets are `agent` or `new-agent` only. Has `run-once`, `logs`. | No. No shell target, no predicate. | Agent or a new agent. | Rejected, same reason. Stays right for judgment jobs. |
| `paseo wait` | `packages/cli/src/commands/agent/wait.ts`: returns on idle / timeout / permission / error. | It blocks on one agent; keeps no declarations or thresholds. | Neither. | Not a monitor. |
| Plugin lifecycle hooks | `public-docs/plugins/reference.md:820-839` (`agent.closed`, `turn_started`, `turn_ended`, `permission_requested`, `archived`); `docs/plugins.md:429-438`: observers run in the daemon even with no app open, and must not be awaited inside agent mutations. | Could, with plugin timers: arm on `turn_ended`, fire after the threshold. It needs new plugin code and its own declaration store. No installed plugin does this. | Could call `agent.send`; operator only through some other channel. | **Best later home** for an event-driven detector (precise, no poll). Deferred: more code, deadlock rules, a plugin contract to learn. |
| `bin/deadline` | `bin/deadline:892-915` lists agents with `status == "running"` and a stale `UpdatedAt`; `:430` calls `hermes-ping`; `:438` allows `idle/running/closed` for its own sender. | Watches **stuck-running** turns, not idle agents; it has no declarations. | Both, for its own alerts. | Different state, no overlap with idle-with-work (F3). Keep untouched; do not borrow its sender. |
| `bin/ade-sched` ([scheduling.md](scheduling.md)) | Host jobs on launchd/systemd/cron; judgment jobs are Paseo schedules. | Yes: zero-token script every 5 minutes. | Whatever the script calls. | **Chosen scheduler.** |
| Progress plugin (installed `@stevecastaneda/paseo-progress` 1.14.6) | README: Explorer panel plus a pill above the composer for questions and stuck items. `server/cli.ts`: `activity add/update`, `stuck set/clear` print their ids; no `--json`. `server/store.ts:40-50`: one store per **worktree realpath**, outside the repo. `paseo-progress` is a no-model CLI. | It displays; it does not detect. | Operator, through Paseo's UI. | **Chosen primary UI** (D). Needs an unfinished run in that worktree. |
| Herald (installed 0.6.1) | `index.server.ts:24-39`, `server/hooks.ts:309-399`: attention records are built from native events (`agent:turn:<id>`). No external publish call found. | No. | Operator, but only for events it observed. | Not a sink: a notice would mean forging an event or writing its internal file. |
| PR Radar | Manifest: a PR queue for PR-linked workspaces. | No. | — | Wrong domain. |
| Cafe | Plugin-directory browser. | No. | — | Irrelevant. |
| "Tasks" / "Questions please" (`paseo-asks`) | `~/.paseo/plugins/sources.json` has no such entry; the `paseo-asks` directory is empty. | — | — | No verified publication API found. This is a finding about what was inspected, not a claim that none exists anywhere. |
| baton plugin | `baton/…/checkout/server/core.ts:8-27` has idle timers and a persistent pending entry. | Idle timers exist, but for goal handoff, not obligation reminders. | — | Pattern to reuse only if the plugin route is taken later. |

B1. Plugin `timeline.append` with a stable `id` replaces its old row
(`public-docs/plugins/reference.md:1520-1545`): a no-model dedupe building block for a *custom* ADE
inbox plugin. It needs a renderer and plugin code, so it is the slice-3 option, not slice 1.

## C. Architecture

C1. One stdlib Python CLI `bin/ade-progress` (in `bin/`, tested like `bin/deadline`) with five
subcommands: `declare`, `retire`, `scan`, `inbox`, `ack`. `bin/ade-sched` runs `scan --yes` every
five minutes (inventory row in slice 1b). No model call, transcript read, git read or network
request happens in a pass. Subprocesses use argv lists; each has a timeout.

C2. **Declarations.** Stored in `~/.local/state/djbclark-ade/progress/v1/` (dir 0700, files 0600),
outside worktrees. A declaration binds `{paseo_home_realpath, agent_id}` — Paseo CLI output has no
`server_id` field (F3) — and holds: unique task id, generation, `state` (`open` | `waiting` |
`retired`), `pending_count` (> 0 when unfinished), `idle_after_min` (default 30), `review_after`
UTC, a one-line `summary` (the text of every nudge and notice), and the agent's `workspace` realpath
(used only to reach the Progress store). Only the owner or orchestrator runs `declare`/`retire`;
a stale generation is rejected. No declaration, no reminder: nothing is inferred from a quiet agent.

C3. **Two checks, plus one transition** (slice 1; a pass reads `paseo ls -g --background --json`
once and `paseo inspect <id> --json` only for enrolled agents, at most 16 declarations and 45 s):

| Reason enum | Trigger | Wake? |
|---|---|---|
| `due` | `open`/`waiting` with `pending_count > 0` and `review_after <= now`. | Only if the agent is also idle by the rule below. |
| `idle_with_work` | `open` with `pending_count > 0`; native status `idle`; not archived; no pending permission; `UpdatedAt` older than the threshold. | **Yes.** |
| `stopped_with_open_work` (F2) | `open`/`waiting` with `pending_count > 0` and the agent is `closed`, `error` or archived. | **No.** Operator notice only; a stopped session is never restarted. |

A `waiting` declaration gets a `due` notice but never an `idle_with_work` wake. Missing,
unparseable or contradictory native data is `unknown`: it is recorded as source health and neither
paged nor woken. Over the 16-declaration cap, the pass reports `partial` and does not claim the
rest are clear (round-robin cursors are deferred).

C4. **Event key and cooldown.** Key = `{paseo_home, agent_id, task, generation, reason}`. A tick, a
new timestamp or an unrelated commit is not a new event. A new key notifies at once; an unresolved
key may notify again after **3 hours** (one ping per pass, a digest when several are due).
`ack` records that the operator saw it (not that the work is done); `retire` stops reminders; both
close the Progress item (D2). Clock rollback or a future timestamp suppresses sends for that pass.

## D. Delivery channels

D1. A new event writes channels in this order; each is independent, and one failing never blocks
the next:

| # | Channel | Mechanism | Receipt kept |
|---|---|---|---|
| 1 | Local inbox (the record) | Atomic write (temp + `mv`) under a non-blocking lock; read back and hash-compare. | `published-local`. Only this advances the cooldown cursor. |
| 2 | **Paseo Progress panel (primary operator UI)** | `paseo-progress stuck set "<summary>"` with cwd = the declaration's workspace; parse the printed `S<n>` id; read it back with `paseo-progress show`. | `ui_id=S<n>` and `verified` / `unverified` / `no-run`. |
| 3 | Operator page | `hermes-ping "ade-progress: <task> <reason>"` (one line; full URLs if it names a PR). | `ping rc=<n>` only. Exit 0 is **not** proof the operator read it. |
| 4 | Agent wake (`idle_with_work` only) | `paseo send --json --no-wait <agent_id> "<nudge>"` with no `--behavior` flag (the agent is idle; `~/CLAUDE.md` item 4). | `.status` of `sent` / `completed` = accepted by the daemon; anything else = `unknown`. |

D2. **Why `stuck set`, not `activity add`.** `stuck` raises the "N stuck" pill above the composer
(Progress README), the operator-visible attention signal; `activity` is a quiet feed line. It is an
*item*, not a question: no invented human question, and the agent's own ticker is never touched.
`ack`/`retire`/recovery run `stuck clear <id>` using the saved id, so a repeat updates one item
rather than stacking. `paseo-progress` refuses an unfinished-run-less worktree ("The run … is
finished"): that outcome is recorded as `no-run` and channels 3 and 4 still go. If the plugin is
absent or errors, the same: recorded, never retried blindly, never an empty success.

D3. **Honest receipts.** `queued`/`accepted` is not `delivered`; `delivered` is not `read`; a
process exit code proves nothing about a human. A timeout or malformed reply is `unknown`, and an
`unknown` send is **never re-sent blindly** (no replay to another route either): it stays visible in
the inbox, and the next attempt waits for the 3-hour cooldown *and* records the prior uncertain
attempt. A provably refused send (non-zero exit with a structured refusal) may retry after the
cooldown, at most three attempts per key.

D4. **Wake nudge text** is fixed and short: task id, declared `summary`, count and "reply with
status or `ade-progress ack`". It copies no free-text TODO or remote content, and carries no
authority to run commands, answer permissions or change modes.

## E. Failure handling

E1. **Lock and crash.** A non-blocking per-user lock covers fresh read, event selection and state
write; a busy lock exits without effects. Intent (`prepared`) is written before any channel
effect. After a crash, an attempt left `prepared`/in flight is `unknown`: inbox and Progress
artifacts are reconciled by id and hash; a wake or ping that may have gone out is not repeated.
Corrupt state is preserved and reported; there is no empty-state fallback.

E2. **Overlap.** `bin/deadline` alerts stuck-`running` agents; `ade-progress` acts on `idle` or
stopped agents with a declaration; the statuses are disjoint, so no shared dedupe contract is
needed. A running deadline for the same agent suppresses nothing, because it covers a different
state. Neither tool disables the other.

E3. **The inspect/send race, accepted.** Between inspect and send an agent can start a turn, close
or raise a permission. Mitigation, not a veto: re-inspect immediately before the send, and wake
only if the status is still `idle` with an unchanged `UpdatedAt` and zero `PendingPermissions`.
Residual risk, recorded in the design: `paseo send` loads and, if needed, unarchives a stored
runtime (`agent/agent-prompt.ts`), an agent send without `--behavior` defaults to `interrupt` for a
sourceless caller (`cli/src/commands/agent/send.ts:207`), and the send path passes
`clearPendingPermissions: true` (`server/session.ts`, send path near lines 8255-8290). So a
permission card raised in the final moments could be cleared, and a turn started in them
interrupted. The recheck and the idle-only rule make this a small window; this is an *accepted*
risk, and `closed`/`error`/archived agents are never sent to at all (C3).

E4. **Host availability.** Sleep or offline time is unavailable time: missed ticks coalesce into
one evaluation after wake. A loaded timer alone proves nothing; report last successful scan and
per-channel last receipt separately. The scanner cannot detect its own host outage.

E5. **Item 13 compliance.** No recurring model prompt: the poll is a zero-token script. A wake or
ping fires only for a deterministic transition on declared work (`pending_count > 0`), with the
3-hour cooldown and event-key dedupe — each firing carries real work.

## F. Review findings, resolved

F1 **Silent sink** — resolved: every new event reaches the Progress panel, `hermes-ping` and (when
idle) the agent itself, with the inbox as record. F2 **Stopped owner** — resolved:
`stopped_with_open_work`, operator notice, no wake. F3 **`server_id`** — resolved: key is
`{paseo_home_realpath, agent_id}`; deadline-vs-progress statuses stated (E2). F4 **stale blob link** —
resolved: a repo-relative link to the walkthrough, which merged in PR 562. F5 **overbuilt slice** —
resolved: git ancestry, producer receipts, quota/review adapters, the eight-state delivery machine
and round-robin cursors are deferred (G3).

## G. Implementation sequence

G1. **Slice 1 — the first PR (after operator approval of this design).**

| File | Content |
|---|---|
| `bin/ade-progress` | ~350 LoC stdlib: `declare`, `retire`, `scan [--dry-run\|--yes] [--json]`, `inbox [--json]`, `ack`. State-changing commands default to `--dry-run`; `--yes` is explicit. Tool paths via env overrides in the `bin/deadline` `tool()` style (`ADE_PROGRESS_PASEO`, `…_HERMES_PING`, `…_PASEO_PROGRESS`). |
| `tests/test_ade_progress.py` | Fixture tests with fake `paseo`, `hermes-ping` and `paseo-progress` executables. |
| `docs/scheduling.md` | A pointer line only; no job row yet. |
| `changelog.d/persistent-progress-design.md` | Entry ends `(#N)` of the slice-1 PR. |

G2. **Required tests.** Unchanged facts stay quiet; `due` crossing, `idle_with_work` and
`stopped_with_open_work` each notify once; cooldown holds 3 h; snooze/`ack`/`retire`/stale
generation behave; `waiting`, busy, permission-pending, unknown and over-cap agents never wake;
closed/error/archived agents get a notice and **no** `paseo send` (assert on the fake's call log);
re-inspect-changed-status cancels the wake; one channel failing does not block the others; an
`unknown` send is not replayed; `no-run` and absent `paseo-progress` are recorded; two real
concurrent scans take the lock once; a crash between write and receipt reconciles without a
duplicate send; a cold `--dry-run` writes nothing; no model call is made.

G3. **Later slices.** 1b: an `ade-sched` inventory row `com.djbclark.ade-progress` and doctor
expectations, enabled only after the operator has seen `scan --dry-run` on real declarations.
2: git-handoff ancestry, producer/quota/review receipts, round-robin cursors. 3: an ADE plugin on
`agent.turn_ended` timers plus `timeline.append` rows (B1) if polling latency or the `stuck`
semantics prove inadequate.

G4. **Separate runtime acceptance** (not covered by source or mocks): check the installed Paseo and
`paseo-progress` versions, run one authorized canary on a throwaway idle agent, and confirm the
Progress pill, the ping and the single wake appear exactly once.
