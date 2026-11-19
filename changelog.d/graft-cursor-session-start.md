### Added

- The graft/Trail helper now answers Cursor's `sessionStart` too: `.cursor/hooks.json` now has a `sessionStart` entry, and
  `graft-hooks.cjs` (both the `.claude/helpers` and `.cursor/hooks` copies) treats `cursor-session-start` like
  `session-start` and writes Cursor's `additional_context` shape instead of Claude Code's `hookSpecificOutput`. The Trail
  offer also says what to do when `npm install -g` fails with EACCES: point npm at `~/.npm-global`, never `sudo`. The
  `AGENTS.md` graft section now carries the tool-by-tool guidance `skills/graft/SKILL.md` already states. (#798)
