### Changed

- `bin/review-pr`: the `yolo` runtime needs the newest ref update of the PR branch to be a direct push, force-push or branch creation by the operator (`head_pusher_check(allowed=DIRECT_PUSHES)`), so a head that arrived by merging a child PR is reviewed restricted; the author's login and numeric id now come from the PR's own record (`gh api repos/R/pulls/N`, `.user`), not from a lookup by login; the stale "owner-authored" wording in the `review-pr` docstring, README.md and docs/review-boundary.md now says the operator also pushed the head (#NNN)
