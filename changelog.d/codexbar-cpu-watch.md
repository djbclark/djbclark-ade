### Added

- `bin/codexbar-cpu-watch` and its launchd job (2026-10-31): every 5 minutes one 3 s CPU sample of CodexBar's process tree into `~/.local/state/codexbar-cpu-watch/samples.jsonl` (0600 in a 0700 dir, one O_APPEND line per sample, rotated past 5 MB). No command line is stored, only pid, percent, RSS, a name and flag names; a spike lists the top 15. `report` lists the last samples; `install [--ade DIR]` refuses a linked worktree or cow pasture; `uninstall` removes the job (#202).
