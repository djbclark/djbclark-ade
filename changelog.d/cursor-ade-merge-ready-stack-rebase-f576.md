### Added

- `ade-merge-ready stack-rebase` dry-run / `--yes --repo-dir` restack for open stack children after a bottom lands (conflict refuse; no APPROVE invent; no merge) (#512).

### Fixed

- `stack-rebase` refuses fork/cross-repo heads and uses `git rebase --onto` with the old parent tip so squash-merged parent commits are not replayed (#512).
