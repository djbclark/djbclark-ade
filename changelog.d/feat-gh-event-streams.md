### Added

- Added `bin/gh-pr-wait` to wait for `github.com` PR checks, reviews, merges, or events over GitHub Event Streams (`gh event listen`) with attach-then-read ordering, slow safety-net re-checks, mode-specific field-limited queries, safe keep-on-exit subscription reuse (relying on 24 h TTL + `gh-pr-wait cleanup`, with explicit single-consumer `--delete-on-exit` opt-in), `bin/deadline` self-supervision, automatic `>= 60 s` polling fallback, and a `cleanup` subcommand (#995).
- Added the `gh-event-streams` skill (`skills/gh-event-streams/SKILL.md`) documenting Event Streams prerequisites, `gh-pr-wait` usage, attach-then-read, safe keep-on-exit lifecycle + `cleanup`, field-limited queries, and trust boundaries (#995).

### Changed

- Linked `gh-pr-wait` into `~/.local/bin` via `bin/ade-update` (`BIN_LINKS`) and updated `claude/hooks/bash_habits_gate.py` plus orchestration/footer docs to recommend `gh-pr-wait` / `gh event listen` first for `github.com` PR waits (#995).
