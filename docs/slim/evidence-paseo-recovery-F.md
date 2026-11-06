# Paseo-native recovery inventory (section F of docs/checkpoint.md on PR 290's branch, 2026-11-04)

Taken verbatim for Wave 3 (D3/D11). Source branch `claude/issue-278-checkpointing` @ 15186fb2; PR 290 is parked (checkin-rulings R4).

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

