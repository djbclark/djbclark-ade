### Added

- `skills/herdr/SKILL.md`: the official herdr skill, tracked from `herdr --skill` and linked into every TUI by `bin/skill-everywhere --all`, with a loosened description so agents infer use from "in tab xyz" / pane / workspace rather than only an explicit Herdr mention. `bin/herdr-skill-refresh` regenerates it (`--check` reports drift; atomic write, clear errors when herdr is missing). Listed in `docs/skills.md`.
