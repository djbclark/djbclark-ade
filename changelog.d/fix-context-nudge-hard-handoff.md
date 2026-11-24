### Fixed

- Repeated hard-tier context-size nudges (`kind="ask_repeat"`, every 60 s on `PostToolUse` and on every `UserPromptSubmit`), fired a once-per-climb `hermes-ping` at the hard tier instead of waiting for unreachable `400k` on a `267k` wall, persisted `handoff_due` (`kind="post_compact_handoff_due"`) across auto-compaction, and stamped pending hard handoff metadata in `precompact_handoff.py` checkpoints (#PR)
