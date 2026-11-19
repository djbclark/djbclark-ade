### Changed

- Migrated the build wrapper references from `bg` to `bgrun` (the wrapper was renamed so it no longer collides with the shell's `bg` builtin; djbclark/site-djbclark#281). `bin/load-watch`, `bin/pytest`, `claude/hooks/bg_test_gate.py`, `bash_habits_gate.py`, `opencode-plugins/bg-cargo-gate.*`, docs and tests now name `bgrun`, while `bin/bg` is still recognized as a transitional alias. (#811)
