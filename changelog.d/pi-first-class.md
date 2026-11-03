### Added

- `acp-run` and `acp-dispatch` target Pi through `pi-acp` (independent OpenAI API routing profile, `--perm all` only), with paid-capacity admission that refuses identity-changing pass-through options (`--model`, `--set`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`) and persists the admitted minimum headroom across resumes (#273)
- Pi session history, fleet detection, resume hints and `ade-backup-stores` coverage; exact liveness requires a session-file identity (#273)
- Safe Pi native session naming and lifecycle controls (`skills/autorename/pi-bridge.ts`, `pi_native.py`); external automatic Pi compaction always refuses (#273)
- `bin/pi-skill-dedup`: reversible, policy-checked cleanup of duplicate shared skills for Pi, refusing when Linux inode flags, macOS xattrs/flags or ACLs cannot be preserved (#273)
- Pi subagent extension with per-invocation `model` and `thinking` overrides (invocation, then frontmatter, then Pi default), documented in `docs/pi-subagent.md` (#273)

### Changed

- Shared skills discovery no longer warns about duplicates for Pi, and shared tests scrub inherited Pi/OMP environment markers and isolate `AUTORENAME_STATE_DIR` (#273)
- `autorename` state paths follow `AUTORENAME_STATE_DIR` (#273)
