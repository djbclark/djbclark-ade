### Added

- `bin/ade-worker-run`: launches a lead's worker into the lead's one `workers <middle> <lead id>` window (strips
  `PASEO_AGENT_ID`/`PASEO_AGENT_CWD`/`PASEO_WORKSPACE_ID`, finds the window by exact name and refuses two matches, mints and
  renames it on the first launch reading its id from the launch and failing closed otherwise, adds `--label ade.lead=` and
  `--label slice=`, renames the tab `worker <NAME> <lead id>`, prints `{agentId, workspaceId, windowName, tabName}`), and
  `ade-worker-run archive-window` archives the window only when no live labelled or other agent remains; `skills/fan-out` and
  `docs/workspace-layout.md` use it instead of the five hand-run steps, and `tests/test_ade_worker_run.py` covers it
  against a stub `paseo`. (#PR)
