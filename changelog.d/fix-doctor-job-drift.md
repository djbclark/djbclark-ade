### Fixed

- `tests/test_ade_jobs_inventory.py`: both `doctor()` calls pass `skip_credential_bak=True`, so the suite no longer
  reads this machine's `~/.local/state/ade/credential-bak` and no longer fails on the vault residue's passed
  `delete-after` (2026-11-19) instead of on job drift. (#807)
