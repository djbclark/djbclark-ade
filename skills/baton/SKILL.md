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
   deleted.

If a waiter times out (it is bounded) with no `.done`, check the detached job
is still alive (`launchctl list | grep <label>`) before re-arming once more or
reporting it lost.

`/resume` is the same thing under its older name (the `resume` skill was
folded in here on 2026-10-08; Claude Code keeps a `/resume` command wrapper
that loads this skill, next to its own built-in `/resume` session picker).

Do not duplicate the reader protocol's steps here — if they ever change,
they change in exactly one place (`session-handoff`'s SKILL.md), not two.
