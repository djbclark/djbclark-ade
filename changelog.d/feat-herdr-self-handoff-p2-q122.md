### Added

- Added `bin/ade-herdr-handoff` (`bin/ade_herdr_handoff.py`, linked into `~/.local/bin` via `bin/ade-update` `BIN_LINKS`) to restore automated Herdr self-handoff for genuinely Herdr-hosted sessions outside Paseo (Carried #122 Phase 2): enforces strict Paseo-wins / live `herdr pane current --current` caller verification, fail-closed preflight before layout mutation, per-pane `flock` serialization, durable `schema_version: 1` (`0600`) records and checkpoint preservation, single-submit `/baton` (Claude) or `$baton` (Codex) launch in a new tab without closing the predecessor pane or blind-retrying, plus `--dry-run` and `--status` (#PR).

### Changed

- Updated `claude/hooks/context_size_nudge.py` to distinguish Paseo (`PASEO_AGENT_ID`), Herdr (`PASEO_AGENT_ID` unset/blank with `HERDR_ENV=1` and `HERDR_PANE_ID`), and standalone non-Paseo modes across all four nudges, `_successor_note`, and operator pings, directing Herdr sessions to local Steps 0–7 plus either `bin/ade-herdr-handoff` or manual `/new` + `/baton` without forbidding `/new` (#PR).
- Updated `skills/self-handoff/SKILL.md`, `skills/baton/SKILL.md`, `skills/herdr/SKILL.md`, `docs/self-session.md` (Section H), `docs/context-hygiene.md`, and `docs/queue.md` (closing Carried #122) to document the restored Herdr automated self-handoff path alongside Paseo `ade-self-session` and standalone `/new` + `/baton` (#PR).
