### Added

- `ade-install apply` (full apply) runs `ade-sched reconcile` for ADE-owned labeled jobs; `just sched-reconcile-checks` names the daily check + core ADE jobs (Linux one-step demanual) (#516).

### Changed

- `ade-install` full-apply reconcile keeps the linked-worktree refuse (implicit `ade=None`; blocks when catalog root is a linked worktree) (#516).
