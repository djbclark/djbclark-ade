### Added

- `ref lookup ID` (`CLAUDE-74` or `74`): prints the bot, issue time and agent hint of an id from `issued.log` under a shared flock, creating nothing; exit 1 for an id never issued or issued to another bot. `claude/hooks/ref_integrity_gate.py`, a Claude Code Stop hook (registered in `agents/claude/settings.json.tmpl`, linked by `ade-update`): when the final post's last line is `Ref:` it checks the form `Ref: <BOT>-<base36>`, that the id is in `issued.log`, that the bot prefix matches and that the id was not used earlier in the transcript, and otherwise blocks once with an instruction to run `ref <BOT>`; a long post with no Ref line gets a non-blocking note. It honours `stop_hook_active`, skips sub-agents and fails open. Tests in `tests/test_ref_integrity_gate.py`, `tests/test_ref_labels.py`. (#861)

### Changed

- `docs/ref-labels.md` Part B says what a Ref is (a unique script-issued id for one operator-facing post, never a hash, PR number or hand-typed text; growing from 1 to 3 characters at 1296), how the hook check works and what to do when it blocks; it drops the never-shipped `ref_audit.py`. (#861)
