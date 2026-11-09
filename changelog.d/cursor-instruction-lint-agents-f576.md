### Changed
- `bin/instruction-lint` expands `~` in FILE arguments so `~/AGENTS.md` and
  `~/.cursor/rules/home-agents.mdc` lint outside the repo; `docs/context-hygiene.md` cites
  `--root ~` / those paths and the nightly `context-budget-check --instruction-lint` coverage (#0)
