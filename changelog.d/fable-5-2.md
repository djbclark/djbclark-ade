### Changed

- Every specific mention of "Fable 5.1" is now "Fable 5.2" (operator 2026-11-13): the `frontier` role id `claude-fable-5-2` in `config/model-tiers.toml` and the `bin/model_tiers.py` defaults, the context-size nudge, Claude settings template, `acp-run` docs, skills, routing config, tests and docs. The retired id `claude-fable-5-1` stays known as a `[former]` frontier row (`classify` returns `former`) and in the `claude-cost-*` price tables for old transcripts; Fable 5.2 is priced as 5.1 ($10/MTok base, 0.025 cache read) until a source for 5.2 is checked. (#627)
