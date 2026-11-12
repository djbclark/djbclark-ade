### Fixed

- Defer disruptive scheduler reconciliation without shared admission, per-job idle and safe-drain evidence; persist intent and preserve backend migration ownership. (#595)

- Identify deferred Paseo intent by its target backend so retries across host backend selections retain one record. (#595)
