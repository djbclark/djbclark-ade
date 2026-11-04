# ADE recovery

A passive Paseo plugin (issue 278). It watches five lifecycle hooks (`agent.create.after`,
`agent.turn.before`, `agent.turn.after`, `agent.close.after`, `agent.archive.after`) and keeps one
small, atomically written record per agent under
`<state base>/ade/<serverId>/ade-recovery/recovery/v1/`: identity, turn history, interruption
evidence and hardened read-only git evidence (head, tracked and untracked fingerprints).

It never prompts, reloads, archives, interrupts or creates agents, never refetches a timeline, and
never stages or commits in git. It has no npm dependencies; Node runs the TypeScript directly.

Read the records with `bin/paseo-checkpoint list|show AGENT_ID [--json]`. The verdict is
`resumable-native` only when the last turn ended cleanly and was observed and the tree still matches;
an interrupted turn is `needs-review`; a user stop or archive is `do-not-resume`.

Tests: `npm test` in this directory, or `bin/pytest -q tests/test_ade_recovery_plugin.py`.
