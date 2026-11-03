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
2. `bin/self-slash "/compact focus to preserve"` **refuses external compaction**
   (exit 2). The installed public API cannot prove that the main editor owns focus.
   `getEditorText()` can read an empty hidden editor while a built-in model,
   settings, session or tree selector owns input, including its own search text.
   `ui_prompt_start/end` covers extension prompts, not those built-in selectors;
   `isIdle()` describes agent activity, not UI focus. None is sufficient evidence.
   The bridge fails closed at both admission and execution, without private TUI
   introspection, speculative API methods or a bypass. Safe native rename remains
   available. Operator-invoked built-in compaction is outside this bridge.
3. `bin/self-slash --dry-run "/compact focus"` checks session and selected-model
   identity without creating a request, and reports the intentional compaction
   limitation. A successful identity-only dry run does **not** mean admission is
   supported. A future public focus contract and regression proof are prerequisites
   for enabling external compaction.
4. Other self-slash commands, `--finish`, `--then`, `--no-then` and successor
   options are refused. In particular no `/new`, `/clear`, `/reset`, `/quit`,
   `/model` or arbitrary prompt fallback exists. `--delay` is ignored on Pi:
   it cannot bypass the refusal. Dispatched `ACP_RUN_AGENT=1` slices
   cannot compact (exit 9). Other native refusals/unknown outcomes exit 2.

## Identity, naming and lifecycle

Pi process markers and tool-session variables are inherited; environment presence
alone does not establish ownership. Before selecting Pi, walk the process ancestry
nearest-first. A nearer `omp` with `OMPCODE=1` and its own PID-keyed bridge record
uses that record's session ID. A nearer `opencode` with a valid per-tool
`ADE_OPENCODE_SESSION_ID` and absolute `ADE_OPENCODE_DIRECTORY` uses its native
scope (any `OPENCODE_SESSION_ID` must agree). Explicit rename IDs cannot escape
that child; neither child route renames an inherited host tab. Nested OpenCode
self-slash permits only its scoped `/compact` route, whose existing native Go
guard still admits execution. OMP has no native self-slash route here and refuses.
These checks coordinate trusted same-user processes, not malicious same-UID peers.

Otherwise `PI_SESSION_ID` and `PI_SESSION_FILE` must match the nearest runtime's
Pi bridge registration. A Pi record, even invalid, or an unverified agent/Node/Bun
runtime is a barrier: failed Pi identity never permits ancestor/host fallback.
Nonstandard process names may cause safe refusals; use a standard process, not a
bypass. Custom Pi session IDs are opaque strings, never filename components.
Ephemeral sessions use a null session-file identity. Environments without Pi
markers retain the preexisting non-Pi selection and host behavior.

Known limitation (2026-11-03, deliberate): a Claude Code, Codex, Grok or
cursor-agent session started inside a Pi/OMP shell inherits `PI_SESSION_ID`, and
those runtimes are barriers, so its autorename and self-slash refuse (exit 2)
instead of falling back to its own host. Letting the nearer runtime win would
need per-runtime proof that it is not a wrapper around the Pi parent; until
that exists, unset the inherited `PI_*`/`AI_AGENT` variables when launching such a
nested agent.

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
are atomic and newly created instance directories/files request modes 0700/0600.
**Precondition:** the operator must supply a trusted, operator-owned, non-shared
state root and path ancestors, with the `pi` directory private (0700), and no
symlink/redirection to untrusted storage. The implementation follows paths; it does
not validate existing directory ownership, modes or symlinks. Recursive creation
and mode arguments do not repair existing permissive directories or guarantee
privacy of intermediate directories. The same trust precondition applies to OMP
registration state used for child selection. Do not use shared/tmp/project-writable
state directories. This is same-user local IPC, not authenticated peer IPC or a
sandbox/security boundary against malicious processes running as the operator.

The synchronous receipt says renamed/skipped/refused. Compaction currently never
passes admission, so it is not queued or executed and `compact_status` stays null.
The retained queue protocol distinguishes **queued (not completed)** from execution;
if enabled after a supported focus contract exists, `compact_status` contains the request nonce and
`queued`, `running`, `completed`, `failed` or `refused` status. It is ephemeral:
shutdown removes the registration and pending work, so disappearance is not proof
of completion. Verify a completed compaction against Pi's session entry when needed.
A request timeout is unknown outcome, never permission to retry automatically.

The retained (currently unreachable) queue allows only one pending/running
compaction, expires pending work after 15 minutes, and requires a 30-minute gap.
A competing built-in/automatic compaction cancels pending work. Both TUI and RPC
external compaction are refused; RPC additionally cannot observe the host draft.
Renaming works in all modes.

Tests in `tests/test_pi_native_controls.py` use isolated files, fake process
ancestry and a fake public Pi API, executing the exact bridge source with Node.
They cover actual backend selection with inherited Pi markers, native child/parent
isolation, selector search text hidden from the main-editor getter, refusal without
false queue/completion claims, pinning and replacement-instance rejection. They make
no provider calls and never operate a live session. Live installation/reload and
native rename require separate operator/lead verification after CI and independent
review. Provider-backed external compaction remains intentionally unavailable.
