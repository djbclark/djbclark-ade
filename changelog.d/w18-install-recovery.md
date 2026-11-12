### Added

- `ade-install doctor` now reports crash leftovers of an interrupted install as `install-state` rows (an orphaned
  `pending` ledger entry, a killed lock holder, a half-written temp file, a dead Python acquisition), judged by pid plus
  process start time, and `ade-install recover [--yes]` is the explicit repair: it relabels orphaned `pending` entries
  `interrupted`, quarantines temp files and appends everything to `recovery-evidence.jsonl`, deleting nothing, never
  waiting on a running installer and refusing as root. `python-acquire.pending` no longer reports `owner-active` for a
  reused pid. (#PRNUM)
