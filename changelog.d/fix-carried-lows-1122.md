### Fixed

- `ade-self-session finish` no longer fails when the successor's daemon state file is a deeply nested JSON document (`RecursionError` is treated as an unreadable file, so the lead-window advice falls back); a test pins that and that only the successor's own state file is read (carried lows of #928) (#PR)

### Changed

- Docs and tests: resume-first wording in `docs/paseo-only-rearchitecture.md`, a stronger relaunch-reason assertion in `tests/test_agent_footer_gate.py` (lows of #929), how to count open ledger PRs in `docs/macroscope-spend.md` (low of #930), queue Carried 118 (a failing coord-adapter test on master) and 119 (chrome-devtools EPERM under macOS 27 App Data protection, also in `docs/mcp-servers.md`) (#PR)
