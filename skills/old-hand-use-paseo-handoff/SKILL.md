---
name: old-hand-use-paseo-handoff
description: "OLD WAY: short alias for the ADE recovery handoff. Prefer paseo-handoff for a fresh agent."
---

# Old hand — use paseo-handoff for a fresh agent

The operator types `hand` in every TUI because `/handoff` historically collided
with omp's built-in command of that name (omp is archive-only under the
2026-11-08 Pi-only ruling; queue item 36), which only compacted the context in
place and never reached the `handoff` skill. The short name stayed.

1. Read the `old-handoff-use-paseo-handoff` skill (`~/src/djbclark-ade/skills/old-handoff-use-paseo-handoff/SKILL.md`) and
   follow it exactly from its first step, as if the operator had invoked it.
2. Pass the arguments through unchanged: `hand paseo` is `handoff paseo`; any
   other text is the focus.
3. Do not summarize or shortcut the skill because this file is short; this file
   adds no behavior of its own.

Per-TUI spelling (2026-11-09; Pi sole third-party TUI): `/hand` in Claude Code,
Cursor, Hermes (skill route), and Pi (via `~/.agents/skills`, shared with Codex);
`$hand` in Codex (its `/prompts:hand` form is deprecated and not installed).
Archived wrappers for retired clients remain in-repo only
(`omp/commands/hand.md`, `opencode/commands/hand.md`) — never install targets.
Prefer Paseo's `paseo-handoff` for a fresh agent.
