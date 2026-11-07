---
name: hand
description: >-
  Operator alias: `hand` runs the `handoff` skill with the same arguments. Use
  only when the operator types /hand, $hand or /skill:hand (omp's built-in
  /handoff is a different command that only compacts context).
---

# hand: alias for `handoff`

The operator types `hand` in every TUI because `/handoff` collides with omp's
built-in command of that name, which only compacts the context in place and
never reaches the `handoff` skill.

1. Read the `handoff` skill (`~/src/djbclark-ade/skills/handoff/SKILL.md`) and
   follow it exactly from its first step, as if the operator had invoked it.
2. Pass the arguments through unchanged: `hand paseo` is `handoff paseo`; any
   other text is the focus.
3. Do not summarize or shortcut the skill because this file is short; this file
   adds no behavior of its own.

Per-TUI spelling (2026-11-04): `/hand` in Claude Code, Cursor,
Hermes (skill route), omp and opencode;
`$hand` in Codex (its `/prompts:hand` form is deprecated and not installed).
The operator wrappers live in `omp/commands/`
and `opencode/commands/` because those TUIs do not turn a plain skill into a
bare `/name` command (the pi and zcode wrappers were deleted 2026-11-06 with those TUIs).
