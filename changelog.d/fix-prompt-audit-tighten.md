### Fixed

- Prompt-audit tightening (operator ruling 2026-11-21): `AGENTS.md` carries a search-fallback rule below the managed graft block (`rg <pattern> <path>`, never `grep -r`); `skills/old-handoff-use-paseo-handoff/SKILL.md` commits with `git -C` and `git-commit-own` instead of `cd` plus bare `git commit`; `skills/baton/SKILL.md` messages an idle agent with `paseo send --no-wait`, never `--behavior steer`. (#889)
