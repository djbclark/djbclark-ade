### Fixed

- `bin/route_agent.py plan` no longer refuses research as "no pool has room" for about a third of every quarter hour while Gemini is at 100%: a pool aiuse lists in `stale_pools` only because its reused reading passed a shorter per-provider fresh limit (antigravity: 600 s fresh, one query per 900 s, `--live` cannot beat the gate) keeps its reading when the row is at most 20 minutes old and shows at least 50% headroom (`STALE_REUSE_MAX_AGE`, `STALE_REUSE_MIN_LEFT`; documented in `docs/model-routing.md` D1). Older, lower or expired readings still read unknown. (#864)
