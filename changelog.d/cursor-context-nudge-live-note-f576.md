### Added

- `ade-install doctor` / `just install-doctor` WARNs when live
  `~/.claude/settings.json` omits a `context_size_nudge.py` hook event that
  `agents/claude/settings.json.tmpl` registers (queue Carried #10); observe-only,
  never mutates the live file (order 11) (#0).

### Changed

- Documented the live settings gap and operator hand-apply steps for
  `context_size_nudge.py` in `docs/context-hygiene.md` (#0).
