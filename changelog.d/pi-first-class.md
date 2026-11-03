### Added

- `acp-run` and `acp-dispatch` target Pi through `pi-acp` (independent OpenAI API routing profile, `--perm all` only), with paid-capacity admission that refuses identity-changing pass-through options (`--model`, `--set`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`) and persists the admitted minimum headroom across resumes (#273)
- Pi session history, fleet detection, resume hints and `ade-backup-stores` coverage; exact liveness requires a session-file identity (#273)
- Safe Pi native session naming and lifecycle controls (`skills/autorename/pi-bridge.ts`, `pi_native.py`); external automatic Pi compaction always refuses (#273)
- `bin/pi-skill-dedup`: a manual, claim-gated tool that adds exact `SKILL.md` exclusions to Pi's settings for an explicit duplicate pair (reversible with `undo`; refuses when Linux inode flags, macOS xattrs/flags or ACLs cannot be preserved). No existing duplicate is removed or hidden until an operator runs it (#273)
- `skill-everywhere` gains a `pi` target (Pi reads `~/.agents/skills`, shared with codex and goose); a `pi` routing service (OpenAI API billing, `api-only` eligible alongside omp, `measured_only` so it fails closed without a measured reading and prints no RESERVE advice); committed canonical `.pi/agents/` profiles (`astra-worker`, `frontier-astra`; installing them is manual, see `docs/pi-agent-profiles.md`) (#273)
- Pi subagent extension with per-invocation `model` and `thinking` overrides (invocation, then frontmatter, then Pi default), documented in `docs/pi-subagent.md`; project-local agents always prompt in a UI session and are refused headless unless `PI_SUBAGENT_ALLOW_PROJECT_AGENTS=1` (#273)

### Changed

- Skill discovery for Pi no longer creates a second link farm, so it adds no new duplicates (existing ones stay), and shared tests scrub inherited Pi/OMP environment markers and isolate `AUTORENAME_STATE_DIR` (#273)
- `autorename` state paths follow `AUTORENAME_STATE_DIR`; `api-only` routing is no longer omp-only; Pi/OMP transcript `native_id` now splits at the first underscore, so ids containing underscores are kept whole; fleet detection counts only the `pi` executable (or node/bun running a `pi` script) as a Pi seat (#273)
