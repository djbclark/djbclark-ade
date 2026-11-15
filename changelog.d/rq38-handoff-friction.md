### Fixed

- `bin/ade_send_guard.py` redirects a send addressed to a self-handoff predecessor to its successor from `acknowledged` on, not only after `finish`, so peers stop waking a predecessor that `finish` is waiting to see idle; the hop needs a successor Paseo reports live, and every other consumer of the succession ledger still follows completed links only. (#736)
- The self-handoff prompt tells the successor to read lead-log / LEAD-STATE lines newer than the checkpoint (they fall outside the checkpoint hash) and to announce its takeover right after `accept`. (#736)
