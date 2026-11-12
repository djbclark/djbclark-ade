### Fixed

- The top-level successor launch in AGENTS.md and docs/context-hygiene.md now also strips `PASEO_WORKSPACE_ID`:
  with only the two agent variables removed, `paseo run` still inherited the caller's workspace and ignored `--cwd`
  (live, 2026-11-12, ade-yolo canary r2). (#PRNUM)
