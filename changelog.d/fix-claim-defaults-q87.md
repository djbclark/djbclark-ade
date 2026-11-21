### Changed

- `ade_claims.py new`: `--id` is now optional (generated, so a re-claim after `release` needs no new id; an explicit existing id exits 3 with a hint to omit it), `--owner-record` defaults to `--owner-agent` when that is a Paseo agent id, and `--branch` / `--base-sha` default from the worktree's `HEAD` (exit 2 naming the flag when the path is not a git worktree). `skills/fan-out` and `docs/git-guard.md` show the one-line worker form (#877)
