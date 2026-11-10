### Added

- Declared agents/ template secrets in `secrets/secretspec.toml` and companion field homes under `companion/` (Phase 1). (#396)
- Owned-key `modify_` merge helpers for Claude and Codex under `agents/claude/modify_merge.py` and `agents/codex/modify_merge.py` (keep unowned live keys; refuse live home paths). (#396)

### Changed

- `ade-template-check` closes PR 23 round-3 scanner LOWs (closed Authorization schemes, `]` terminator, `--key`/`--access-key`, YAML name/value headers) and requires secretspec declarations. (#396)
