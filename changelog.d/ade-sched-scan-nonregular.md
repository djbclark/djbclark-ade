### Fixed

- `ade-sched reconcile`'s live backend scan (`list_backend_labels`) no longer opens a non-regular `*.plist`/`*.service`
  entry: a FIFO (or a symlink to one) planted in the agents or unit directory used to hang the scan forever. Entries are
  `lstat`-checked, opened `O_NONBLOCK` with a re-check on the descriptor, read at most 4 KiB, and reported as source
  `non-regular` (report only). (#PRN)
