### Fixed

- `bin/completion-notice`: a 4-6 digit SHA in a `gh run list --commit` hint of a done notice is refused without asking git (a short prefix can resolve to another repository's commit about 1 time in 15), so the floor is 7 digits; `docs/orchestration-practices.md` item 6 now puts the short-SHA sentence after its Why paragraph (#721).
