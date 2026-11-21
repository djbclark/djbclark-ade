### Fixed

- `bin/route_agent.py` no longer binds a stale exhausted (or 0%) quota reading when the window's `resets_at` is already in the past: such a window reads unknown (re-probe) instead of exhausted, at both the row and window fold, so a pool that refilled overnight is not treated as out of quota. (#840)
- `bin/quota_nudge.py --reset` names every pool whose binding window has already refilled, and `skills/model-routing/SKILL.md` D5b records the rule to re-probe before a quota-sensitive dispatch. (#840)
