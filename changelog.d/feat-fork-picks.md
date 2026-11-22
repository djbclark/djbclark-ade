### Added

- `config/fork-picks.toml` and `bin/ade-fork-picks` (`list`, `apply`, `mark`, `check-upstream`): a registry of desired future cherry-picks into our patched fork builds, seeded with the Paseo picks; sources are commit, branch, PR head or a local-only commit, with `targets`, `carried`/`landed:main` statuses, `trial_required`, `hold` and `expected_head`; apply cherry-picks into a clean linked worktree, skips patch-equivalents already present and aborts on a conflict (exit 3); check-upstream lists drop candidates as stable JSON for the upstream-release alerts (#PR)
- `docs/fork-picks.md` and `tests/test_ade_fork_picks.py` (temp git repos, no network; nine branches mutation-checked) (#PR)
