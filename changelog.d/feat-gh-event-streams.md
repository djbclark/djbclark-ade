### Added

- Added `bin/gh-pr-wait` to wait for `github.com` PR checks, reviews, merges, or events over GitHub Event Streams (`gh event listen`) with attach-then-read ordering, safety-net re-reads, stop-before-delete subscription cleanup, `bin/deadline` self-supervision, automatic `>= 60 s` polling fallback, and a `cleanup` subcommand (#PR).
- Added the `gh-event-streams` skill (`skills/gh-event-streams/SKILL.md`) documenting Event Streams prerequisites, `gh-pr-wait` usage, attach-then-read, subscription cap cleanup, and trust boundaries (#PR).

### Changed

- Linked `gh-pr-wait` into `~/.local/bin` via `bin/ade-update` (`BIN_LINKS`) and updated `claude/hooks/bash_habits_gate.py` plus orchestration/footer docs to recommend `gh-pr-wait` / `gh event listen` first for `github.com` PR waits (#PR).
