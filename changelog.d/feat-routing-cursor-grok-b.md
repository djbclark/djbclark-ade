### Added

- `cursor-grok` routing service (operator 2026-11-21, `skills/research` 1b): the newest Grok on Cursor's native provider as a model family (`grok-*`, resolved from `paseo provider models cursor --json`, never pinned) for `frontier` (r4, `judgment_tier`) and `research` (r14), drawing the Cursor third-party pool through `shares_pool`; `[dispatch].frontier_slice_models` gains `grok-*`. `grok` and `grok-bot` stay in `never_route` (not the GrokBot pool, not the retired standalone CLI). (#PR)
