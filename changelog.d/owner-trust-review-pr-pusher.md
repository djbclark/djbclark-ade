### Changed

- `bin/review-pr` gives the full-permission (`yolo`) runtime only to a PR the operator authored (login and numeric user id, `gh api users/LOGIN`) AND whose head the operator pushed (the merge gate's `head_pusher_check`, reused through `gh api`); a head pushed by anyone else, a fork head, or any unreadable answer is reviewed restricted, and `--runtime yolo` is refused with the reason (#683)
- The gate's branch-name check is ASCII-only and a full match (no `$`-before-newline, no Unicode letters); the `pr_merge` residual and `docs/code-review.md` rule 1 (owner trust and its pusher requirement) are written down; `approve-post`'s paste hint says every tip gets a comment (#683)
