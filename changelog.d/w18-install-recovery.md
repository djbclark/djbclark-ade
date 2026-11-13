### Added

- `ade-install doctor` now reports crash leftovers of an interrupted install as `install-state` rows (an orphaned
  `pending` ledger entry, a killed lock holder, a half-written temp file, a dead Python acquisition), judged by pid plus
  process start time, and `ade-install recover [--yes]` is the explicit repair: it relabels orphaned `pending` entries
  `interrupted`, quarantines temp files and appends everything to `recovery-evidence.jsonl`, deleting nothing, never
  waiting on a running installer and refusing as root. `python-acquire.pending` no longer reports `owner-active` for a
  reused pid. (#609)
- Running the installer as root now walks the state directory from `/` with directory file descriptors and refuses a
  symlink, a non-root-owned component or one writable by others (sticky excepted) before creating or opening anything, and
  opens `ledger.lock` and the evidence log relative to that descriptor, so a root-owned link into a user-controlled
  directory or a swap after the check cannot redirect a root write. (#609)
