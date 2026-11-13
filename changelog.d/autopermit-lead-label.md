### Fixed

- `bin/ade-auto-permit` now also approves permission requests from agents whose Paseo labels include
  `ade.lead=<its --lead id>` (audit reason `lead-label`, checked by default via the exact `ls -a -g --label` filter), so
  a lead's env-stripped top-level workers, which are not descendants, no longer stall on prompts. The launch shapes in
  `skills/fan-out`, `docs/orchestration-practices.md`, `docs/scheduling.md` and `skills/handoff` document the label. (#0)
