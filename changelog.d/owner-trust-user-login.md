### Changed

- Owner trust is keyed to the operator's GitHub user login (`TRUSTED_OWNER_LOGINS` in `bin/adversary_marker.py`, also used by `bin/review-pr` and `bin/ade-merge-ready`), not to whoever owns the repository, so the move to the `frdminc` org does not change who is trusted (but see the write-access precondition in `docs/review-boundary.md`); the PR author must be a `User`. The `ade-merge-gate` App manifest is now `"public": true` (2026-11-14). (#670)
