### Fixed

- `load-watch ci decide` audit-log events name the decided mode (`lw-pending-approved`, `lw-pending-denied`, `lw-pending-unavailable`), not always `lw-local-*` (#760).
- The `archived_send_gate` backstop no longer judges an agent id that sits in a path component (`agent-reports/<id>/`) as a send target (#760).

### Removed

- The tracked `.claude/skills/fastino-glide/` skill and its `skills-lock.json` entry (#760).
