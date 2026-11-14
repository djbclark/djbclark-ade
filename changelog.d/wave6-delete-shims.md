### Removed

- Deleted the three Wave 6 shims: `skills/session-finder/relay.py`, `bin/acp-dispatch` (+ `acp-dispatch-wait`, its report schema) and `tools/acp-run`, with their tests, `bin/agent_guard.py` and `docs/agent-guard-contract.md`; the OpenCode Go enforcement tests that ran through them went too (`route_agent.py` still refuses costly Go rows). Agents launch with native `paseo run` / `bin/ade-worker-run` and message with `paseo send`; docs, AGENTS.md "Machine context", the threat model and queue Carried 1 now say so (#699).
