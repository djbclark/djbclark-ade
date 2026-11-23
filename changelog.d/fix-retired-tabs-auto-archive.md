### Added

- `bin/ade-archive-retired`: added a dry-run-by-default (`--apply` to act) zero-token re-archiver for unarchived `RETIRED ` tabs and completed-handoff predecessors (operator ruling 2026-11-23), fail-closed on inspect (`Archived: false`, `Status` idle/closed, `PendingPermissions == []`, timezone-aware `UpdatedAt` quiet >= `--min-idle` 120 s), self, standing load watcher (`watcher.json`), and exclude list, with flock, JSONL audit log, and readback verification; wired into `bin/ade-pin-sweep` before pinning (#PR)

### Fixed

- `bin/ade-pin-interactive` and `bin/ade-pin-workspaces.mjs`: stopped tagging archived, `RETIRED `, and completed-handoff predecessor agents (switched listing from `paseo ls -a -g` to `paseo ls -g`, added explicit guards and `--paseo-bin`/`ADE_PASEO_BIN` injection) and skipped `RETIRED ` windows in workspace pinning (#PR)
