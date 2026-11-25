### Changed

- Updated `claude/hooks/context_size_nudge.py` to detect Paseo mode (`PASEO_AGENT_ID` set and non-blank, taking precedence over inherited `HERDR_ENV=1`) vs non-Paseo / Herdr Claude Code mode (operator ruling 2026-11-25, Carried #122): in non-Paseo mode all four nudges (`boundary`, `ask`, `ask_repeat`, `post_compact_handoff_due`) and pings direct local `/self-handoff` Steps 0–7, skip Step 9, and let the operator run `/new` + `/baton` manually instead of demanding `ade-self-session handoff` or claiming "never hand the operator a /new" (#996).
- Updated `skills/self-handoff/SKILL.md`, `docs/self-session.md`, `docs/context-hygiene.md`, `docs/cross-harness-messaging.md`, and `docs/queue.md` (Carried #122 Phase 1) to document non-Paseo / Herdr local-handoff mode and require `--reply-file` via `bin/xmsg to-paseo` when messaging a Paseo lead (#996).

### Fixed

- Improved `bin/ade_self_session.py` (`Service.actor()`) so an unset or blank `PASEO_AGENT_ID` reports a clear Paseo-only error (`PASEO_AGENT_ID is unset (a full UUID is required; ade-self-session is Paseo-only)`) pointing non-Paseo / Herdr Claude Code sessions to local Steps 0–7 + manual `/new` + `/baton`, while keeping `ident()` strict for malformed UUIDs (#996).
