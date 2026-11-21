### Fixed

- `skill-everywhere --remove paseo` removes the Hermes `paseo` link when it is ours (it was a silent no-op), `--remove` of other names still leaves it alone; `bin/ade-update`'s `linked now:` line names `paseo` when the Hermes link was made even if a stuck Paseo-owned row remains; docs/skill-everywhere.md gives the real `== paseo (managed by Paseo)` header wording. (#PR)

### Changed

- `skills/fan-out/SKILL.md` and `docs/workspace-layout.md` say that `bin/ade-worker-run` checks the prompt argument itself for the absolute worktree path (a brief file the prompt only points to is refused); `skills/steps/SKILL.md` records that Antigravity sessions under Paseo skip `ask_question` and use the numbered text walk until ACP elicitation is wired (getpaseo/paseo#9355). (#PR)
