### Changed

- Tests `pytest-linux` short-circuits the full suite when every changed path is under `CHANGELOG.md`, `changelog.d/**`, or `docs/**` (keeps the required check name; see `docs/ci-notes.md`). (#325)
