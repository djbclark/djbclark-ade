### Fixed

- `ade-install doctor` TUI wiring check: stderr warnings attach to a TUI structurally (`warning: <tui-id> …`), every stderr line is kept (deduplicated, capped at 200 distinct), cursor-agent reads `unknown` when claude is not installed, and the inherited `SKILL_EVERYWHERE_GROKBOT_NOTE` (plus `OPS_ROOT`, `CODEX_HOME`, `HERMES_HOME` when HOME is pinned) is scrubbed (#PR)
- `tests/test_ade_install.py` runs with a temporary HOME: two doctor tests failed only on a Mac whose real credential-bak vault was inside its delete-after window (#PR)
