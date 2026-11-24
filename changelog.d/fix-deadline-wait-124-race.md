### Fixed
- `bin/deadline_wait.py` / `tests/test_deadline_wrappers.py`: honor enforcer exit `124` in `supervised()` even before the inner start mark is touched instead of falling back to an unregistered wait, and wait for the inner start mark in the expiry test (#993)
