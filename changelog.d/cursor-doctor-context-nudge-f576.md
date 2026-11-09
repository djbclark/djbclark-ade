### Added

- `ade-install doctor` / `just install-doctor` detects a missing live
  `~/.claude/settings.json` `context_size_nudge.py` registration versus
  `agents/claude/settings.json.tmpl` (queue Carried #10) and prints a hand-apply
  hint; observe-only, never mutates the live file (order 11) (#399).
