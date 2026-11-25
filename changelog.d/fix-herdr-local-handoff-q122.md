### Changed

- Updated `claude/hooks/context_size_nudge.py` to detect Paseo mode (`PASEO_AGENT_ID` set and non-blank, taking precedence over inherited `HERDR_ENV=1`) vs non-Paseo / Herdr Claude Code mode (operator ruling 2026-11-25, Carried #122): in non-Paseo mode all four nudges (`boundary`, `ask`, `ask_repeat`, `post_compact_handoff_due`), `_successor_note`, and both pings direct local `/self-handoff` Steps 0–7, skip Step 9, and let the operator run `/new` then `/baton <exact Tier 1 pointer>` (or `/baton`) manually instead of demanding `ade-self-session handoff` or claiming "never hand the operator a /new" (#996).
- Updated `skills/self-handoff/SKILL.md`, `skills/baton/SKILL.md`, `docs/self-session.md`, `docs/context-hygiene.md`, `docs/cross-harness-messaging.md`, and `docs/queue.md` (Carried #122 Phase 1) to document ownership-checked non-Paseo / Herdr local-handoff and `/baton` resume mode and require both `--reply-file` and `--reply-name` via `bin/xmsg to-paseo` when messaging a Paseo lead (#996).

### Fixed

- Fixed the Paseo hard-tier operator ping in `claude/hooks/context_size_nudge.py` so it reports the tier and acknowledged `/self-handoff` Step 9 guidance (without advertising `/new` or promising unverified actions), aligned `_successor_note` per mode, and isolated `LOG_PATH` in `claude/hooks/handoff-tools/tests/test_context_size_nudge.py` (#996).
- Improved `bin/ade_self_session.py` (`Service.actor()`) so an unset or blank `PASEO_AGENT_ID` reports a clear Paseo-only error (`PASEO_AGENT_ID is unset (a full UUID is required; ade-self-session is Paseo-only)`) pointing non-Paseo / Herdr Claude Code sessions to local Steps 0–7 + manual `/new` then `/baton <exact Tier 1 pointer>`, while keeping `ident()` strict for malformed UUIDs (#996).
