### Added

- `bin/ade-self-session handoff --predecessor AGENT_ID`: allows a supervisor or lead to re-hand a stuck agent (including `Status: error`) other than itself, recording `requested_by` and `cross_agent: true`, resolving the target's own workspace instead of the caller's, and authorizing the recorded requester (never the successor) for `reconcile`, `verify-turn`, and `retry`. (#823)
- `bin/ade-supervisor-rehandoff`: drives `ade-self-session handoff --predecessor` for planned stuck Pi agents under `ADE_SUPERVISOR_REHANDOFF=live`, skipping non-Pi entries and agents with no healthy alternative without archiving predecessors directly. (#823)
