---
name: baton
description: >-
  Start-of-session resume from the Tier 1 pointer: follow session-handoff's
  Reader protocol for this directory, or its chain discovery when cwd resolves
  to none. Use when the operator types /baton or /resume, or says "baton",
  "pick up the baton", "resume", "pick up where we left off" or "continue this
  task" at the start of a session.
---

# Baton — resume a task workspace from its Tier 1 pointer

**Provider scope (2026-10-25).** A native OpenCode compaction continues its existing session; it does not start a new baton. Only resume a fresh session after the owned Tier 1 checkpoint is durable and the supported lifecycle controller has acknowledged that successor. Never clear a parent session to make a child resume. See [context hygiene](../../docs/context-hygiene.md).

Since 2026-10-19 `bin/self-slash "/new"` (also `/clear`, `/reset`) queues
`/baton` into the fresh session itself (`--then`, default `/baton`; `--no-then`
turns it off), so after a handoff nobody types this; a `/baton` that arrives
right after a `/clear` is that follow-up (`~/.local/state/self-slash.log`
shows `then: /baton` and `sent /baton`), not a request for anything else.

**Syntax is per client (2026-10-25).** In Claude Code the skill is typed `/baton`. In Codex a skill is invoked with
`$` (`$baton`, `$baton PATH`) and `/` is reserved for Codex's built-ins (`/new`, `/compact`, `/quit`): a `/baton` typed
into a Codex composer is just text and starts nothing (seen live 2026-10-25, three Enters later it still sat in the
composer). `self-slash` picks the spelling from the provider herdr reports for the pane, so in a Codex pane the
follow-up above is `$baton`, and a `--then "/baton PATH"` is rewritten once to `$baton PATH`. The same skill answers
to either spelling; treat `$baton PATH` exactly like `/baton PATH`. Never write `$baton` for a Claude pane.

`/baton` never clears, compacts or starts a new session itself: `/new` queues
`/baton`, so a `/baton` that started a `/new` would recurse. If the pointer
has nothing to resume (no open work, `latest_handoff` already finished), say
so and offer the `loose` Rule 4 choices (handoff and continue, finish and
archive, keep working); never write another handoff automatically.

A `/baton` can arrive three ways: typed by the operator, queued by `self-slash "/new"` (the same agent, fresh
context), or as the first prompt of a successor another session started (`self-slash --finish --successor` on
Paseo or herdr, `launch.py start --baton`). Treat all three alike. Since 2026-10-25 a successor the operator will
talk to is a real TUI (an `acp-run` pane has no readable transcript); a session that does turn out to be an
`acp-run` client (`ACP_RUN_AGENT=1`) cannot use `self-slash` (exit 9), so it ends with a document-only handoff.

This is a thin entry point, not a separate protocol. Follow the
`session-handoff` skill's **Reader protocol** section exactly (read
`SESSION_LOG.md` if present, check sidecars newer than `updated_at`, run
the staleness check against real `HEAD`, state a resume plan before
touching anything, bootstrap a minimal log if none exists — never ask
the operator for information the file already answers).

If the operator invoked this with no argument, resolve the current
directory against the Tier 1 path convention in `session-handoff` (or,
if you were handed an explicit path in the prompt, use that instead of
resolving from cwd). If cwd doesn't resolve (e.g. running in the bare
home directory), that is NOT a dead end — go straight to
`session-handoff`'s **Chain discovery fallback** (step 0 of its Reader
protocol) instead of asking the operator to supply a path.

## Re-arm detached jobs (after the resume plan, before other work)

Background work does not carry over on its own: a `run_in_background` task or
waiter belongs to the session that started it. What survives is on disk, in
bigteam's job records (`~/.local/state/bigteam/<task>/jobs/<name>.json`; format
in the `bigteam` skill, Step 4). For each open job named under `## Detached
jobs` in the handoff (or, with no handoff, each record without a `"closed"` key
under the task directory the Tier 1 pointer names; never adopt a record whose
`owner` session is still alive and is not the handoff's author):

1. If its `done` path already exists, skip the wait: read the report (step 3).
2. Otherwise start the record's `rearm` command as **its own
   `run_in_background` Bash call**, one per job, then carry on with the
   resume plan. A job that was launched detached (launchd) is still running;
   only the waiter is new.
3. Point the record at this session so the next handoff lists it: set
   `owner` to `$CLAUDE_CODE_SESSION_ID`
   (`jq --arg o "$CLAUDE_CODE_SESSION_ID" '.owner=$o' f > f.tmp && mv -f f.tmp f`).
4. When the waiter returns, read the report, act on it, then **close the
   record** by appending `"closed": <epoch seconds>` with the same
   temp-file-and-`mv -f` form (`.closed=(now|floor)`). Records are closed, never
   deleted. A rearm written by `acp-dispatch` since 2026-10-10 ends in
   `acp-dispatch check <record>`: exit 1 means partial, 3 means no-report (a
   last line `NO-REPORT: ...` says why), and 4 means BLOCKED. A quota stop is
   resumed in place automatically (2026-10-18): the waiter keeps waiting
   through the scheduled resume, and `check` on such a record prints
   `resume-scheduled` with exit 1 (still running; re-arm the waiter). Exit 3
   with `NO-REPORT: quota` means no automatic resume is pending; the line ends
   with the exact `acp-dispatch resume <record> --detach --no-wait` to run
   after the retry time, never a fresh dispatch. An older rearm exits 0 on any
   `.done`, so run `acp-dispatch check` on its record yourself.

If a waiter times out (it is bounded) with no `.done`, run `acp-dispatch reap
<record>` (or `acp-dispatch check <record>`, which applies the same rule): a
slice whose process is gone (a reboot, SIGKILL, power loss) is finalized on the
spot with its exit from the runner's exit file or launchd, else 255 `lost`, and
`check` then gives the real verdict; a live slice is left alone, so re-arm the
waiter. Never judge liveness by hand from `launchctl list` or `ps`: pids are
reused after a reboot (2026-10-17: trackpad-settings read as running for
hours), and `wait` returns only once a record is finalized or reaped, never on
the agent's own `.done` touch (2026-10-18). A launchd sweep
(`acp-dispatch reap --install`) does the same at login and every 30 min.

`/resume` is the same thing under its older name (the `resume` skill was
folded in here on 2026-10-08; Claude Code keeps a `/resume` command wrapper
that loads this skill, next to its own built-in `/resume` session picker).

Do not duplicate the reader protocol's steps here — if they ever change,
they change in exactly one place (`session-handoff`'s SKILL.md), not two.

OpenCode V2 Go sessions use the native `ade_compact` tool for manual compaction.
The plugin never rewrites shell commands. A supported host controller may pass
an explicit validated session and directory to `self-slash "/compact"`.
These paths compact only the verified current session; they do not implement a
new-session/baton successor.
See `docs/context-hygiene.md`. Write the checkpoint first and require the normal
host identity/acknowledgment checks for a lifecycle cycle.
