# Native Pi controls

Snapshot: 2026-11-03. This adapter targets the installed
`@earendil-works/pi-coding-agent` public extension API, not OMP's API.

## Installation (operator/lead step, not performed by this slice)

After integration, load `skills/autorename/pi-bridge.ts` from the promoted ADE
checkout: link it into `~/.pi/agent/extensions/autorename-bridge.ts`, or add its
absolute path to Pi's extensions setting. The global directory can instead be
under `PI_CODING_AGENT_DIR`. Start a new Pi or reload from the operator's top-level
session. Do not load `omp-bridge.ts` into Pi. No dependency installation is needed.
Do not install from a disposable task worktree. Shared skill linking alone does
not install this extension; this slice deliberately does not change the installer.

## Commands

1. `python3 skills/autorename/autorename.py "Title"` sets the live Pi session name
   with `pi.setSessionName`. `--auto` preserves operator-pinned names; `--show`
   reports the bridge's current name and provenance. An explicit `--session-id`
   must equal this shell's Pi ID. Pi names are `session_info` entries, not OMP's
   first-line title slot. Unknown existing names are treated as operator-pinned.
2. `bin/self-slash "/compact focus to preserve"` queues native compaction for this
   Pi only. It returns after acknowledgment, **not after compaction**. Use as the
   turn's last action and finish the turn: waiting on completion from that turn
   would deadlock. The bridge runs `ctx.compact` only after Pi is idle with no
   pending messages, no dialog and an exactly empty editor. A draft appearing
   after acceptance cancels the queued operation; nothing types over it.
3. `bin/self-slash --dry-run "/compact focus"` checks session and selected-model
   identity without creating a request. It does not promise that admission will
   succeed later (draft, mode, cooldown and busy checks are server-side).
4. Other self-slash commands, `--finish`, `--then`, `--no-then` and successor
   options are refused. In particular no `/new`, `/clear`, `/reset`, `/quit`,
   `/model` or arbitrary prompt fallback exists. `--delay` is ignored on Pi:
   the native idle boundary is used instead. Dispatched `ACP_RUN_AGENT=1` slices
   cannot compact (exit 9). Other native refusals/unknown outcomes exit 2.

## Identity, naming and lifecycle

`PI_SESSION_ID` and `PI_SESSION_FILE` must match an ancestor's bridge registration.
The first unregistered agent/Node/Bun runtime is a barrier: nested agents cannot
fall back to a registered parent even with inherited Pi or host environment.
Nonstandard process names may cause safe refusals; use a standard Pi process,
not a bypass. Custom session IDs are opaque strings, never filename components.
Ephemeral sessions use a null session-file identity.

The registration includes the selected provider, model and effective reasoning
level. Compaction checks shell values at dispatch and rechecks them in Pi both
at admission and before execution. Virtual routing does not substitute the last
physical assistant model for the selected model. A changed model cancels pending
compaction rather than silently using another model.

`--auto` is checked inside Pi, not just from a stale Python snapshot. The bridge
persists an `ade.pi.autorename` custom entry with the corresponding `session_info`
entry ID and auto/user provenance. A later `/name`, even with identical text,
therefore pins the name. Direct autorename requests also pin it. The Pi path
never edits transcripts, OMP state, or a possibly inherited Paseo/herdr tab.
OMP's existing bridge and dispatch remain separate and unchanged.

Pi does not have OMP's `ctx.setInterval` or `session_switch` event. A Node timer
starts only on `session_start` and is disposed on `session_shutdown`, including
reload/new/resume/fork runtime replacement. Each runtime has a random instance
ID; requests are bound to it as well as to the session ID/file. Shutdown discards
pending requests rather than executing them in the replacement session.

## Receipts and limits

State root: `$AUTORENAME_STATE_DIR/pi`, default
`~/.local/state/autorename/pi`. A `<pid>.json` registration points to an
instance-specific directory. Request/receipt filenames use random nonces; writes
are atomic, directories private and files mode 0600. This is same-user local IPC,
not a sandbox/security boundary against other processes running as the operator.

The synchronous receipt says renamed/skipped/refused or **queued (not completed)**.
The registration's `compact_status` contains the request nonce and
`queued`, `running`, `completed`, `failed` or `refused` status. It is ephemeral:
shutdown removes the registration and pending work, so disappearance is not proof
of completion. Verify a completed compaction against Pi's session entry when needed.
A request timeout is unknown outcome, never permission to retry automatically.

Only one compaction can be pending/running. Pending work expires after 15 minutes;
any compaction in the previous 30 minutes blocks admission. A competing built-in
or automatic compaction cancels pending work. Compaction is TUI-only: RPC's editor
getter cannot prove that the host composer is empty. Renaming works in all modes.

Tests in `tests/test_pi_native_controls.py` use isolated files, fake process
ancestry and a fake public Pi API, executing the exact bridge source with Node.
They make no provider calls and never operate a live session. Live installation,
reload, real TUI compaction and provider-backed completion require separate
operator/lead verification after CI and independent review.
