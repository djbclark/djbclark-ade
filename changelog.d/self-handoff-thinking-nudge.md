### Added

- `ade-self-session handoff --thinking LEVEL` sets the successor's thinking level (passed to `paseo agent run --thinking`; a malformed value is refused before any native call; recorded as `thinking` in the transaction record); without it the successor inherits the predecessor's own level when `agent inspect` reports an explicit one, and an unknown or `auto` level launches with no flag as before (2026-11-14: a `high` lead handed off to an `auto` successor). `skills/handoff` Step 9 and `docs/self-session.md` document it. (#663)

### Changed

- The context-size nudge (`claude/hooks/context_size_nudge.py`, boundary and ask messages) now tells a lead whose work remains to run handoff Step 9 itself (`bin/ade-self-session handoff`, an acknowledged self-handoff) instead of telling the operator `/new` is ready, per djbclark's 2026-11-14 rule; the ~46k versus ~72k cost note stays. (#663)
