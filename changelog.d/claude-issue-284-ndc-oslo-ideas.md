### Added
- Added `bin/instruction-lint`, a deterministic lint for `AGENTS.md`, `GEMINI.md` and `.cursor/rules/*.mdc` (directory-tree
  blocks and cross-file duplicates are errors; phase D7 sweep terms and skill-name headings warn); CI's `context-policy`
  job runs it and `context-budget-check --instruction-lint` adds its counts to the nightly run (#284)
- Added `bin/post-edit-check`, a single-file fast lint (ruff syntax selection, `bash -n`, `jq empty`, `tomllib`) that never
  runs tests, registered as a Claude PostToolUse hook in the settings template (#284)
- Added `/steps plan`, an explicit interview-before-plan mode of the `steps` skill (#284)
- Added `bin/ade-retro` and the `retro` skill, read-only material for a periodic self-review (merged PRs, changelog
  entries, handoffs since a date) (#284)
### Security
- Added a secret-file read-deny policy, `config/secret-deny.toml`, rendered by `bin/render-secret-deny` into the Claude
  template's `permissions.deny`, plus the PreToolUse gate `claude/hooks/secret_read_gate.py` for file tools, Grep and Bash
  command text; a Grep whose root holds a denied file (a project `.env`, anything at or above `$HOME`) is refused until
  a narrower `path`, `glob` or `type` excludes it (#284)
