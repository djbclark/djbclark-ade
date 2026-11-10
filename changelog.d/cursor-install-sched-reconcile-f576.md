### Added

- `ade-install apply` (full apply) ran `ade-sched reconcile` for ADE-owned labeled jobs; `just sched-reconcile-checks` named the daily check + core ADE jobs (Linux one-step demanual) (#516).

### Changed

- `ade-install` full-apply reconcile kept the linked-worktree refuse (implicit `ade=None`; blocked when catalog root is a linked worktree) (#516).
