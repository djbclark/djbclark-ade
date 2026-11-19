# Runtime retirement evidence for the controlled pilot

A1. Read-only source audit on 2026-11-18 examined the release matching the
live `paseo daemon status --json` result (`daemonVersion`, `serverId`): Paseo `v0.16.0-beta.2`, tag object
`b7605043878e509699bf2d8428253a257dda478d`, source commit
`23bae61535542a45ade7196a7b3c152705f16de3`. Revalidate the running daemon and
provider before using this release-specific evidence. It is not a version pin
or a substitute for current runtime checks.

A2. `AgentManager.archiveAgentUnlocked` marks the stored record archived
**before** it awaits `closeAgentRuntime`. An `Archived: true` readback alone
therefore does not establish successful runtime shutdown. A lost or failed
archive response remains an unresolved retirement operation.
Evidence: [agent-manager.ts:2206](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/agent/agent-manager.ts#L2206).

A3. `closeAgentRuntime` awaits the provider session's `close()` before it
publishes the closed snapshot. A failed close preserves runtime ownership.
Evidence: [agent-manager.ts:2140](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/agent/agent-manager.ts#L2140).

A4. For the native Codex provider in this audited release, `close()` awaits
`disposeClient()`, which awaits transport disposal. The transport awaits
`terminateWithTreeKill` with a bounded force-exit wait and throws if the child
does not report exit after SIGKILL. A successful, reconciled archive operation
therefore carries useful provider-process retirement evidence for this
controlled provider. It does not require guessing an undocumented PID field.
Evidence: [Codex close](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/agent/providers/codex-app-server-agent.ts#L5499),
[transport disposal](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/server/agent/providers/codex/app-server-transport.ts#L339).

A5. The tree-kill helper waits for the direct child's exit, not proof that
every possible descendant has disappeared. Tree-signal failure can fall back
to signalling only that child. Detached jobs and arbitrary external operations
still require separate tracked-job reconciliation, bound-resource process-user
census and operation-ledger reconciliation. Never infer all-job quiescence
from provider exit, archive status, idle, heartbeat expiry or quota exhaustion.
Evidence: [tree-kill.ts:32](https://github.com/getpaseo/paseo/blob/23bae61535542a45ade7196a7b3c152705f16de3/packages/server/src/utils/tree-kill.ts#L32).

A6. Acceptable pilot scope is explicitly enrolled resources with controlled
launchers and tracked background jobs. Bind retirement success, process census,
job/operation state and verified checkpoint bytes to the exact draining owner,
epoch, role revision and resource manifest. Unknown prior-host access, failed
inspection or unsupported provider shutdown semantics blocks transfer. Other
providers need their own audited close contract or independently captured
process birth identities with confirmed exit.

A7. Source retrieval procedure: save large repository trees or source bodies
privately and print only selected file paths or bounded function spans. A
truncated tree listing is not complete discovery evidence. Never collect or
print provider argv/environment to guess identity; those can hold credentials.

A8. Correction: the baseline audit reported 0.16.1, but the native daemon-status RPC reported 0.16.0-beta.2 on server srv_3QHQeiJniWBD. CLI version is not daemon version. The exact beta.2 source was fetched and the four shutdown functions checked again; the described await/exit behavior is present there too.
