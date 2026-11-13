### Fixed

- `ade-sched reconcile`'s live backend scan (`list_backend_labels`), `ade-sched status` with no label
  (`installed_labels`) and reconcile's whole-file byte-match reads no longer open a non-regular `*.plist`/`*.service`
  entry: a FIFO (or a symlink to one) planted in the agents or unit directory used to hang them forever. Entries are
  `lstat`-checked, opened `O_NONBLOCK|O_NOCTTY` with a re-check on the descriptor and read with a bound. A non-regular
  entry is listed as source `non-regular`, is not a live identity, and gets one scan note. (#PRN)
