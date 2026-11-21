### Added

- `plugins/ade-claim` + `bin/ade_claims.py`: on `agent.create.after`, a claim whose owner agent is archived (or gone, `AGENT_NOT_FOUND`) is rebound to the newly created agent in that workspace through the new compare-and-swap `ade_claims.py rebind-owner` (plugin use only), one log line per rebind; a live owner, a harness-label or session-keyed owner, a released claim or any owner-lookup failure rebinds nothing (operator ruling Q4, 2026-11-20). (#841)
