### Added

- `bin/ade-update` links the repo tools the instructions name bare (`git-commit-own`, `load-watch`, `agent-id`; the `BIN_LINKS` table) as `~/.local/bin/<name>` -> the canonical checkout's `bin/<name>`: a missing link is created, a stale link into a djbclark-ade checkout or worktree is repaired, a regular file or foreign symlink is never touched (reported, exit 10), a tool absent from `bin/` is skipped with an info line, and `--check` writes nothing. (#853)
