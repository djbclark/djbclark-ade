### Added

- Added `--lead-ack` and `--check-ack` to `bin/completion-notice` supporting dual-route delivery proof with unique UUID message IDs and atomic disk acks per operator ruling 2026-11-12 (#573).

### Fixed

- Mitigated Antigravity stream interruption race (`replaceRunning: true` upstream issue https://github.com/getpaseo/paseo/issues/9498) by enforcing that completing workers end their turns immediately and leads idle-gate prompt acks alongside atomic disk acks (#573).
- Updated `docs/orchestration-practices.md`, `docs/dispatch-footer.md`, `skills/fan-out/SKILL.md`, and `AGENTS.md` standing order 10 with dual-route completion semantics (#573).
