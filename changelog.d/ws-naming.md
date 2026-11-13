### Changed

- Window names are now `<KIND> <repo> (<work>)` with KIND `MAIN` (a lead's own window), `WORKERS` (the workers the lead starts
  itself) or `USER` (operator-started agents a lead was connected to), and carry no lead id (operator rulings, 2026-11-13);
  the lead id stays in the tab name `worker <slice> <lead id>` and the `ade.lead` label. `bin/ade-worker-run` finds the WORKERS
  window by exact name (or, without `--window-middle`, by the lead's labelled agents), refuses two matches or a window that
  holds another lead's labelled agents, and renames a legacy `workers <middle> <lead id>`, `WORKERS <middle> <lead id>` or
  `MAIN <middle>` window to the new form in place (same window id) before it launches. (#0)
- `docs/workspace-layout.md`, `skills/fan-out`, `skills/handoff`, `docs/orchestration-practices.md` and the AGENTS.md table row
  carry the new naming rule with the operator's words. (#0)

### Added

- `bin/ade_ws_names.py`: the importable window-name builder and parser (`build`, `parse`, `parse_legacy`, `migrated_name`,
  `repo_of`) that the tidy skill reuses. (#0)
- `ade-worker-run --placement main` (alias `--interactive`): launches a worker the operator asked for into the lead's own MAIN
  window, resolved from the lead's agent record; `ade-worker-run rename-main` names that window `MAIN <repo> (<work>)`;
  `archive-window` accepts current and legacy names, never archives MAIN or USER, and ignores a MAIN-placed worker. (#0)
- `ade-worker-run` appends `Also follow every item of <repo root>/docs/dispatch-footer.md.` to the brief it launches
  (`--no-footer` to skip), and `docs/dispatch-footer.md` item 25 requires `python3 bin/changelog-fold --repo . --check` before a
  changelog fragment is committed or pushed (a worker's fragment with no `###` heading turned #637 CI red). (#0)
