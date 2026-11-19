### Added

- The graft/Trail helper now answers Cursor's `sessionStart` too: `.cursor/hooks.json` now has a `sessionStart` entry, and
  `graft-hooks.cjs` (both the `.claude/helpers` and `.cursor/hooks` copies) treats `cursor-session-start` like
  `session-start` and writes Cursor's `additional_context` shape instead of Claude Code's `hookSpecificOutput`. When an
  installed trail/graft only knows the Claude event, the helper runs its `session-start` and re-shapes what it printed,
  so the hook works with trail installed instead of only down the no-trail fallback. The Trail
  offer also says what to do when `npm install -g` fails with EACCES: point npm at `~/.npm-global`, never `sudo`. The
  `AGENTS.md` graft section now carries the tool-by-tool guidance `skills/graft/SKILL.md` already states. (#798)
