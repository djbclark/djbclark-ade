### Changed

- `bin/load-watch`: `ci decide DIR pending` is gated exactly like `local` (Allow dialog + Touch ID, logged in `approvals.log`); an existing row of the same mode only changes its note, `ci` stays ungated. Closes the ungated `pending` route (a `ci` row downgraded to run here, or a `DIR/*` glob) from the PR 744 review. (#758)
