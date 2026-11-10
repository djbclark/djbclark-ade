### Fixed

- `ade-sched` paseo reconcile: presence checks use only `backend=paseo` live jobs; delete failures keep `pending-remove` so the next run retries (#520).
