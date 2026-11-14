### Changed

- `ade-self-session finish` waits (bounded, read-only) for the predecessor to stay idle with no permission waits for a stable window (`--stable`, default 45 s; `--wait-timeout`, default 25 min; `--poll`) before archiving, and an `agent archive` that answers the structured code `AGENT_RUNNING` returns to the wait and retries inside the same bound; every other archive error is still recorded and not retried. A timeout records `PREDECESSOR_NOT_IDLE`, exits non-zero and keeps both sessions. (#714)
