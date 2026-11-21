### Changed

- Frontier tail order (operator ruling 2026-11-21 via /steps): with claude Fable-short and codex out, `antigravity-argon` goes before `cursor-grok`; the order is Neon (r3), Argon (r5), cursor-grok (now frontier r6), by static rank inside the tail so pressure cannot swap it (`_frontier_tail`). `docs/model-routing.md` B4a says so and states the `frontier_order` precedence exactly (after `fallback_after`/`fallback_kinds`, among pools that passed the gates; PR 911 LOW-1), with tests. (#919)
