### Fixed

- `bin/completion-notice`: a short commit SHA in a `gh run list --commit` hint of a done notice's title or detail is expanded to the full SHA with `git rev-parse` (or the notice is refused, exit 2, when it names no commit), because gh matches only the full 40-character SHA and `gh run list --commit 5a2228d` prints `[]` with exit 0, so a lead's poll never found the run; `docs/dispatch-footer.md` rule 20 now tells workers to use `gh run list --branch BRANCH` or the full SHA (#704).
