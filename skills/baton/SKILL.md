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

`/resume` is the same thing under its older name (the `resume` skill was
folded in here on 2026-10-08; Claude Code keeps a `/resume` command wrapper
that loads this skill, next to its own built-in `/resume` session picker).

Do not duplicate the reader protocol's steps here — if they ever change,
they change in exactly one place (`session-handoff`'s SKILL.md), not two.
