### Changed

- Owner trust in the merge gate also requires that the operator pushed the head (`head_pusher_check`: every `pull_request`/`push` workflow run at the head is by the pinned operator `User`; otherwise the owner PR is judged like an outside PR) and pins the operator by GitHub user id as well as login (`TRUSTED_OWNER_USER_IDS`); `bin/review-pr` and `bin/ade-merge-ready` refuse an `is_bot` author. The marker job gets `actions: read`. (#675)
