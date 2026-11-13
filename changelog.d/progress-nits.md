### Added

- Added `plan_reconcile` tests that pin the ledger-id equality in the "inventory row ... is not chosen" remove reason, the `retired` reason winning over it, and the `ade-sched`/`paseo` kind filter on the installed-but-unchosen report. (#PR)

### Changed

- Narrowed the wording in `docs/scheduling.md` and the `progress-1b-r2` changelog fragment: the installed-but-unchosen `reconcile` report applies only to ADE-owned `ade-sched` and `paseo` rows, and the remove reason only when the ledger id equals the row name. (#PR)
