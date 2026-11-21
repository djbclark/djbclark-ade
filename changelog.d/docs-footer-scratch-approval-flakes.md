### Changed

- Dispatch footer (2026-11-21): rule 28, scratch files live under the slice's own worktree or folder, never a shared session scratchpad (two adversaries both wrote `scratchpad/mut/out.log`); rule 29, a review slice never runs `load-watch ci decide … local`, `bgrun approve-local` or another approval command, since each opens the operator's `sudo-ask` dialog and a timeout is logged as a denial; it relies on CI instead. Queue Carried 110 records the two flaky tests seen on PRs 905 and 898 (#PR)
